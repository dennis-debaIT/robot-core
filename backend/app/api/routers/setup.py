from __future__ import annotations

import json
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import available_timezones

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import FRONTEND_INDEX
from app.database.db import get_connection, read_state, write_state

router = APIRouter()

_SETUP_KEY = "setup_state"
_FRONTEND_SETUP = Path("/app/frontend/setup.html")

_TIMEZONE_FLAG = "/timezone.flag"
_HOSTNAME_FLAG = "/hostname.flag"
_WLAN_FLAG     = "/wlan.flag"
_HA_FLAG       = "/ha-install.flag"


def _get_setup_state() -> dict[str, Any]:
    with get_connection() as conn:
        state = read_state(conn, _SETUP_KEY, {}) or {}
    return state


def _save_setup_state(state: dict[str, Any]) -> None:
    with get_connection() as conn:
        write_state(conn, _SETUP_KEY, state)


def _host_ip() -> str:
    try:
        ip = Path("/host-ip.txt").read_text().strip()
        if ip:
            return ip
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "unbekannt"


def _timezone_list() -> list[str]:
    zones = sorted(available_timezones())
    # Europe first
    eu = [z for z in zones if z.startswith("Europe/")]
    rest = [z for z in zones if not z.startswith("Europe/")]
    return eu + rest


@router.get("/setup", response_class=FileResponse)
def setup_page() -> Any:
    return FileResponse(_FRONTEND_SETUP)


@router.get("/setup/status")
def setup_status() -> dict[str, Any]:
    state = _get_setup_state()
    return {
        "completed": bool(state.get("completed")),
        "step":      int(state.get("step", 1)),
        "host_ip":   _host_ip(),
        "hostname":  _get_hostname(),
        "timezone":  _get_current_timezone(),
    }


@router.get("/setup/wifi/scan")
def wifi_scan() -> dict[str, Any]:
    """Liefert verfügbare WLAN-Netze (liest gecachte Scan-Datei vom Host)."""
    scan_file = Path("/wifi-scan.json")
    if scan_file.exists():
        try:
            return json.loads(scan_file.read_text())
        except Exception:
            pass
    return {"networks": [], "error": "Scan nicht verfügbar"}


@router.get("/setup/timezones")
def get_timezones() -> dict[str, Any]:
    return {"timezones": _timezone_list()}


@router.post("/setup/network")
def setup_network(payload: dict[str, Any]) -> dict[str, Any]:
    hostname = str(payload.get("hostname") or "").strip()
    ssid     = str(payload.get("ssid") or "").strip()
    password = str(payload.get("password") or "").strip()
    use_wlan = bool(payload.get("use_wlan", False))

    if hostname:
        try:
            Path(_HOSTNAME_FLAG).write_text(json.dumps({"hostname": hostname}))
        except Exception as exc:
            raise HTTPException(500, f"Hostname-Flag: {exc}") from exc

    if use_wlan and ssid:
        try:
            Path(_WLAN_FLAG).write_text(json.dumps({"ssid": ssid, "password": password}))
        except Exception as exc:
            raise HTTPException(500, f"WLAN-Flag: {exc}") from exc

    state = _get_setup_state()
    state["step"] = 2
    state["network_done"] = True
    _save_setup_state(state)
    return {"ok": True}


@router.post("/setup/timezone")
def setup_timezone(payload: dict[str, Any]) -> dict[str, Any]:
    tz = str(payload.get("timezone") or "").strip()
    if not tz:
        raise HTTPException(400, "Zeitzone fehlt")
    all_tz = available_timezones()
    if tz not in all_tz:
        raise HTTPException(400, f"Unbekannte Zeitzone: {tz}")
    try:
        Path(_TIMEZONE_FLAG).write_text(json.dumps({"timezone": tz}))
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc

    state = _get_setup_state()
    state["step"] = 3
    state["timezone"] = tz
    state["timezone_done"] = True
    _save_setup_state(state)
    return {"ok": True, "timezone": tz}


@router.post("/setup/ha")
def setup_ha(payload: dict[str, Any]) -> dict[str, Any]:
    mode    = str(payload.get("mode") or "existing")  # "existing" | "install"
    ha_url  = str(payload.get("ha_url") or "").strip()
    ha_token = str(payload.get("ha_token") or "").strip()

    from app.services.homeassistant_runtime_config_service import HomeAssistantRuntimeConfigService
    from app.services.integration_config_service import IntegrationConfigService

    if mode == "existing" and ha_url:
        # HA-URL direkt in die Runtime-Config schreiben
        try:
            parts = ha_url.replace("http://", "").replace("https://", "").split(":")
            host = parts[0]
            port = int(parts[1]) if len(parts) > 1 else 8123
            scheme = "https" if ha_url.startswith("https") else "http"
            cfg_patch = {
                "system": {
                    "home_assistant": {
                        "scheme": scheme,
                        "host": host,
                        "port": port,
                        "token": ha_token,
                    }
                }
            }
            IntegrationConfigService().update_config(cfg_patch)
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc

    elif mode == "install":
        try:
            Path(_HA_FLAG).write_text(
                json.dumps({"requested_at": datetime.now(timezone.utc).isoformat()})
            )
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc

    state = _get_setup_state()
    state["step"] = 4
    state["ha_mode"] = mode
    state["ha_done"] = True
    _save_setup_state(state)
    return {"ok": True}


@router.post("/setup/components")
def setup_components(payload: dict[str, Any]) -> dict[str, Any]:
    """Startet den Download der ausgewählten HA-Komponenten als Hintergrundaufgabe."""
    components = payload.get("components") or []
    try:
        Path("/components.flag").write_text(json.dumps({
            "components": components,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }))
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc

    state = _get_setup_state()
    state["step"] = 5
    state["components"] = components
    _save_setup_state(state)
    return {"ok": True}


@router.post("/setup/complete")
def setup_complete() -> dict[str, Any]:
    state = _get_setup_state()
    state["completed"] = True
    state["completed_at"] = datetime.now(timezone.utc).isoformat()
    _save_setup_state(state)
    return {"ok": True}


@router.post("/setup/reset")
def setup_reset() -> dict[str, Any]:
    _save_setup_state({})
    return {"ok": True}


def _get_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return ""


def _get_current_timezone() -> str:
    try:
        result = subprocess.run(
            ["cat", "/etc/timezone"], capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "UTC"
