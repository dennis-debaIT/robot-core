from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.database.db import get_connection, read_state, write_state


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


class PersonRelationshipService:
    POSITIVE_PATTERN = re.compile(
        r"\b(danke|bitte|super|toll|klasse|gut|lieb|nett|freue|cool|prima)\b",
        re.IGNORECASE,
    )
    NEGATIVE_PATTERN = re.compile(
        r"\b(nervig|genervt|blöd|doof|dumm|schlecht|sauer|wütend|gestresst|traurig|müde)\b",
        re.IGNORECASE,
    )
    HOSTILE_PATTERN = re.compile(
        r"\b(scheiße|scheisse|kacke|unfähig|idiot|halt den mund|geh weg|lass mich|verpiss|gemein)\b",
        re.IGNORECASE,
    )

    def _ensure_row(self, person_id: int) -> None:
        with get_connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM person_relationship_state WHERE person_id = ?",
                (person_id,),
            ).fetchone()
            if not exists:
                conn.execute(
                    """
                    INSERT INTO person_relationship_state(
                        person_id, warmth, tension, openness, interaction_count, last_interaction_at, updated_at
                    )
                    VALUES (?, 0.0, 0.0, 0.0, 0, NULL, ?)
                    """,
                    (person_id, now_iso()),
                )

    def get_person_state(self, person_id: int) -> dict[str, Any]:
        self._ensure_row(person_id)
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM person_relationship_state WHERE person_id = ?",
                (person_id,),
            ).fetchone()
        return dict(row) if row else {}

    def get_global_state(self) -> dict[str, Any]:
        with get_connection() as conn:
            state = read_state(conn, "global_relationship_state", None)
        return state or {
            "warmth": 0.0,
            "tension": 0.0,
            "openness": 0.0,
            "interaction_count": 0,
            "updated_at": None,
        }

    def reset_person_state(self, person_id: int) -> dict[str, Any]:
        self._ensure_row(person_id)
        timestamp = now_iso()
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE person_relationship_state
                SET warmth = 0.0, tension = 0.0, openness = 0.0,
                    interaction_count = 0, last_interaction_at = NULL, updated_at = ?
                WHERE person_id = ?
                """,
                (timestamp, person_id),
            )
        return self.get_person_state(person_id)

    def reset_global_state(self) -> dict[str, Any]:
        fresh = {
            "warmth": 0.0,
            "tension": 0.0,
            "openness": 0.0,
            "interaction_count": 0,
            "updated_at": now_iso(),
        }
        with get_connection() as conn:
            write_state(conn, "global_relationship_state", fresh)
        return self.get_global_state()

    def apply_user_message(self, *, person_id: int, message: str) -> dict[str, Any]:
        self._ensure_row(person_id)
        message = message.strip()
        positive = len(self.POSITIVE_PATTERN.findall(message))
        negative = len(self.NEGATIVE_PATTERN.findall(message))
        hostile = len(self.HOSTILE_PATTERN.findall(message))

        sentiment = clamp((positive * 0.22) - (negative * 0.18) - (hostile * 0.35), -1.0, 1.0)
        hostility = 1.0 if hostile else 0.0

        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM person_relationship_state WHERE person_id = ?",
                (person_id,),
            ).fetchone()
            current = dict(row) if row else {
                "warmth": 0.0,
                "tension": 0.0,
                "openness": 0.0,
                "interaction_count": 0,
                "last_interaction_at": None,
                "updated_at": None,
            }

            warmth = clamp((float(current["warmth"]) * 0.985) + (sentiment * 0.16) - (hostility * 0.08), -1.0, 1.0)
            tension = clamp((float(current["tension"]) * 0.985) + max(0.0, -sentiment) * 0.14 + (hostility * 0.2) - (positive * 0.04), 0.0, 1.0)
            openness = clamp((float(current["openness"]) * 0.992) + (positive * 0.06) - (hostility * 0.05), -1.0, 1.0)
            interaction_count = int(current["interaction_count"]) + 1
            timestamp = now_iso()

            conn.execute(
                """
                UPDATE person_relationship_state
                SET warmth = ?, tension = ?, openness = ?, interaction_count = ?, last_interaction_at = ?, updated_at = ?
                WHERE person_id = ?
                """,
                (warmth, tension, openness, interaction_count, timestamp, timestamp, person_id),
            )

            global_state = read_state(conn, "global_relationship_state", self.get_global_state())
            updated_global = {
                "warmth": clamp((float(global_state["warmth"]) * 0.998) + (warmth - float(current["warmth"])) * 0.06, -1.0, 1.0),
                "tension": clamp((float(global_state["tension"]) * 0.998) + (tension - float(current["tension"])) * 0.04, 0.0, 1.0),
                "openness": clamp((float(global_state["openness"]) * 0.998) + (openness - float(current["openness"])) * 0.03, -1.0, 1.0),
                "interaction_count": int(global_state.get("interaction_count", 0)) + 1,
                "updated_at": timestamp,
            }
            write_state(conn, "global_relationship_state", updated_global)

        return {
            "person_state": self.get_person_state(person_id),
            "global_state": self.get_global_state(),
            "signal": {
                "sentiment": round(sentiment, 3),
                "hostility": hostility,
                "positive_terms": positive,
                "negative_terms": negative,
                "hostile_terms": hostile,
            },
        }
