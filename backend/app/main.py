from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import deps
from app.api.deps import BASE_DIR
from app.api.routers import (
    chat,
    content,
    features,
    ha_calendar,
    reminders as reminders_router,
    ha_cameras,
    ha_devices,
    ha_energy_costs,
    ha_lights,
    ha_printer,
    ha_pv,
    ha_robots,
    ha_waste,
    layout,
    license,
    local_admin,
    memory,
    notes as notes_router,
    notifications,
    people,
    personality_audio,
    setup,
    simulation,
    system,
    theme,
    timer,
    tournament,
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
    from app.audit.service import AuditService
    _audit = AuditService()
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
            from app.database.db import write_state
            for row in light_rows:
                result = None
                error = None
                try:
                    result = HomeAssistantProvider().execute_light_command(row["light_command"])
                except Exception as exc:
                    error = str(exc)
                    _audit.log_error(source="reminder_watcher.light", message=error, details={"command": row["light_command"]})
                try:
                    with get_connection() as conn:
                        conn.execute(
                            "UPDATE reminders SET notified=1, dismissed=1 WHERE id=?",
                            (row["id"],),
                        )
                        write_state(conn, "last_light_schedule_result", {
                            "command": row["light_command"],
                            "result": result,
                            "error": error,
                            "executed_at": datetime.now(timezone.utc).isoformat(),
                        })
                except Exception:
                    pass

            # Normale Erinnerungen (ohne light_command) als notified markieren
            with get_connection() as conn:
                conn.execute(
                    "UPDATE reminders SET notified=1 WHERE notified=0 AND dismissed=0 AND fire_at <= ?",
                    (now_iso,),
                )
        except Exception as exc:
            _audit.log_error(source="reminder_watcher_loop", message=str(exc))
        await asyncio.sleep(5)


async def _notification_check_loop(interval_seconds: int = 30) -> None:
    from app.services.notification_service import NotificationService
    from app.database.db import get_connection, read_state, write_state
    from app.audit.service import AuditService
    svc = NotificationService()
    _audit = AuditService()
    while True:
        try:
            triggered = svc.check_rules()
            if triggered:
                with get_connection() as conn:
                    existing = read_state(conn, "pending_notifications") or []
                    write_state(conn, "pending_notifications", existing + triggered)
        except Exception as exc:
            _audit.log_error(source="notification_check_loop", message=str(exc))
        await asyncio.sleep(interval_seconds)


async def _memory_maintenance_loop() -> None:
    from app.services.memory_service import MemoryService
    from app.audit.service import AuditService
    _audit = AuditService()
    await asyncio.sleep(300)  # 5min Startup-Verzögerung
    while True:
        try:
            svc = MemoryService()
            for person_name in svc.get_all_person_names():
                try:
                    svc.ensure_todays_daily_summary(person_name)
                    svc.refresh_active_topics(person_name)
                    svc.compress_dailies_to_weekly(person_name)
                    svc.prune_old_summaries(person_name)
                except Exception as exc:
                    _audit.log_error(source="memory_maintenance", message=str(exc), details={"person": person_name})
        except Exception as exc:
            _audit.log_error(source="memory_maintenance_loop", message=str(exc))
        await asyncio.sleep(3600)


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


async def _sync_loop(interval_seconds: int = 60) -> None:
    """Synchronisiert alle 60 Sekunden mit dem erika-sync-server.
    Läuft still wenn keine Sync-Credentials verfügbar sind."""
    from app.services import sync_service as _sync
    from app.services.integration_config_service import IntegrationConfigService as _ICS
    await asyncio.sleep(30)
    while True:
        try:
            url, tok = _sync.get_credentials()
            if url and tok:
                cfg     = _ICS().get_config()
                modules = (cfg.get("sync") or {}).get("modules", {})

                if modules.get("shopping", True):
                    _sync.push_unsynced()
                    since = _sync.get_last_sync_time()
                    _sync.pull_and_merge(since)

                if modules.get("notes", False):
                    _sync.push_persons()
                    _sync.push_notes()
                    _sync.pull_notes()

                if modules.get("reminders", False):
                    _sync.push_reminders()
                    _sync.pull_reminders()

                if modules.get("chores", False):
                    _sync.push_persons()
                    _sync.push_chore_tasks()
                    _sync.push_chore_completions()
                    _sync.pull_chore_completions()

                if modules.get("waste", False):
                    _sync.push_waste()

                if modules.get("news", False):
                    _sync.push_news()

                if modules.get("pv", False):
                    _sync.push_pv()
        except Exception:
            pass
        await asyncio.sleep(interval_seconds)


async def _license_renewal_loop(interval_hours: int = 24) -> None:
    """Erneuert eine installierte Abo-Lizenz täglich beim Lizenzserver.
    Lifetime-Lizenzen und fehlende Lizenzen werden übersprungen (still)."""
    from app.api.routers.license import renew_license

    await asyncio.sleep(120)  # Startup-Verzögerung (Netzwerk/HA erst hochfahren)
    while True:
        try:
            renew_license()
        except Exception:
            pass
        await asyncio.sleep(max(3600, interval_hours * 3600))


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
    memory_task = asyncio.create_task(_memory_maintenance_loop())
    license_task = asyncio.create_task(_license_renewal_loop())
    shopping_sync_task = asyncio.create_task(_sync_loop())
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
        memory_task.cancel()
        license_task.cancel()
        shopping_sync_task.cancel()
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
        with suppress(asyncio.CancelledError):
            await memory_task
        with suppress(asyncio.CancelledError):
            await license_task
        deps.clear_runtime()


app = FastAPI(title="Robot Core", version="0.3.0", lifespan=lifespan)

# Sicherheit: Frontend wird same-origin von dieser API ausgeliefert, daher
# normalerweise kein Cross-Origin-Zugriff nötig. ROBOT_CORS_ORIGINS (kommagetrennt)
# erlaubt zusätzliche Origins für lokale Entwicklung (z.B. Vite-Dev-Server).
# Ohne Angabe ist Cross-Origin-Zugriff komplett deaktiviert — verhindert, dass
# eine im selben Netzwerk geöffnete fremde Webseite per Browser-JS Antworten
# dieser API (z.B. /llm/config, /audit-log) auslesen kann.
_cors_origins = [o.strip() for o in os.environ.get("ROBOT_CORS_ORIGINS", "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Statische Assets (z.B. Mülltonnen-Bilder unter /assets/waste/*.png)
app.mount("/assets", StaticFiles(directory=str(BASE_DIR / "frontend" / "assets")), name="assets")

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
app.include_router(ha_energy_costs.router)
app.include_router(ha_waste.router)
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
app.include_router(theme.router)
app.include_router(layout.router)
app.include_router(features.router)
app.include_router(license.router)
app.include_router(tournament.router)
from app.api.routers import liga
app.include_router(liga.router)

# ── Paid-Module (Erika Plus) — optional ──────────────────────
# Diese Module fehlen im Community-Build. Ist die Datei nicht vorhanden,
# werden die Endpunkte gar nicht registriert (404 statt 403).
try:
    from app.api.routers import ha_pv_stats
    app.include_router(ha_pv_stats.router)
except ImportError:
    pass

try:
    from app.api.routers import chores
    app.include_router(chores.router)
except ImportError:
    pass

from app.api.routers import sync
app.include_router(sync.router)
