"""Test fixtures. LiteLLM is mocked at the single provider-call boundary;
the API, SQLite storage, failover loop and metadata logic are all exercised
for real."""

from __future__ import annotations

import os
import tempfile
import time
from types import SimpleNamespace

import pytest

# Set configuration before importing the application module.
os.environ["LLM_API_KEYS"] = "test-key-1,test-key-2"
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(
    tempfile.gettempdir(), "lyftr_pytest_app.db"
)
os.environ["LLM_MODEL"] = "test-model"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:3000"
os.environ["ENABLE_FAILURE_SIMULATION"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app import llm, main  # noqa: E402
from app.db import Database  # noqa: E402


def fake_response(text: str, usage: tuple[int, int], cache_hit: bool = False):
    message = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=message)
    token_usage = SimpleNamespace(
        prompt_tokens=usage[0], completion_tokens=usage[1]
    )
    return SimpleNamespace(
        choices=[choice],
        usage=token_usage,
        model="test-model",
        _hidden_params={"cache_hit": True} if cache_hit else {},
    )


class FakeProvider:
    """Mimics one LiteLLM completion call, including LiteLLM's cache hit flag."""

    def __init__(self):
        self.calls: list[dict] = []
        self.cache: dict[str, tuple[str, tuple[int, int]]] = {}
        self.delay = 0.0
        self.first_call_error: Exception | None = None

    def __call__(
        self,
        *,
        model,
        api_key,
        messages,
        cache_key,
        cache_enabled=True,
        fail_status=None,
    ):
        self.calls.append(
            {
                "model": model,
                "api_key": api_key,
                "messages": messages,
                "cache_key": cache_key,
                "cache_enabled": cache_enabled,
                "fail_status": fail_status,
            }
        )
        if fail_status is not None:
            raise llm.ProviderFailure(fail_status, f"simulated HTTP {fail_status}")
        if self.first_call_error is not None and len(self.calls) == 1:
            raise self.first_call_error
        if cache_enabled and cache_key in self.cache:
            text, usage = self.cache[cache_key]
            return fake_response(text, usage, cache_hit=True)
        if self.delay:
            time.sleep(self.delay)
        text = f"answer to {messages[-1]['content']}"
        usage = (len(messages[-1]["content"].split()) + 5, 4)
        response = fake_response(text, usage)
        if cache_enabled:
            self.cache[cache_key] = (text, usage)
        return response


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fresh database, cache and provider mock for each test."""
    database = Database("sqlite:///" + str(tmp_path / "messages.db"))
    monkeypatch.setattr(main, "database", database)
    monkeypatch.setattr(
        main.settings, "api_keys", [("key_1", "dummy-1"), ("key_2", "dummy-2")]
    )
    monkeypatch.setattr(main.settings, "enable_failure_simulation", True)
    llm.configure_cache()

    provider = FakeProvider()
    monkeypatch.setattr(llm, "call_provider", provider)

    with TestClient(main.app, raise_server_exceptions=False) as client:
        yield client, provider, database


def post_chat(client, session_id="s-test", message="hello", headers=None):
    return client.post(
        "/chat",
        json={"session_id": session_id, "message": message},
        headers=headers or {},
    )
