from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.services.integration_config_service import IntegrationConfigService
from app.services.waste_service import WasteService

router = APIRouter()


@router.get("/ha/waste")
def get_waste() -> dict[str, Any]:
    config = IntegrationConfigService().get_config()
    return WasteService().get_display_data(config)


@router.post("/ha/waste/push-test")
def test_waste_push() -> dict[str, Any]:
    """Sendet eine Test-Push-Benachrichtigung und gibt Diagnose-Info zurück."""
    from app.services import push_service

    # Firebase-Initialisierung prüfen
    try:
        push_service._get_firebase_app()
    except RuntimeError as exc:
        return {"ok": False, "sent": 0, "total_tokens": 0, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "sent": 0, "total_tokens": 0, "error": f"Firebase-Initialisierung fehlgeschlagen: {exc}"}

    # Registrierte Geräte holen
    try:
        tokens = push_service._get_device_tokens()
    except Exception as exc:
        return {"ok": False, "sent": 0, "total_tokens": 0, "error": f"Sync Server nicht erreichbar: {exc}"}

    if not tokens:
        return {
            "ok": False, "sent": 0, "total_tokens": 0,
            "error": "Keine Geräte registriert. Companion App verbinden und Push-Benachrichtigungen in der App erlauben.",
        }

    sent = push_service.send_notification(
        title="🗑 Test-Benachrichtigung",
        body="Wenn du das liest, funktionieren Push-Benachrichtigungen!",
        channel="waste",
    )

    if sent == 0:
        return {
            "ok": False, "sent": 0, "total_tokens": len(tokens),
            "error": f"FCM-Zustellung an {len(tokens)} Gerät(e) fehlgeschlagen. Prüfe ob die App Push-Benachrichtigungen erlaubt.",
        }

    return {"ok": True, "sent": sent, "total_tokens": len(tokens), "error": None}
