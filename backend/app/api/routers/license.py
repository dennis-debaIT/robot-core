from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.audit.service import AuditService
from app.services.feature_service import FeatureService
from app.services.license_service import LicenseService, _LICENSE_FILE
from app.services import sync_service as svc

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
    """Periodisches Renewal + Edition-Abgleich (vom Hintergrund-Loop aufgerufen).

    1. Abo-Lizenz: beim Server verlängern (frische, länger gültige Lizenz).
    2. Danach Edition an den TATSÄCHLICHEN Lizenzstatus angleichen:
       gültig → Plan, abgelaufen/gesperrt/ungültig → community.
       set_edition() löst bei Änderung den Rebuild aus → entfernt den Paid-Code
       physisch aus dem Image (bzw. bringt ihn rein). Damit werden Features bei
       Ablauf nicht nur im Frontend, sondern auch im Image deaktiviert.

    Grace Period bleibt erhalten: Server kurz offline + Lizenz noch nicht
    abgelaufen → Edition bleibt plan (kein Rebuild). Erst wenn valid_until
    überschritten ist → community + Rebuild.
    """
    svc = LicenseService()
    lic = svc.load()
    if not lic:
        return None  # keine Lizenz (Community-Gerät) — nichts zu tun

    # Abo (kein Lifetime): beim Server zu verlängern versuchen
    if lic.get("valid_until"):
        code = str(lic.get("license_key") or "").strip()
        if code:
            try:
                return _install_and_apply(_server_activate(code, svc.device_id())).get("plan")
            except Exception:
                pass  # offline/gesperrt → unten Edition mit Ablaufstatus abgleichen

    # Lifetime ohne sync_jwt: einmalig erneuern damit Sync-Credentials nachgetragen werden
    if not lic.get("valid_until") and not lic.get("sync_jwt"):
        code = str(lic.get("license_key") or "").strip()
        if code:
            try:
                _install_and_apply(_server_activate(code, svc.device_id()))
            except Exception:
                pass

    # Edition an den effektiven Lizenzstatus angleichen (Live-Ablaufprüfung).
    # Bei Änderung triggert set_edition den Rebuild (Paid-Code rein/raus).
    effective = svc.current_edition()
    FeatureService().set_edition(effective)
    return effective if effective != "community" else None


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
    result = _install_and_apply(lic)
    AuditService().log(
        action="license.activated",
        target_type="license",
        summary="Lizenz wurde aktiviert.",
        details={"valid": result.get("valid"), "plan": result.get("plan"), "reason": result.get("reason")},
    )
    return result


@router.post("/license")
def install_license(payload: dict) -> dict:
    """Signierte license.json direkt hochladen (Fallback ohne Server)."""
    result = _install_and_apply(payload)
    AuditService().log(
        action="license.installed",
        target_type="license",
        summary="Lizenz wurde manuell installiert.",
        details={"valid": result.get("valid"), "plan": result.get("plan"), "reason": result.get("reason")},
    )
    return result


@router.post("/license/pair-device")
def pair_device(payload: dict) -> dict:
    """Koppelt dieses Gerät mit einer eigenständigen Geräte-Identität beim
    Sync Server, statt sich weiterhin als die Person hinter email/password
    auszugeben (nötig damit z.B. das Display Nachrichten an die eigenen
    Haushaltsmitglieder senden kann). email/password werden bewusst aus dem
    Request gelesen statt aus license.json — erzwingt aktive Bestätigung bei
    jeder (Re-)Kopplung."""
    email = str(payload.get("email") or "").strip()
    password = str(payload.get("password") or "").strip()
    if not email or not password:
        raise HTTPException(400, "email und password sind erforderlich")

    lic: dict = {}
    if _LICENSE_FILE.exists():
        try:
            lic = json.loads(_LICENSE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    url = str(lic.get("sync_url") or "").rstrip("/")
    if not url:
        raise HTTPException(400, "Kein Sync-Server konfiguriert")

    login_result = svc._do_login(url, email, password)
    if not login_result:
        raise HTTPException(401, "E-Mail oder Passwort falsch")
    access_token, _refresh = login_result

    device_token = svc._do_issue_device_token(url, access_token)
    if not device_token:
        raise HTTPException(502, "Gerätekopplung beim Sync Server fehlgeschlagen")

    lic["sync_device_token"] = device_token
    lic.pop("sync_password", None)
    lic["sync_email"] = email
    _LICENSE_FILE.write_text(json.dumps(lic, indent=2), encoding="utf-8")
    svc.reset_token_cache()

    AuditService().log(
        action="license.device_paired",
        target_type="license",
        summary="Gerät wurde mit eigenständiger Geräte-Identität gekoppelt.",
    )
    return {"ok": True}


@router.delete("/license")
def remove_license() -> dict:
    """Lizenz entfernen → zurück auf Community."""
    try:
        Path(_LICENSE_FILE).unlink(missing_ok=True)
    except OSError:
        pass
    FeatureService().set_edition("community")
    AuditService().log(
        action="license.removed",
        target_type="license",
        summary="Lizenz wurde entfernt — zurück auf Community.",
    )
    return {"removed": True, "plan": "community"}
