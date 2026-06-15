"""Hausaufgaben-Service — Erika Plus (kostenpflichtig).

Aufgabenverwaltung + Erledigungs-Log + Wochen-/Monats-/Jahresstatistik pro
Person. Completion-Events fallen selten an (wenige Einträge/Tag), daher
genügt ein einfaches Event-Log (`chore_completions`) ohne Aggregat- oder
Retention-Tabelle — "Langzeit-Statistik" entsteht einfach dadurch, dass
nichts gelöscht wird. Woche/Monat/Jahr werden per SQL-Aggregation über
Kalenderzeiträume (lokale TZ) berechnet.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.database.db import get_connection


class ChoreService:
    @staticmethod
    def _local_tz():
        try:
            return ZoneInfo(os.environ.get("TZ", "Europe/Berlin"))
        except ZoneInfoNotFoundError:
            return timezone.utc

    @staticmethod
    def _period_start_utc(period: str, now_local: datetime) -> datetime:
        if period == "month":
            start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif period == "year":
            start = now_local.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:  # week (Montag 00:00 der laufenden Kalenderwoche)
            start = (now_local - timedelta(days=now_local.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        return start.astimezone(timezone.utc)

    @staticmethod
    def _task_row_to_dict(row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "icon": row["icon"],
            "sort_order": row["sort_order"],
            "active": bool(row["active"]),
        }

    def list_tasks(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM chore_tasks"
        if not include_inactive:
            query += " WHERE active = 1"
        query += " ORDER BY sort_order ASC, name ASC"
        with get_connection() as conn:
            rows = conn.execute(query).fetchall()
        return [self._task_row_to_dict(row) for row in rows]

    def create_task(self, name: str, icon: str | None = None) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with get_connection() as conn:
            next_sort = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM chore_tasks"
            ).fetchone()["n"]
            cur = conn.execute(
                """
                INSERT INTO chore_tasks(name, icon, sort_order, active, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (name, icon, next_sort, now, now),
            )
            row = conn.execute("SELECT * FROM chore_tasks WHERE id = ?", (cur.lastrowid,)).fetchone()
        return self._task_row_to_dict(row)

    def update_task(
        self,
        task_id: int,
        name: str | None = None,
        icon: str | None = None,
        sort_order: int | None = None,
        active: bool | None = None,
    ) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc).isoformat()
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM chore_tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                return None
            new_name = name if name is not None else row["name"]
            new_icon = icon if icon is not None else row["icon"]
            new_sort = sort_order if sort_order is not None else row["sort_order"]
            new_active = int(active) if active is not None else row["active"]
            conn.execute(
                "UPDATE chore_tasks SET name=?, icon=?, sort_order=?, active=?, updated_at=? WHERE id=?",
                (new_name, new_icon, new_sort, new_active, now, task_id),
            )
            row = conn.execute("SELECT * FROM chore_tasks WHERE id = ?", (task_id,)).fetchone()
        return self._task_row_to_dict(row)

    def delete_task(self, task_id: int) -> bool:
        """Soft-Delete: deaktiviert die Aufgabe, behält historische Completions."""
        now = datetime.now(timezone.utc).isoformat()
        with get_connection() as conn:
            cur = conn.execute(
                "UPDATE chore_tasks SET active = 0, updated_at = ? WHERE id = ?",
                (now, task_id),
            )
        return cur.rowcount > 0

    def log_completion(self, task_id: int, person_id: int) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO chore_completions(task_id, person_id, completed_at) VALUES (?, ?, ?)",
                (task_id, person_id, now.isoformat()),
            )
        return {"id": cur.lastrowid, "task_id": task_id, "person_id": person_id, "completed_at": now.isoformat()}

    def delete_completion(self, completion_id: int) -> bool:
        with get_connection() as conn:
            cur = conn.execute("DELETE FROM chore_completions WHERE id = ?", (completion_id,))
        return cur.rowcount > 0

    def task_stats(self, task_id: int, period: str = "week") -> dict[str, Any] | None:
        tz = self._local_tz()
        now_local = datetime.now(tz)
        start_utc = self._period_start_utc(period, now_local)
        with get_connection() as conn:
            task_row = conn.execute("SELECT name FROM chore_tasks WHERE id = ?", (task_id,)).fetchone()
            if not task_row:
                return None
            rows = conn.execute(
                """
                SELECT p.id AS person_id, p.name AS name, COUNT(*) AS count
                FROM chore_completions c
                JOIN persons p ON p.id = c.person_id
                WHERE c.task_id = ? AND c.completed_at >= ?
                GROUP BY p.id, p.name
                ORDER BY count DESC, p.name ASC
                """,
                (task_id, start_utc.isoformat()),
            ).fetchall()
        persons = [{"person_id": r["person_id"], "name": r["name"], "count": r["count"]} for r in rows]
        return {
            "task_id": task_id,
            "task_name": task_row["name"],
            "period": period,
            "persons": persons,
            "leader": persons[0] if persons else None,
        }

    def overall_weekly_stats(self) -> dict[str, Any]:
        tz = self._local_tz()
        now_local = datetime.now(tz)
        start_utc = self._period_start_utc("week", now_local)
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT p.id AS person_id, p.name AS name, COUNT(*) AS count
                FROM chore_completions c
                JOIN persons p ON p.id = c.person_id
                JOIN chore_tasks t ON t.id = c.task_id
                WHERE t.active = 1 AND c.completed_at >= ?
                GROUP BY p.id, p.name
                ORDER BY count DESC, p.name ASC
                """,
                (start_utc.isoformat(),),
            ).fetchall()
        persons = [{"person_id": r["person_id"], "name": r["name"], "count": r["count"]} for r in rows]
        return {
            "period": "week",
            "persons": persons,
            "leader": persons[0] if persons else None,
        }
