from __future__ import annotations

from typing import Any

from app.database.db import get_connection, read_state, write_state


class DeviceService:
    VALID_STATES = {
        "factory",
        "network_setup",
        "updating",
        "ready",
        "maintenance",
        "offline_degraded",
    }
    VALID_UPDATE_STATUSES = {
        "idle",
        "available",
        "checking",
        "downloading",
        "installing",
        "restarting",
        "failed",
    }

    DEFAULTS: dict[str, Any] = {
        "device_name": "Erika",
        "site_label": "Mein Haushalt",
        "device_state": "factory",
        "network_connected": False,
        "server_connected": False,
        "local_ip": None,
        "software_version": "0.2-alpha",
        "update_status": "idle",
        "last_server_contact_at": None,
        "maintenance_mode": False,
        "provisioning_status": "factory_bound",
    }

    def ensure_state(self) -> None:
        with get_connection() as conn:
            for key, value in self.DEFAULTS.items():
                existing = conn.execute("SELECT 1 FROM system_state WHERE key = ?", (key,)).fetchone()
                if not existing:
                    write_state(conn, key, value)

    def get(self) -> dict[str, Any]:
        with get_connection() as conn:
            payload = {key: read_state(conn, key, value) for key, value in self.DEFAULTS.items()}
        payload["effective_state"] = self._effective_state(payload)
        payload["state_hint"] = self._state_hint(payload["effective_state"])
        payload["next_step"] = self._next_step(payload)
        payload["checklist"] = self._checklist(payload)
        return payload

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        if "device_state" in patch and patch["device_state"] not in self.VALID_STATES:
            raise ValueError("invalid_device_state")
        if "update_status" in patch and patch["update_status"] not in self.VALID_UPDATE_STATUSES:
            raise ValueError("invalid_update_status")

        with get_connection() as conn:
            current = {key: read_state(conn, key, value) for key, value in self.DEFAULTS.items()}
            merged = {**current, **patch}

            for key, value in merged.items():
                if key in self.DEFAULTS:
                    write_state(conn, key, value)

        return self.get()

    @staticmethod
    def _effective_state(payload: dict[str, Any]) -> str:
        if payload["maintenance_mode"]:
            return "maintenance"
        if payload["update_status"] in {"checking", "downloading", "installing", "restarting"}:
            return "updating"
        if payload["device_state"] == "factory":
            return "factory"
        if not payload["network_connected"]:
            return "network_setup" if payload["device_state"] == "network_setup" else "offline_degraded"
        if payload["network_connected"] and not payload["server_connected"]:
            return "offline_degraded"
        return payload["device_state"]

    @staticmethod
    def _state_hint(state: str) -> str:
        hints = {
            "factory": "Gerät ist noch nicht lokal eingerichtet.",
            "network_setup": "Netzwerk muss eingerichtet oder geprüft werden.",
            "updating": "Gerät aktualisiert sich gerade und sollte nicht unterbrochen werden.",
            "ready": "Gerät ist betriebsbereit.",
            "maintenance": "Gerät ist im Wartungsmodus.",
            "offline_degraded": "Gerät läuft lokal weiter, hat aber keine vollständige Plattformverbindung.",
        }
        return hints[state]

    @staticmethod
    def _next_step(payload: dict[str, Any]) -> str:
        if payload["maintenance_mode"]:
            return "Wartungsmodus beenden, wenn das Gerät wieder normal arbeiten soll."
        if payload["device_state"] == "factory":
            return "Gerätename, Standort und Netzwerk hinterlegen."
        if not payload["network_connected"]:
            return "LAN oder WLAN einrichten, damit Erika online gehen kann."
        if payload["update_status"] == "available":
            return "Update starten, bevor das Gerät produktiv genutzt wird."
        if payload["update_status"] in {"checking", "downloading", "installing", "restarting"}:
            return "Update abschließen lassen und den Status beobachten."
        if not payload["server_connected"]:
            return "Serververbindung prüfen, damit Updates, Service und LLM verfügbar sind."
        if payload["device_state"] != "ready":
            return "Gerät auf betriebsbereit setzen und den lokalen Betrieb starten."
        return "Lokalen Betrieb testen und anschließend Personen, Zonen und Verhalten anlernen."

    @staticmethod
    def _checklist(payload: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "label": "Gerät benannt",
                "done": bool(payload["device_name"] and payload["device_name"].strip()),
            },
            {
                "label": "Wohnort gesetzt",
                "done": bool(payload["site_label"] and payload["site_label"].strip()),
            },
            {
                "label": "Netzwerk verbunden",
                "done": bool(payload["network_connected"]),
            },
            {
                "label": "Server verbunden",
                "done": bool(payload["server_connected"]),
            },
            {
                "label": "Keine ausstehenden Updates",
                "done": payload["update_status"] in {"idle", "failed"} or payload["device_state"] == "ready",
            },
            {
                "label": "Betriebsbereit",
                "done": payload["effective_state"] == "ready",
            },
        ]
