from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import FRONTEND_INDEX, get_core, get_settings_service
from app.api.schemas import ConfigPatchRequest, DevicePatchRequest
from app.database.db import get_connection, read_state, write_state

router = APIRouter()

_GIT_DIR = "/app"
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
