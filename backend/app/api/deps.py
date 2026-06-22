from __future__ import annotations

from pathlib import Path

from app.core.settings import SettingsService
from app.integrations.robot_core import RobotCore


BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_INDEX = BASE_DIR / "frontend" / "index.html"
DISPLAY_INDEX = BASE_DIR / "frontend" / "display.html"
DISPLAY_CSS = BASE_DIR / "frontend" / "display.css"
DISPLAY_PLUS_JS = BASE_DIR / "frontend" / "display-plus.js"
DISPLAY_CHORES_JS = BASE_DIR / "frontend" / "display-chores.js"
DISPLAY_LIGA_JS = BASE_DIR / "frontend" / "display-liga.js"
DISPLAY_SYNC_JS = BASE_DIR / "frontend" / "display-sync.js"
LOCAL_ADMIN_INDEX = BASE_DIR / "frontend" / "local-admin.html"
LOCAL_ADMIN_CSS = BASE_DIR / "frontend" / "local-admin.css"

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
