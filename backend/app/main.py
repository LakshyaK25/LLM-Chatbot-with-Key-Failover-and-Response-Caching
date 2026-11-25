"""FastAPI application exposing exactly the three contracted endpoints."""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import DEFAULT_SYSTEM_PROMPT, load_settings
from .db import Database
from .llm import AllProvidersUnavailable, configure_cache, generate_reply, parse_failure_header
from .schemas import ChatRequest

settings = load_settings()
database = Database(settings.database_url)
configure_cache()

app = FastAPI(
    title="LLM Chatbot",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unexpected_error_handler(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


def _reply_text(response) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError):
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for part in content:
            text = getattr(part, "text", None)
            if text:
                parts.append(str(text))
        return "".join(parts).strip()
    return str(content or "").strip()


@app.get("/health")
def health() -> dict:
    if not database.ping():
        raise HTTPException(status_code=503, detail="database unavailable")
    return {
        "status": "ok",
        "keys_configured": len(settings.api_keys),
        "cache_enabled": True,
    }


@app.post("/chat")
def chat(
    payload: ChatRequest,
    x_simulate_failure: Annotated[str | None, Header(alias="X-Simulate-Failure")] = None,
) -> dict:
    if payload.system_prompt is not None:
        system_prompt = payload.system_prompt
    else:
        system_prompt = database.get_system_prompt(payload.session_id) or DEFAULT_SYSTEM_PROMPT

    history = database.get_history(payload.session_id)
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend({"role": item["role"], "content": item["content"]} for item in history)
    messages.append({"role": "user", "content": payload.message})

    failure_map = parse_failure_header(
        x_simulate_failure,
        [key_id for key_id, _ in settings.api_keys],
        settings.enable_failure_simulation,
    )

    started = time.perf_counter()
    try:
        response, key_id, fallback_attempts, cache_hit = generate_reply(
            model=settings.model,
            api_keys=settings.api_keys,
            messages=messages,
            failure_map=failure_map,
        )
    except AllProvidersUnavailable:
        raise HTTPException(status_code=503, detail="all providers unavailable")

    latency_ms = int((time.perf_counter() - started) * 1000)
    reply = _reply_text(response)
    if not reply:
        raise HTTPException(status_code=503, detail="all providers unavailable")

    usage = getattr(response, "usage", None)
    metadata = {
        "resolution_source": "LLM_CACHE" if cache_hit else "LIVE_INFERENCE",
        # The LiteLLM model identifier from configuration, matching the API contract.
        "model": settings.model,
        "latency_ms": latency_ms,
        "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "key_id": None if cache_hit else key_id,
        "fallback_attempts": 0 if cache_hit else fallback_attempts,
    }

    database.save_turn(
        payload.session_id,
        payload.message,
        reply,
        metadata,
        payload.system_prompt,
    )
    return {
        "session_id": payload.session_id,
        "reply": reply,
        "metadata": metadata,
    }


@app.get("/sessions/{session_id}/messages")
def get_messages(session_id: str) -> dict:
    messages = database.get_history(session_id)
    if not messages:
        raise HTTPException(status_code=404, detail="session not found")
    return {"session_id": session_id, "messages": messages}
