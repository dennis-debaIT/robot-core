"""FCM Push-Notification Service.

Sendet Push-Nachrichten an alle registrierten Geräte eines Tenants.
Credentials werden aus der Umgebungsvariable FIREBASE_CREDENTIALS_B64 (Base64-JSON)
geladen. Fallback: Datei FIREBASE_CREDENTIALS_FILE (Pfad).
"""
from __future__ import annotations

import base64
import json
import os

_app = None


def _get_firebase_app():
    global _app
    if _app is not None:
        return _app
    import firebase_admin
    from firebase_admin import credentials

    b64 = os.getenv("FIREBASE_CREDENTIALS_B64", "").strip()
    if b64:
        cred_dict = json.loads(base64.b64decode(b64).decode())
        cred = credentials.Certificate(cred_dict)
    else:
        path = os.getenv("FIREBASE_CREDENTIALS_FILE", "")
        if not path or not os.path.exists(path):
            raise RuntimeError("FCM nicht konfiguriert: FIREBASE_CREDENTIALS_B64 fehlt in .env")
        cred = credentials.Certificate(path)

    _app = firebase_admin.initialize_app(cred)
    return _app


def _get_device_tokens() -> list[str]:
    """Holt FCM-Tokens aller Geräte vom Sync Server."""
    from app.services.sync_service import get_credentials, _sync_request
    url, token = get_credentials()
    if not (url and token):
        return []
    result = _sync_request("GET", "/devices/tokens")
    if not result:
        return []
    return result.get("tokens", [])


def send_notification(title: str, body: str, channel: str = "reminders") -> int:
    """Sendet Push-Notification an alle registrierten Geräte.
    Gibt die Anzahl der erfolgreich gesendeten Nachrichten zurück."""
    try:
        _get_firebase_app()
        from firebase_admin import messaging
        tokens = _get_device_tokens()
        if not tokens:
            return 0
        sent = 0
        for token in tokens:
            try:
                messaging.send(messaging.Message(
                    notification=messaging.Notification(title=title, body=body),
                    data={"channel": channel},
                    android=messaging.AndroidConfig(
                        priority="high",
                        notification=messaging.AndroidNotification(channel_id=channel),
                    ),
                    token=token,
                ))
                sent += 1
            except Exception:
                pass
        return sent
    except Exception as exc:
        from app.audit.service import AuditService
        AuditService().log_warn(source="push", message=f"Push-Benachrichtigung konnte nicht gesendet werden: {type(exc).__name__}: {exc}")
        return 0
