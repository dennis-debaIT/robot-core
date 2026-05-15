from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.database.db import get_connection


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditService:
    def log(
        self,
        *,
        action: str,
        target_type: str,
        target_id: str | None = None,
        actor_type: str = "local_admin",
        actor_id: str | None = "local_console",
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = json.dumps(details or {}, ensure_ascii=False)
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO audit_log(
                    action, target_type, target_id, actor_type, actor_id, summary, details, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (action, target_type, target_id, actor_type, actor_id, summary, payload, now_iso()),
            )
            row = conn.execute("SELECT * FROM audit_log WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self._row_to_dict(row) if row else {}

    def list_entries(self, limit: int = 100) -> list[dict[str, Any]]:
        effective_limit = max(1, min(limit, 500))
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM audit_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (effective_limit,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["details"] = json.loads(item["details"]) if item.get("details") else {}
        return item
