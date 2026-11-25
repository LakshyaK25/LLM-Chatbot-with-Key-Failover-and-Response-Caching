"""Environment-driven configuration for the backend."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    load_dotenv()
except ImportError:
    pass

DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant. Answer clearly and concisely."


@dataclass
class Settings:
    api_keys: list[tuple[str, str]]
    model: str
    database_url: str
    allowed_origins: list[str]
    enable_failure_simulation: bool


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def load_settings() -> Settings:
    keys = _split(os.getenv("LLM_API_KEYS", ""))
    return Settings(
        api_keys=[(f"key_{index}", key) for index, key in enumerate(keys, start=1)],
        model=os.getenv("LLM_MODEL", "gemini/gemini-3.5-flash"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./data/app.db"),
        allowed_origins=_split(
            os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
        ),
        enable_failure_simulation=os.getenv(
            "ENABLE_FAILURE_SIMULATION", "false"
        ).lower()
        == "true",
    )
