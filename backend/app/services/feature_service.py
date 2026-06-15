from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.database.db import get_connection, read_state, write_state

_STATE_KEY = "edition"

# Gemountete Host-Datei (docker-compose: ./edition:/app/edition).
# update.sh liest sie, um Community-Geräte ohne Paid-Module zu bauen.
# So bleibt die Admin-Auswahl (DB) mit dem nächsten Build synchron.
_EDITION_FILE = Path("/app/edition")

# Update-Trigger (gemountet ./update.flag:/update.flag). Cron prüft minütlich
# und startet update.sh → Rebuild mit der Edition aus der edition-Datei.
_UPDATE_FLAG = Path("/update.flag")

# Secure by default: ohne gesetzte Edition gilt Community. Plus/Family wird
# erst durch den Admin-Schalter bzw. später den Lizenz-Check aktiviert.
DEFAULT_EDITION = "community"

# Feature-ID  →  minimal nötiger Tier
# Alles was hier NICHT steht, ist implizit "community" (immer frei).
# Konvention: nur die kostenpflichtige *Tiefe* eines Moduls wird gegated,
# die Basis-Anzeige (z.B. aktueller PV-Wert) bleibt frei.
FEATURES: dict[str, str] = {
    "pv_stats":        "plus",   # PV-Statistik + Energiefluss-Diagramm
    "camera_events":   "plus",   # Kamera-Ereignisliste + Türklingel-Historie
    "vehicle_history": "plus",   # Fahrzeug-Ladeverlauf
    "waste":           "plus",   # Abfallkalender-Widget
    "theme_schedule":  "plus",   # Zeitabhängiges Design (Tag/Nacht-Theme-Wechsel)
    "energy_costs":    "plus",   # Stromkosten-Berechnung (Verbrauch je Sensor bleibt frei)
}

_TIER_RANK = {"community": 0, "plus": 1, "family": 2}


class FeatureService:
    def get_edition(self) -> str:
        # Eine installierte Lizenz hat Vorrang (Live-Prüfung inkl. Ablauf):
        # gültig → Plan aus Lizenz, abgelaufen/ungültig → community.
        from app.services.license_service import LicenseService
        lic = LicenseService()
        if lic.load() is not None:
            edition = lic.current_edition()
            return edition if edition in _TIER_RANK else "community"
        # Keine Lizenzdatei → manueller Wert (Admin-Test-Schalter), Default community.
        with get_connection() as conn:
            ed = read_state(conn, _STATE_KEY)
        return ed if ed in _TIER_RANK else DEFAULT_EDITION

    def set_edition(self, edition: str) -> str:
        if edition not in _TIER_RANK:
            edition = DEFAULT_EDITION
        with get_connection() as conn:
            previous = read_state(conn, _STATE_KEY)
            write_state(conn, _STATE_KEY, edition)
        # Host-Datei mitschreiben, damit update.sh dieselbe Edition baut.
        # Schlägt still fehl wenn nicht gemountet (z.B. Tests) — DB bleibt führend.
        try:
            _EDITION_FILE.write_text(edition + "\n")
        except OSError:
            pass
        # Edition geändert → Rebuild anstoßen, damit Paid-Module ins Image
        # kommen bzw. verschwinden (z.B. nach Lizenz-Aktivierung/-Entfernung).
        if previous != edition:
            self._trigger_rebuild()
        return edition

    @staticmethod
    def _trigger_rebuild() -> None:
        """Setzt update.flag → Cron baut innerhalb ~1 Min mit der neuen Edition neu."""
        try:
            _UPDATE_FLAG.write_text(
                json.dumps({"requested_at": datetime.now(timezone.utc).isoformat()})
            )
        except OSError:
            pass

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
