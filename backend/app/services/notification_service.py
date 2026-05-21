from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database.db import get_connection
from app.services.homeassistant_service import HomeAssistantService


class NotificationService:
    def __init__(self, ha: HomeAssistantService | None = None) -> None:
        self.ha = ha or HomeAssistantService()

    # ── Regeln ───────────────────────────────────────────────────

    def list_rules(self) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM notification_rules ORDER BY created_at ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def create_rule(self, payload: dict[str, Any]) -> dict[str, Any]:
        label = str(payload.get("label") or "").strip()
        entity_id = str(payload.get("entity_id") or "").strip()
        condition_type = str(payload.get("condition_type") or "").strip()
        if not label or not entity_id or not condition_type:
            raise ValueError("label, entity_id und condition_type sind Pflichtfelder")
        now = datetime.now(timezone.utc).isoformat()
        with get_connection() as conn:
            cur = conn.execute(
                """INSERT INTO notification_rules(label, entity_id, condition_type, condition_value, message, enabled, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (label, entity_id, condition_type,
                 str(payload.get("condition_value") or "").strip() or None,
                 str(payload.get("message") or "").strip() or None,
                 1 if payload.get("enabled", True) else 0, now),
            )
            rule_id = cur.lastrowid
        return {"id": rule_id, "label": label}

    def update_rule(self, rule_id: int, payload: dict[str, Any]) -> None:
        with get_connection() as conn:
            conn.execute(
                """UPDATE notification_rules SET label=?, entity_id=?, condition_type=?,
                   condition_value=?, message=?, enabled=? WHERE id=?""",
                (str(payload.get("label") or "").strip(),
                 str(payload.get("entity_id") or "").strip(),
                 str(payload.get("condition_type") or "").strip(),
                 str(payload.get("condition_value") or "").strip() or None,
                 str(payload.get("message") or "").strip() or None,
                 1 if payload.get("enabled", True) else 0,
                 rule_id),
            )

    def delete_rule(self, rule_id: int) -> None:
        with get_connection() as conn:
            conn.execute("DELETE FROM notification_rules WHERE id=?", (rule_id,))
            conn.execute("DELETE FROM notification_rule_state WHERE rule_id=?", (rule_id,))

    # ── Benachrichtigungen ────────────────────────────────────────

    def list_notifications(self, unread_only: bool = False) -> list[dict[str, Any]]:
        with get_connection() as conn:
            if unread_only:
                rows = conn.execute(
                    "SELECT * FROM notifications WHERE read=0 ORDER BY created_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM notifications ORDER BY created_at DESC LIMIT 50"
                ).fetchall()
        return [dict(r) for r in rows]

    def unread_count(self) -> int:
        with get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) as n FROM notifications WHERE read=0").fetchone()
        return row["n"] if row else 0

    def mark_read(self, notification_id: int) -> None:
        with get_connection() as conn:
            conn.execute("UPDATE notifications SET read=1 WHERE id=?", (notification_id,))

    def mark_all_read(self) -> None:
        with get_connection() as conn:
            conn.execute("UPDATE notifications SET read=1")

    def delete_notification(self, notification_id: int) -> None:
        with get_connection() as conn:
            conn.execute("DELETE FROM notifications WHERE id=?", (notification_id,))

    def _create_notification(self, conn: Any, rule_id: int | None, message: str, entity_id: str | None) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            "INSERT INTO notifications(rule_id, message, entity_id, read, created_at) VALUES (?,?,?,0,?)",
            (rule_id, message, entity_id, now),
        )
        return cur.lastrowid

    # ── Regel-Check-Loop ─────────────────────────────────────────

    def check_rules(self) -> list[dict[str, Any]]:
        """Prüft alle aktiven Regeln gegen HA-Zustände. Gibt neue Benachrichtigungen zurück."""
        triggered: list[dict[str, Any]] = []
        with get_connection() as conn:
            rules = conn.execute(
                "SELECT * FROM notification_rules WHERE enabled=1"
            ).fetchall()

            for rule in rules:
                rule_id = rule["id"]
                entity_id = rule["entity_id"]
                condition_type = rule["condition_type"]
                condition_value = rule["condition_value"] or ""
                custom_msg = rule["message"] or ""
                label = rule["label"]

                state_row = self.ha.get_state(entity_id)
                if not state_row:
                    continue
                current_value = str(state_row.get("state") or "").strip()
                if current_value in ("unavailable", "unknown", ""):
                    continue

                prev = conn.execute(
                    "SELECT last_value, condition_active, last_fired_at FROM notification_rule_state WHERE rule_id=?",
                    (rule_id,)
                ).fetchone()
                last_value = prev["last_value"] if prev else None
                condition_active = bool(prev["condition_active"]) if prev else False

                fire = False
                condition_met = self._evaluate(condition_type, current_value, condition_value, last_value)

                if condition_met and not condition_active:
                    fire = True
                elif not condition_met and condition_active:
                    # Bedingung nicht mehr erfüllt → Reset
                    conn.execute(
                        "INSERT OR REPLACE INTO notification_rule_state(rule_id, last_value, last_fired_at, condition_active) VALUES (?,?,?,0)",
                        (rule_id, current_value, prev["last_fired_at"] if prev else None),
                    )

                if fire:
                    msg = custom_msg or self._auto_message(label, condition_type, condition_value, current_value)
                    notif_id = self._create_notification(conn, rule_id, msg, entity_id)
                    conn.execute(
                        "INSERT OR REPLACE INTO notification_rule_state(rule_id, last_value, last_fired_at, condition_active) VALUES (?,?,?,1)",
                        (rule_id, current_value, datetime.now(timezone.utc).isoformat()),
                    )
                    triggered.append({"id": notif_id, "message": msg, "entity_id": entity_id})
                else:
                    conn.execute(
                        "INSERT OR IGNORE INTO notification_rule_state(rule_id, last_value, condition_active) VALUES (?,?,?)",
                        (rule_id, current_value, 1 if condition_active else 0),
                    )
                    conn.execute(
                        "UPDATE notification_rule_state SET last_value=? WHERE rule_id=?",
                        (current_value, rule_id),
                    )

        return triggered

    @staticmethod
    def _evaluate(condition_type: str, current: str, target: str, last: str | None) -> bool:
        try:
            if condition_type == "lt":
                return float(current) < float(target)
            if condition_type == "gt":
                return float(current) > float(target)
            if condition_type == "eq":
                return current.lower() == target.lower()
            if condition_type == "changed_to":
                return current.lower() == target.lower() and (last is None or last.lower() != target.lower())
            if condition_type == "changed":
                return last is not None and current != last
        except (TypeError, ValueError):
            pass
        return False

    @staticmethod
    def _auto_message(label: str, condition_type: str, target: str, current: str) -> str:
        cond_map = {
            "lt": f"unter {target}",
            "gt": f"über {target}",
            "eq": f"ist {target}",
            "changed_to": f"gewechselt zu {target}",
            "changed": f"hat sich geändert auf {current}",
        }
        cond = cond_map.get(condition_type, condition_type)
        return f"{label}: {cond}"
