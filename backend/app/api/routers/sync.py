"""Sync-Endpunkte — Einkaufsliste (lokal + Sync-Trigger). Erika Plus."""
from __future__ import annotations

import asyncio
import json
import ssl
import urllib.request as _ureq
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.services import sync_service as svc

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode    = ssl.CERT_NONE

router = APIRouter()

_LICENSE_FILE = Path("/data/license.json")
_DEFAULT_SYNC_URL = "https://erika.wdk-it.de:9000"


def _require_sync() -> None:
    from app.services.feature_service import FeatureService
    if not FeatureService().has_feature("sync"):
        raise HTTPException(status_code=403, detail="Companion-App erfordert Erika Plus")


@router.get("/sync/items")
def get_items() -> dict[str, Any]:
    _require_sync()
    return {"items": svc.list_items()}


@router.get("/sync/items/stream")
async def stream_items(request: Request) -> StreamingResponse:
    """SSE-Stream fürs Display: sendet die aktuelle Liste sofort bei jeder
    lokalen Änderung (200ms Poll auf die lokale DB, kein Cloud-Roundtrip
    nötig — der läuft unabhängig im 3s-Fast-Sync-Loop)."""
    _require_sync()

    async def generate():
        last = svc.items_max_updated_at()
        yield f"data: {json.dumps({'items': svc.list_items()})}\n\n"
        while not await request.is_disconnected():
            await asyncio.sleep(0.2)
            current = svc.items_max_updated_at()
            if current != last:
                last = current
                yield f"data: {json.dumps({'items': svc.list_items()})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/sync/items")
def add_item(payload: dict[str, Any]) -> dict[str, Any]:
    _require_sync()
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text fehlt")
    item = svc.create_item(text)
    svc.push_item(item)
    return item


@router.patch("/sync/items/{item_id}")
def patch_item(item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _require_sync()
    item = svc.update_item(
        item_id,
        text=payload.get("text"),
        checked=payload.get("checked"),
        sort_order=payload.get("sort_order"),
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    svc.push_item(item)
    return item


@router.delete("/sync/items/{item_id}")
def remove_item(item_id: str) -> dict[str, Any]:
    _require_sync()
    if not svc.delete_item(item_id):
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    svc.push_item({"id": item_id, "deleted": True})
    return {"ok": True}


@router.delete("/sync/items")
def clear_checked() -> dict[str, Any]:
    _require_sync()
    return {"deleted": svc.clear_checked()}


@router.post("/sync/trigger")
def trigger_sync() -> dict[str, Any]:
    _require_sync()
    """Manuellen Sync anstoßen — alle aktivierten Module."""
    import traceback as _tb
    from app.services.integration_config_service import IntegrationConfigService
    try:
        modules = (IntegrationConfigService().get_config().get("sync") or {}).get("modules", {})
    except Exception as exc:
        return {"pushed": 0, "pulled": 0, "error": f"config: {exc}"}

    pushed = pulled = 0
    errors: list[str] = []

    if modules.get("shopping", True):
        try:
            pushed += svc.push_unsynced()
            svc.reconcile_items()
            since   = svc.get_last_sync_time()
            pulled += svc.pull_and_merge(since)
        except Exception as exc:
            errors.append(f"shopping: {exc}")

    if modules.get("notes", False):
        try:
            svc.push_persons()
            pushed += svc.push_notes()
            pulled += svc.pull_notes()
        except Exception as exc:
            errors.append(f"notes: {exc}")

    if modules.get("reminders", False):
        try:
            pushed += svc.push_reminders()
            pulled += svc.pull_reminders()
        except Exception as exc:
            errors.append(f"reminders: {exc}")

    if modules.get("chores", False):
        try:
            svc.push_persons()
            pushed += svc.push_chore_tasks()
            pushed += svc.push_chore_completions()
            pulled += svc.pull_chore_completions()
        except Exception as exc:
            errors.append(f"chores: {_tb.format_exc()}")

    if modules.get("lights", False):
        try:
            svc.push_lights()
            svc.push_light_scenes()
            svc.poll_light_commands()
        except Exception as exc:
            errors.append(f"lights: {exc}")

    try:
        svc.push_device_heartbeat()
    except Exception:
        pass

    result: dict[str, Any] = {"pushed": pushed, "pulled": pulled}
    if errors:
        result["errors"] = errors
    return result


# ── Sync-Credentials (Admin-Konfiguration) ────────────────────────────────

@router.get("/sync/config")
def get_sync_config() -> dict[str, Any]:
    """Aktuelle Sync-Credentials lesen. Passwort wird nicht zurückgegeben."""
    try:
        if _LICENSE_FILE.exists():
            lic = json.loads(_LICENSE_FILE.read_text(encoding="utf-8"))
            url   = str(lic.get("sync_url")      or "").rstrip("/")
            email = str(lic.get("sync_email")    or "").strip()
            has_pw = bool(str(lic.get("sync_password") or "").strip())
            device_paired = bool(str(lic.get("sync_device_token") or "").strip())
            return {"url": url, "email": email, "has_password": has_pw,
                    "configured": bool(url and email and has_pw),
                    "device_paired": device_paired}
    except Exception:
        pass
    return {"url": "", "email": "", "has_password": False, "configured": False, "device_paired": False}


def _bg_update_edition() -> None:
    """Erneuert die signierte Lizenz vom Lizenzserver (falls license_key vorhanden).

    Läuft als FastAPI-Background-Task, damit der HTTP-Handler sofort antwortet.
    Kein direktes DB-Schreiben — Editionen sind nur via signierter Lizenz gültig.
    """
    try:
        from app.api.routers.license import renew_license
        renew_license()
    except Exception:
        pass


@router.post("/sync/config")
def save_sync_config(payload: dict[str, Any], bg: BackgroundTasks) -> dict[str, Any]:
    """Sync-Credentials speichern. Bestehende Lizenzfelder bleiben erhalten."""
    url   = str(payload.get("url") or _DEFAULT_SYNC_URL).rstrip("/").strip()
    email = str(payload.get("email")    or "").strip()
    pw    = str(payload.get("password") or "").strip()
    if not email or not pw:
        raise HTTPException(400, "email und password sind erforderlich")
    lic: dict = {}
    try:
        if _LICENSE_FILE.exists():
            lic = json.loads(_LICENSE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    # sync_url ist Teil der signierten Lizenz. Nur setzen wenn:
    # a) noch keine signierte Lizenz (kein sync_jwt) — normaler Erstsetup
    # b) sync_url fehlt (z.B. nach Entfernen) — Wiederherstellung mit Default
    # Wenn sync_jwt + sync_url beide vorhanden: nicht überschreiben (Signatur!)
    if not lic.get("sync_jwt") or not lic.get("sync_url"):
        lic["sync_url"] = url
    lic["sync_email"]    = email
    lic["sync_password"] = pw
    _LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LICENSE_FILE.write_text(json.dumps(lic, indent=2), encoding="utf-8")
    svc.reset_token_cache()
    # Edition-Update läuft im Hintergrund — Handler antwortet sofort.
    bg.add_task(_bg_update_edition)
    return {"ok": True}


@router.delete("/sync/config")
def remove_sync_config() -> dict[str, Any]:
    """Sync-Credentials aus license.json entfernen."""
    try:
        if _LICENSE_FILE.exists():
            lic = json.loads(_LICENSE_FILE.read_text(encoding="utf-8"))
            # sync_url ist Teil der signierten Lizenz — darf NICHT entfernt werden
            for k in ("sync_email", "sync_password"):
                lic.pop(k, None)
            _LICENSE_FILE.write_text(json.dumps(lic, indent=2), encoding="utf-8")
    except Exception:
        pass
    svc.reset_token_cache()
    return {"ok": True}


@router.get("/sync/account")
def get_sync_account() -> dict[str, Any]:
    """Ruft /auth/me vom Sync-Server ab — Tier, Ablaufdatum, Rolle."""
    url_base, token = svc.get_credentials()
    if not url_base or not token:
        return {"connected": False}
    req = _ureq.Request(f"{url_base}/auth/me")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with _ureq.urlopen(req, timeout=8, context=_SSL_CTX) as resp:
            data = json.loads(resp.read())
        return {"connected": True, **data}
    except Exception as exc:
        from app.audit.service import AuditService
        AuditService().log_warn(source="sync", message=f"Sync-Server /auth/me nicht erreichbar: {type(exc).__name__}: {exc}")
        return {"connected": False, "error": str(exc)}
