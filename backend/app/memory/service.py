from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.database.db import get_connection, memory_fingerprint


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryService:
    def list_memories(self, status: str | None = None, subject: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM memory_entries"
        params: list[Any] = []
        clauses: list[str] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if subject:
            clauses.append("lower(coalesce(subject, '')) = lower(?)")
            params.append(subject)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC"

        with get_connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def list_approved_for_subject(self, subject: str) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_entries
                WHERE status = 'approved' AND lower(coalesce(subject, '')) = lower(?)
                ORDER BY id DESC
                """,
                (subject,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_by_subject(self, subject: str) -> int:
        with get_connection() as conn:
            return conn.execute(
                "DELETE FROM memory_entries WHERE lower(coalesce(subject, '')) = lower(?)",
                (subject,),
            ).rowcount

    def find_duplicate(
        self,
        *,
        subject: str | None,
        category: str,
        content: str,
        statuses: tuple[str, ...] = ("pending", "approved"),
    ) -> dict[str, Any] | None:
        fingerprint = memory_fingerprint(subject, category, content)
        placeholders = ",".join("?" for _ in statuses)

        with get_connection() as conn:
            row = conn.execute(
                f"""
                SELECT * FROM memory_entries
                WHERE fingerprint = ? AND status IN ({placeholders})
                ORDER BY id DESC
                LIMIT 1
                """,
                (fingerprint, *statuses),
            ).fetchone()

        return dict(row) if row else None

    def propose(
        self,
        content: str,
        category: str = "general",
        subject: str | None = None,
        source: str = "api",
        dedupe_statuses: tuple[str, ...] | None = None,
        candidate_kind: str | None = None,
        decision_reason: str | None = None,
        confidence: float | None = None,
    ) -> dict[str, Any]:
        if dedupe_statuses:
            existing = self.find_duplicate(
                subject=subject,
                category=category,
                content=content,
                statuses=dedupe_statuses,
            )
            if existing:
                return existing

        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO memory_entries(
                    subject, category, content, source, status, created_at, fingerprint,
                    candidate_kind, decision_reason, confidence
                )
                VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
                """,
                (
                    subject,
                    category,
                    content,
                    source,
                    now_iso(),
                    memory_fingerprint(subject, category, content),
                    candidate_kind,
                    decision_reason,
                    confidence,
                ),
            )
            row = conn.execute("SELECT * FROM memory_entries WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return dict(row)

    def approve(self, memory_id: int) -> dict[str, Any] | None:
        return self._review(memory_id, "approved")

    def reject(self, memory_id: int) -> dict[str, Any] | None:
        return self._review(memory_id, "rejected")

    def update_content(self, memory_id: int, new_content: str) -> dict[str, Any] | None:
        content = new_content.strip()
        if not content:
            return None
        with get_connection() as conn:
            conn.execute(
                "UPDATE memory_entries SET content = ? WHERE id = ?",
                (content, memory_id),
            )
            row = conn.execute("SELECT * FROM memory_entries WHERE id = ?", (memory_id,)).fetchone()
        return dict(row) if row else None

    def _review(self, memory_id: int, status: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            conn.execute(
                "UPDATE memory_entries SET status = ?, reviewed_at = ? WHERE id = ?",
                (status, now_iso(), memory_id),
            )
            row = conn.execute("SELECT * FROM memory_entries WHERE id = ?", (memory_id,)).fetchone()
        return dict(row) if row else None

    def extract_proposals_from_chat(self, text: str, person_name: str | None) -> list[dict[str, Any]]:
        normalized = text.strip()
        proposals: list[dict[str, Any]] = []

        name_match = re.search(
            r"\b(?:ich hei(?:ss|ß)e|mein name ist)\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß-]*)",
            normalized,
            re.IGNORECASE,
        )
        if name_match:
            name = name_match.group(1).strip()
            proposals.append(
                self.propose(
                    content=f"Der Nutzer heißt {name}.",
                    category="person_profile",
                    subject=name,
                    source="chat_auto",
                    dedupe_statuses=("pending", "approved"),
                )
            )

        likes_match = re.search(r"\b(?:ich mag|ich liebe)\s+(.+)", normalized, re.IGNORECASE)
        if likes_match:
            preference = likes_match.group(1).strip().rstrip(".!?")
            subject = person_name or "unknown_user"
            proposals.append(
                self.propose(
                    content=f"{subject} mag {preference}.",
                    category="preference",
                    subject=subject,
                    source="chat_auto",
                    dedupe_statuses=("pending", "approved"),
                )
            )

        return proposals
