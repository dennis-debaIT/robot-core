from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/admin/backup", tags=["backup"])


@router.get("/info")
def get_backup_info() -> dict:
    from app.services.backup_service import backup_info
    try:
        return backup_info()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/create")
def create_backup() -> dict:
    from app.services.backup_service import create_backup as _create
    try:
        size = _create()
        return {"ok": True, "size_bytes": size}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/restore")
def restore_backup() -> dict:
    from app.services.backup_service import restore_backup as _restore
    try:
        _restore()
        return {"ok": True, "message": "Backup wiederhergestellt. Erika startet neu."}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
