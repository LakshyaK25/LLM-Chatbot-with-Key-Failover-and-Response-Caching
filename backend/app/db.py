"""SQLite storage for sessions and messages."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sqlite_path(database_url: str) -> str:
    if database_url.startswith("sqlite:///"):
        return database_url[len("sqlite:///") :]
    if database_url.startswith("sqlite://"):
        return database_url[len("sqlite://") :]
    return database_url


class Database:
    def __init__(self, database_url: str):
        self.path = _sqlite_path(database_url)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        connection = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages (session_id, id);
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    system_prompt TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            connection.commit()
        finally:
            connection.close()

    def ping(self) -> bool:
        connection = self._connect()
        try:
            connection.execute("SELECT 1").fetchone()
            return True
        finally:
            connection.close()

    def get_history(self, session_id: str) -> list[dict]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT role, content, metadata FROM messages "
                "WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        finally:
            connection.close()

        messages: list[dict] = []
        for row in rows:
            item = {"role": row["role"], "content": row["content"]}
            if row["role"] == "assistant" and row["metadata"]:
                item["metadata"] = json.loads(row["metadata"])
            messages.append(item)
        return messages

    def get_system_prompt(self, session_id: str) -> str | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT system_prompt FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return row["system_prompt"] if row else None
        finally:
            connection.close()

    def save_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_reply: str,
        metadata: dict,
        system_prompt: str | None = None,
    ) -> None:
        now = _timestamp()
        connection = self._connect()
        try:
            connection.execute(
                "INSERT INTO messages (session_id, role, content, metadata, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, "user", user_message, None, now),
            )
            connection.execute(
                "INSERT INTO messages (session_id, role, content, metadata, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    session_id,
                    "assistant",
                    assistant_reply,
                    json.dumps(metadata),
                    now,
                ),
            )
            if system_prompt is not None:
                connection.execute(
                    "INSERT INTO sessions (session_id, system_prompt, created_at) "
                    "VALUES (?, ?, ?) "
                    "ON CONFLICT(session_id) DO UPDATE SET system_prompt = excluded.system_prompt",
                    (session_id, system_prompt, now),
                )
            connection.commit()
        finally:
            connection.close()
