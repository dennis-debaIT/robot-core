from __future__ import annotations

import os
import shutil
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from fastapi import APIRouter

router = APIRouter()

_TIMEOUT = 4


def _ok(name: str, detail: str = "") -> dict[str, str]:
    return {"name": name, "status": "ok", "detail": detail}


def _warn(name: str, detail: str = "") -> dict[str, str]:
    return {"name": name, "status": "warn", "detail": detail}


def _err(name: str, detail: str = "") -> dict[str, str]:
    return {"name": name, "status": "error", "detail": detail}


# ── individuelle Checks ──────────────────────────────────────────────────────

def _chk_db() -> dict:
    try:
        from app.database.db import get_connection
        with get_connection() as conn:
            conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        return _ok("Datenbank", "erreichbar")
    except Exception as exc:
        return _err("Datenbank", str(exc))


def _chk_data_write() -> dict:
    path = "/data/.diag_write_test"
    try:
        with open(path, "w") as f:
            f.write("ok")
        os.unlink(path)
        return _ok("Schreibrechte /data", "OK")
    except Exception as exc:
        return _err("Schreibrechte /data", str(exc))


def _chk_disk() -> dict:
    try:
        usage = shutil.disk_usage("/data")
        free_gb = usage.free / 1024 ** 3
        total_gb = usage.total / 1024 ** 3
        detail = f"{free_gb:.1f} GB frei von {total_gb:.1f} GB"
        if free_gb < 1.0:
            return _err("Freier Speicher", detail + " — kritisch")
        if free_gb < 5.0:
            return _warn("Freier Speicher", detail + " — wenig")
        return _ok("Freier Speicher", detail)
    except Exception as exc:
        return _err("Freier Speicher", str(exc))


def _chk_ha() -> dict:
    try:
        from app.services.homeassistant_runtime_config_service import HomeAssistantRuntimeConfigService
        result = HomeAssistantRuntimeConfigService.test_connection()
        if result.get("ok"):
            return _ok("Home Assistant", f"erreichbar ({result.get('base_url', '')})")
        detail = result.get("detail", "Verbindung fehlgeschlagen")
        if result.get("token_required") and not HomeAssistantRuntimeConfigService.get_config().get("token"):
            return _err("Home Assistant", "Token nicht konfiguriert")
        return _err("Home Assistant", detail)
    except Exception as exc:
        return _err("Home Assistant", f"Fehler: {type(exc).__name__}: {exc}")


def _chk_llm() -> dict:
    try:
        from app.brain.llm_client import ExternalLLMClient
        client = ExternalLLMClient()
        if not client.is_configured():
            return _err("LLM", "URL nicht konfiguriert")
        # Nur Erreichbarkeit prüfen, kein vollständiger Inferenz-Call
        api_url = client.api_url or ""
        base = api_url.split("/v1/")[0] if "/v1/" in api_url else api_url.rsplit("/", 2)[0]
        try:
            urllib.request.urlopen(base, timeout=_TIMEOUT)
        except urllib.error.HTTPError:
            pass  # HTTP-Fehler = Server antwortet zumindest
        return _ok("LLM", f"erreichbar ({client.model or 'Modell unbekannt'})")
    except Exception as exc:
        return _err("LLM", f"nicht erreichbar: {type(exc).__name__}")


def _chk_tts() -> dict:
    provider = os.getenv("ROBOT_TTS_PROVIDER", "disabled")
    if provider in ("disabled", ""):
        return _warn("TTS", "deaktiviert")
    if provider == "edge_tts":
        voice = os.getenv("ROBOT_TTS_VOICE_LABEL", "nicht gesetzt")
        return _ok("TTS", f"edge_tts · {voice}")
    if provider == "sherpa_onnx":
        model = os.getenv("ROBOT_TTS_VITS_MODEL", "")
        ok = bool(model and os.path.exists(model))
        return (_ok if ok else _err)("TTS", f"sherpa_onnx · Modell {'gefunden' if ok else 'nicht gefunden'}")
    return _ok("TTS", provider)


def _chk_sync() -> dict:
    try:
        from app.services.sync_service import get_credentials, _sync_request
        url, token = get_credentials()
        if not (url and token):
            return _warn("Sync Server", "nicht konfiguriert (kein Token)")
        result = _sync_request("GET", "/health")
        if result is None:
            return _err("Sync Server", "nicht erreichbar")
        return _ok("Sync Server", url)
    except Exception as exc:
        return _err("Sync Server", f"{type(exc).__name__}: {exc}")


def _chk_fcm() -> dict:
    try:
        from app.services.push_service import _get_firebase_app
        _get_firebase_app()
        return _ok("Firebase (FCM)", "Credentials gültig")
    except RuntimeError as exc:
        return _err("Firebase (FCM)", str(exc))
    except Exception as exc:
        return _err("Firebase (FCM)", f"Initialisierung fehlgeschlagen: {type(exc).__name__}")


def _chk_devices() -> dict:
    try:
        from app.services.push_service import _get_device_tokens
        tokens = _get_device_tokens()
        count = len(tokens)
        if count == 0:
            return _warn("Companion App", "keine Geräte gekoppelt")
        return _ok("Companion App", f"{count} Gerät(e) registriert")
    except Exception as exc:
        return _warn("Companion App", f"Token-Abfrage fehlgeschlagen: {type(exc).__name__}")


def _chk_backup() -> dict:
    try:
        from app.services.backup_service import backup_info
        info = backup_info()
        if not info.get("exists"):
            return _warn("Cloud-Backup", "kein Backup vorhanden")
        created = info.get("created_at", "unbekannt")[:16].replace("T", " ")
        size_mb = round((info.get("size_bytes") or 0) / 1024 / 1024, 1)
        return _ok("Cloud-Backup", f"vorhanden · {created} · {size_mb} MB")
    except Exception as exc:
        return _warn("Cloud-Backup", f"nicht abrufbar: {type(exc).__name__}")


def _chk_last_error() -> dict:
    try:
        from app.audit.service import AuditService
        entries = AuditService().list_entries(limit=100)
        errors = [e for e in entries if e.get("level") in ("error", "ERROR")]
        if not errors:
            return _ok("Letzter Fehler", "keine Einträge")
        last = errors[0]
        ts = (last.get("timestamp") or "")[:16].replace("T", " ")
        source = last.get("source") or "?"
        msg = (last.get("message") or "")[:80]
        return _warn("Letzter Fehler", f"{ts} [{source}] {msg}")
    except Exception as exc:
        return _warn("Letzter Fehler", f"Audit-Log nicht lesbar: {type(exc).__name__}")


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.get("/admin/diagnostics")
def get_diagnostics() -> dict[str, Any]:
    from app.api.routers.system import _current_version

    git_hash = os.getenv("GIT_HASH", "")[:8] or "unbekannt"
    edition = "unknown"
    try:
        edition = open("/app/edition").read().strip()
    except Exception:
        pass

    try:
        version = _current_version()
    except Exception:
        version = "unbekannt"

    checks = [
        _chk_db(),
        _chk_data_write(),
        _chk_disk(),
        _chk_ha(),
        _chk_llm(),
        _chk_tts(),
        _chk_sync(),
        _chk_fcm(),
        _chk_devices(),
        _chk_backup(),
        _chk_last_error(),
    ]

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Plaintext-Report (keine Secrets)
    icon = {"ok": "✓", "warn": "⚠", "error": "✗"}
    lines = [
        "=== Erika Diagnose-Report ===",
        f"Zeitstempel : {generated_at}",
        f"Version     : {version} ({git_hash})",
        f"Edition     : {edition}",
        "",
    ]
    for c in checks:
        sym = icon.get(c["status"], "?")
        detail = f" — {c['detail']}" if c.get("detail") else ""
        lines.append(f"{sym} {c['name']}{detail}")
    lines.append("")
    lines.append("=== Ende Report ===")
    report_text = "\n".join(lines)

    return {
        "checks": checks,
        "generated_at": generated_at,
        "version": version,
        "git_hash": git_hash,
        "edition": edition,
        "report_text": report_text,
    }
