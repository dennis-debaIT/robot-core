"""Einkaufslisten-Service.

Lokale SQLite-Tabelle als primäre Quelle (funktioniert auch offline).
Änderungen werden mit dem Sync-Server unter SHOPPING_SYNC_URL via Delta-
Sync abgeglichen: Robot pusht eigene Änderungen, pullt neue Einträge der
Android-App.

Sync-Protokoll (identisch mit erika-sync-server):
  GET  /items?since=<ISO>  →  alle Einträge mit updated_at > since
  POST /items              →  Eintrag anlegen (idempotent via INSERT OR REPLACE)
  PATCH /items/{id}        →  Text / checked / sort_order ändern
  DELETE /items/{id}       →  Soft-Delete
"""
from __future__ import annotations

import os
import ssl
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib import request as _req
import json

from app.database.db import get_connection

SYNC_URL: str   = os.getenv("SHOPPING_SYNC_URL", "").rstrip("/")
SYNC_TOKEN: str = os.getenv("SHOPPING_SYNC_TOKEN", "")

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode    = ssl.CERT_NONE   # self-signed wie beim Lizenzserver


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            "SELECT * FROM shopping_items WHERE deleted = 0 ORDER BY sort_order ASC, created_at ASC"
        ).fetchall()
    return [_row(r) for r in rows]


def create_item(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise ValueError("text darf nicht leer sein")
    now       = _now()
    item_id   = str(uuid.uuid4())
    with get_connection() as conn:
        next_order = (conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM shopping_items WHERE deleted = 0"
        ).fetchone()[0])
        conn.execute(
            """
            INSERT INTO shopping_items(id, text, checked, sort_order, created_at, updated_at, deleted)
            VALUES (?, ?, 0, ?, ?, ?, 0)
            """,
            (item_id, text, next_order, now, now),
        )
        row = conn.execute("SELECT * FROM shopping_items WHERE id = ?", (item_id,)).fetchone()
    return _row(row)


def update_item(item_id: str, text: str | None = None, checked: bool | None = None) -> dict[str, Any] | None:
    now = _now()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM shopping_items WHERE id = ? AND deleted = 0", (item_id,)
        ).fetchone()
        if not row:
            return None
        new_text    = text.strip()    if text    is not None else row["text"]
        new_checked = int(checked)    if checked is not None else row["checked"]
        conn.execute(
            "UPDATE shopping_items SET text = ?, checked = ?, updated_at = ? WHERE id = ?",
            (new_text, new_checked, now, item_id),
        )
        row = conn.execute("SELECT * FROM shopping_items WHERE id = ?", (item_id,)).fetchone()
    return _row(row)


def delete_item(item_id: str) -> bool:
    now = _now()
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE shopping_items SET deleted = 1, updated_at = ? WHERE id = ? AND deleted = 0",
            (now, item_id),
        )
    return cur.rowcount > 0


def clear_checked() -> int:
    now = _now()
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE shopping_items SET deleted = 1, updated_at = ? WHERE checked = 1 AND deleted = 0",
            (now,),
        )
    return cur.rowcount


# ── Sync-Hilfsfunktionen ───────────────────────────────────────────────────

def _sync_request(method: str, path: str, body: dict | None = None) -> dict | None:
    if not SYNC_URL or not SYNC_TOKEN:
        return None
    url  = f"{SYNC_URL}{path}"
    data = json.dumps(body).encode() if body else None
    req  = _req.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {SYNC_TOKEN}")
    req.add_header("Content-Type", "application/json")
    try:
        with _req.urlopen(req, timeout=8, context=_SSL_CTX) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def push_item(item: dict[str, Any]) -> None:
    """Lokalen Eintrag zum Sync-Server pushen (idempotent)."""
    if item.get("deleted"):
        _sync_request("DELETE", f"/items/{item['id']}")
    else:
        result = _sync_request("POST", "/items", {
            "id":         item["id"],
            "text":       item["text"],
            "sort_order": item["sort_order"],
            "created_at": item["created_at"],
        })
        if result and not item.get("checked") is None:
            _sync_request("PATCH", f"/items/{item['id']}", {"checked": item["checked"]})
    _mark_synced(item["id"])


def pull_and_merge(since: str | None = None) -> int:
    """Neue/geänderte Einträge vom Sync-Server holen und lokal mergen.
    Gibt die Anzahl übernommener Einträge zurück."""
    path = "/items" + (f"?since={since}" if since else "")
    result = _sync_request("GET", path)
    if not result:
        return 0
    merged = 0
    now    = _now()
    with get_connection() as conn:
        for item in result.get("items", []):
            existing = conn.execute(
                "SELECT updated_at FROM shopping_items WHERE id = ?", (item["id"],)
            ).fetchone()
            remote_ts = item.get("updated_at", "")
            if existing and existing["updated_at"] >= remote_ts:
                continue   # lokale Version ist neuer oder gleich — nicht überschreiben
            conn.execute(
                """
                INSERT OR REPLACE INTO shopping_items
                    (id, text, checked, sort_order, created_at, updated_at, deleted, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["id"],
                    item.get("text", ""),
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
        row = conn.execute(
            "SELECT MAX(synced_at) AS t FROM shopping_items"
        ).fetchone()
    return row["t"] if row else None


def _mark_synced(item_id: str) -> None:
    now = _now()
    with get_connection() as conn:
        conn.execute(
            "UPDATE shopping_items SET synced_at = ? WHERE id = ?", (now, item_id)
        )


def push_unsynced() -> int:
    """Alle noch nicht synchronisierten lokalen Einträge pushen."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM shopping_items WHERE synced_at IS NULL OR updated_at > synced_at"
        ).fetchall()
    count = 0
    for r in rows:
        push_item(_row(r) | {"deleted": bool(r["deleted"])})
        count += 1
    return count
