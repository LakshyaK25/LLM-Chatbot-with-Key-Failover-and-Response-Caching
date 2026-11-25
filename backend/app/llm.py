"""LiteLLM calls, built-in caching and key failover."""

from __future__ import annotations

import hashlib
import json

import litellm
from litellm.litellm_core_utils.hidden_params import served_from_cache

SIMULATION_STATUSES = {429, 500, 502, 503}


class ProviderFailure(Exception):
    """A provider/key failure that can be retried with the next key."""

    def __init__(self, status_code: int, detail: str = ""):
        self.status_code = status_code
        super().__init__(detail or f"provider returned HTTP {status_code}")


class AllProvidersUnavailable(Exception):
    """Every configured key failed for this request."""


def configure_cache() -> bool:
    """Enable LiteLLM's own in-memory response cache (no custom cache)."""
    litellm.cache = litellm.Cache(type="local")
    return True


def parse_failure_header(
    header: str | None, key_ids: list[str], enabled: bool
) -> dict[str, int]:
    """Parse e.g. 'key_1=429,key_2=500' or '*=429' into a per-request map."""
    if not enabled or not header:
        return {}

    failures: dict[str, int] = {}
    for entry in header.split(","):
        entry = entry.strip()
        if "=" not in entry:
            continue
        target, raw_status = (part.strip() for part in entry.split("=", 1))
        try:
            status = int(raw_status)
        except ValueError:
            continue
        if status not in SIMULATION_STATUSES:
            continue
        targets = key_ids if target == "*" else [target]
        for key_id in targets:
            if key_id in key_ids:
                failures[key_id] = status
    return failures


def _cache_key(model: str, messages: list[dict]) -> str:
    """Cache key derived only from the model and the full message list."""
    material = json.dumps(
        {"model": model, "messages": messages}, sort_keys=True, ensure_ascii=False
    )
    return "chat:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def call_provider(
    *,
    model: str,
    api_key: str,
    messages: list[dict],
    cache_key: str,
    cache_enabled: bool = True,
    fail_status: int | None = None,
):
    """One LiteLLM call. Simulation raises before the network call, so both
    simulated and real failures go through the same retry loop below."""
    if fail_status is not None:
        raise ProviderFailure(fail_status, f"simulated HTTP {fail_status}")

    kwargs = {
        "model": model,
        "api_key": api_key,
        "messages": messages,
        "cache_key": cache_key,
    }
    if not cache_enabled:
        kwargs["caching"] = False
    return litellm.completion(**kwargs)


def generate_reply(
    *,
    model: str,
    api_keys: list[tuple[str, str]],
    messages: list[dict],
    failure_map: dict[str, int] | None = None,
) -> tuple[object, str | None, int, bool]:
    """Try each key in order until one succeeds.

    Returns (response, successful key id, failed attempts before success,
    cache hit flag). Raises AllProvidersUnavailable if all keys fail.
    """
    failures = failure_map or {}
    key = _cache_key(model, messages)
    # A simulated request must exercise real provider failover, so it never
    # reads or writes the LiteLLM cache.
    cache_enabled = not failures

    attempts = 0
    for key_id, api_key in api_keys:
        try:
            response = call_provider(
                model=model,
                api_key=api_key,
                messages=messages,
                cache_key=key,
                cache_enabled=cache_enabled,
                fail_status=failures.get(key_id),
            )
            return response, key_id, attempts, bool(served_from_cache(response))
        except Exception:
            # Includes LiteLLM rate-limit/quota/5xx errors and simulated
            # failures. Any key error is retryable; all failures become 503.
            attempts += 1

    raise AllProvidersUnavailable()
