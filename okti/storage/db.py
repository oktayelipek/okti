"""SQLite storage — sessions, messages, and tool call history."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from okti.models.provider import Message, Role, ToolCall

logger = logging.getLogger(__name__)

DB_FILENAME = "okti.db"


class Storage:
    """Async SQLite storage for sessions and messages."""

    def __init__(self, db_path: Path | None = None):
        if db_path is None:
            db_path = Path.home() / ".config" / "okti" / DB_FILENAME
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open the database and create tables."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                workspace TEXT,
                model TEXT,
                metadata TEXT DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT DEFAULT '',
                tool_calls TEXT DEFAULT '[]',
                tool_call_id TEXT,
                model TEXT,
                token_usage TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
            CREATE TABLE IF NOT EXISTS plans (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                scope TEXT NOT NULL,
                summary TEXT DEFAULT '',
                tasks_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );
            CREATE INDEX IF NOT EXISTS idx_plans_session ON plans(session_id);
        """)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    # --- Sessions ---

    async def create_session(
        self,
        name: str | None = None,
        workspace: str | None = None,
        model: str | None = None,
    ) -> str:
        """Create a new session and return its ID."""
        session_id = uuid.uuid4().hex[:12]
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "INSERT INTO sessions (id, name, created_at, updated_at, workspace, model) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, name or f"Session {now[:10]}", now, now, workspace, model),
        )
        await self._db.commit()
        logger.info("Created session: %s", session_id)
        return session_id

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        cursor = await self._db.execute(
            "SELECT id, name, created_at, updated_at, workspace, model FROM sessions WHERE id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "name": row[1],
            "created_at": row[2],
            "updated_at": row[3],
            "workspace": row[4],
            "model": row[5],
        }

    async def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        cursor = await self._db.execute(
            "SELECT id, name, created_at, updated_at, model FROM sessions ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            {"id": r[0], "name": r[1], "created_at": r[2], "updated_at": r[3], "model": r[4]}
            for r in rows
        ]

    # --- Messages ---

    async def add_message(
        self,
        session_id: str,
        message: Message,
    ) -> str:
        """Store a message in the session."""
        msg_id = uuid.uuid4().hex[:12]
        now = datetime.now(UTC).isoformat()

        tool_calls_json = json.dumps([
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            for tc in message.tool_calls
        ]) if message.tool_calls else "[]"

        usage_json = json.dumps({
            "prompt_tokens": message.token_usage.prompt_tokens if message.token_usage else 0,
            "completion_tokens": message.token_usage.completion_tokens if message.token_usage else 0,
            "total_tokens": message.token_usage.total_tokens if message.token_usage else 0,
        }) if message.token_usage else "{}"

        await self._db.execute(
            """INSERT INTO messages (id, session_id, role, content, tool_calls, tool_call_id, model, token_usage, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (msg_id, session_id, message.role.value, message.content, tool_calls_json,
             message.tool_call_id, message.model, usage_json, now),
        )

        # Update session timestamp
        await self._db.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (now, session_id),
        )
        await self._db.commit()
        return msg_id

    async def get_messages(self, session_id: str) -> list[Message]:
        """Load all messages for a session."""
        cursor = await self._db.execute(
            "SELECT role, content, tool_calls, tool_call_id, model FROM messages WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        )
        rows = await cursor.fetchall()
        messages: list[Message] = []
        for row in rows:
            tool_calls = []
            if row[2] and row[2] != "[]":
                for tc in json.loads(row[2]):
                    tool_calls.append(ToolCall(
                        id=tc.get("id", ""),
                        name=tc.get("name", ""),
                        arguments=tc.get("arguments", {}),
                    ))
            messages.append(Message(
                role=Role(row[0]),
                content=row[1] or "",
                tool_calls=tool_calls,
                tool_call_id=row[3],
                model=row[4],
            ))
        return messages

    async def get_latest_session(self, workspace: str | None = None) -> dict[str, Any] | None:
        """Get the most recent session, optionally filtered by workspace."""
        if workspace:
            cursor = await self._db.execute(
                "SELECT id, name, created_at, updated_at, workspace, model FROM sessions WHERE workspace = ? ORDER BY updated_at DESC LIMIT 1",
                (workspace,),
            )
        else:
            cursor = await self._db.execute(
                "SELECT id, name, created_at, updated_at, workspace, model FROM sessions ORDER BY updated_at DESC LIMIT 1",
            )
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "name": row[1],
            "created_at": row[2],
            "updated_at": row[3],
            "workspace": row[4],
            "model": row[5],
        }

    async def get_message_count(self, session_id: str) -> int:
        """Return the number of messages stored for a session."""
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session and its messages."""
        await self._db.execute("DELETE FROM plans WHERE session_id = ?", (session_id,))
        await self._db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        cursor = await self._db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await self._db.commit()
        return cursor.rowcount > 0

    # --- Plans (long-horizon checkpoints) ---

    async def save_plan(self, session_id: str, plan_dict: dict[str, Any]) -> str:
        """Upsert the active plan for a session.

        Only one active plan per session — we keep the plan id stable
        across saves so callers can display "Plan #<id>" without churn.
        """
        now = datetime.now(UTC).isoformat()
        tasks_json = json.dumps(plan_dict.get("tasks", []), ensure_ascii=False)
        scope = plan_dict.get("scope", "")
        summary = plan_dict.get("summary", "")

        cursor = await self._db.execute(
            "SELECT id FROM plans WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
            (session_id,),
        )
        row = await cursor.fetchone()
        if row:
            plan_id = row[0]
            await self._db.execute(
                "UPDATE plans SET scope = ?, summary = ?, tasks_json = ?, updated_at = ? WHERE id = ?",
                (scope, summary, tasks_json, now, plan_id),
            )
        else:
            plan_id = uuid.uuid4().hex[:12]
            await self._db.execute(
                "INSERT INTO plans (id, session_id, scope, summary, tasks_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (plan_id, session_id, scope, summary, tasks_json, now, now),
            )
        await self._db.commit()
        return plan_id

    async def load_plan(self, session_id: str) -> dict[str, Any] | None:
        """Return the most recent plan attached to a session, or None."""
        cursor = await self._db.execute(
            "SELECT id, scope, summary, tasks_json, created_at, updated_at "
            "FROM plans WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
            (session_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        try:
            tasks = json.loads(row[3])
        except json.JSONDecodeError:
            tasks = []
        return {
            "id": row[0],
            "scope": row[1],
            "summary": row[2],
            "tasks": tasks,
            "created_at": row[4],
            "updated_at": row[5],
        }

    async def list_plans(self, limit: int = 20) -> list[dict[str, Any]]:
        cursor = await self._db.execute(
            "SELECT id, session_id, scope, summary, tasks_json, updated_at "
            "FROM plans ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                tasks = json.loads(row[4])
            except json.JSONDecodeError:
                tasks = []
            out.append({
                "id": row[0], "session_id": row[1], "scope": row[2],
                "summary": row[3], "tasks": tasks, "updated_at": row[5],
            })
        return out
