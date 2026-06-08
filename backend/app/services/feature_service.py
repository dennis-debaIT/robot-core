from __future__ import annotations

from app.database.db import get_connection, read_state, write_state

_STATE_KEY = "edition"

# Phase 1: Default "plus" — alles freigeschaltet, bis die Lizenzprüfung
# diesen Wert setzt. Später liefert der Lizenz-Check die Edition.
DEFAULT_EDITION = "plus"

# Feature-ID  →  minimal nötiger Tier
# Alles was hier NICHT steht, ist implizit "community" (immer frei).
# Konvention: nur die kostenpflichtige *Tiefe* eines Moduls wird gegated,
# die Basis-Anzeige (z.B. aktueller PV-Wert) bleibt frei.
FEATURES: dict[str, str] = {
    "pv_stats":        "plus",   # PV-Statistik + Energiefluss-Diagramm
    "camera_events":   "plus",   # Kamera-Ereignisliste + Türklingel-Historie
    "vehicle_history": "plus",   # Fahrzeug-Ladeverlauf
}

_TIER_RANK = {"community": 0, "plus": 1, "family": 2}


class FeatureService:
    def get_edition(self) -> str:
        with get_connection() as conn:
            ed = read_state(conn, _STATE_KEY)
        return ed if ed in _TIER_RANK else DEFAULT_EDITION

    def set_edition(self, edition: str) -> str:
        if edition not in _TIER_RANK:
            edition = DEFAULT_EDITION
        with get_connection() as conn:
            write_state(conn, _STATE_KEY, edition)
        return edition

    def enabled_features(self) -> dict:
        rank = _TIER_RANK[self.get_edition()]
        features = {
            feat: rank >= _TIER_RANK[tier]
            for feat, tier in FEATURES.items()
        }
        return {"edition": self.get_edition(), "features": features}

    def has_feature(self, feature_id: str) -> bool:
        required = FEATURES.get(feature_id)
        if required is None:
            return True  # nicht gelistet = community = immer frei
        return _TIER_RANK[self.get_edition()] >= _TIER_RANK[required]
