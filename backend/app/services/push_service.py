"""FCM Push-Notification Service.

Sendet Push-Nachrichten an alle registrierten Geräte eines Tenants.
Liest FCM-Tokens vom Sync Server, sendet via Firebase Admin SDK.
"""
from __future__ import annotations

import os
from typing import Any

_app = None


def _get_firebase_app():
    global _app
    if _app is not None:
        return _app
    creds_path = os.getenv("FIREBASE_CREDENTIALS", "/app/firebase-credentials.json")
    if not os.path.exists(creds_path):
        raise FileNotFoundError(f"Firebase credentials nicht gefunden: {creds_path}")
    import firebase_admin
    from firebase_admin import credentials
    cred = credentials.Certificate(creds_path)
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
    except Exception:
        return 0
