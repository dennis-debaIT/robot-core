from typing import Any

from app.database.db import DEFAULT_PERSONALITY, get_connection


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class PersonalityService:
    fields = tuple(DEFAULT_PERSONALITY.keys())

    def get(self) -> dict[str, Any]:
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM personality WHERE id = 1").fetchone()
            return {field: row[field] for field in self.fields}

    def update(self, payload: dict[str, float]) -> dict[str, Any]:
        if not payload:
            return self.get()

        current = self.get()
        merged = {**current, **payload}
        cleaned = {field: clamp(float(merged[field])) for field in self.fields}

        with get_connection() as conn:
            conn.execute(
                """
                UPDATE personality
                SET friendliness = ?, humor = ?, curiosity = ?, talkativeness = ?,
                    caution = ?, directness = ?, sarcasm = ?, patience = ?,
                    updated_at = datetime('now')
                WHERE id = 1
                """,
                tuple(cleaned[field] for field in self.fields),
            )
        return cleaned

    def reset_defaults(self) -> dict[str, Any]:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE personality
                SET friendliness = ?, humor = ?, curiosity = ?, talkativeness = ?,
                    caution = ?, directness = ?, sarcasm = ?, patience = ?,
                    updated_at = datetime('now')
                WHERE id = 1
                """,
                tuple(DEFAULT_PERSONALITY[field] for field in self.fields),
            )
        return self.get()
