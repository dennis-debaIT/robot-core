from __future__ import annotations

import base64
import json
from datetime import date
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# ─────────────────────────────────────────────────────────────
# Lizenz-Verifizierung (offline, fälschungssicher)
# ─────────────────────────────────────────────────────────────
# Eine license.json wird mit dem PRIVATEN Ed25519-Schlüssel signiert
# (robot-core-plus/licensing/sign_license.py). Hier wird sie mit dem
# ÖFFENTLICHEN Gegenstück geprüft — der darf öffentlich im Code stehen.
#
# Manipuliert jemand die Lizenz (Plan/Ablauf), passt die Signatur nicht
# mehr → ungültig → Community. Ohne privaten Schlüssel nicht fälschbar.
#
# Der öffentliche Schlüssel wird mit gen_keys.py erzeugt und hier eingesetzt
# (Base64 der rohen 32 Bytes). Leer = es kann keine gültige Lizenz geben.
_PUBLIC_KEY_B64 = ""

# Lizenz liegt im DB-Volume → überlebt Updates und Image-Wechsel.
_LICENSE_FILE = Path("/data/license.json")


def _canonical(payload: dict) -> bytes:
    """Kanonische Bytes über alle Felder außer 'signature' — Basis der Signatur."""
    data = {k: v for k, v in payload.items() if k != "signature"}
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


class LicenseService:
    def _public_key(self) -> Ed25519PublicKey | None:
        if not _PUBLIC_KEY_B64:
            return None
        try:
            return Ed25519PublicKey.from_public_bytes(base64.b64decode(_PUBLIC_KEY_B64))
        except Exception:
            return None

    def verify(self, lic: dict) -> dict:
        """Prüft Signatur und Ablaufdatum. Gibt {valid, plan, reason, ...} zurück."""
        key = self._public_key()
        if key is None:
            return {"valid": False, "plan": "community", "reason": "no_public_key"}

        sig_b64 = lic.get("signature")
        if not sig_b64:
            return {"valid": False, "plan": "community", "reason": "no_signature"}

        try:
            key.verify(base64.b64decode(sig_b64), _canonical(lic))
        except (InvalidSignature, Exception):
            return {"valid": False, "plan": "community", "reason": "bad_signature"}

        # Signatur ok → Ablauf prüfen
        valid_until = lic.get("valid_until")
        if valid_until:
            try:
                if date.fromisoformat(valid_until) < date.today():
                    return {"valid": False, "plan": "community", "reason": "expired",
                            "valid_until": valid_until}
            except ValueError:
                return {"valid": False, "plan": "community", "reason": "bad_date"}

        return {
            "valid": True,
            "plan": lic.get("plan", "community"),
            "email": lic.get("email", ""),
            "valid_until": valid_until,
            "device_id": lic.get("device_id", ""),
            "reason": "ok",
        }

    def load(self) -> dict | None:
        if not _LICENSE_FILE.exists():
            return None
        try:
            return json.loads(_LICENSE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return None

    def status(self) -> dict:
        """Aktueller Lizenzstatus für Admin/Integration."""
        lic = self.load()
        if not lic:
            return {"valid": False, "plan": "community", "reason": "no_license"}
        return self.verify(lic)

    def current_edition(self) -> str:
        """Edition aus gültiger Lizenz, sonst community."""
        result = self.status()
        return result["plan"] if result.get("valid") else "community"

    def install(self, lic: dict) -> dict:
        """Lizenz prüfen und bei Gültigkeit speichern."""
        result = self.verify(lic)
        if result.get("valid"):
            _LICENSE_FILE.write_text(json.dumps(lic, indent=2), encoding="utf-8")
        return result
