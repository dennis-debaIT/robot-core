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
