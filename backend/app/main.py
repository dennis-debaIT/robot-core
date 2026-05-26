from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import deps
from app.api.routers import (
    chat,
    content,
    ha_calendar,
    reminders as reminders_router,
    ha_cameras,
    ha_devices,
    ha_lights,
    ha_printer,
    ha_pv,
    ha_robots,
    local_admin,
    memory,
    notes as notes_router,
    notifications,
    people,
    personality_audio,
    setup,
    simulation,
    system,
    timer,
)
from app.core.settings import SettingsService
from app.database.db import init_db
from app.integrations.robot_core import RobotCore
from app.services.integration_config_service import IntegrationConfigService
from app.services.robot_service import RobotService
from app.services.vehicle_service import VehicleService


async def _robot_error_history_loop(interval_seconds: int = 15) -> None:
    service = RobotService()
    while True:
        try:
            service.list_robots()
        except Exception:
            pass
        await asyncio.sleep(interval_seconds)


async def _timer_watcher_loop() -> None:
    from app.database.db import get_connection, read_state, write_state
    import time as _time
    while True:
        try:
            with get_connection() as conn:
                t = read_state(conn, "active_timer")
            if t and not t.get("finished") and not t.get("notified"):
                elapsed = _time.time() - float(t["started_at"])
                if elapsed >= float(t["duration_seconds"]):
                    t["finished"] = True
                    t["notified"] = True
                    with get_connection() as conn:
                        write_state(conn, "active_timer", t)
                    # Nur als abgelaufen markieren; Piepton + TTS macht das Frontend
        except Exception:
            pass
        await asyncio.sleep(1)


async def _auto_update_loop() -> None:
    from app.database.db import get_connection, read_state
    from app.api.routers.system import check_for_update, trigger_install
    await asyncio.sleep(60)  # Startup-Verzögerung
    while True:
        try:
            with get_connection() as conn:
                settings = read_state(conn, "update_settings", {}) or {}
            interval = settings.get("interval", "daily")
            auto_install = bool(settings.get("auto_install", False))
            sleep_seconds = {"hourly": 3600, "6h": 21600, "daily": 86400}.get(interval, 0)
            if sleep_seconds == 0:
                await asyncio.sleep(3600)
                continue
            result = await asyncio.to_thread(check_for_update)
            if auto_install and result.get("update_available"):
                await asyncio.to_thread(trigger_install)
        except Exception:
            pass
        await asyncio.sleep(sleep_seconds if sleep_seconds > 0 else 3600)


async def _reminder_watcher_loop() -> None:
    from app.database.db import get_connection
    while True:
        try:
            from datetime import datetime, timezone
            now_iso = datetime.now(timezone.utc).isoformat()

            # Rows erst fetchen, Verbindung danach schließen
            with get_connection() as conn:
                light_rows = conn.execute(
                    "SELECT id, light_command FROM reminders "
                    "WHERE notified=0 AND dismissed=0 AND fire_at <= ? AND light_command IS NOT NULL",
                    (now_iso,),
                ).fetchall()

            # Jede Licht-Erinnerung in eigener Transaktion — so ist das Commit unabhängig
            # vom Erfolg/Misserfolg der HA-Ausführung und von anderen parallelen Schreibern
            from app.search.providers.homeassistant import HomeAssistantProvider
            for row in light_rows:
                try:
                    HomeAssistantProvider().execute_light_command(row["light_command"])
                except Exception:
                    pass
                try:
                    with get_connection() as conn:
                        conn.execute(
                            "UPDATE reminders SET notified=1, dismissed=1 WHERE id=?",
                            (row["id"],),
                        )
                except Exception:
                    pass

            # Normale Erinnerungen (ohne light_command) als notified markieren
            with get_connection() as conn:
                conn.execute(
                    "UPDATE reminders SET notified=1 WHERE notified=0 AND dismissed=0 AND fire_at <= ?",
                    (now_iso,),
                )
        except Exception:
            pass
        await asyncio.sleep(5)


async def _notification_check_loop(interval_seconds: int = 30) -> None:
    from app.services.notification_service import NotificationService
    from app.database.db import get_connection, read_state, write_state
    svc = NotificationService()
    while True:
        try:
            triggered = svc.check_rules()
            if triggered:
                with get_connection() as conn:
                    existing = read_state(conn, "pending_notifications") or []
                    write_state(conn, "pending_notifications", existing + triggered)
        except Exception:
            pass
        await asyncio.sleep(interval_seconds)


async def _vehicle_location_history_loop(interval_seconds: int = 30) -> None:
    config_service = IntegrationConfigService()
    vehicle_service = VehicleService()
    while True:
        try:
            config = config_service.get_config()
            vehicle_service.record_locations(config)
            vehicle_service.record_charging(config)
            interval_seconds = int((config.get("vehicles") or {}).get("poll_seconds", interval_seconds))
        except Exception:
            pass
        await asyncio.sleep(max(10, min(interval_seconds, 300)))


@asynccontextmanager
async def lifespan(_: FastAPI) -> Any:
    init_db()
    settings_service = SettingsService()
    settings_service.ensure_runtime_state()
    IntegrationConfigService().ensure_runtime_state()
    core = RobotCore()
    core.cloud.ensure_state()
    core.device.ensure_state()
    robot_service = RobotService()
    robot_service.bootstrap_error_history()
    history_task = asyncio.create_task(_robot_error_history_loop())
    vehicle_history_task = asyncio.create_task(_vehicle_location_history_loop())
    auto_update_task = asyncio.create_task(_auto_update_loop())
    timer_task = asyncio.create_task(_timer_watcher_loop())
    notification_task = asyncio.create_task(_notification_check_loop())
    reminder_task = asyncio.create_task(_reminder_watcher_loop())
    deps.set_runtime(core, settings_service)
    try:
        yield
    finally:
        history_task.cancel()
        vehicle_history_task.cancel()
        auto_update_task.cancel()
        timer_task.cancel()
        notification_task.cancel()
        reminder_task.cancel()
        with suppress(asyncio.CancelledError):
            await history_task
        with suppress(asyncio.CancelledError):
            await vehicle_history_task
        with suppress(asyncio.CancelledError):
            await auto_update_task
        with suppress(asyncio.CancelledError):
            await timer_task
        with suppress(asyncio.CancelledError):
            await notification_task
        with suppress(asyncio.CancelledError):
            await reminder_task
        deps.clear_runtime()


app = FastAPI(title="Robot Core", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(chat.router)
app.include_router(memory.router)
app.include_router(content.router)
app.include_router(ha_devices.router)
app.include_router(ha_cameras.router)
app.include_router(ha_robots.router)
app.include_router(ha_lights.router)
app.include_router(ha_printer.router)
app.include_router(ha_pv.router)
app.include_router(local_admin.router)
app.include_router(setup.router)
app.include_router(simulation.router)
app.include_router(personality_audio.router)
app.include_router(people.router)
app.include_router(timer.router)
app.include_router(notifications.router)
app.include_router(ha_calendar.router)
app.include_router(reminders_router.router)
app.include_router(notes_router.router)
