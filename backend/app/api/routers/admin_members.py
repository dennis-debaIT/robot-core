"""Admin-Member-Verwaltung — Proxy zu Sync Server. Erika Family."""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request as _ureq
from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException

from app.database.db import get_connection
from app.services import sync_service as svc

router = APIRouter(prefix="/admin", tags=["admin-members"])
auth_router = APIRouter(tags=["auth"])

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def _require_family() -> None:
    from app.services.feature_service import FeatureService
    if not FeatureService().has_feature("admin_members"):
        raise HTTPException(status_code=403, detail="Member-Verwaltung erfordert Erika Family")


def _sync_url() -> str:
    url_base, _ = svc.get_credentials()
    if not url_base:
        raise HTTPException(status_code=503, detail="Sync Server nicht konfiguriert")
    return url_base


def _sync_request(method: str, path: str, token: str, data: dict | None = None) -> Any:
    url = f"{_sync_url()}{path}"
    body = json.dumps(data).encode() if data is not None else None
    req = _ureq.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with _ureq.urlopen(req, timeout=10, context=_SSL_CTX) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail", str(exc))
        except Exception:
            detail = str(exc)
        from app.audit.service import AuditService
        AuditService().log_warn(source="sync_server", message=f"Sync Server antwortete mit Fehler bei {method} {path}: HTTP {exc.code}: {detail}")
        raise HTTPException(status_code=exc.code, detail=detail)
    except Exception as exc:
        from app.audit.service import AuditService
        AuditService().log_warn(source="sync_server", message=f"Sync Server nicht erreichbar bei {method} {path}: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=502, detail=f"Sync Server Fehler: {exc}")


@router.get("/members")
def list_members() -> dict[str, Any]:
    """Mitgliederliste des Tenants vom Sync Server (Family only)."""
    _require_family()
    _, token = svc.get_credentials()
    data = _sync_request("GET", "/users", token)
    # Haushalt-ID aus Tenant-Profil anhängen
    try:
        me = _sync_request("GET", "/auth/me", token)
        data["household_id"] = me.get("household_id")
    except Exception as exc:
        from app.audit.service import AuditService
        AuditService().log_warn(source="sync_server", message=f"Haushalt-ID konnte nicht vom Sync Server geladen werden: {type(exc).__name__}: {exc}")
    with get_connection() as conn:
        persons = conn.execute(
            "SELECT id, name, sync_user_id FROM persons WHERE sync_user_id IS NOT NULL"
        ).fetchall()
    person_map = {p["sync_user_id"]: {"id": p["id"], "name": p["name"]} for p in persons}
    for u in data.get("users", []):
        u["linked_person"] = person_map.get(u["id"])
    return data


@router.post("/members/invite")
def invite_member(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Neues Mitglied einladen (Family only, master only)."""
    _require_family()
    email = str(payload.get("email") or "").strip()
    password = str(payload.get("password") or "").strip()
    display_name = str(payload.get("display_name") or "").strip()
    if not email or not password or not display_name:
        raise HTTPException(status_code=400, detail="email, password und display_name erforderlich")
    _, token = svc.get_credentials()
    return _sync_request("POST", "/auth/invite", token, {
        "email": email,
        "password": password,
        "display_name": display_name,
    })


@router.delete("/members/{user_id}")
def remove_member(user_id: str) -> dict[str, Any]:
    """Mitglied deaktivieren. Person-Verknüpfung wird aufgehoben, Daten bleiben erhalten."""
    _require_family()
    with get_connection() as conn:
        conn.execute(
            "UPDATE persons SET sync_user_id = NULL WHERE sync_user_id = ?", (user_id,)
        )
    _, token = svc.get_credentials()
    return _sync_request("DELETE", f"/users/{user_id}", token)


@router.patch("/persons/{person_id}/link-user")
def link_user_to_person(
    person_id: int,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Person mit einem Sync-User verknüpfen. sync_user_id=null zum Entknüpfen."""
    _require_family()
    sync_user_id = payload.get("sync_user_id")
    with get_connection() as conn:
        person = conn.execute("SELECT id FROM persons WHERE id = ?", (person_id,)).fetchone()
        if not person:
            raise HTTPException(status_code=404, detail="Person nicht gefunden")
        if sync_user_id:
            conn.execute(
                "UPDATE persons SET sync_user_id = NULL WHERE sync_user_id = ? AND id != ?",
                (sync_user_id, person_id),
            )
        conn.execute(
            "UPDATE persons SET sync_user_id = ? WHERE id = ?", (sync_user_id, person_id)
        )
    return {"ok": True, "person_id": person_id, "sync_user_id": sync_user_id}


@router.get("/households/contacts")
def list_household_contacts() -> dict[str, Any]:
    """Verknüpfte Haushalte mit Status (mutual/pending) und Mitgliedern."""
    _require_family()
    _, token = svc.get_credentials()
    return _sync_request("GET", "/households/contacts", token)


@router.post("/households/connect")
def add_household_contact(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Haushalt per Erika-ID verknüpfen (master only)."""
    _require_family()
    household_id = str(payload.get("household_id") or "").strip()
    if not household_id:
        raise HTTPException(status_code=400, detail="household_id erforderlich")
    _, token = svc.get_credentials()
    return _sync_request("POST", "/households/connect", token, {"household_id": household_id})


@router.delete("/households/connect/{household_id}")
def remove_household_contact(household_id: str) -> dict[str, Any]:
    """Haushalt-Verbindung entfernen (master only)."""
    _require_family()
    _, token = svc.get_credentials()
    return _sync_request("DELETE", f"/households/connect/{household_id}", token)


@auth_router.get("/auth/whoami")
def whoami(authorization: str = Header(default="")) -> dict[str, Any]:
    """
    Gibt Profil des eingeloggten App-Users zurück.
    Die App schickt ihren Sync-Server-JWT — robot-core validiert ihn und reichert mit lokaler Person an.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Kein Bearer Token")
    user_token = authorization[7:]
    url_base = _sync_url()
    req = _ureq.Request(f"{url_base}/auth/me")
    req.add_header("Authorization", f"Bearer {user_token}")
    try:
        with _ureq.urlopen(req, timeout=8, context=_SSL_CTX) as resp:
            me = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        from app.audit.service import AuditService
        AuditService().log_warn(source="sync_server", message=f"Token-Validierung beim Sync Server fehlgeschlagen: HTTP {exc.code}")
        raise HTTPException(status_code=exc.code, detail="Token ungültig")
    except Exception as exc:
        from app.audit.service import AuditService
        AuditService().log_warn(source="sync_server", message=f"Sync Server für /auth/whoami nicht erreichbar: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=502, detail=f"Sync Server nicht erreichbar: {exc}")
    user_id = me.get("user_id", "")
    with get_connection() as conn:
        person = conn.execute(
            "SELECT id, name FROM persons WHERE sync_user_id = ?", (user_id,)
        ).fetchone()
    return {
        "user_id":      user_id,
        "display_name": me.get("display_name"),
        "person_name":  person["name"] if person else None,
        "person_id":    person["id"]   if person else None,
        "role":         me.get("role"),
        "tier":         me.get("tier"),
        "household_id": me.get("household_id"),
    }
