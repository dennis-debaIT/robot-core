from __future__ import annotations

import os
import urllib.parse
import urllib.request
from typing import Any

from app.database.db import get_connection, read_state


class HomeAssistantRuntimeConfigService:
    _STATE_KEY = "local_admin_integration_config"

    @staticmethod
    def default_config() -> dict[str, Any]:
        raw_url = os.environ.get("ROBOT_HA_URL", "http://192.168.1.246:8123").strip() or "http://192.168.1.246:8123"
        parsed = urllib.parse.urlparse(raw_url if "://" in raw_url else f"http://{raw_url}")
        scheme = parsed.scheme or "http"
        host = parsed.hostname or "192.168.1.246"
        port = parsed.port or (443 if scheme == "https" else 8123)
        return {
            "scheme": scheme,
            "host": host,
            "port": port,
            "token": os.environ.get("ROBOT_HA_TOKEN", "").strip(),
            "username": os.environ.get("ROBOT_HA_USERNAME", "").strip(),
            "password": os.environ.get("ROBOT_HA_PASSWORD", "").strip(),
        }

    @classmethod
    def sanitize(cls, value: Any) -> dict[str, Any]:
        defaults = cls.default_config()
        if not isinstance(value, dict):
            return defaults
        scheme = str(value.get("scheme") or defaults["scheme"]).strip().lower()
        if scheme not in {"http", "https"}:
            scheme = defaults["scheme"]
        host = str(value.get("host") or defaults["host"]).strip() or defaults["host"]
        try:
            port = int(value.get("port") or defaults["port"])
        except (TypeError, ValueError):
            port = int(defaults["port"])
        port = min(max(port, 1), 65535)
        return {
            "scheme": scheme,
            "host": host,
            "port": port,
            "token": str(value.get("token", defaults["token"]) or "").strip(),
            "username": str(value.get("username", defaults["username"]) or "").strip(),
            "password": str(value.get("password", defaults["password"]) or "").strip(),
        }

    @classmethod
    def get_config(cls) -> dict[str, Any]:
        with get_connection() as conn:
            state = read_state(conn, cls._STATE_KEY, {})
        system = state.get("system", {}) if isinstance(state, dict) else {}
        home_assistant = system.get("home_assistant", {}) if isinstance(system, dict) else {}
        return cls.sanitize(home_assistant)

    @classmethod
    def build_base_url(cls, config: dict[str, Any] | None = None) -> str:
        current = cls.sanitize(config if config is not None else cls.get_config())
        return f"{current['scheme']}://{current['host']}:{current['port']}"

    @classmethod
    def to_public_payload(cls, config: dict[str, Any] | None = None) -> dict[str, Any]:
        current = cls.sanitize(config if config is not None else cls.get_config())
        return {
            **current,
            "base_url": cls.build_base_url(current),
            "token_configured": bool(current["token"]),
            "password_configured": bool(current["password"]),
        }

    @classmethod
    def test_connection(cls, config: dict[str, Any] | None = None) -> dict[str, Any]:
        current = cls.sanitize(config if config is not None else cls.get_config())
        base_url = cls.build_base_url(current)
        token = current.get("token", "")
        if not token:
            return {
                "ok": False,
                "base_url": base_url,
                "detail": "Fuer die Home-Assistant-REST-API wird aktuell ein Long-Lived Access Token benoetigt.",
                "token_required": True,
            }

        req = urllib.request.Request(
            f"{base_url}/api/",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                payload = resp.read().decode("utf-8", errors="replace")
                return {
                    "ok": resp.status == 200,
                    "base_url": base_url,
                    "detail": "Verbindung erfolgreich." if resp.status == 200 else "Unerwartete Antwort von Home Assistant.",
                    "response_preview": payload[:200],
                    "token_required": True,
                }
        except Exception as exc:
            return {
                "ok": False,
                "base_url": base_url,
                "detail": f"Verbindung fehlgeschlagen: {exc}",
                "token_required": True,
            }
