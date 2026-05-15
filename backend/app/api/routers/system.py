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
_UPDATE_FLAG = "/data/update.flag"
_SSH_CMD = "ssh -o StrictHostKeyChecking=no -o BatchMode=yes"


def _git(*args: str, timeout: int = 30) -> str:
    env = {**os.environ, "GIT_SSH_COMMAND": _SSH_CMD, "HOME": "/root"}
    r = subprocess.run(
        ["git"] + list(args), cwd=_GIT_DIR,
        capture_output=True, text=True, timeout=timeout, env=env,
    )
    return r.stdout.strip()


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
        upd = read_state(conn, "update_status", {}) or {}
    result["update_available"] = bool(upd.get("update_available", False))
    return result


@router.get("/system/update/status")
def get_update_status() -> dict[str, Any]:
    with get_connection() as conn:
        return read_state(conn, "update_status", {}) or {}


@router.post("/system/update/check")
def check_for_update() -> dict[str, Any]:
    try:
        _git("fetch", "origin", "main", timeout=20)
        current = _git("rev-parse", "HEAD")[:12]
        latest  = _git("rev-parse", "origin/main")[:12]
        available = current != latest and bool(current) and bool(latest)
        result: dict[str, Any] = {
            "update_available": available,
            "current_hash": current,
            "latest_hash": latest,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "error": None,
        }
    except Exception as exc:
        result = {
            "update_available": False,
            "current_hash": os.environ.get("GIT_HASH", "unknown"),
            "latest_hash": None,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "error": str(exc),
        }
    with get_connection() as conn:
        write_state(conn, "update_status", result)
    return result


@router.post("/system/update/install")
def trigger_install() -> dict[str, Any]:
    try:
        with open(_UPDATE_FLAG, "w") as f:
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
