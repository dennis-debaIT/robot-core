from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database.db import get_connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class NoteService:
    def list_notes(self, person_id: int | None = None) -> list[dict[str, Any]]:
        with get_connection() as conn:
            if person_id is None:
                rows = conn.execute(
                    "SELECT * FROM person_notes ORDER BY updated_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM person_notes WHERE person_id = ? OR person_id IS NULL ORDER BY updated_at DESC",
                    (person_id,),
                ).fetchall()
        return [dict(r) for r in rows]

    def list_for_person(self, person_id: int) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM person_notes WHERE person_id = ? ORDER BY updated_at DESC",
                (person_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_global(self) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM person_notes WHERE person_id IS NULL ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get(self, note_id: int) -> dict[str, Any] | None:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM person_notes WHERE id = ?", (note_id,)
            ).fetchone()
        return dict(row) if row else None

    def create(self, title: str, content: str, person_id: int | None = None) -> dict[str, Any]:
        now = _now()
        with get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO person_notes(person_id, title, content, created_at, updated_at) VALUES (?,?,?,?,?)",
                (person_id, title.strip(), content.strip(), now, now),
            )
            row = conn.execute(
                "SELECT * FROM person_notes WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return dict(row)

    def update(self, note_id: int, title: str | None = None, content: str | None = None) -> dict[str, Any] | None:
        note = self.get(note_id)
        if not note:
            return None
        new_title   = title.strip()   if title   is not None else note["title"]
        new_content = content.strip() if content is not None else note["content"]
        with get_connection() as conn:
            conn.execute(
                "UPDATE person_notes SET title=?, content=?, updated_at=? WHERE id=?",
                (new_title, new_content, _now(), note_id),
            )
            row = conn.execute("SELECT * FROM person_notes WHERE id=?", (note_id,)).fetchone()
        return dict(row) if row else None

    def delete(self, note_id: int) -> bool:
        with get_connection() as conn:
            rc = conn.execute("DELETE FROM person_notes WHERE id=?", (note_id,)).rowcount
        return rc > 0

    def search(self, query: str, person_id: int | None = None) -> list[dict[str, Any]]:
        """Sucht in Titel und Inhalt (case-insensitiv)."""
        q = f"%{query.lower()}%"
        with get_connection() as conn:
            if person_id is not None:
                rows = conn.execute(
                    """SELECT * FROM person_notes
                    WHERE (person_id = ? OR person_id IS NULL)
                      AND (lower(title) LIKE ? OR lower(content) LIKE ?)
                    ORDER BY updated_at DESC""",
                    (person_id, q, q),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM person_notes
                    WHERE lower(title) LIKE ? OR lower(content) LIKE ?
                    ORDER BY updated_at DESC""",
                    (q, q),
                ).fetchall()
        return [dict(r) for r in rows]
