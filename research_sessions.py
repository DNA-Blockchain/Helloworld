"""Explicitly saved, local-only research sessions for evidence recall."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_SESSION_STORE = Path("dna_shell_data") / "research_sessions.sqlite3"


class ResearchSessionStore:
    def __init__(self, path: str | Path = DEFAULT_SESSION_STORE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS research_sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    query TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    model TEXT NOT NULL,
                    sources_json TEXT NOT NULL,
                    citations_json TEXT NOT NULL,
                    records_fetched INTEGER NOT NULL CHECK (records_fetched >= 0)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def save(
        self,
        *,
        query: str,
        answer: str,
        model: str,
        sources: list[str],
        citations: list[dict],
        records_fetched: int,
    ) -> dict:
        if not query.strip():
            raise ValueError("saved session query cannot be empty")
        if not answer.strip():
            raise ValueError("saved session answer cannot be empty")
        if not model.strip():
            raise ValueError("saved session model cannot be empty")
        if type(records_fetched) is not int or records_fetched < 0:
            raise ValueError("records_fetched must be a nonnegative integer")
        if not all(isinstance(source, str) and source.strip() for source in sources):
            raise ValueError("sources must contain nonempty names")
        if not all(isinstance(citation, dict) for citation in citations):
            raise ValueError("citations must contain objects")

        session = {
            "session_id": uuid.uuid4().hex,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "query": query,
            "answer": answer,
            "model": model,
            "sources": sorted(set(sources)),
            "citations": citations,
            "records_fetched": records_fetched,
            "storage": "local-only",
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO research_sessions (
                    session_id, created_at, query, answer, model, sources_json,
                    citations_json, records_fetched
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session["session_id"],
                    session["created_at"],
                    session["query"],
                    session["answer"],
                    session["model"],
                    json.dumps(session["sources"], ensure_ascii=False),
                    json.dumps(session["citations"], ensure_ascii=False),
                    records_fetched,
                ),
            )
        return session

    def list(self, *, limit: int = 20) -> list[dict]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id, created_at, query, model, sources_json,
                       records_fetched
                FROM research_sessions
                ORDER BY created_at DESC, session_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [{
            "session_id": row["session_id"],
            "created_at": row["created_at"],
            "query": row["query"],
            "model": row["model"],
            "sources": json.loads(row["sources_json"]),
            "records_fetched": row["records_fetched"],
            "storage": "local-only",
        } for row in rows]

    def get(self, session_id: str) -> dict:
        try:
            normalized_id = str(uuid.UUID(hex=session_id))
        except (ValueError, AttributeError) as error:
            raise ValueError("session ID must be a UUID") from error
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM research_sessions WHERE session_id = ?",
                (normalized_id.replace("-", ""),),
            ).fetchone()
        if row is None:
            raise KeyError(f"research session not found: {session_id}")
        return {
            "session_id": row["session_id"],
            "created_at": row["created_at"],
            "query": row["query"],
            "answer": row["answer"],
            "model": row["model"],
            "sources": json.loads(row["sources_json"]),
            "citations": json.loads(row["citations_json"]),
            "records_fetched": row["records_fetched"],
            "storage": "local-only",
        }

    def forget(self, session_id: str) -> None:
        session = self.get(session_id)
        with self._connect() as connection:
            deleted = connection.execute(
                "DELETE FROM research_sessions WHERE session_id = ?",
                (session["session_id"],),
            ).rowcount
        if deleted != 1:
            raise KeyError(f"research session not found: {session_id}")
