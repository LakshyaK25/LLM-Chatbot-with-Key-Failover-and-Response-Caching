"""Backend tests covering the assignment's verification checklist."""

from __future__ import annotations

import httpx
import litellm
import pytest

from app import llm, main
from app.db import Database
from app.llm import call_provider as real_call_provider


def post_chat(client, session_id="s-test", message="hello", headers=None):
    return client.post(
        "/chat",
        json={"session_id": session_id, "message": message},
        headers=headers or {},
    )


def test_health_endpoint(env):
    client, _, _ = env
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "keys_configured": 2,
        "cache_enabled": True,
    }


@pytest.mark.parametrize(
    "body",
    [
        {"message": "hello"},
        {"session_id": "s-test"},
        {"session_id": "", "message": "hello"},
        {"session_id": "x" * 129, "message": "hello"},
        {"session_id": "s-test", "message": "   "},
        {"session_id": "s-test", "message": "x" * 4001},
    ],
)
def test_request_validation_returns_422(env, body):
    client, provider, _ = env
    response = client.post("/chat", json=body)
    assert response.status_code == 422
    assert "detail" in response.json()
    assert provider.calls == []


def test_malformed_json_returns_422(env):
    client, provider, _ = env
    response = client.post(
        "/chat", content="{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert "detail" in response.json()
    assert provider.calls == []


def test_successful_chat_response_has_all_metadata(env):
    client, _, _ = env
    response = post_chat(client, "s-1", "What is the capital of France?")
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "s-1"
    assert body["reply"] == "answer to What is the capital of France?"
    meta = body["metadata"]
    assert set(meta) == {
        "resolution_source",
        "model",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "key_id",
        "fallback_attempts",
    }
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["model"] == "test-model"
    assert isinstance(meta["latency_ms"], int)
    assert meta["input_tokens"] > 0
    assert meta["output_tokens"] > 0
    assert meta["key_id"] == "key_1"
    assert meta["fallback_attempts"] == 0


def test_multi_turn_conversation_memory(env):
    client, provider, _ = env
    post_chat(client, "s-2", "hello")
    post_chat(client, "s-2", "how are you?")
    messages = provider.calls[-1]["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[1]["content"] == "hello"
    assert messages[2]["content"] == "answer to hello"
    assert messages[3]["content"] == "how are you?"


def test_sessions_are_separate(env):
    client, _, _ = env
    post_chat(client, "session-a", "hello A")
    post_chat(client, "session-b", "hello B")
    history_a = client.get("/sessions/session-a/messages").json()["messages"]
    history_b = client.get("/sessions/session-b/messages").json()["messages"]
    assert history_a[0]["content"] == "hello A"
    assert history_b[0]["content"] == "hello B"
    assert len(history_a) == len(history_b) == 2


def test_sqlite_persistence(env):
    client, _, database = env
    post_chat(client, "s-persist", "persist me")
    reopened = Database("sqlite:///" + database.path)
    history = reopened.get_history("s-persist")
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert history[0]["content"] == "persist me"


def test_history_endpoint_and_unknown_session(env):
    client, _, _ = env
    created = post_chat(client, "s-history", "hello").json()
    response = client.get("/sessions/s-history/messages")
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "s-history"
    messages = body["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "hello"
    assert messages[1]["metadata"] == created["metadata"]
    assert all(m["role"] != "system" for m in messages)

    missing = client.get("/sessions/does-not-exist/messages")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "session not found"}


def test_cache_hit_across_sessions(env):
    client, provider, _ = env
    first = post_chat(client, "cache-session-1", "same first message")
    second = post_chat(client, "cache-session-2", "same first message")
    assert first.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert second.json()["metadata"]["resolution_source"] == "LLM_CACHE"
    assert second.json()["metadata"]["key_id"] is None
    assert second.json()["metadata"]["fallback_attempts"] == 0
    assert provider.calls[0]["cache_enabled"] is True
    assert provider.calls[1]["cache_key"] == provider.calls[0]["cache_key"]


def test_identical_cached_reply(env):
    client, _, _ = env
    first = post_chat(client, "reply-1", "identical reply please").json()
    second = post_chat(client, "reply-2", "identical reply please").json()
    assert second["reply"] == first["reply"]
    assert second["reply"] == "answer to identical reply please"


def test_cached_token_usage(env):
    client, _, _ = env
    first = post_chat(client, "tokens-1", "token usage please").json()["metadata"]
    second = post_chat(client, "tokens-2", "token usage please").json()["metadata"]
    assert second["input_tokens"] == first["input_tokens"]
    assert second["output_tokens"] == first["output_tokens"]


def test_real_litellm_built_in_cache_is_used(env, monkeypatch):
    """Use LiteLLM's own mock_response hook so the real Cache and its
    cache_hit hidden param are exercised (no provider credentials needed)."""
    client, _, _ = env
    monkeypatch.setattr(llm, "call_provider", real_call_provider)
    monkeypatch.setattr(main.settings, "model", "gpt-3.5-turbo")
    real_completion = litellm.completion

    def mocked_completion(**kwargs):
        kwargs["mock_response"] = "real litellm cache answer"
        return real_completion(**kwargs)

    monkeypatch.setattr(litellm, "completion", mocked_completion)
    first = post_chat(client, "litellm-cache-1", "real cache message").json()
    second = post_chat(client, "litellm-cache-2", "real cache message").json()
    assert first["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert second["metadata"]["resolution_source"] == "LLM_CACHE"
    assert second["reply"] == first["reply"] == "real litellm cache answer"
    assert second["metadata"]["key_id"] is None


def test_different_message_does_not_reuse_cache(env):
    client, _, _ = env
    first = post_chat(client, "diff-1", "first different message").json()
    second = post_chat(client, "diff-2", "second different message").json()
    assert second["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert second["reply"] != first["reply"]


def test_cache_latency_is_lower_than_live_call(env):
    client, provider, _ = env
    provider.delay = 0.05
    live = post_chat(client, "latency-1", "measure latency")
    provider.delay = 0.0
    cached = post_chat(client, "latency-2", "measure latency")
    live_ms = live.json()["metadata"]["latency_ms"]
    cached_ms = cached.json()["metadata"]["latency_ms"]
    assert live_ms >= 50
    assert cached_ms < live_ms


def test_key_1_429_fails_over_to_key_2(env):
    client, provider, _ = env
    response = post_chat(
        client,
        "failover-429",
        "unique failover 429 request",
        headers={"X-Simulate-Failure": "key_1=429"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["metadata"]["key_id"] == "key_2"
    assert body["metadata"]["fallback_attempts"] == 1
    assert body["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert body["reply"] == "answer to unique failover 429 request"
    assert provider.calls[0]["fail_status"] == 429
    assert provider.calls[1]["fail_status"] is None


def test_key_1_500_fails_over_to_key_2(env):
    client, provider, _ = env
    response = post_chat(
        client,
        "failover-500",
        "unique failover 500 request",
        headers={"X-Simulate-Failure": "key_1=500"},
    )
    assert response.status_code == 200
    assert response.json()["metadata"]["key_id"] == "key_2"
    assert response.json()["metadata"]["fallback_attempts"] == 1
    assert provider.calls[0]["fail_status"] == 500


def test_all_keys_failing_returns_503(env):
    client, _, _ = env
    response = post_chat(
        client,
        "all-fail",
        "all keys down",
        headers={"X-Simulate-Failure": "*=429"},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "all providers unavailable"}


def test_failed_requests_are_not_saved(env):
    client, _, _ = env
    response = post_chat(
        client,
        "no-history",
        "this must not be stored",
        headers={"X-Simulate-Failure": "key_1=500,key_2=502"},
    )
    assert response.status_code == 503
    history = client.get("/sessions/no-history/messages")
    assert history.status_code == 404
    assert history.json() == {"detail": "session not found"}


def test_failure_simulation_disabled_by_switch(env, monkeypatch):
    client, provider, _ = env
    monkeypatch.setattr(main.settings, "enable_failure_simulation", False)
    response = post_chat(
        client,
        "simulation-off",
        "unique simulation disabled request",
        headers={"X-Simulate-Failure": "key_1=429"},
    )
    assert response.status_code == 200
    assert response.json()["metadata"]["key_id"] == "key_1"
    assert provider.calls[0]["fail_status"] is None


@pytest.mark.parametrize(
    "status,exception",
    [
        (
            429,
            lambda: litellm.RateLimitError(
                message="quota exhausted",
                llm_provider="openai",
                model="test-model",
                response=httpx.Response(status_code=429),
            ),
        ),
        (
            500,
            lambda: litellm.InternalServerError(
                message="server error",
                llm_provider="openai",
                model="test-model",
                response=httpx.Response(status_code=500),
            ),
        ),
        (
            502,
            lambda: litellm.APIError(
                status_code=502,
                message="bad gateway",
                llm_provider="openai",
                model="test-model",
                response=httpx.Response(status_code=502),
            ),
        ),
        (
            503,
            lambda: litellm.ServiceUnavailableError(
                message="unavailable",
                llm_provider="openai",
                model="test-model",
                response=httpx.Response(status_code=503),
            ),
        ),
    ],
)
def test_provider_rate_limit_quota_and_5xx_errors_fail_over(env, status, exception):
    client, provider, _ = env
    provider.first_call_error = exception()
    response = post_chat(client, f"provider-error-{status}", f"provider error {status}")
    assert response.status_code == 200
    assert response.json()["metadata"]["key_id"] == "key_2"
    assert response.json()["metadata"]["fallback_attempts"] == 1
