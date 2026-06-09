from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.services.feature_service import FeatureService
from app.services.license_service import LicenseService, _LICENSE_FILE

router = APIRouter()

# Online-Lizenzserver (signiert Lizenzen). Überschreibbar via Umgebung.
_LICENSE_SERVER = os.environ.get("LICENSE_SERVER_URL", "https://lic.wdk-it.de")


@router.get("/license/status")
def license_status() -> dict:
    result = LicenseService().status()
    result["device_id"] = LicenseService.device_id()
    return result


@router.post("/license/activate")
def activate_license(payload: dict) -> dict:
    """Kunde gibt nur den Code ein → Server signiert eine an dieses Gerät
    gebundene Lizenz → wird lokal installiert. Auch für periodisches Renewal."""
    code = str(payload.get("code") or "").strip().upper()
    if not code:
        raise HTTPException(400, "Lizenzcode erforderlich")

    device_id = LicenseService.device_id()
    body = json.dumps({"code": code, "device_id": device_id}).encode("utf-8")
    req = urllib.request.Request(
        f"{_LICENSE_SERVER}/activate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail", "")
        except Exception:
            detail = ""
        raise HTTPException(e.code, detail or f"Aktivierung fehlgeschlagen (HTTP {e.code})")
    except urllib.error.URLError:
        raise HTTPException(503, "Lizenzserver nicht erreichbar — Internetverbindung prüfen")

    license_doc = data.get("license")
    if not license_doc:
        raise HTTPException(502, "Ungültige Antwort vom Lizenzserver")

    result = LicenseService().install(license_doc)
    if result.get("valid"):
        FeatureService().set_edition(result.get("plan", "community"))
    return result


@router.post("/license")
def install_license(payload: dict) -> dict:
    """Signierte license.json hochladen. Bei Gültigkeit wird sie gespeichert
    und die Edition (DB + Build-Datei) entsprechend gesetzt."""
    result = LicenseService().install(payload)
    if result.get("valid"):
        FeatureService().set_edition(result.get("plan", "community"))
    return result


@router.delete("/license")
def remove_license() -> dict:
    """Lizenz entfernen → zurück auf Community."""
    try:
        Path(_LICENSE_FILE).unlink(missing_ok=True)
    except OSError:
        pass
    FeatureService().set_edition("community")
    return {"removed": True, "plan": "community"}
