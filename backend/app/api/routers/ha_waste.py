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
def test_waste_push(real: bool = False) -> dict[str, Any]:
    """Sendet eine Test-Push-Benachrichtigung und gibt Diagnose-Info zurück.

    real=false (Standard): generische Test-Nachricht
    real=true: echte HA-Mülltonnen-Daten, nächster fälliger Termin
    """
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

    if real:
        # Echte HA-Daten: nächster fälliger Termin unabhängig vom Datum
        try:
            cfg = IntegrationConfigService().get_config()
            waste_data = WasteService().get_display_data(cfg)
            bins = waste_data.get("bins", [])
        except Exception as exc:
            return {"ok": False, "sent": 0, "total_tokens": len(tokens), "error": f"HA-Kalenderdaten nicht abrufbar: {exc}"}

        if not bins:
            return {"ok": False, "sent": 0, "total_tokens": len(tokens), "error": "Keine Mülltonnen-Termine im HA-Kalender gefunden."}

        # Nächsten Termin nehmen (bins ist bereits nach Datum sortiert)
        next_bin = bins[0]
        labels = ", ".join(b["label"] for b in bins if b.get("date") == next_bin.get("date"))
        date_str = next_bin.get("date", "?")
        title = "🗑️ Müllabfuhr Test (echte Daten)"
        body = f"{date_str}: {labels}"
    else:
        title = "🗑 Test-Benachrichtigung"
        body = "Wenn du das liest, funktionieren Push-Benachrichtigungen!"

    sent = push_service.send_notification(title=title, body=body, channel="waste")

    if sent == 0:
        return {
            "ok": False, "sent": 0, "total_tokens": len(tokens),
            "error": f"FCM-Zustellung an {len(tokens)} Gerät(e) fehlgeschlagen. Prüfe ob die App Push-Benachrichtigungen erlaubt.",
        }

    return {"ok": True, "sent": sent, "total_tokens": len(tokens), "error": None}
