from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.database.db import get_connection, read_state, write_state


class CloudBoundaryService:
    DEFAULTS: dict[str, Any] = {
        "device_id": None,
        "device_secret": None,
        "tenant_binding": "factory_assigned",
        "tenant_id": None,
        "cloud_endpoint": None,
        "sync_enabled": False,
        "sync_mode": "hybrid",
        "sync_cursor": None,
    }

    def ensure_state(self) -> None:
        with get_connection() as conn:
            defaults = dict(self.DEFAULTS)
            defaults["device_id"] = read_state(conn, "device_id") or f"erika-{uuid4().hex[:12]}"
            defaults["device_secret"] = read_state(conn, "device_secret") or uuid4().hex
            defaults["tenant_id"] = read_state(conn, "tenant_id") or "tenant-demo-local"
            defaults["cloud_endpoint"] = read_state(conn, "cloud_endpoint") or "https://cloud.erika.local"

            for key, value in defaults.items():
                current = read_state(conn, key, None)
                existing = conn.execute("SELECT 1 FROM system_state WHERE key = ?", (key,)).fetchone()
                if not existing or current is None:
                    write_state(conn, key, value)

    def get_device_identity(self) -> dict[str, Any]:
        self.ensure_state()
        with get_connection() as conn:
            return {
                "device_id": read_state(conn, "device_id"),
                "tenant_id": read_state(conn, "tenant_id"),
                "tenant_binding": read_state(conn, "tenant_binding", "factory_assigned"),
                "cloud_endpoint": read_state(conn, "cloud_endpoint"),
                "sync_enabled": read_state(conn, "sync_enabled", False),
                "sync_mode": read_state(conn, "sync_mode", "hybrid"),
                "provisioning_source": "factory",
            }

    def get_sync_contract(self) -> dict[str, Any]:
        identity = self.get_device_identity()
        return {
            "backend_role": "device_runtime",
            "paired_cloud_backend": "future_cloud_platform",
            "identity": identity,
            "source_of_truth": {
                "local_device": [
                    "robot_state",
                    "person_profiles",
                    "memories",
                    "conversation_context",
                    "hardware_events",
                    "audit_events",
                ],
                "cloud_platform": [
                    "tenant_management",
                    "user_accounts",
                    "device_registry",
                    "billing",
                    "fleet_updates",
                    "llm_provider_configuration",
                ],
            },
            "sync_domains": [
                {
                    "name": "device_status",
                    "direction": "device_to_cloud",
                    "transport": "async_push",
                    "priority": "high",
                },
                {
                    "name": "approved_profiles",
                    "direction": "bidirectional",
                    "transport": "async_sync",
                    "priority": "medium",
                },
                {
                    "name": "memories",
                    "direction": "device_to_cloud",
                    "transport": "batched_sync",
                    "priority": "medium",
                },
                {
                    "name": "updates_and_policy",
                    "direction": "cloud_to_device",
                    "transport": "pull_then_apply",
                    "priority": "high",
                },
            ],
            "constraints": [
                "Der lokale Robot-Core bleibt offline arbeitsfähig.",
                "Direkte Hardware-Steuerung bleibt lokal auf dem Gerät.",
                "Das Cloud-Backend ist organisatorisch und betrieblich getrennt.",
                "Private Personendaten werden nicht automatisch für Service-Rollen freigeschaltet.",
            ],
        }
