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
    backup,
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

            # Normale Erinnerungen (ohne light_command): FCM senden + notified markieren
            with get_connection() as conn:
                pending_rows = conn.execute(
                    "SELECT id, text, person_id FROM reminders "
                    "WHERE notified=0 AND dismissed=0 AND fire_at <= ? AND light_command IS NULL",
                    (now_iso,),
                ).fetchall()

            for row in pending_rows:
                try:
                    from app.services.push_service import send_notification
                    title = "Erinnerung"
                    body  = str(row["text"] or "")
                    send_notification(title, body, channel="reminders")
                except Exception:
                    pass

            with get_connection() as conn:
                conn.execute(
                    "UPDATE reminders SET notified=1 WHERE notified=0 AND dismissed=0 AND fire_at <= ?",
                    (now_iso,),
                )
        except Exception as exc:
            _audit.log_error(source="reminder_watcher_loop", message=str(exc))
        await asyncio.sleep(5)


async def _waste_push_loop() -> None:
    """Sendet täglich zur konfigurierten Uhrzeit eine Push-Notification
    falls morgen Müllabfuhr ist. Verhindert Doppelsendungen per Tages-Flag."""
    from app.audit.service import AuditService
    _audit = AuditService()
    last_notified_date: str | None = None
    await asyncio.sleep(60)
    while True:
        try:
            from datetime import datetime, timezone, date as _date
            from app.services.integration_config_service import IntegrationConfigService
            from app.services.waste_service import WasteService
            from app.services.push_service import send_notification

            cfg         = IntegrationConfigService().get_config()
            waste_cfg   = cfg.get("waste") or {}
            push_cfg    = waste_cfg.get("push_notifications") or {}
            if not push_cfg.get("enabled", True):
                await asyncio.sleep(60)
                continue

            notify_time = str(push_cfg.get("notify_time", "18:00"))
            now_local   = datetime.now()
            today_str   = now_local.strftime("%Y-%m-%d")
            current_hm  = now_local.strftime("%H:%M")

            if current_hm == notify_time and last_notified_date != today_str:
                tomorrow = (_date.today().toordinal() + 1)
                tomorrow_str = _date.fromordinal(tomorrow).isoformat()

                waste_data = WasteService().get_display_data(cfg)
                bins_tomorrow = [
                    b["label"] for b in waste_data.get("bins", [])
                    if b.get("date") == tomorrow_str
                ]
                if bins_tomorrow:
                    labels = ", ".join(bins_tomorrow)
                    send_notification(
                        title="🗑️ Müllabfuhr morgen",
                        body=f"Morgen wird abgeholt: {labels}",
                        channel="waste",
                    )
                    last_notified_date = today_str
        except Exception as exc:
            try:
                from app.audit.service import AuditService
                AuditService().log_error(source="waste_push_loop", message=str(exc))
            except Exception:
                pass
        await asyncio.sleep(60)


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

                if modules.get("calendar", False):
                    _sync.push_calendar()

                if modules.get("lights", False):
                    _sync.push_light_scenes()
        except Exception:
            pass
        await asyncio.sleep(interval_seconds)


async def _pv_fast_sync_loop(interval_seconds: int = 10) -> None:
    """Pusht PV-Echtzeitdaten alle 10 Sekunden — unabhängig vom 60s-Sync-Loop."""
    from app.services import sync_service as _sync
    from app.services.integration_config_service import IntegrationConfigService as _ICS
    await asyncio.sleep(35)
    while True:
        try:
            url, tok = _sync.get_credentials()
            if url and tok:
                cfg = _ICS().get_config()
                modules = (cfg.get("sync") or {}).get("modules", {})
                if modules.get("pv", False):
                    _sync.push_pv()
        except Exception:
            pass
        await asyncio.sleep(interval_seconds)


async def _light_command_poll_loop(interval_seconds: int = 3) -> None:
    """Pollt Licht-Befehle alle 3 Sekunden für schnelle Reaktion auf App-Befehle."""
    from app.services import sync_service as _sync
    from app.services.integration_config_service import IntegrationConfigService as _ICS
    await asyncio.sleep(38)
    while True:
        try:
            url, tok = _sync.get_credentials()
            if url and tok:
                cfg = _ICS().get_config()
                if (cfg.get("sync") or {}).get("modules", {}).get("lights", False):
                    _sync.poll_light_commands()
        except Exception:
            pass
        await asyncio.sleep(interval_seconds)


async def _ha_lights_ws_loop() -> None:
    """Abonniert HA WebSocket für state_changed auf Licht-Entitäten und pusht
    sofort zum Sync Server — kein Polling-Intervall nötig."""
    import json as _json
    from app.services import sync_service as _sync
    from app.services.integration_config_service import IntegrationConfigService as _ICS

    await asyncio.sleep(40)

    while True:
        try:
            url, tok = _sync.get_credentials()
            if not (url and tok):
                await asyncio.sleep(60)
                continue

            cfg = _ICS().get_config()
            if not (cfg.get("sync") or {}).get("modules", {}).get("lights", False):
                await asyncio.sleep(60)
                continue

            from app.services.homeassistant_runtime_config_service import HomeAssistantRuntimeConfigService as _HARCS
            runtime = _HARCS.to_public_payload()
            base_url = str(runtime.get("base_url") or "")
            ha_token = str(runtime.get("token") or "")
            if not (base_url and ha_token):
                await asyncio.sleep(60)
                continue

            ws_url = base_url.replace("https://", "wss://").replace("http://", "ws://") + "/api/websocket"

            import websockets
            async with websockets.connect(ws_url) as ws:
                # Authentifizierung
                msg = _json.loads(await ws.recv())
                if msg.get("type") != "auth_required":
                    await asyncio.sleep(30)
                    continue
                await ws.send(_json.dumps({"type": "auth", "access_token": ha_token}))
                msg = _json.loads(await ws.recv())
                if msg.get("type") != "auth_ok":
                    await asyncio.sleep(60)
                    continue

                # state_changed abonnieren
                await ws.send(_json.dumps({"id": 1, "type": "subscribe_events", "event_type": "state_changed"}))
                await ws.recv()  # result-Bestätigung

                async for raw in ws:
                    try:
                        event = _json.loads(raw)
                        if event.get("type") != "event":
                            continue
                        data = (event.get("event") or {}).get("data") or {}
                        entity_id = str(data.get("entity_id") or "")
                        if not (entity_id.startswith("light.") or entity_id.startswith("switch.")):
                            continue
                        await asyncio.to_thread(_sync.push_lights)
                    except Exception:
                        pass
        except Exception:
            pass
        await asyncio.sleep(10)  # Reconnect-Pause bei Verbindungsabbruch


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


def _run_liga_cache_warm() -> None:
    """Synchrone Helferfunktion — läuft in einem Executor-Thread."""
    try:
        from app.services.integration_config_service import IntegrationConfigService
        from app.services.liga_service import LigaService
        cfg = IntegrationConfigService().get_config().get("liga") or {}
        if not (cfg.get("enabled") and cfg.get("api_key")):
            return
        codes = [c for c in (cfg.get("leagues") or []) if c in {"BL1", "BL2", "BL3"}]
        if not codes:
            return
        LigaService(cfg["api_key"]).warm_all_league_caches(codes, cfg.get("favorite_team_name", ""))
    except Exception:
        pass


async def _liga_cache_daemon(interval_hours: int = 12) -> None:
    """Hält Liga-Caches warm: Kader + Vereinsprofil + Transfers für alle
    konfigurierten Ligen. Lieblingsverein wird zuerst verarbeitet.
    Startet 90 Sekunden nach Hochfahren, danach alle 12 Stunden."""
    await asyncio.sleep(90)
    loop = asyncio.get_event_loop()
    while True:
        await loop.run_in_executor(None, _run_liga_cache_warm)
        await asyncio.sleep(interval_hours * 3600)


def _migrate_deprecated_llm_models() -> None:
    """Ersetzt abgekündigte LLM-Modelle automatisch durch den empfohlenen Nachfolger."""
    _REPLACEMENTS = {"llama-3.1-8b-instant": "openai/gpt-oss-20b"}
    try:
        from app.database.db import get_connection, read_state, write_state
        with get_connection() as conn:
            cfg = dict(read_state(conn, "llm_config", {}) or {})
            if cfg.get("model") in _REPLACEMENTS:
                cfg["model"] = _REPLACEMENTS[cfg["model"]]
                write_state(conn, "llm_config", cfg)
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_: FastAPI) -> Any:
    init_db()
    _migrate_deprecated_llm_models()
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
    waste_push_task = asyncio.create_task(_waste_push_loop())
    memory_task = asyncio.create_task(_memory_maintenance_loop())
    license_task = asyncio.create_task(_license_renewal_loop())
    shopping_sync_task = asyncio.create_task(_sync_loop())
    pv_fast_sync_task = asyncio.create_task(_pv_fast_sync_loop())
    light_cmd_poll_task = asyncio.create_task(_light_command_poll_loop())
    ha_lights_ws_task = asyncio.create_task(_ha_lights_ws_loop())
    liga_cache_task = asyncio.create_task(_liga_cache_daemon())
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
        waste_push_task.cancel()
        memory_task.cancel()
        license_task.cancel()
        shopping_sync_task.cancel()
        pv_fast_sync_task.cancel()
        light_cmd_poll_task.cancel()
        ha_lights_ws_task.cancel()
        liga_cache_task.cancel()
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
            await waste_push_task
        with suppress(asyncio.CancelledError):
            await memory_task
        with suppress(asyncio.CancelledError):
            await license_task
        with suppress(asyncio.CancelledError):
            await liga_cache_task
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
app.include_router(backup.router)
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
