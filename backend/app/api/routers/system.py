from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app.api.deps import FRONTEND_INDEX, get_core, get_settings_service
from app.api.schemas import ConfigPatchRequest, DevicePatchRequest
from app.database.db import get_connection, read_state, write_state

router = APIRouter()

_GIT_DIR = "/app"


def _detect_network() -> dict[str, Any]:
    import re
    try:
        out = subprocess.run(
            ["ip", "route", "get", "1.1.1.1"],
            capture_output=True, text=True, timeout=2,
        ).stdout
        m = re.search(r"\bdev\s+(\S+)", out)
        if m:
            iface = m.group(1)
            if iface.startswith(("eth", "enp", "ens", "eno", "enx")):
                return {"type": "lan", "connected": True, "interface": iface}
            if iface.startswith(("wlan", "wlp", "wlx")):
                return {"type": "wifi", "connected": True, "interface": iface}
            return {"type": "unknown", "connected": True, "interface": iface}
    except Exception:
        pass
    # Fallback: /sys/class/net carrier
    try:
        for iface in sorted(os.listdir("/sys/class/net")):
            if iface == "lo":
                continue
            try:
                carrier = Path(f"/sys/class/net/{iface}/carrier").read_text().strip()
                if carrier == "1":
                    if iface.startswith(("eth", "enp", "ens", "eno")):
                        return {"type": "lan", "connected": True, "interface": iface}
                    if iface.startswith(("wlan", "wlp")):
                        return {"type": "wifi", "connected": True, "interface": iface}
            except Exception:
                continue
    except Exception:
        pass
    return {"type": "unknown", "connected": False, "interface": ""}
_UPDATE_FLAG = "/update.flag"
_REBOOT_FLAG = "/reboot.flag"
_SSH_CMD = "ssh -o StrictHostKeyChecking=no -o BatchMode=yes"
_VERSION_FILE = "/app/VERSION"


def _git(*args: str, timeout: int = 30) -> str:
    env = {**os.environ, "GIT_SSH_COMMAND": _SSH_CMD, "HOME": "/root"}
    r = subprocess.run(
        ["git", "-c", "safe.directory=/app"] + list(args),
        cwd=_GIT_DIR, capture_output=True, text=True, timeout=timeout, env=env,
    )
    return r.stdout.strip()


def _version_from_count(commit_ref: str = "HEAD") -> str:
    try:
        with open(_VERSION_FILE) as f:
            base = f.read().strip()
    except Exception:
        base = "0.1"
    try:
        count = _git("rev-list", "--count", commit_ref)
        return f"{base}.{count}"
    except Exception:
        return base


def _built_hash() -> str:
    """Hash der laufenden Container-Build — gebacken bei docker build."""
    h = os.environ.get("GIT_HASH", "").strip()
    return h if h and h != "unknown" else ""


def _current_version() -> str:
    """Version des laufenden Containers (aus Build-Hash, nicht HEAD)."""
    h = _built_hash()
    if h:
        return _version_from_count(h)
    return _version_from_count("HEAD")


@router.get("/", response_class=FileResponse)
def index() -> Any:
    return FileResponse(FRONTEND_INDEX)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/status")
def status() -> dict[str, Any]:
    result = get_core().get_status()
    with get_connection() as conn:
        upd = read_state(conn, "git_update_status", {}) or {}
    result["update_available"] = bool(upd.get("update_available", False))
    result["network"] = _detect_network()
    return result


@router.get("/system/update/status")
def get_update_status() -> dict[str, Any]:
    with get_connection() as conn:
        cached = read_state(conn, "git_update_status", {}) or {}
    cached["current_version"] = _current_version()
    return cached


@router.post("/system/update/check")
def check_for_update() -> dict[str, Any]:
    try:
        _git("fetch", "origin", "main", timeout=20)
        # Laufender Build-Hash (gebacken beim docker build)
        built = _built_hash() or _git("rev-parse", "HEAD")
        latest_hash = _git("rev-parse", "origin/main")
        available = (built[:12] != latest_hash[:12]) and bool(latest_hash)
        result: dict[str, Any] = {
            "update_available": available,
            "current_version": _current_version(),
            "latest_version":  _version_from_count("origin/main"),
            "current_hash": built[:12],
            "latest_hash":  latest_hash[:12],
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "error": None,
        }
    except Exception as exc:
        result = {
            "update_available": False,
            "current_version": _current_version(),
            "latest_hash": None,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "error": str(exc),
        }
    with get_connection() as conn:
        write_state(conn, "git_update_status", result)
    return result


@router.get("/system/update/log")
def get_update_log() -> dict[str, Any]:
    log_path = "/update.log"
    try:
        with open(log_path) as f:
            lines = f.readlines()
        return {"lines": [l.rstrip() for l in lines[-40:]], "error": None}
    except FileNotFoundError:
        return {"lines": [], "error": None}
    except Exception as exc:
        return {"lines": [], "error": str(exc)}


@router.post("/system/update/install")
def trigger_install() -> dict[str, Any]:
    try:
        # Auto-Backup vor dem Update
        try:
            backup_data = _create_backup_zip()
            backup_dir = Path("/data/backups")
            backup_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            (backup_dir / f"pre_update_{ts}.zip").write_bytes(backup_data)
        except Exception:
            pass  # Backup-Fehler blockiert das Update nicht
        with open(_UPDATE_FLAG, "w") as f:
            json.dump({"requested_at": datetime.now(timezone.utc).isoformat()}, f)
        # Update-Status sofort auf "läuft" setzen → Display zeigt nicht mehr "verfügbar"
        with get_connection() as conn:
            cached = read_state(conn, "git_update_status", {}) or {}
            cached["update_available"] = False
            cached["installing"] = True
            write_state(conn, "git_update_status", cached)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── AUTO-UPDATE SETTINGS ──────────────────────────────────────

@router.get("/system/update/settings")
def get_update_settings() -> dict[str, Any]:
    with get_connection() as conn:
        settings = read_state(conn, "update_settings", {}) or {}
    return {
        "interval": settings.get("interval", "daily"),
        "auto_install": bool(settings.get("auto_install", False)),
    }


@router.post("/system/update/settings")
def save_update_settings(payload: dict[str, Any]) -> dict[str, Any]:
    interval = payload.get("interval", "daily")
    if interval not in ("never", "daily", "6h", "hourly"):
        interval = "daily"
    settings = {
        "interval": interval,
        "auto_install": bool(payload.get("auto_install", False)),
    }
    with get_connection() as conn:
        write_state(conn, "update_settings", settings)
    return settings


# ── BACKUP & RESTORE ──────────────────────────────────────────

def _db_path() -> str:
    from app.database.db import get_db_path
    return get_db_path()


def _create_backup_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        db = _db_path()
        if os.path.exists(db):
            zf.write(db, "robot_core.db")
        # .env falls vorhanden
        for env_path in ("/app/.env", "/.env"):
            if os.path.exists(env_path):
                zf.write(env_path, ".env")
                break
    return buf.getvalue()


@router.post("/system/backup/create")
def create_backup() -> dict[str, Any]:
    try:
        data = _create_backup_zip()
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"erika_backup_{ts}.zip"
        backup_dir = Path("/data/backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / filename).write_bytes(data)
        return {"ok": True, "filename": filename, "size": len(data)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/system/backup/download")
def download_backup() -> StreamingResponse:
    try:
        data = _create_backup_zip()
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"erika_backup_{ts}.zip"
        return StreamingResponse(
            io.BytesIO(data),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/system/backup/restore")
async def restore_backup(file: UploadFile = File(...)) -> dict[str, Any]:
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Nur ZIP-Dateien erlaubt")
    try:
        data = await file.read()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            if "robot_core.db" not in names:
                raise HTTPException(status_code=400, detail="Kein gültiges Backup (robot_core.db fehlt)")
            db_path = _db_path()
            # Sicherheitskopie vor Restore
            if os.path.exists(db_path):
                shutil.copy2(db_path, db_path + ".pre_restore")
            with tempfile.TemporaryDirectory() as tmp:
                zf.extractall(tmp)
                shutil.copy2(os.path.join(tmp, "robot_core.db"), db_path)
        return {"ok": True, "restored_files": names}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/system/printer/start")
def start_printer_bridge() -> dict[str, Any]:
    """Startet den Anycubic MQTT-Bridge-Container (Profil 'printer')."""
    from app.services.integration_config_service import IntegrationConfigService
    from app.services.homeassistant_runtime_config_service import HomeAssistantRuntimeConfigService
    try:
        cfg     = IntegrationConfigService().get_config()
        printer = cfg.get("printer") or {}
        ha_cfg  = HomeAssistantRuntimeConfigService.get_config()
        payload = {
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "printer_ip":   printer.get("printer_ip", ""),
            "mqtt_host":    ha_cfg.get("host", ""),
            "mqtt_port":    1883,
            "mqtt_user":    printer.get("mqtt_user", ""),
            "mqtt_pass":    printer.get("mqtt_pass", ""),
        }
        flag_path = Path("/printer-start.flag")
        flag_path.write_text(json.dumps(payload))
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/system/resources")
def get_system_resources() -> dict[str, Any]:
    result: dict[str, Any] = {}
    # CPU (1s blocking sample — akzeptabel für Admin-Poll)
    try:
        cpu_times1 = Path("/proc/stat").read_text().splitlines()[0].split()
        import time as _time
        _time.sleep(0.5)
        cpu_times2 = Path("/proc/stat").read_text().splitlines()[0].split()
        idle1, total1 = int(cpu_times1[4]), sum(int(x) for x in cpu_times1[1:])
        idle2, total2 = int(cpu_times2[4]), sum(int(x) for x in cpu_times2[1:])
        dtotal = total2 - total1
        result["cpu_percent"] = round((1 - (idle2 - idle1) / dtotal) * 100, 1) if dtotal else 0.0
    except Exception:
        result["cpu_percent"] = None
    # RAM
    try:
        meminfo = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            meminfo[k.strip()] = int(v.strip().split()[0])
        total_kb = meminfo.get("MemTotal", 0)
        avail_kb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
        used_kb  = total_kb - avail_kb
        result["ram"] = {
            "total_mb": round(total_kb / 1024, 1),
            "used_mb":  round(used_kb / 1024, 1),
            "percent":  round(used_kb / total_kb * 100, 1) if total_kb else 0.0,
        }
    except Exception:
        result["ram"] = None
    # Disk (/data)
    try:
        st = os.statvfs("/data")
        total = st.f_frsize * st.f_blocks
        free  = st.f_frsize * st.f_bfree
        used  = total - free
        result["disk"] = {
            "total_gb": round(total / 1024**3, 1),
            "used_gb":  round(used / 1024**3, 1),
            "percent":  round(used / total * 100, 1) if total else 0.0,
        }
    except Exception:
        result["disk"] = None
    return result


@router.post("/system/reboot")
def trigger_reboot() -> dict[str, Any]:
    try:
        with open(_REBOOT_FLAG, "w") as f:
            json.dump({"requested_at": datetime.now(timezone.utc).isoformat()}, f)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── LLM KONFIGURATION ────────────────────────────────────────

_LLM_PROVIDERS: dict[str, dict[str, Any]] = {
    "groq":    {"url": "https://api.groq.com/openai/v1/chat/completions",                             "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "gemma2-9b-it", "mixtral-8x7b-32768"]},
    "openai":  {"url": "https://api.openai.com/v1/chat/completions",                                  "models": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"]},
    "gemini":  {"url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",    "models": ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]},
    "mistral": {"url": "https://api.mistral.ai/v1/chat/completions",                                  "models": ["mistral-small-latest", "open-mistral-nemo", "mistral-large-latest"]},
    "custom":  {"url": "", "models": []},
}


@router.get("/llm/config")
def get_llm_config() -> dict[str, Any]:
    with get_connection() as conn:
        cfg = read_state(conn, "llm_config", {}) or {}
    key = cfg.get("api_key", "")
    masked = ("•" * (len(key) - 4) + key[-4:]) if len(key) > 4 else ("•" * len(key))
    return {
        "api_provider":   cfg.get("api_provider", ""),
        "api_url":        cfg.get("api_url", ""),
        "api_key_masked": masked,
        "api_key_set":    bool(key),
        "model":          cfg.get("model", ""),
        "fallback_model": cfg.get("fallback_model", ""),
        "max_tokens":     cfg.get("max_tokens", 220),
        "temperature":    cfg.get("temperature", 0.4),
        "enabled":        bool(cfg.get("api_url")),
        "providers":      _LLM_PROVIDERS,
    }


@router.post("/llm/config")
def save_llm_config(payload: dict[str, Any]) -> dict[str, Any]:
    with get_connection() as conn:
        existing = read_state(conn, "llm_config", {}) or {}
    api_key = payload.get("api_key", "").strip()
    if not api_key:
        api_key = existing.get("api_key", "")
    try:
        max_tokens = max(50, min(4096, int(payload.get("max_tokens", 220))))
    except (TypeError, ValueError):
        max_tokens = 220
    try:
        temperature = max(0.0, min(2.0, float(payload.get("temperature", 0.4))))
    except (TypeError, ValueError):
        temperature = 0.4
    cfg = {
        "api_provider":   str(payload.get("api_provider", "custom")).strip(),
        "api_url":        str(payload.get("api_url", "")).strip(),
        "api_key":        api_key,
        "model":          str(payload.get("model", "")).strip(),
        "fallback_model": str(payload.get("fallback_model", "")).strip(),
        "max_tokens":     max_tokens,
        "temperature":    temperature,
    }
    with get_connection() as conn:
        write_state(conn, "llm_config", cfg)
    return {"ok": True}


_models_cache: dict[str, Any] = {"models": [], "fetched_at": 0.0}
_MODELS_TTL = 3600  # 1 Stunde

# Modelle die für Konversations-KI ungeeignet sind
_NON_CHAT_IDS = frozenset({"whisper", "guard", "safeguard", "embedding", "tts", "moderation"})


@router.get("/llm/models")
def get_llm_models() -> dict[str, Any]:
    import time as _time
    from app.brain.llm_client import ExternalLLMClient
    import urllib.request as _req
    import urllib.error as _err

    now = _time.time()
    if now - _models_cache["fetched_at"] < _MODELS_TTL and _models_cache["models"]:
        return {"models": _models_cache["models"], "cached": True}

    client = ExternalLLMClient()
    if not client.api_key:
        return {"models": [], "error": "Kein API-Key konfiguriert"}

    # Basis-URL aus api_url ableiten (alles bis /v1/)
    base = (client.api_url or "").split("/v1/")[0] if "/v1/" in (client.api_url or "") else ""
    if not base:
        return {"models": [], "error": "API-URL ungültig"}

    try:
        req = _req.Request(
            f"{base}/v1/models",
            headers={"Authorization": f"Bearer {client.api_key}", "User-Agent": "Mozilla/5.0"},
        )
        import json as _json
        with _req.urlopen(req, timeout=8) as resp:
            data = _json.loads(resp.read().decode())
        raw = data.get("data", [])
        models = [
            {"id": m["id"], "owned_by": m.get("owned_by", "")}
            for m in raw
            if not any(kw in m["id"].lower() for kw in _NON_CHAT_IDS)
        ]
        models.sort(key=lambda m: m["id"])
        _models_cache["models"] = models
        _models_cache["fetched_at"] = now
        return {"models": models, "cached": False}
    except Exception as exc:
        return {"models": _models_cache.get("models", []), "error": str(exc)}


@router.post("/llm/test")
def test_llm_config() -> dict[str, Any]:
    from app.brain.llm_client import ExternalLLMClient
    client = ExternalLLMClient()
    if not client.is_configured():
        raise HTTPException(status_code=400, detail="Keine LLM-URL konfiguriert")
    try:
        result = client.generate({
            "message": "Antworte mit genau einem Wort: Hallo",
            "messages": [
                {"role": "system", "content": "Du bist ein Testassistent. Antworte kurz."},
                {"role": "user",   "content": "Antworte mit genau einem Wort: Hallo"},
            ],
            "personality": {"directness": 0.8, "humor": 0.0},
            "llm_max_tokens": 10,
        }, timeout_seconds=10)
        return {"ok": True, "reply": result.get("reply", ""), "model": client.model}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/llm/usage")
def get_llm_usage() -> dict[str, Any]:
    with get_connection() as conn:
        data = read_state(conn, "llm_rate_limit", {}) or {}
    return data


@router.post("/llm/usage/refresh")
def refresh_llm_usage() -> dict[str, Any]:
    """Macht einen Minimal-Request um aktuelle Rate-Limit-Header zu lesen."""
    from app.brain.llm_client import ExternalLLMClient
    client = ExternalLLMClient()
    if not client.is_configured():
        raise HTTPException(status_code=400, detail="Kein LLM konfiguriert")
    try:
        client.generate({
            "message": "1",
            "messages": [{"role": "user", "content": "1"}],
            "personality": {"directness": 1.0, "humor": 0.0},
            "llm_max_tokens": 1,
        }, timeout_seconds=8)
    except Exception:
        pass  # Headers wurden trotzdem gespeichert
    with get_connection() as conn:
        data = read_state(conn, "llm_rate_limit", {}) or {}
    return data


@router.get("/device/identity")
def get_device_identity() -> dict[str, Any]:
    return get_core().get_device_identity()


@router.get("/sync/contract")
def get_sync_contract() -> dict[str, Any]:
    return get_core().get_sync_contract()


@router.get("/device")
def get_device() -> dict[str, Any]:
    return get_core().get_device()


@router.patch("/device")
def patch_device(payload: DevicePatchRequest) -> dict[str, Any]:
    try:
        return get_core().update_device(payload.to_patch())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/config")
def get_config() -> dict[str, Any]:
    return get_settings_service().describe()


@router.patch("/config")
def patch_config(payload: ConfigPatchRequest) -> dict[str, Any]:
    patch = payload.to_patch()
    effective = get_settings_service().update_runtime_overrides(patch)
    get_core().audit.log(
        action="config.updated",
        target_type="config",
        target_id="runtime_config",
        summary="Laufzeit-Konfiguration wurde geändert.",
        details={"patch": patch},
    )
    return {
        "effective": effective.model_dump(),
        "runtime_overrides": get_settings_service().get_runtime_overrides(),
    }



@router.get("/audit-log")
def get_audit_log(limit: int = 100) -> dict[str, Any]:
    from app.audit.service import AuditService
    return {"entries": AuditService().list_entries(limit)}


@router.get("/debug/light-schedule")
def debug_light_schedule() -> dict[str, Any]:
    """Letztes Ergebnis eines zeitgesteuerten Lichtbefehls + bekannte HA-Licht-Entities."""
    from app.database.db import get_connection, read_state
    from app.search.providers.homeassistant import HomeAssistantProvider
    with get_connection() as conn:
        last = read_state(conn, "last_light_schedule_result")
    try:
        lights = [
            {"entity_id": l["entity_id"], "name": l["name"], "is_group": l["is_group"]}
            for l in HomeAssistantProvider().get_lights()
        ]
    except Exception as exc:
        lights = [{"error": str(exc)}]
    return {"last_execution": last, "known_lights": lights}
