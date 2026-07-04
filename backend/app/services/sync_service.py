"""Sync-Service — allgemeiner Relay-Sync mit dem erika-sync-server.

Lokale SQLite-Tabelle als primäre Quelle (funktioniert auch offline).
Sync-Credentials werden automatisch aus der Lizenz-Datei geladen sobald
eine Plus/Family-Lizenz installiert ist — kein manuelles .env nötig.

Auth-Pfade (Priorität):
  1. license.json: sync_email + sync_password → Login via /auth/login (JWT)
  2. license.json: sync_jwt → statisches Token (Legacy)
  3. Env-Vars: SYNC_EMAIL + SYNC_PASSWORD → Login via /auth/login
  4. Env-Vars: SYNC_SERVER_TOKEN → statisches Token (Self-Hosted)

Sync-Protokoll:
  GET  /items?since=<ISO>  → Delta-Sync (inkl. deleted=1)
  POST /items              → Eintrag anlegen (idempotent)
  PATCH /items/{id}        → Text / checked / sort_order
  DELETE /items/{id}       → Soft-Delete
"""
from __future__ import annotations

import json
import os
import ssl
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import request as _req

from app.database.db import get_connection

_LICENSE_FILE = Path("/data/license.json")

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode    = ssl.CERT_NONE

# Token-Cache für email/password Auth (verhindert Login-Spam)
_token_cache: dict[str, Any] = {
    "access_token":   "",
    "refresh_token":  "",
    "expires_at":     None,  # datetime oder None
    "base_url":       "",
}
_token_lock = threading.Lock()


def reset_token_cache() -> None:
    """Token-Cache leeren — sofort neuen Login erzwingen (z.B. nach Credential-Änderung)."""
    with _token_lock:
        _token_cache.update({"access_token": "", "refresh_token": "", "expires_at": None, "base_url": ""})


def push_device_heartbeat() -> None:
    """Registriert dieses Gerät mit seinem Namen am Sync-Server."""
    from app.services.integration_config_service import IntegrationConfigService
    from app.services.license_service import LicenseService
    try:
        device_id = LicenseService.device_id()
        cfg = IntegrationConfigService().get_config()
        name = (cfg.get("system") or {}).get("device", {}).get("name") or "Erika"
    except Exception:
        return
    _sync_request("POST", "/devices/erika/heartbeat", {"device_id": device_id, "name": name})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _do_login(url: str, email: str, password: str) -> tuple[str, str] | None:
    """Führt POST /auth/login aus. Gibt (access_token, refresh_token) zurück."""
    body = json.dumps({"email": email, "password": password}).encode()
    req  = _req.Request(f"{url}/auth/login", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with _req.urlopen(req, timeout=10, context=_SSL_CTX) as resp:
            data = json.loads(resp.read())
        return data["access_token"], data.get("refresh_token", "")
    except Exception:
        return None


def _do_refresh(url: str, refresh_token: str) -> tuple[str, str] | None:
    """Führt POST /auth/refresh aus. Gibt (access_token, refresh_token) zurück."""
    body = json.dumps({"refresh_token": refresh_token}).encode()
    req  = _req.Request(f"{url}/auth/refresh", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with _req.urlopen(req, timeout=10, context=_SSL_CTX) as resp:
            data = json.loads(resp.read())
        return data["access_token"], data.get("refresh_token", "")
    except Exception:
        return None


def _get_token_via_email(url: str, email: str, password: str) -> str:
    """Gibt ein gültiges Access-Token zurück (mit automatischem Refresh)."""
    now = datetime.now(timezone.utc)
    with _token_lock:
        c = _token_cache
        if (
            c["access_token"]
            and c["base_url"] == url
            and c["expires_at"] is not None
            and now < c["expires_at"] - timedelta(minutes=5)
        ):
            return c["access_token"]

        # Refresh versuchen wenn Token vorhanden aber abgelaufen
        if c["refresh_token"] and c["base_url"] == url:
            result = _do_refresh(url, c["refresh_token"])
            if result:
                access, refresh = result
                c["access_token"]  = access
                c["refresh_token"] = refresh
                c["expires_at"]    = now + timedelta(hours=1)
                c["base_url"]      = url
                return access

        # Frischer Login
        result = _do_login(url, email, password)
        if result:
            access, refresh = result
            c["access_token"]  = access
            c["refresh_token"] = refresh
            c["expires_at"]    = now + timedelta(hours=1)
            c["base_url"]      = url
            return access

    return ""


def get_credentials() -> tuple[str, str]:
    """Sync-URL und Token laden.

    Gibt (sync_url, bearer_token) zurück. Beide leer → kein Sync konfiguriert.
    """
    try:
        lic = json.loads(_LICENSE_FILE.read_text(encoding="utf-8"))
        url   = str(lic.get("sync_url")      or "").rstrip("/")
        email = str(lic.get("sync_email")    or "").strip()
        pw    = str(lic.get("sync_password") or "").strip()
        if url and email and pw:
            tok = _get_token_via_email(url, email, pw)
            return url, tok
        tok = str(lic.get("sync_jwt") or "")
        if url and tok:
            return url, tok
    except Exception:
        pass

    # Fallback: Env-Vars
    url   = os.getenv("SYNC_SERVER_URL",   "").rstrip("/")
    email = os.getenv("SYNC_EMAIL",        "").strip()
    pw    = os.getenv("SYNC_PASSWORD",     "").strip()
    if url and email and pw:
        tok = _get_token_via_email(url, email, pw)
        return url, tok
    return url, os.getenv("SYNC_SERVER_TOKEN", "")


def _row(r) -> dict[str, Any]:
    return {
        "id":         r["id"],
        "text":       r["text"],
        "checked":    bool(r["checked"]),
        "sort_order": r["sort_order"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "deleted":    bool(r["deleted"]),
    }


# ── Lokale CRUD ────────────────────────────────────────────────────────────

def list_items() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM sync_items WHERE deleted = 0 ORDER BY sort_order ASC, created_at ASC"
        ).fetchall()
    return [_row(r) for r in rows]


def create_item(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise ValueError("text darf nicht leer sein")
    now     = _now()
    item_id = str(uuid.uuid4())
    with get_connection() as conn:
        next_order = (conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM sync_items WHERE deleted = 0"
        ).fetchone()[0])
        conn.execute(
            "INSERT INTO sync_items(id, text, checked, sort_order, created_at, updated_at, deleted) VALUES (?,?,0,?,?,?,0)",
            (item_id, text, next_order, now, now),
        )
        row = conn.execute("SELECT * FROM sync_items WHERE id = ?", (item_id,)).fetchone()
    return _row(row)


def update_item(item_id: str, text: str | None = None, checked: bool | None = None, sort_order: int | None = None) -> dict[str, Any] | None:
    now = _now()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM sync_items WHERE id = ? AND deleted = 0", (item_id,)
        ).fetchone()
        if not row:
            return None
        new_text       = text.strip()    if text       is not None else row["text"]
        new_checked    = int(checked)    if checked    is not None else row["checked"]
        new_sort_order = int(sort_order) if sort_order is not None else row["sort_order"]
        conn.execute(
            "UPDATE sync_items SET text=?, checked=?, sort_order=?, updated_at=? WHERE id=?",
            (new_text, new_checked, new_sort_order, now, item_id),
        )
        row = conn.execute("SELECT * FROM sync_items WHERE id=?", (item_id,)).fetchone()
    return _row(row)


def delete_item(item_id: str) -> bool:
    now = _now()
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE sync_items SET deleted=1, updated_at=? WHERE id=? AND deleted=0",
            (now, item_id),
        )
    return cur.rowcount > 0


def clear_checked() -> int:
    now = _now()
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE sync_items SET deleted=1, updated_at=? WHERE checked=1 AND deleted=0",
            (now,),
        )
    return cur.rowcount


# ── Sync-Hilfsfunktionen ───────────────────────────────────────────────────

def _sync_request(method: str, path: str, body: dict | None = None) -> dict | None:
    url_base, token = get_credentials()
    if not url_base or not token:
        return None
    url  = f"{url_base}{path}"
    data = json.dumps(body).encode() if body else None
    req  = _req.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with _req.urlopen(req, timeout=8, context=_SSL_CTX) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def push_item(item: dict[str, Any]) -> None:
    if item.get("deleted"):
        _sync_request("DELETE", f"/items/{item['id']}")
    else:
        _sync_request("POST", "/items", {
            "id":         item["id"],
            "text":       item["text"],
            "sort_order": item["sort_order"],
            "created_at": item["created_at"],
        })
        if item.get("checked") is not None:
            _sync_request("PATCH", f"/items/{item['id']}", {"checked": item["checked"]})
    _mark_synced(item["id"])


def pull_and_merge(since: str | None = None) -> int:
    path   = "/items" + (f"?since={since}" if since else "")
    result = _sync_request("GET", path)
    if not result:
        return 0
    merged = 0
    now    = _now()
    with get_connection() as conn:
        for item in result.get("items", []):
            existing  = conn.execute(
                "SELECT updated_at FROM sync_items WHERE id = ?", (item["id"],)
            ).fetchone()
            remote_ts = item.get("updated_at", "")
            if existing and existing["updated_at"] >= remote_ts:
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO sync_items
                    (id, text, checked, sort_order, created_at, updated_at, deleted, synced_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    item["id"], item.get("text", ""),
                    int(bool(item.get("checked"))),
                    item.get("sort_order", 0),
                    item.get("created_at", now),
                    remote_ts,
                    int(bool(item.get("deleted"))),
                    now,
                ),
            )
            merged += 1
    return merged


def get_last_sync_time() -> str | None:
    with get_connection() as conn:
        row = conn.execute("SELECT MAX(synced_at) AS t FROM sync_items").fetchone()
    return row["t"] if row else None


def _mark_synced(item_id: str) -> None:
    now = _now()
    with get_connection() as conn:
        conn.execute("UPDATE sync_items SET synced_at=? WHERE id=?", (now, item_id))


def push_unsynced() -> int:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM sync_items WHERE synced_at IS NULL OR updated_at > synced_at"
        ).fetchall()
    count = 0
    for r in rows:
        push_item(_row(r) | {"deleted": bool(r["deleted"])})
        count += 1
    return count


# ── Personen ───────────────────────────────────────────────────────────────

def push_persons() -> int:
    with get_connection() as conn:
        rows = conn.execute("SELECT id, name FROM persons").fetchall()
    count = 0
    for r in rows:
        result = _sync_request("POST", "/persons", {
            "id":   str(r["id"]),
            "name": r["name"],
        })
        if result:
            count += 1
    return count


# ── Notizen ────────────────────────────────────────────────────────────────

def _notes_push_key() -> str:
    return "__notes_push_sync__"


def _notes_pull_key() -> str:
    return "__notes_pull_sync__"


def _get_notes_last_sync() -> str | None:
    return _get_state_ts(_notes_push_key())


def _set_notes_last_sync(ts: str) -> None:
    _set_state_ts(_notes_push_key(), ts)


def _get_notes_pull_sync() -> str | None:
    return _get_state_ts(_notes_pull_key())


def _set_notes_pull_sync(ts: str) -> None:
    _set_state_ts(_notes_pull_key(), ts)


def push_notes() -> int:
    since = _get_notes_last_sync()
    with get_connection() as conn:
        if since:
            rows = conn.execute(
                "SELECT * FROM person_notes WHERE updated_at > ? ORDER BY updated_at ASC",
                (since,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM person_notes ORDER BY updated_at ASC"
            ).fetchall()
    now = _now()
    count = 0
    for r in rows:
        sync_id = str(r["id"])
        result = _sync_request("POST", "/notes", {
            "id":         sync_id,
            "title":      r["title"],
            "content":    r["content"],
            "person_id":  str(r["person_id"]) if r["person_id"] else None,
            "created_at": r["created_at"],
        })
        if result and not result.get("error"):
            # sync_server_id lokal setzen damit pull_notes das Original erkennt
            if not r["sync_server_id"]:
                with get_connection() as conn2:
                    conn2.execute(
                        "UPDATE person_notes SET sync_server_id=? WHERE id=?",
                        (sync_id, r["id"]),
                    )
            count += 1
    if count > 0:
        _set_notes_last_sync(now)
    return count


def pull_notes() -> int:
    since = _get_notes_pull_sync()
    now   = _now()
    path  = "/notes" + (f"?since={since}" if since else "")
    result = _sync_request("GET", path)
    if not result:
        return 0
    merged = 0
    with get_connection() as conn:
        for note in result.get("notes", []):
            sync_id = str(note["id"])
            remote_ts = note.get("updated_at", "")
            if note.get("deleted"):
                conn.execute(
                    "DELETE FROM person_notes WHERE sync_server_id = ?", (sync_id,)
                )
                merged += 1
                continue
            existing = conn.execute(
                "SELECT id, updated_at FROM person_notes WHERE sync_server_id = ?", (sync_id,)
            ).fetchone()
            if existing and existing["updated_at"] >= remote_ts:
                continue
            person_id = int(note["person_id"]) if note.get("person_id") else None
            if existing:
                conn.execute(
                    "UPDATE person_notes SET title=?, content=?, person_id=?, updated_at=? WHERE id=?",
                    (note["title"], note.get("content", ""), person_id, remote_ts, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO person_notes(title, content, person_id, created_at, updated_at, sync_server_id) VALUES (?,?,?,?,?,?)",
                    (
                        note["title"], note.get("content", ""),
                        person_id,
                        note.get("created_at", remote_ts),
                        remote_ts,
                        sync_id,
                    ),
                )
            merged += 1
    _set_notes_pull_sync(now)
    return merged


# ── Erinnerungen ───────────────────────────────────────────────────────────

def _reminders_push_key() -> str:
    return "__reminders_push_sync__"


def _reminders_pull_key() -> str:
    return "__reminders_pull_sync__"


def _get_reminders_last_sync() -> str | None:
    return _get_state_ts(_reminders_push_key())


def _set_reminders_last_sync(ts: str) -> None:
    _set_state_ts(_reminders_push_key(), ts)


def _get_reminders_pull_sync() -> str | None:
    return _get_state_ts(_reminders_pull_key())


def _set_reminders_pull_sync(ts: str) -> None:
    _set_state_ts(_reminders_pull_key(), ts)


def _get_state_ts(key: str) -> str | None:
    import json as _json
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM system_state WHERE key = ?", (key,)
        ).fetchone()
    if not row:
        return None
    try:
        return _json.loads(row["value"]).get("t")
    except Exception:
        return None


def _set_state_ts(key: str, ts: str) -> None:
    import json as _json
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO system_state(key, value) VALUES (?,?)",
            (key, _json.dumps({"t": ts})),
        )


def push_reminders() -> int:
    since = _get_reminders_last_sync()
    with get_connection() as conn:
        if since:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE created_at > ? ORDER BY created_at ASC",
                (since,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM reminders ORDER BY created_at ASC").fetchall()
        # Push dismissals for already-synced reminders — created_at might predate since
        dismissed_rows = conn.execute(
            "SELECT * FROM reminders WHERE dismissed=1 AND sync_server_id IS NOT NULL"
        ).fetchall()
    now = _now()
    count = 0
    for r in rows:
        sync_id = str(r["id"])
        result = _sync_request("POST", "/reminders", {
            "id":          sync_id,
            "text":        r["text"],
            "fire_at":     r["fire_at"],
            "person_name": r["person_name"],
            "created_at":  r["created_at"],
        })
        if result and not result.get("error"):
            if r["dismissed"]:
                _sync_request("PATCH", f"/reminders/{sync_id}", {"dismissed": True})
            if r["notified"]:
                _sync_request("PATCH", f"/reminders/{sync_id}", {"notified": True})
            if not r["sync_server_id"]:
                with get_connection() as conn2:
                    conn2.execute(
                        "UPDATE reminders SET sync_server_id=? WHERE id=?",
                        (sync_id, r["id"]),
                    )
            count += 1
    # Push dismissals for reminders that were already synced before last push
    for r in dismissed_rows:
        _sync_request("PATCH", f"/reminders/{r['sync_server_id']}", {"dismissed": True})
    if count > 0:
        _set_reminders_last_sync(now)
    return count


def pull_reminders() -> int:
    since = _get_reminders_pull_sync()
    now   = _now()
    path  = "/reminders" + (f"?since={since}" if since else "")
    result = _sync_request("GET", path)
    if not result:
        return 0
    merged = 0
    with get_connection() as conn:
        for rem in result.get("reminders", []):
            sync_id = str(rem["id"])
            if rem.get("deleted"):
                conn.execute("DELETE FROM reminders WHERE sync_server_id = ?", (sync_id,))
                merged += 1
                continue
            existing = conn.execute(
                "SELECT id, dismissed FROM reminders WHERE sync_server_id = ?", (sync_id,)
            ).fetchone()
            if existing:
                if rem.get("dismissed") and not existing["dismissed"]:
                    conn.execute("UPDATE reminders SET dismissed=1 WHERE id=?", (existing["id"],))
                merged += 1
            else:
                conn.execute(
                    "INSERT INTO reminders(text, fire_at, person_name, notified, dismissed, created_at, sync_server_id) VALUES (?,?,?,0,0,?,?)",
                    (
                        rem["text"],
                        rem["fire_at"],
                        rem.get("person_name"),
                        rem.get("created_at", _now()),
                        sync_id,
                    ),
                )
                merged += 1
    _set_reminders_pull_sync(now)
    return merged


# ── Hausaufgaben ───────────────────────────────────────────────────────────

def _chores_last_sync_key() -> str:
    return "__chores_last_sync__"


def _get_chores_last_sync() -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM system_state WHERE key = ?", (_chores_last_sync_key(),)
        ).fetchone()
    if not row:
        return None
    import json as _json
    try:
        return _json.loads(row["value"]).get("t")
    except Exception:
        return None


def _set_chores_last_sync(ts: str) -> None:
    import json as _json
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO system_state(key, value) VALUES (?,?)",
            (_chores_last_sync_key(), _json.dumps({"t": ts})),
        )


def push_chore_tasks() -> int:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, icon, sort_order, active, points, created_at, updated_at FROM chore_tasks"
        ).fetchall()
    count = 0
    for r in rows:
        result = _sync_request("POST", "/chores/tasks", {
            "id":         str(r["id"]),
            "name":       r["name"],
            "icon":       r["icon"],
            "sort_order": r["sort_order"],
            "active":     bool(r["active"]),
            "points":     r["points"] if r["points"] is not None else 1,
            "created_at": r["created_at"],
        })
        if result and not result.get("error"):
            count += 1
    return count


def push_chore_completions() -> int:
    since = _get_chores_last_sync()
    with get_connection() as conn:
        if since:
            rows = conn.execute(
                "SELECT * FROM chore_completions WHERE completed_at > ? ORDER BY completed_at ASC",
                (since,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM chore_completions ORDER BY completed_at ASC"
            ).fetchall()
    now = _now()
    count = 0
    for r in rows:
        result = _sync_request("POST", "/chores/completions", {
            "id":           str(r["id"]),
            "task_id":      str(r["task_id"]),
            "person_id":    str(r["person_id"]),
            "completed_at": r["completed_at"],
        })
        if result and not result.get("error"):
            count += 1
    if count > 0:
        _set_chores_last_sync(now)
    return count


def _get_chores_last_pull() -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM system_state WHERE key = ?", ("__chores_last_pull__",)
        ).fetchone()
    if not row:
        return None
    import json as _json
    try:
        return _json.loads(row["value"]).get("t")
    except Exception:
        return None


def _set_chores_last_pull(ts: str) -> None:
    import json as _json
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO system_state(key, value) VALUES (?,?)",
            ("__chores_last_pull__", _json.dumps({"t": ts})),
        )


def pull_chore_completions() -> int:
    since = _get_chores_last_pull()
    path  = "/chores/completions" + (f"?since={since}" if since else "")
    result = _sync_request("GET", path)
    if not result:
        return 0
    merged = 0
    with get_connection() as conn:
        for comp in result.get("completions", []):
            sync_id = str(comp.get("id", ""))

            # task_id / person_id müssen lokale Integer sein
            try:
                task_id   = int(comp["task_id"])
                person_id = int(comp["person_id"])
            except (ValueError, TypeError):
                continue

            if comp.get("deleted"):
                try:
                    local_id = int(sync_id)
                    conn.execute("DELETE FROM chore_completions WHERE id = ?", (local_id,))
                except (ValueError, TypeError):
                    conn.execute(
                        "DELETE FROM chore_completions WHERE sync_id = ?", (sync_id,)
                    )
                merged += 1
                continue

            # Duplikat-Prüfung: Integer-IDs über id, UUID-IDs über sync_id
            try:
                local_id = int(sync_id)
                existing = conn.execute(
                    "SELECT id FROM chore_completions WHERE id = ?", (local_id,)
                ).fetchone()
            except (ValueError, TypeError):
                local_id = None
                existing = conn.execute(
                    "SELECT id FROM chore_completions WHERE sync_id = ?", (sync_id,)
                ).fetchone()

            if existing:
                continue

            try:
                if local_id is not None:
                    conn.execute(
                        "INSERT INTO chore_completions(id, task_id, person_id, completed_at) VALUES (?,?,?,?)",
                        (local_id, task_id, person_id, comp["completed_at"]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO chore_completions(task_id, person_id, completed_at, sync_id) VALUES (?,?,?,?)",
                        (task_id, person_id, comp["completed_at"], sync_id),
                    )
                merged += 1
            except Exception:
                pass
    _set_chores_last_pull(_now())
    return merged


def push_chore_completion_deletion(completion_id: int, sync_id: str | None = None) -> None:
    """Informiert den Sync-Server über eine lokal gelöschte Completion."""
    remote_id = sync_id if sync_id else str(completion_id)
    _sync_request("DELETE", f"/chores/completions/{remote_id}")


# ── Abfallkalender ─────────────────────────────────────────────────────────

def push_waste() -> bool:
    from datetime import date
    try:
        from app.services.waste_service import WasteService
        from app.services.integration_config_service import IntegrationConfigService
        config = IntegrationConfigService().get_config()
        waste_cfg = config.get("waste") or {}
        if not waste_cfg.get("enabled"):
            return False
        bins_cfg = waste_cfg.get("bins") or []
        entity   = (waste_cfg.get("calendar_entity") or "calendar.abfallkalender").strip()
        from app.search.providers.homeassistant import HomeAssistantProvider
        ha     = HomeAssistantProvider()
        events = ha.get_events_upcoming(days=42, selected_calendars=[entity])
        today  = date.today()
        result_events: list[dict] = []
        seen: set[tuple] = set()
        for ev in events:
            title = (ev.get("summary") or ev.get("title") or "").lower()
            start = ev.get("start") or {}
            dstr  = start.get("date") or (start.get("dateTime", "")[:10])
            if not dstr:
                continue
            try:
                edate = date.fromisoformat(dstr)
            except ValueError:
                continue
            if edate < today:
                continue
            days = (edate - today).days
            for rule in bins_cfg:
                match = str(rule.get("match") or "").lower().strip()
                if match and match in title:
                    key = (dstr, rule.get("label", match))
                    if key not in seen:
                        seen.add(key)
                        result_events.append({
                            "date":   dstr,
                            "label":  rule.get("label") or match,
                            "color":  rule.get("color") or "black",
                            "days":   days,
                        })
                    break
        result_events.sort(key=lambda e: e["date"])
        _sync_request("POST", "/waste", {"events": result_events})
        return True
    except Exception:
        return False


# ── News ────────────────────────────────────────────────────────────────────

_news_push_key = "__news_push_sync__"


def push_news() -> bool:
    try:
        import time as _time
        import json as _json
        # Nur alle 10 Minuten pushen — News ändern sich selten
        with get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM system_state WHERE key=?", (_news_push_key,)
            ).fetchone()
        if row:
            last = _json.loads(row["value"]).get("t", 0)
            if _time.time() - float(last) < 600:
                return True

        from app.api.routers.content import get_news, _news_cache
        from app.services.integration_config_service import IntegrationConfigService
        from datetime import datetime, timezone, timedelta
        # Populate cache if empty
        if not _news_cache.get("items"):
            get_news()
        cfg = IntegrationConfigService()
        lookback = cfg.get_news_lookback_hours()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback)

        def _pd(v: str):
            try:
                dt = datetime.fromisoformat(v)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                return datetime.min.replace(tzinfo=timezone.utc)

        items = [
            {
                "title":      i["title"],
                "link":       i.get("link", ""),
                "pub_date":   i.get("pub_date", ""),
                "description": (i.get("description") or "")[:200],
                "source":     i.get("source", ""),
                "source_key": i.get("source_key", ""),
            }
            for i in _news_cache.get("items", [])
            if _pd(i.get("pub_date", "")) >= cutoff
        ][:30]

        _sync_request("POST", "/news", {"items": items})
        with get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO system_state(key,value) VALUES(?,?)",
                (_news_push_key, _json.dumps({"t": str(_time.time())})),
            )
        return True
    except Exception:
        return False


# ── PV ──────────────────────────────────────────────────────────────────────

# Tagesdaten (feed-in, grid draw, costs) werden aus der HA-History berechnet —
# das ist teuer, daher nur alle 60 Sekunden neu abgerufen.
_pv_daily_cache: dict = {"data": None, "ts": 0.0}
_PV_DAILY_TTL = 60.0


def push_pv() -> bool:
    import time as _time
    try:
        from app.services.integration_config_service import IntegrationConfigService
        from app.services.pv_service import PvService
        from app.api.routers.ha_energy_costs import (
            _energy_sensors,
            _energy_tariffs,
            _integrate_power_daily_from_history,
            _energy_costs,
            _fixed_costs,
            _LOCAL_TZ,
        )
        from app.search.providers.homeassistant import HomeAssistantProvider
        from datetime import datetime, timezone

        cfg = IntegrationConfigService().get_config()
        pv_cfg = cfg.get("pv") or {}
        if not pv_cfg.get("enabled"):
            return False

        # ── Echtzeitdaten (immer frisch) ──────────────────────────────────
        sensors = pv_cfg.get("sensors") or {}
        state = PvService().get_state(sensors)

        def _val(key: str):
            entry = state.get(key)
            if not entry:
                return None
            v = entry.get("value")
            if v is None or str(v).lower() in ("unavailable", "unknown", ""):
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        # ── Tagesdaten aus HA-History (gecacht) ──────────────────────────
        now_t = _time.time()
        if now_t - _pv_daily_cache["ts"] >= _PV_DAILY_TTL:
            sensors_cfg = _energy_sensors(cfg)
            feed_in_ct, grid_ct, base_eur_year, extra_eur_year = _energy_tariffs(cfg)
            annual_fixed = base_eur_year + extra_eur_year

            now_loc = datetime.now(_LOCAL_TZ)
            now_utc = now_loc.astimezone(timezone.utc)
            start_utc = now_loc.replace(
                hour=0, minute=0, second=0, microsecond=0
            ).astimezone(timezone.utc)
            today_key = now_loc.strftime("%Y-%m-%d")

            ha = HomeAssistantProvider()
            daily_feed_in  = 0.0
            daily_grid_draw = 0.0

            for s in sensors_cfg:
                eid = s.get("entity_id", "")
                if not eid:
                    continue
                signed = s.get("role") == "grid"
                daily = _integrate_power_daily_from_history(
                    eid, start_utc, now_utc, ha, signed
                )
                today = daily.get(today_key, {})
                if signed:
                    daily_feed_in  += today.get("einspeisung", 0.0)
                    daily_grid_draw += today.get("netzbezug", 0.0)

            costs = None
            if feed_in_ct > 0 or grid_ct > 0 or annual_fixed > 0:
                fixed_today = _fixed_costs(now_loc, now_loc, annual_fixed)
                costs = _energy_costs(daily_feed_in, daily_grid_draw, feed_in_ct, grid_ct, fixed_today)

            _pv_daily_cache["data"] = {
                "daily_feed_in_kwh":  round(daily_feed_in, 2)  if sensors_cfg else None,
                "daily_grid_draw_kwh": round(daily_grid_draw, 2) if sensors_cfg else None,
                "daily_earnings_eur": costs["einspeisung_value"] if costs else None,
                "daily_cost_eur":     costs["netzbezug_cost"]    if costs else None,
                "daily_saldo_eur":    costs["saldo"]             if costs else None,
            }
            _pv_daily_cache["ts"] = now_t

        cached = _pv_daily_cache["data"] or {}

        data = {
            "power_w":            _val("power"),
            "daily_kwh":          _val("daily"),
            "battery_pct":        _val("battery"),
            "grid_w":             _val("grid"),
            "house_w":            _val("house_consumption"),
            **cached,
        }
        _sync_request("POST", "/pv", {"data": data})
        return True
    except Exception:
        return False


# ── Lichter ────────────────────────────────────────────────────────────────────

def push_lights() -> bool:
    try:
        from app.services.integration_config_service import IntegrationConfigService
        from app.services.light_service import LightService
        config = IntegrationConfigService().get_config()
        light_cfg = config.get("lights") or {}
        if not light_cfg.get("enabled", True):
            return False
        lights = LightService().list_lights(config)
        # Nur Top-Level-Gruppen: Mitglieder ausblenden (gleiche Logik wie Display-Panel)
        member_ids: set[str] = set()
        for light in lights:
            member_ids.update(str(m) for m in (light.get("members") or []))
        top_level = [l for l in lights if l.get("entity_id") not in member_ids]
        _sync_request("POST", "/lights", {"lights": top_level})
        return True
    except Exception:
        return False


def push_light_scenes() -> bool:
    try:
        from app.services.integration_config_service import IntegrationConfigService
        from app.database.db import get_connection as _rc_conn
        config = IntegrationConfigService().get_config()
        light_cfg = config.get("lights") or {}
        if not light_cfg.get("enabled", True):
            return False
        with _rc_conn() as conn:
            rows = conn.execute(
                "SELECT id, name FROM light_scenes ORDER BY created_at ASC"
            ).fetchall()
        scenes = [{"id": r["id"], "name": r["name"]} for r in rows]
        _sync_request("POST", "/lights/scenes", {"scenes": scenes})
        return True
    except Exception:
        return False


def poll_light_commands() -> int:
    try:
        result = _sync_request("GET", "/lights/commands/pending")
        if not result:
            return 0
        commands = result.get("commands") or []
        if not commands:
            return 0
        import json as _json
        from app.services.integration_config_service import IntegrationConfigService
        from app.services.light_service import LightService
        from app.database.db import get_connection as _rc_conn
        config = IntegrationConfigService().get_config()
        svc = LightService()
        done_ids: list[str] = []
        for cmd in commands:
            try:
                if cmd["type"] == "control":
                    svc.control_light(cmd["payload"])
                elif cmd["type"] == "scene_apply":
                    scene_id = cmd["payload"].get("scene_id")
                    if scene_id is not None:
                        with _rc_conn() as conn:
                            row = conn.execute(
                                "SELECT light_states FROM light_scenes WHERE id = ?", (scene_id,)
                            ).fetchone()
                        if row:
                            states: list[dict] = _json.loads(row["light_states"])
                            for light in states:
                                entity_id = light.get("entity_id", "")
                                if not entity_id:
                                    continue
                                if light.get("state") == "off":
                                    svc.control_light({"entity_id": entity_id, "service": "turn_off"})
                                else:
                                    payload: dict = {"entity_id": entity_id, "service": "turn_on"}
                                    if light.get("brightness_pct") is not None:
                                        payload["brightness_pct"] = light["brightness_pct"]
                                    if light.get("hs_color"):
                                        payload["hs_color"] = light["hs_color"]
                                    elif light.get("color_temp_kelvin"):
                                        payload["color_temp_kelvin"] = light["color_temp_kelvin"]
                                    svc.control_light(payload)
            except Exception:
                pass
            done_ids.append(cmd["id"])
        if done_ids:
            _sync_request("POST", "/lights/commands/done", {"ids": done_ids})
        return len(done_ids)
    except Exception:
        return 0


# ── Kalender ────────────────────────────────────────────────────────────────

def push_calendar() -> bool:
    try:
        from app.services.integration_config_service import IntegrationConfigService
        from app.search.providers.homeassistant import HomeAssistantProvider

        cfg = IntegrationConfigService().get_config()
        cal_cfg = cfg.get("calendar") or {}
        selected = cal_cfg.get("selected_calendars") or None
        excluded = list(cal_cfg.get("excluded_calendars") or [])
        days = int(cal_cfg.get("sync_days") or 30)

        # Mülltonnen-Kalender nicht synchronisieren — wird in der App separat dargestellt
        waste_entity = ((cfg.get("waste") or {}).get("calendar_entity") or "calendar.abfallkalender").strip()
        if waste_entity not in excluded:
            excluded.append(waste_entity)

        ha = HomeAssistantProvider()
        raw_events = ha.get_events_upcoming(
            days=days,
            selected_calendars=selected,
            exclude_calendars=excluded if excluded else None,
        )

        events = []
        for ev in raw_events:
            start = ev.get("start") or {}
            end   = ev.get("end")   or {}
            events.append({
                "summary":     ev.get("summary", ""),
                "description": ev.get("description") or "",
                "start":       start.get("dateTime") or start.get("date") or "",
                "end":         end.get("dateTime")   or end.get("date")   or "",
                "all_day":     "dateTime" not in start,
                "calendar":    ev.get("_calendar", ""),
            })

        _sync_request("POST", "/calendar", {"events": events})
        return True
    except Exception:
        return False
