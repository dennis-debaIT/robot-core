from __future__ import annotations

import base64
import json
import uuid
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
# Privates Gegenstück: robot-core-plus/licensing/private_key.pem
_PUBLIC_KEY_B64 = "9gMS1WDzh0w/GBE51ykGEUDgQHKIwQFv9ZzNVTh1jBM="

# Lizenz liegt im DB-Volume → überlebt Updates und Image-Wechsel.
_LICENSE_FILE = Path("/data/license.json")


# Felder die der Lizenzserver signiert (muss signing.py auf lic.wdk-it.de entsprechen).
# Der deployed Lizenzserver fügt sync_jwt + sync_url VOR der Signatur hinzu.
# Lokal hinzugefügte Felder (sync_email, sync_password) dürfen die Prüfung nicht
# beeinflussen — sie werden NACH dem Signieren per save_sync_config angefügt.
_SIGNED_FIELDS = frozenset({
    "license_key", "email", "plan", "device_id",
    "device_limit", "issued_at", "valid_until",
    "sync_jwt", "sync_url",  # vom Lizenzserver vor der Signatur gesetzt
})


def _canonical(payload: dict) -> bytes:
    """Kanonische Bytes über die vom Lizenzserver signierten Felder."""
    data = {k: v for k, v in payload.items() if k in _SIGNED_FIELDS}
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
        """Lizenz prüfen und bei Gültigkeit speichern.

        Bindet zusätzlich an dieses Gerät: stimmt die device_id der Lizenz
        nicht mit der echten Hardware-ID überein, wird sie abgelehnt
        (leere device_id = nicht gebunden, wird akzeptiert)."""
        result = self.verify(lic)
        if result.get("valid"):
            lic_device = (lic.get("device_id") or "").strip()
            if lic_device and lic_device != self.device_id():
                return {"valid": False, "plan": "community", "reason": "wrong_device"}
            _LICENSE_FILE.write_text(json.dumps(lic, indent=2), encoding="utf-8")
        return result

    @staticmethod
    def device_id() -> str:
        """Stabile Hardware-ID dieses Geräts.

        Bevorzugt die Pi-Seriennummer (/proc/cpuinfo zeigt im Container die
        des Hosts), Fallback auf MAC-Adresse.
        Das Ergebnis wird in /data/device_id persistiert, damit die ID auch
        nach Container-Rebuilds (neue Docker-MAC) stabil bleibt."""
        _DEVICE_ID_FILE = Path("/data/device_id")
        # 1. Bereits persistierte ID verwenden (überlebt Rebuilds)
        try:
            stored = _DEVICE_ID_FILE.read_text(encoding="utf-8").strip()
            if stored:
                return stored
        except OSError:
            pass
        # 2. Pi-Seriennummer bevorzugen
        try:
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.lower().startswith("serial"):
                    serial = line.split(":", 1)[1].strip()
                    if serial and set(serial) != {"0"}:
                        did = f"pi-{serial}"
                        try:
                            _DEVICE_ID_FILE.write_text(did, encoding="utf-8")
                        except OSError:
                            pass
                        return did
        except OSError:
            pass
        # 3. MAC-Adresse als Fallback — persistieren damit sie stabil bleibt
        did = f"mac-{uuid.getnode():012x}"
        try:
            _DEVICE_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
            _DEVICE_ID_FILE.write_text(did, encoding="utf-8")
        except OSError:
            pass
        return did
