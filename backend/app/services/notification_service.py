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
                """INSERT INTO notification_rules(label, entity_id, condition_type, condition_value, message, enabled, use_llm, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (label, entity_id, condition_type,
                 str(payload.get("condition_value") or "").strip() or None,
                 str(payload.get("message") or "").strip() or None,
                 1 if payload.get("enabled", True) else 0,
                 1 if payload.get("use_llm") else 0, now),
            )
            rule_id = cur.lastrowid
        return {"id": rule_id, "label": label}

    def update_rule(self, rule_id: int, payload: dict[str, Any]) -> None:
        with get_connection() as conn:
            conn.execute(
                """UPDATE notification_rules SET label=?, entity_id=?, condition_type=?,
                   condition_value=?, message=?, enabled=?, use_llm=? WHERE id=?""",
                (str(payload.get("label") or "").strip(),
                 str(payload.get("entity_id") or "").strip(),
                 str(payload.get("condition_type") or "").strip(),
                 str(payload.get("condition_value") or "").strip() or None,
                 str(payload.get("message") or "").strip() or None,
                 1 if payload.get("enabled", True) else 0,
                 1 if payload.get("use_llm") else 0,
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

    def delete_all(self) -> None:
        with get_connection() as conn:
            conn.execute("DELETE FROM notifications")

    def _create_notification(
        self, conn: Any, rule_id: int | None, message: str, entity_id: str | None, title: str = "Erika"
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            "INSERT INTO notifications(rule_id, message, entity_id, read, created_at) VALUES (?,?,?,0,?)",
            (rule_id, message, entity_id, now),
        )
        try:
            from app.services.push_service import send_notification
            send_notification(title=title, body=message, channel="reminders")
        except Exception as exc:
            from app.audit.service import AuditService
            AuditService().log_warn(source="push", message=f"Push-Weiterleitung fehlgeschlagen: {type(exc).__name__}: {exc}")
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
                now_iso = datetime.now(timezone.utc).isoformat()
                last_fired = prev["last_fired_at"] if prev else None

                is_change_type = condition_type in ("changed_to", "changed")

                if is_change_type:
                    # Für Zustands-Änderungen: feuert bei echter Transition, Cooldown 5 Min.
                    condition_met = self._evaluate(condition_type, current_value, condition_value, last_value)
                    cooldown_ok = True
                    if last_fired:
                        try:
                            from datetime import timedelta
                            elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(last_fired)
                            cooldown_ok = elapsed.total_seconds() >= 300
                        except Exception:
                            pass
                    if condition_met and cooldown_ok:
                        fire = True
                else:
                    # Für Schwellwerte: einmal feuern wenn Bedingung eintritt, Reset wenn nicht mehr
                    condition_met = self._evaluate(condition_type, current_value, condition_value, last_value)
                    if condition_met and not condition_active:
                        fire = True
                    elif not condition_met and condition_active:
                        conn.execute(
                            "INSERT OR REPLACE INTO notification_rule_state(rule_id, last_value, last_fired_at, condition_active) VALUES (?,?,?,0)",
                            (rule_id, current_value, last_fired),
                        )

                if fire:
                    if rule["use_llm"]:
                        style_examples = self._sibling_style_examples(conn, label, rule_id)
                        msg = self._llm_message(label, condition_type, condition_value, current_value, style_examples) \
                            or custom_msg or self._auto_message(label, condition_type, condition_value, current_value)
                    else:
                        msg = custom_msg or self._auto_message(label, condition_type, condition_value, current_value)
                    notif_id = self._create_notification(conn, rule_id, msg, entity_id, title=label or "Erika")
                    conn.execute(
                        "INSERT OR REPLACE INTO notification_rule_state(rule_id, last_value, last_fired_at, condition_active) VALUES (?,?,?,1)",
                        (rule_id, current_value, now_iso),
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

    def create_manual_notification(self, message: str, entity_id: str | None = None, title: str = "Erika") -> int:
        """Für Benachrichtigungen ohne zugehörige Regel (z.B. proaktive
        Kalender-Erinnerungen, Insights) — nutzt dieselbe Zustellung
        (Glocke + TTS + Push) wie regelbasierte Benachrichtigungen."""
        with get_connection() as conn:
            return self._create_notification(conn, None, message, entity_id, title=title)

    def _entities_with_enabled_rules(self) -> set[str]:
        """Entity-IDs, für die bereits eine aktive Benachrichtigungsregel
        existiert — genutzt vom Roboter-Status-Insight, um Roboter nicht
        doppelt zu melden, die schon über eine eigene Regel abgedeckt sind."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT entity_id FROM notification_rules WHERE enabled=1"
            ).fetchall()
        return {row["entity_id"] for row in rows if row["entity_id"]}

    @staticmethod
    def _sibling_style_examples(conn: Any, label: str, exclude_rule_id: int) -> list[str]:
        """Holt vorhandene eigene Texte anderer Regeln zum selben Gerät
        (grobe Zuordnung über das erste Wort des Labels, z.B. "Robert") als
        Stilvorlage fürs LLM — damit generierte Meldungen zum etablierten
        Ton passen statt generisch zu klingen."""
        prefix = (label or "").split()[0] if label else ""
        if not prefix:
            return []
        rows = conn.execute(
            "SELECT message FROM notification_rules WHERE id != ? AND message IS NOT NULL AND label LIKE ?",
            (exclude_rule_id, f"%{prefix}%"),
        ).fetchall()
        return [r["message"] for r in rows if r["message"]]

    @staticmethod
    def _llm_message(label: str, condition_type: str, target: str, current: str, style_examples: list[str] | None = None) -> str | None:
        """Lässt das LLM eine natürliche Formulierung für ein ausgelöstes
        Ereignis bauen. Gibt bei jedem Fehler/leerer Antwort None zurück —
        der Aufrufer fällt dann auf die feste Vorlage zurück, es entsteht
        nie eine leere Benachrichtigung."""
        try:
            from app.brain.llm_client import LLMRouter
            # Rohe HA-Zustandswerte (z.B. "outside_wire") sagen dem LLM nichts —
            # es hat "outside_wire" zuletzt fälschlich als "wartet auf sein Kabel"
            # gedeutet statt "außerhalb des Begrenzungsdrahts". Über dieselbe
            # Übersetzungstabelle wie im Roboter-Fehlerprotokoll auflösen, bevor
            # der Wert in den Prompt wandert.
            from app.services.robot_service import RobotService
            _translate = RobotService()._translate_error_state
            target_de = _translate(target) if target else target
            current_de = _translate(current) if current else current

            cond_map = {
                "lt": f"ist unter {target_de} gefallen (aktuell {current_de})",
                "gt": f"ist über {target_de} gestiegen (aktuell {current_de})",
                "eq": f"hat den Wert {target_de} erreicht",
                "changed_to": f"ist jetzt im Zustand '{target_de}'",
                "changed": f"hat sich geändert auf '{current_de}'",
            }
            event = cond_map.get(condition_type, f"{condition_type} ({current_de})")

            examples_block = ""
            if style_examples:
                examples_lines = "\n".join(f"- {e}" for e in style_examples[:4])
                examples_block = (
                    "\n\nSo klangen frühere Meldungen zu diesem Gerät (genau diesen Ton treffen):\n"
                    f"{examples_lines}"
                )

            prompt = (
                f"Ereignis: {label} {event}."
                f"{examples_block}\n\n"
                "Formuliere daraus eine kurze, NEUE Benachrichtigung im selben Tonfall wie oben "
                "(max. 1 Satz, kein Markdown, keine Anführungszeichen, auf Deutsch). "
                "Nicht eines der Beispiele wiederholen, sondern eine eigene, passende Formulierung finden."
            )
            result = LLMRouter().generate(
                {
                    "messages": [
                        {"role": "system", "content": (
                            "Du bist Erika, ein Haushaltsassistent mit trocken-humorvollem, leicht "
                            "süffisantem Tonfall — kein neutraler Systemton. Bei Fehlern oder Problemen "
                            "(feststecken, blockiert, Kabel verloren, hängengeblieben o.ä.) darf es ruhig "
                            "sarkastisch werden. Bei normalen Status-Meldungen (läuft, ist fertig, ist "
                            "zurück) bleibt der Ton locker mit einem Augenzwinkern, nicht übertrieben. "
                            "Erfinde dabei keine Gegenstände, Werkzeuge, Körperteile oder biologischen "
                            "Handlungen (Atmen, Luft anhalten, Gefühle spüren o.ä.), die zum jeweiligen "
                            "Gerät nicht passen — es ist eine Maschine, kein Lebewesen (ein Mähroboter hat "
                            "z.B. Klingen, keine Gabel, und atmet nicht). Ein Zustand wie 'Angehoben' "
                            "bedeutet, dass der Hubsensor kurz ausgelöst hat (z.B. weil er hochgehoben "
                            "wurde) — nicht, dass er dauerhaft in der Luft schwebt oder darauf wartet, "
                            "wieder den Boden zu berühren. "
                            "Antworte ausschließlich auf Deutsch, kurz und natürlich."
                        )},
                        {"role": "user", "content": prompt},
                    ],
                    "llm_max_tokens": 60,
                },
                timeout_seconds=8,
            )
            text = (result.get("reply") or "").strip()
            return text or None
        except Exception as exc:
            from app.audit.service import AuditService
            AuditService().log_warn(source="notification", message=f"LLM-Formulierung fehlgeschlagen ({label}): {type(exc).__name__}: {exc}")
            return None

    @staticmethod
    def _auto_message(label: str, condition_type: str, target: str, current: str) -> str:
        try:
            from app.services.robot_service import RobotService
            _translate = RobotService()._translate_error_state
            target = _translate(target) if target else target
            current = _translate(current) if current else current
        except Exception:
            pass
        cond_map = {
            "lt": f"unter {target}",
            "gt": f"über {target}",
            "eq": f"ist {target}",
            "changed_to": f"gewechselt zu {target}",
            "changed": f"hat sich geändert auf {current}",
        }
        cond = cond_map.get(condition_type, condition_type)
        return f"{label}: {cond}"
