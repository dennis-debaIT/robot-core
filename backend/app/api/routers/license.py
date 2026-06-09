from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.services.feature_service import FeatureService
from app.services.license_service import LicenseService, _LICENSE_FILE

router = APIRouter()

# Online-Lizenzserver (signiert Lizenzen). Überschreibbar via Umgebung.
# Custom-Port 8989, selbstsigniertes TLS (kein Let's Encrypt ohne Port 80/443).
_LICENSE_SERVER = os.environ.get("LICENSE_SERVER_URL", "https://lic.wdk-it.de:8989")

# Selbstsigniertes Server-Zertifikat akzeptieren: die Fälschungssicherheit
# liegt in der Ed25519-Signatur der Lizenz, nicht im Transport-TLS. Ein MITM
# kann ohne den privaten Schlüssel keine gültige Lizenz unterschieben.
_TLS_CTX = ssl.create_default_context()
_TLS_CTX.check_hostname = False
_TLS_CTX.verify_mode = ssl.CERT_NONE


def _server_activate(code: str, device_id: str) -> dict:
    """Ruft den Lizenzserver und gibt das signierte Lizenz-Dokument zurück.
    Wirft urllib-Fehler (HTTPError/URLError) bzw. ValueError weiter."""
    body = json.dumps({"code": code, "device_id": device_id}).encode("utf-8")
    req = urllib.request.Request(
        f"{_LICENSE_SERVER}/activate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15, context=_TLS_CTX) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    lic = data.get("license")
    if not lic:
        raise ValueError("Keine Lizenz in der Serverantwort")
    return lic


def _install_and_apply(lic: dict) -> dict:
    """Lizenz installieren und bei Gültigkeit die Edition setzen."""
    result = LicenseService().install(lic)
    if result.get("valid"):
        FeatureService().set_edition(result.get("plan", "community"))
    return result


def renew_license() -> str | None:
    """Periodisches Renewal (vom Hintergrund-Loop aufgerufen).

    Holt für die installierte Abo-Lizenz eine frische, länger gültige Lizenz.
    Still bei Fehlern: Server nicht erreichbar oder Code gesperrt → die lokale
    Lizenz gilt unverändert bis zu ihrem valid_until (= Grace Period), danach
    Rückfall auf Community. Lifetime-Lizenzen (kein valid_until) werden
    übersprungen. Gibt den Plan bei Erfolg zurück, sonst None.
    """
    svc = LicenseService()
    lic = svc.load()
    if not lic or not lic.get("valid_until"):
        return None  # keine Lizenz oder Lifetime → kein Renewal nötig
    code = str(lic.get("license_key") or "").strip()
    if not code:
        return None
    try:
        fresh = _server_activate(code, svc.device_id())
    except Exception:
        return None  # offline/gesperrt → lokale Lizenz bleibt bis valid_until
    result = _install_and_apply(fresh)
    return result.get("plan") if result.get("valid") else None


@router.get("/license/status")
def license_status() -> dict:
    result = LicenseService().status()
    result["device_id"] = LicenseService.device_id()
    return result


@router.post("/license/activate")
def activate_license(payload: dict) -> dict:
    """Kunde gibt nur den Code ein → Server signiert eine an dieses Gerät
    gebundene Lizenz → wird lokal installiert."""
    code = str(payload.get("code") or "").strip().upper()
    if not code:
        raise HTTPException(400, "Lizenzcode erforderlich")
    try:
        lic = _server_activate(code, LicenseService.device_id())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail", "")
        except Exception:
            detail = ""
        raise HTTPException(e.code, detail or f"Aktivierung fehlgeschlagen (HTTP {e.code})")
    except urllib.error.URLError:
        raise HTTPException(503, "Lizenzserver nicht erreichbar — Internetverbindung prüfen")
    except ValueError:
        raise HTTPException(502, "Ungültige Antwort vom Lizenzserver")
    return _install_and_apply(lic)


@router.post("/license")
def install_license(payload: dict) -> dict:
    """Signierte license.json direkt hochladen (Fallback ohne Server)."""
    return _install_and_apply(payload)


@router.delete("/license")
def remove_license() -> dict:
    """Lizenz entfernen → zurück auf Community."""
    try:
        Path(_LICENSE_FILE).unlink(missing_ok=True)
    except OSError:
        pass
    FeatureService().set_edition("community")
    return {"removed": True, "plan": "community"}
