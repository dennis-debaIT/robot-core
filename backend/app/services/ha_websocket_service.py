from __future__ import annotations

import json
import re
from typing import Any


async def get_statistics_during_period(
    ha_url: str,
    token: str,
    statistic_ids: list[str],
    start_time: str,
    end_time: str,
    period: str,
    types: list[str],
) -> dict[str, list[dict]]:
    """
    Fragt HA WebSocket nach Langzeitstatistiken (recorder/statistics_during_period).

    Im Gegensatz zur rohen History-API (/api/history/period, standardmäßig nur
    ~10 Tage retained) liefert dieser Befehl von HA vorab aggregierte, dauerhaft
    gespeicherte Tages-/Monats-/Stundenwerte — und ist nur über die WebSocket-API
    erreichbar (kein REST-Äquivalent).
    """
    import websockets

    ws_url = (
        ha_url.replace("https://", "wss://").replace("http://", "ws://")
        + "/api/websocket"
    )
    try:
        async with websockets.connect(ws_url, open_timeout=8, close_timeout=5) as ws:
            msg = json.loads(await ws.recv())
            if msg.get("type") != "auth_required":
                return {}
            await ws.send(json.dumps({"type": "auth", "access_token": token}))
            msg = json.loads(await ws.recv())
            if msg.get("type") != "auth_ok":
                return {}

            await ws.send(json.dumps({
                "id": 1,
                "type": "recorder/statistics_during_period",
                "start_time": start_time,
                "end_time": end_time,
                "statistic_ids": statistic_ids,
                "period": period,
                "types": types,
            }))
            result_msg = json.loads(await ws.recv())
            if not result_msg.get("success"):
                return {}
            result = result_msg.get("result")
            return result if isinstance(result, dict) else {}
    except Exception as exc:
        from app.audit.service import AuditService
        AuditService().log_warn(source="homeassistant", message=f"HA-WebSocket Statistikabfrage fehlgeschlagen ({statistic_ids}): {type(exc).__name__}: {exc}")
        return {}


async def get_ring_camera_id_map(ha_url: str, token: str) -> dict[str, str]:
    """
    Fragt HA WebSocket nach Device- und Entity-Registry.
    Gibt {entity_id: ring_device_id} für camera.*-Entities zurück,
    deren verknüpftes HA-Gerät einen Ring-Identifier hat.
    """
    import websockets

    ws_url = (
        ha_url.replace("https://", "wss://").replace("http://", "ws://")
        + "/api/websocket"
    )
    try:
        async with websockets.connect(ws_url, open_timeout=8, close_timeout=5) as ws:
            msg = json.loads(await ws.recv())
            if msg.get("type") != "auth_required":
                return {}
            await ws.send(json.dumps({"type": "auth", "access_token": token}))
            msg = json.loads(await ws.recv())
            if msg.get("type") != "auth_ok":
                return {}

            await ws.send(json.dumps({"id": 1, "type": "config/device_registry/list"}))
            dev_msg = json.loads(await ws.recv())
            devices: dict[str, dict[str, Any]] = {
                d["id"]: d for d in (dev_msg.get("result") or [])
            }

            await ws.send(json.dumps({"id": 2, "type": "config/entity_registry/list"}))
            ent_msg = json.loads(await ws.recv())
            entities: list[dict[str, Any]] = ent_msg.get("result") or []

        result: dict[str, str] = {}
        for entity in entities:
            eid = entity.get("entity_id", "")
            if not eid.startswith("camera."):
                continue
            device_id = entity.get("device_id")
            if not device_id:
                continue
            device = devices.get(device_id, {})
            for identifier in device.get("identifiers") or []:
                if not isinstance(identifier, (list, tuple)) or len(identifier) < 2:
                    continue
                platform, value = identifier[0], str(identifier[1])
                if platform == "ring" and re.match(r"^[a-f0-9]{10,16}$", value, re.I):
                    result[eid] = value
                    break
        return result
    except Exception as exc:
        from app.audit.service import AuditService
        AuditService().log_warn(source="homeassistant", message=f"HA-WebSocket Ring-Kamera-Abfrage fehlgeschlagen: {type(exc).__name__}: {exc}")
        return {}
