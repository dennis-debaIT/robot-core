from __future__ import annotations

from pathlib import Path

from app.core.settings import SettingsService
from app.integrations.robot_core import RobotCore


_CANDIDATE_BASE_DIR = Path(__file__).resolve().parents[2]
# Im Docker-Image liegen app/ und frontend/ als Geschwister direkt unter /app
# (parents[2] passt). Im normalen Repo-Checkout liegt zwischen app/ und
# frontend/ zusätzlich ein backend/-Ordner, d.h. parents[2] zeigt dann auf
# backend/ statt auf den Repo-Root. Fallback eine Ebene höher, falls dort
# kein frontend/ existiert.
BASE_DIR = (
    _CANDIDATE_BASE_DIR
    if (_CANDIDATE_BASE_DIR / "frontend").is_dir()
    else _CANDIDATE_BASE_DIR.parent
)
FRONTEND_INDEX = BASE_DIR / "frontend" / "index.html"
DISPLAY_INDEX = BASE_DIR / "frontend" / "display.html"
DISPLAY_CSS = BASE_DIR / "frontend" / "display.css"
DISPLAY_PLUS_JS = BASE_DIR / "frontend" / "display-plus.js"
DISPLAY_CHORES_JS = BASE_DIR / "frontend" / "display-chores.js"
DISPLAY_LIGA_JS = BASE_DIR / "frontend" / "display-liga.js"
DISPLAY_SYNC_JS = BASE_DIR / "frontend" / "display-sync.js"
LOCAL_ADMIN_INDEX = BASE_DIR / "frontend" / "local-admin.html"
LOCAL_ADMIN_CSS = BASE_DIR / "frontend" / "local-admin.css"
FAVICON_PNG = BASE_DIR / "frontend" / "favicon.png"

core: RobotCore | None = None
settings_service: SettingsService | None = None


def set_runtime(robot_core: RobotCore, settings: SettingsService) -> None:
    global core, settings_service
    core = robot_core
    settings_service = settings


def clear_runtime() -> None:
    global core, settings_service
    core = None
    settings_service = None


def get_core() -> RobotCore:
    if core is None:
        raise RuntimeError("RobotCore not initialized")
    return core


def get_settings_service() -> SettingsService:
    if settings_service is None:
        raise RuntimeError("SettingsService not initialized")
    return settings_service
