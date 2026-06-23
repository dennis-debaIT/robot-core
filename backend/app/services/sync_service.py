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
            "SELECT id, name, icon, sort_order, active, created_at, updated_at FROM chore_tasks"
        ).fetchall()
    count = 0
    for r in rows:
        result = _sync_request("POST", "/chores/tasks", {
            "id":         str(r["id"]),
            "name":       r["name"],
            "icon":       r["icon"],
            "sort_order": r["sort_order"],
            "active":     bool(r["active"]),
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


def pull_chore_completions() -> int:
    since = _get_chores_last_sync()
    path  = "/chores/completions" + (f"?since={since}" if since else "")
    result = _sync_request("GET", path)
    if not result:
        return 0
    merged = 0
    with get_connection() as conn:
        for comp in result.get("completions", []):
            if comp.get("deleted"):
                try:
                    conn.execute(
                        "DELETE FROM chore_completions WHERE id = ?", (int(comp["id"]),)
                    )
                except Exception:
                    pass
                merged += 1
                continue
            existing = conn.execute(
                "SELECT id FROM chore_completions WHERE id = ?", (int(comp["id"]),)
            ).fetchone()
            if existing:
                continue
            try:
                conn.execute(
                    "INSERT INTO chore_completions(id, task_id, person_id, completed_at) VALUES (?,?,?,?)",
                    (
                        int(comp["id"]),
                        int(comp["task_id"]),
                        int(comp["person_id"]),
                        comp["completed_at"],
                    ),
                )
                merged += 1
            except Exception:
                pass
    return merged


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

def push_pv() -> bool:
    try:
        from app.services.integration_config_service import IntegrationConfigService
        from app.services.pv_service import PvService

        cfg = IntegrationConfigService().get_config()
        pv_cfg = cfg.get("pv") or {}
        if not pv_cfg.get("enabled"):
            return False
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

        tariffs = pv_cfg.get("tariffs") or {}
        feed_in_ct  = float(tariffs.get("feed_in_ct")   or 0)
        grid_ct     = float(tariffs.get("grid_price_ct") or 0)

        daily_kwh      = _val("daily")
        daily_cons_kwh = _val("daily_consumption")
        daily_fi_kwh   = _val("daily_feed_in")

        # Tagesertrag (Einspeisevergütung)
        earnings = round(daily_fi_kwh  * feed_in_ct  / 100, 2) if daily_fi_kwh  is not None else None
        # Tageskosten (Netzbezug × Strompreis)
        cost     = round(daily_cons_kwh * grid_ct     / 100, 2) if daily_cons_kwh is not None else None

        data = {
            "power_w":               _val("power"),
            "daily_kwh":             daily_kwh,
            "battery_pct":           _val("battery"),
            "grid_w":                _val("grid"),
            "house_w":               _val("house_consumption"),
            "daily_consumption_kwh": daily_cons_kwh,
            "daily_feed_in_kwh":     daily_fi_kwh,
            "daily_earnings_eur":    earnings,
            "daily_cost_eur":        cost,
        }
        _sync_request("POST", "/pv", {"data": data})
        return True
    except Exception:
        return False
