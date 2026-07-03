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
        level: str = "info",
    ) -> dict[str, Any]:
        payload = json.dumps(details or {}, ensure_ascii=False)
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO audit_log(
                    action, level, target_type, target_id, actor_type, actor_id, summary, details, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (action, level, target_type, target_id, actor_type, actor_id, summary, payload, now_iso()),
            )
            row = conn.execute("SELECT * FROM audit_log WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self._row_to_dict(row) if row else {}

    def log_info(self, *, source: str, message: str, details: dict[str, Any] | None = None) -> None:
        try:
            self.log(
                action=source,
                target_type="system",
                target_id=source,
                actor_type="system",
                actor_id="background",
                summary=message[:300],
                details=details,
                level="info",
            )
        except Exception:
            pass

    def log_warn(self, *, source: str, message: str, details: dict[str, Any] | None = None) -> None:
        try:
            self.log(
                action=source,
                target_type="system",
                target_id=source,
                actor_type="system",
                actor_id="background",
                summary=message[:300],
                details=details,
                level="warning",
            )
        except Exception:
            pass

    def log_error(self, *, source: str, message: str, details: dict[str, Any] | None = None) -> None:
        try:
            self.log(
                action="system.error",
                target_type="system",
                target_id=source,
                actor_type="system",
                actor_id="background",
                summary=message[:300],
                details=details,
                level="error",
            )
        except Exception:
            pass

    def list_entries(
        self,
        limit: int = 100,
        level: str | None = None,
        action: str | None = None,
    ) -> list[dict[str, Any]]:
        effective_limit = max(1, min(limit, 500))
        conditions = []
        params: list[Any] = []
        if level:
            conditions.append("level = ?")
            params.append(level)
        if action:
            conditions.append("action LIKE ?")
            params.append(f"%{action}%")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(effective_limit)
        with get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM audit_log {where} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["details"] = json.loads(item["details"]) if item.get("details") else {}
        if "level" not in item:
            item["level"] = "info"
        return item
