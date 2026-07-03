from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database.db import get_connection
from app.memory.service import MemoryService as _MemSvc


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_TRAIT_TO_MEM_CATS: dict[str, list[str]] = {
    "preference": ["preference"],
    "dislike":    ["dislike"],
    "interest":   ["interest", "interest_signal"],
    "age":        ["age"],
    "favorite_color":  ["favorite_color", "favorite_colour"],
    "favorite_food":   ["favorite_food"],
    "favorite_drink":  ["favorite_drink"],
    "occupation":      ["occupation"],
    "residence":       ["residence"],
    "hometown":        ["hometown"],
    "nickname":        ["nickname"],
}


class PersonProfileService:
    SINGLE_VALUE_TRAITS = {
        "person_profile",
        "height",
        "eye_color",
        "favorite_color",
        "age",
        "occupation",
        "hometown",
        "residence",
        "language",
        "favorite_food",
        "favorite_drink",
        "response_humor_preference",
        "response_style_preference",
        "response_length_preference",
    }

    @staticmethod
    def _normalize_name(name: str) -> str:
        return " ".join(name.strip().split())

    @staticmethod
    def _normalize_value(value: str) -> str:
        return " ".join(value.strip().split())

    def ensure_person(self, name: str) -> int:
        normalized_name = self._normalize_name(name)
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM persons WHERE lower(name) = lower(?)",
                (normalized_name,),
            ).fetchone()
            if row:
                return row["id"]

            cursor = conn.execute(
                """
                INSERT INTO persons(name, created_at, updated_at)
                VALUES (?, ?, ?)
                """,
                (normalized_name, now_iso(), now_iso()),
            )
            return int(cursor.lastrowid)

    def upsert_fact(
        self,
        *,
        person_name: str,
        trait_type: str,
        value: str,
        source_memory_id: int | None,
        confidence: float | None,
    ) -> dict[str, Any]:
        result = self.upsert_fact_resolved(
            person_name=person_name,
            trait_type=trait_type,
            value=value,
            source_memory_id=source_memory_id,
            confidence=confidence,
        )
        return result["person"]

    def upsert_fact_resolved(
        self,
        *,
        person_name: str,
        trait_type: str,
        value: str,
        source_memory_id: int | None,
        confidence: float | None,
    ) -> dict[str, Any]:
        normalized_person_name = self._normalize_name(person_name)
        normalized_value = self._normalize_value(value)
        person_id = self.ensure_person(normalized_person_name)
        timestamp = now_iso()
        conflict: dict[str, Any] | None = None

        with get_connection() as conn:
            if trait_type in self.SINGLE_VALUE_TRAITS:
                previous = conn.execute(
                    """
                    SELECT id, value, source_memory_id, confidence
                    FROM person_profile_facts
                    WHERE person_id = ?
                      AND trait_type = ?
                      AND lower(value) <> lower(?)
                    """,
                    (person_id, trait_type, normalized_value),
                ).fetchall()
                if previous:
                    conflict = {
                        "type": "single_value_replaced",
                        "trait_type": trait_type,
                        "old_values": [dict(row) for row in previous],
                        "new_value": normalized_value,
                    }
                conn.execute(
                    """
                    DELETE FROM person_profile_facts
                    WHERE person_id = ?
                      AND trait_type = ?
                      AND lower(value) <> lower(?)
                    """,
                    (person_id, trait_type, normalized_value),
                )

            existing = conn.execute(
                """
                SELECT id
                FROM person_profile_facts
                WHERE person_id = ?
                  AND trait_type = ?
                  AND lower(value) = lower(?)
                LIMIT 1
                """,
                (person_id, trait_type, normalized_value),
            ).fetchone()

            if trait_type == "preference":
                opposite = conn.execute(
                    """
                    SELECT id, value, source_memory_id, confidence
                    FROM person_profile_facts
                    WHERE person_id = ?
                      AND trait_type = 'dislike'
                      AND lower(value) = lower(?)
                    """,
                    (person_id, normalized_value),
                ).fetchall()
                if opposite:
                    conflict = {
                        "type": "preference_overrode_dislike",
                        "trait_type": trait_type,
                        "old_values": [dict(row) for row in opposite],
                        "new_value": normalized_value,
                    }
                    conn.execute(
                        """
                        DELETE FROM person_profile_facts
                        WHERE person_id = ?
                          AND trait_type = 'dislike'
                          AND lower(value) = lower(?)
                        """,
                        (person_id, normalized_value),
                    )
            elif trait_type == "dislike":
                opposite = conn.execute(
                    """
                    SELECT id, value, source_memory_id, confidence
                    FROM person_profile_facts
                    WHERE person_id = ?
                      AND trait_type IN ('preference', 'interest')
                      AND lower(value) = lower(?)
                    """,
                    (person_id, normalized_value),
                ).fetchall()
                if opposite:
                    conflict = {
                        "type": "dislike_overrode_preference",
                        "trait_type": trait_type,
                        "old_values": [dict(row) for row in opposite],
                        "new_value": normalized_value,
                    }
                    conn.execute(
                        """
                        DELETE FROM person_profile_facts
                        WHERE person_id = ?
                          AND trait_type IN ('preference', 'interest')
                          AND lower(value) = lower(?)
                        """,
                        (person_id, normalized_value),
                    )

            if existing:
                conn.execute(
                    """
                    UPDATE person_profile_facts
                    SET value = ?, source_memory_id = ?, confidence = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (normalized_value, source_memory_id, confidence, timestamp, existing["id"]),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO person_profile_facts(
                        person_id, trait_type, value, source_memory_id, confidence, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (person_id, trait_type, normalized_value, source_memory_id, confidence, timestamp, timestamp),
                )

            conn.execute(
                "UPDATE persons SET updated_at = ? WHERE id = ?",
                (timestamp, person_id),
            )

        # Memories der verdrängten Gegenkategorie bereinigen
        if trait_type == "dislike":
            # Preference- und Interest-Memories für diesen Wert löschen
            _MemSvc().delete_by_value(
                normalized_person_name,
                ["preference", "interest", "interest_signal"],
                normalized_value,
            )
        elif trait_type == "preference" and conflict and conflict.get("type") == "preference_overrode_dislike":
            # Dislike-Memories für diesen Wert löschen
            _MemSvc().delete_by_value(
                normalized_person_name,
                ["dislike"],
                normalized_value,
            )

        return {
            "person": self.get_person(normalized_person_name),
            "conflict": conflict,
        }

    def remove_fact_by_memory(self, source_memory_id: int) -> dict[str, Any] | None:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT p.name
                FROM person_profile_facts f
                JOIN persons p ON p.id = f.person_id
                WHERE f.source_memory_id = ?
                LIMIT 1
                """,
                (source_memory_id,),
            ).fetchone()
            if not row:
                return None

            conn.execute(
                "DELETE FROM person_profile_facts WHERE source_memory_id = ?",
                (source_memory_id,),
            )

        return self.get_person(row["name"])

    def clear_trait(self, person_name: str, trait_type: str) -> dict[str, Any] | None:
        normalized_person_name = self._normalize_name(person_name)
        person = self.get_person(normalized_person_name)
        if not person:
            return None

        with get_connection() as conn:
            conn.execute(
                """
                DELETE FROM person_profile_facts
                WHERE person_id = ? AND trait_type = ?
                """,
                (person["id"], trait_type),
            )
            conn.execute(
                "UPDATE persons SET updated_at = ? WHERE id = ?",
                (now_iso(), person["id"]),
            )

        return self.get_person(normalized_person_name)

    def get_person(self, name: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            person = conn.execute(
                "SELECT * FROM persons WHERE lower(name) = lower(?)",
                (name,),
            ).fetchone()
            if not person:
                return None

            facts = conn.execute(
                """
                SELECT id, trait_type, value, source_memory_id, confidence, created_at, updated_at
                FROM person_profile_facts
                WHERE person_id = ?
                ORDER BY trait_type, value
                """,
                (person["id"],),
            ).fetchall()

        return {
            "id": person["id"],
            "name": person["name"],
            "gender": person["gender"],
            "role": person["role"] if "role" in person.keys() else None,
            "emoji": person["emoji"] if "emoji" in person.keys() else None,
            "created_at": person["created_at"],
            "updated_at": person["updated_at"],
            "facts": [dict(row) for row in facts],
        }

    def get_person_by_id(self, person_id: int) -> dict[str, Any] | None:
        with get_connection() as conn:
            person = conn.execute(
                "SELECT * FROM persons WHERE id = ?",
                (person_id,),
            ).fetchone()
            if not person:
                return None
        return self.get_person(person["name"])

    def ensure_person_stub(self, person_name: str) -> dict[str, Any]:
        self.ensure_person(person_name)
        return self.get_person(person_name) or {
            "id": None,
            "name": person_name,
            "created_at": None,
            "updated_at": None,
            "facts": [],
        }

    def update_meta(self, person_id: int, *, role: str | None = ..., emoji: str | None = ...) -> dict[str, Any] | None:
        _VALID_ROLES = {None, "adult_male", "adult_female", "child_male", "child_female"}
        with get_connection() as conn:
            if not conn.execute("SELECT id FROM persons WHERE id = ?", (person_id,)).fetchone():
                return None
            if role is not ...:
                if role not in _VALID_ROLES:
                    role = None
                conn.execute("UPDATE persons SET role = ?, updated_at = ? WHERE id = ?", (role, now_iso(), person_id))
            if emoji is not ...:
                emoji_val = str(emoji).strip()[:8] if emoji else None
                conn.execute("UPDATE persons SET emoji = ?, updated_at = ? WHERE id = ?", (emoji_val, now_iso(), person_id))
        return self.get_person_by_id(person_id)

    def set_gender(self, person_id: int, gender: str | None) -> dict[str, Any] | None:
        if gender not in (None, "m", "w"):
            gender = None
        with get_connection() as conn:
            row = conn.execute("SELECT id FROM persons WHERE id = ?", (person_id,)).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE persons SET gender = ?, updated_at = ? WHERE id = ?",
                (gender, now_iso(), person_id),
            )
        return self.get_person_by_id(person_id)

    def delete_person(self, person_id: int) -> dict[str, Any] | None:
        person = self.get_person_by_id(person_id)
        if not person:
            return None

        with get_connection() as conn:
            deleted_facts = conn.execute(
                "DELETE FROM person_profile_facts WHERE person_id = ?",
                (person_id,),
            ).rowcount
            conn.execute("DELETE FROM persons WHERE id = ?", (person_id,))

        return {
            "id": person["id"],
            "name": person["name"],
            "deleted_fact_count": deleted_facts,
        }

    def list_people(self) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    p.id AS person_id,
                    p.name,
                    p.gender AS gender,
                    p.role AS role,
                    p.emoji AS emoji,
                    p.created_at AS person_created_at,
                    p.updated_at AS person_updated_at,
                    f.trait_type,
                    f.value,
                    f.source_memory_id,
                    f.confidence,
                    f.created_at AS fact_created_at,
                    f.updated_at AS fact_updated_at
                FROM persons p
                LEFT JOIN person_profile_facts f ON f.person_id = p.id
                ORDER BY lower(p.name), f.trait_type, f.value
                """
            ).fetchall()

        people: list[dict[str, Any]] = []
        current_id: int | None = None
        current_person: dict[str, Any] | None = None
        for row in rows:
            if row["person_id"] != current_id:
                current_id = row["person_id"]
                current_person = {
                    "id": row["person_id"],
                    "name": row["name"],
                    "gender": row["gender"],
                    "role": row["role"] if "role" in row.keys() else None,
                    "emoji": row["emoji"] if "emoji" in row.keys() else None,
                    "created_at": row["person_created_at"],
                    "updated_at": row["person_updated_at"],
                    "facts": [],
                }
                people.append(current_person)

            if current_person and row["trait_type"]:
                current_person["facts"].append(
                    {
                        "trait_type": row["trait_type"],
                        "value": row["value"],
                        "source_memory_id": row["source_memory_id"],
                        "confidence": row["confidence"],
                        "created_at": row["fact_created_at"],
                        "updated_at": row["fact_updated_at"],
                    }
                )

        return people

    def delete_fact(self, person_id: int, fact_id: int) -> dict[str, Any] | None:
        person = self.get_person_by_id(person_id)
        if not person:
            return None
        # Fakt vorher auslesen um danach Memories zu bereinigen
        with get_connection() as conn:
            fact_row = conn.execute(
                "SELECT trait_type, value FROM person_profile_facts WHERE id = ? AND person_id = ?",
                (fact_id, person_id),
            ).fetchone()
            conn.execute(
                "DELETE FROM person_profile_facts WHERE id = ? AND person_id = ?",
                (fact_id, person_id),
            )
            conn.execute("UPDATE persons SET updated_at = ? WHERE id = ?", (now_iso(), person_id))

        if fact_row:
            trait_type = fact_row["trait_type"]
            value = fact_row["value"]
            mem_cats = _TRAIT_TO_MEM_CATS.get(trait_type)
            if mem_cats:
                _MemSvc().delete_by_value(person["name"], mem_cats, value)

        return self.get_person_by_id(person_id)

    def update_fact(self, person_id: int, fact_id: int, new_value: str) -> dict[str, Any] | None:
        person = self.get_person_by_id(person_id)
        if not person:
            return None
        normalized = self._normalize_value(new_value)
        with get_connection() as conn:
            conn.execute(
                "UPDATE person_profile_facts SET value = ?, updated_at = ? WHERE id = ? AND person_id = ?",
                (normalized, now_iso(), fact_id, person_id),
            )
            conn.execute("UPDATE persons SET updated_at = ? WHERE id = ?", (now_iso(), person_id))
        return self.get_person_by_id(person_id)

    def upsert_fact_if_missing(
        self, *, person_name: str, trait_type: str, value: str, confidence: float
    ) -> bool:
        """Fügt einen Fakt hinzu wenn er noch nicht existiert. Gibt True zurück wenn neu angelegt."""
        normalized_name = self._normalize_name(person_name)
        normalized_value = self._normalize_value(value)
        person_id = self.ensure_person(normalized_name)
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM person_profile_facts WHERE person_id = ? AND trait_type = ? AND lower(value) = lower(?)",
                (person_id, trait_type, normalized_value),
            ).fetchone()
            if existing:
                return False
            conn.execute(
                """INSERT INTO person_profile_facts(person_id, trait_type, value, source_memory_id, confidence, created_at, updated_at)
                   VALUES (?, ?, ?, NULL, ?, ?, ?)""",
                (person_id, trait_type, normalized_value, confidence, now_iso(), now_iso()),
            )
            conn.execute("UPDATE persons SET updated_at = ? WHERE id = ?", (now_iso(), person_id))
        return True

    def get_response_preferences(self, person_name: str | None) -> dict[str, str]:
        if not person_name:
            return {}
        person = self.get_person(person_name)
        if not person:
            return {}

        traits = {
            "response_humor_preference",
            "response_style_preference",
            "response_length_preference",
            "write_calendar_entity",
        }
        return {
            fact["trait_type"]: fact["value"]
            for fact in person["facts"]
            if fact["trait_type"] in traits
        }
