"""Sync-Service — allgemeiner Relay-Sync mit dem erika-sync-server.

Lokale SQLite-Tabelle als primäre Quelle (funktioniert auch offline).
Sync-Credentials werden automatisch aus der Lizenz-Datei geladen sobald
eine Plus/Family-Lizenz installiert ist — kein manuelles .env nötig.

Fallback: SYNC_SERVER_URL + SYNC_SERVER_TOKEN als Env-Vars für Self-Hosted.

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
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request as _req

from app.database.db import get_connection

_LICENSE_FILE = Path("/data/license.json")

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode    = ssl.CERT_NONE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_credentials() -> tuple[str, str]:
    """Sync-URL und Token aus Lizenz-Datei laden (hat Vorrang vor .env).

    Gibt (sync_url, sync_jwt) zurück. Beide leer → kein Sync konfiguriert.
    Die Lizenz-Datei wird bei jedem Aufruf neu gelesen, damit ein frisches
    JWT nach Lizenz-Renewal sofort aktiv wird ohne Neustart.
    """
    try:
        lic = json.loads(_LICENSE_FILE.read_text(encoding="utf-8"))
        url = str(lic.get("sync_url") or "").rstrip("/")
        tok = str(lic.get("sync_jwt") or "")
        if url and tok:
            return url, tok
    except Exception:
        pass
    # Fallback: manuelle Env-Vars (Self-Hosted ohne Lizenzserver)
    return (
        os.getenv("SYNC_SERVER_URL", "").rstrip("/"),
        os.getenv("SYNC_SERVER_TOKEN", ""),
    )


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


def update_item(item_id: str, text: str | None = None, checked: bool | None = None) -> dict[str, Any] | None:
    now = _now()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM sync_items WHERE id = ? AND deleted = 0", (item_id,)
        ).fetchone()
        if not row:
            return None
        new_text    = text.strip() if text    is not None else row["text"]
        new_checked = int(checked) if checked is not None else row["checked"]
        conn.execute(
            "UPDATE sync_items SET text=?, checked=?, updated_at=? WHERE id=?",
            (new_text, new_checked, now, item_id),
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
