"""Cloud-Backup Service.

Erstellt ein verschlüsseltes ZIP (robot_core.db + .env) und lädt es
zum Sync Server hoch. Restore lädt das ZIP herunter, entschlüsselt es,
stellt die DB direkt wieder her und legt restore.env für den update.sh-
Watcher ab.
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
import zipfile
from pathlib import Path


def _fernet_key(token: str) -> bytes:
    raw = hashlib.sha256(token.encode()).digest()
    return base64.urlsafe_b64encode(raw)


def _encrypt(data: bytes, token: str) -> bytes:
    from cryptography.fernet import Fernet
    return Fernet(_fernet_key(token)).encrypt(data)


def _decrypt(data: bytes, token: str) -> bytes:
    from cryptography.fernet import Fernet
    return Fernet(_fernet_key(token)).decrypt(data)


def _get_sync_token() -> str:
    from app.services.sync_service import get_credentials
    _, token = get_credentials()
    return token or ""


def _db_path() -> Path:
    return Path(os.getenv("ROBOT_CORE_DB_PATH", "/data/robot_core.db"))


def _env_path() -> Path:
    candidates = [
        Path("/restore-env-source/.env"),  # gemounteter Host-Pfad
        Path(os.getenv("ROBOT_ENV_PATH", "")),
    ]
    for p in candidates:
        if p.exists():
            return p
    return Path("/restore-env-source/.env")


def _restore_env_path() -> Path:
    return Path("/restore.env")


def create_backup() -> int:
    """Erstellt Backup und lädt es hoch. Gibt Größe in Bytes zurück."""
    token = _get_sync_token()
    if not token:
        raise RuntimeError("Kein Sync-Token konfiguriert — Backup nicht möglich")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        db = _db_path()
        if db.exists():
            zf.write(db, "robot_core.db")
        env = _env_path()
        if env.exists():
            zf.write(env, ".env")

    payload = _encrypt(buf.getvalue(), token)
    _upload(payload)
    return len(payload)


def restore_backup() -> None:
    """Lädt Backup herunter, stellt DB wieder her, schreibt restore.env."""
    token = _get_sync_token()
    if not token:
        raise RuntimeError("Kein Sync-Token konfiguriert — Restore nicht möglich")

    payload = _download()
    raw = _decrypt(payload, token)

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = zf.namelist()
        if "robot_core.db" in names:
            db_path = _db_path()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            db_path.write_bytes(zf.read("robot_core.db"))
        if ".env" in names:
            _restore_env_path().write_bytes(zf.read(".env"))

    # update.flag setzen → update.sh startet Rebuild mit neuer .env
    flag = Path("/update.flag")
    if flag.exists():
        flag.write_text("restore")


def backup_info() -> dict:
    """Gibt Metadaten des letzten Backups zurück oder {"exists": False}."""
    from app.services.sync_service import _sync_request
    result = _sync_request("GET", "/backup/info")
    if not result:
        return {"exists": False}
    return result


def _upload(data: bytes) -> None:
    from app.services.sync_service import get_credentials
    import urllib.request
    url, token = get_credentials()
    if not (url and token):
        raise RuntimeError("Sync Server nicht konfiguriert")
    req = urllib.request.Request(
        url.rstrip("/") + "/backup/upload",
        data=data,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"Upload fehlgeschlagen: HTTP {resp.status}")


def _download() -> bytes:
    from app.services.sync_service import get_credentials
    import urllib.request
    url, token = get_credentials()
    if not (url and token):
        raise RuntimeError("Sync Server nicht konfiguriert")
    req = urllib.request.Request(
        url.rstrip("/") + "/backup/download",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()
