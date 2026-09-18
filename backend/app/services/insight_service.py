from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.database.db import get_connection, read_state, write_state
from app.search.providers.homeassistant import HomeAssistantProvider
from app.search.providers.weather import WeatherProvider
from app.services.homeassistant_service import HomeAssistantService
from app.services.integration_config_service import IntegrationConfigService
from app.services.notification_service import NotificationService
from app.services.pv_service import PvService

_FUEL_LABELS = {
    "diesel": "Diesel", "e10": "E10", "e5": "E5", "super": "Super",
    "benzin": "Benzin", "lpg": "LPG", "autogas": "LPG",
    "adblue": "AdBlue", "ad_blue": "AdBlue",
}
_FUEL_TREND_DELTA_EUR = 0.05
_FUEL_NEAR_LOW_MARGIN_EUR = 0.01
_PV_SURPLUS_COOLDOWN_SECONDS = 2 * 60 * 60
_WEATHER_COLD_C = 5.0
_WEATHER_HOT_C = 28.0
_WEATHER_RAIN_MM = 1.0


class InsightService:
    """Wertet bereits bekannte Sensordaten (Kraftstoff, PV, Wetter+Kalender)
    selbständig aus und meldet Auffälligkeiten proaktiv — analog zum
    Benachrichtigungs-/Kalender-Erinnerungs-System, aber ohne feste Regel:
    Erika entscheidet selbst, wann etwas erwähnenswert ist."""

    def __init__(
        self,
        ha: HomeAssistantService | None = None,
        pv: PvService | None = None,
        weather_cls: type | None = None,
        notifications: NotificationService | None = None,
    ) -> None:
        self.ha = ha or HomeAssistantService()
        self.pv = pv or PvService(ha=self.ha)
        self._weather_cls = weather_cls or WeatherProvider
        self.notifications = notifications or NotificationService(ha=self.ha)

    def run_checks(self) -> list[dict[str, Any]]:
        config = IntegrationConfigService().get_config()
        insights_cfg = config.get("insights") or {}
        fired: list[dict[str, Any]] = []

        if insights_cfg.get("pv_surplus_enabled"):
            try:
                msg = self._check_pv_surplus(config, insights_cfg)
                if msg:
                    self.notifications.create_manual_notification(msg, entity_id="pv", title="☀️ PV-Überschuss")
                    fired.append({"kind": "pv_surplus", "message": msg})
            except Exception as exc:
                self._log_error("pv_surplus", exc)

        if insights_cfg.get("fuel_price_enabled"):
            try:
                msg = self._check_fuel_price(config)
                if msg:
                    self.notifications.create_manual_notification(msg, entity_id="fuel", title="⛽ Kraftstoffpreis")
                    fired.append({"kind": "fuel_price", "message": msg})
            except Exception as exc:
                self._log_error("fuel_price", exc)

        if insights_cfg.get("weather_tomorrow_enabled"):
            try:
                msg = self._check_weather_tomorrow(config)
                if msg:
                    self.notifications.create_manual_notification(msg, entity_id="weather", title="🌤️ Wetter morgen")
                    fired.append({"kind": "weather_tomorrow", "message": msg})
            except Exception as exc:
                self._log_error("weather_tomorrow", exc)

        if insights_cfg.get("robot_status_enabled"):
            try:
                entries = self._check_robot_status(config)
                for entry in entries:
                    self.notifications.create_manual_notification(
                        entry["message"], entity_id=entry["entity_id"], title=entry["title"]
                    )
                    fired.append({"kind": "robot_status", "message": entry["message"], "entity_id": entry["entity_id"]})
            except Exception as exc:
                self._log_error("robot_status", exc)

        if insights_cfg.get("vehicle_status_enabled"):
            try:
                entries = self._check_vehicles(config, insights_cfg)
                for entry in entries:
                    self.notifications.create_manual_notification(
                        entry["message"], entity_id=entry["entity_id"], title=entry["title"]
                    )
                    fired.append({"kind": entry["kind"], "message": entry["message"], "entity_id": entry["entity_id"]})
            except Exception as exc:
                self._log_error("vehicle_status", exc)

        if insights_cfg.get("severe_weather_enabled"):
            try:
                msg = self._check_severe_weather(insights_cfg)
                if msg:
                    self.notifications.create_manual_notification(msg, entity_id="severe_weather", title="⛈️ Unwetterwarnung")
                    fired.append({"kind": "severe_weather", "message": msg})
            except Exception as exc:
                self._log_error("severe_weather", exc)

        return fired

    @staticmethod
    def _log_error(kind: str, exc: Exception) -> None:
        from app.audit.service import AuditService
        AuditService().log_warn(
            source="insights",
            message=f"Insight-Check '{kind}' fehlgeschlagen: {type(exc).__name__}: {exc}",
        )

    # ── Kraftstoffpreis-Trend ────────────────────────────────────

    def _check_fuel_price(self, config: dict[str, Any]) -> str | None:
        """Läuft 1x/Tag ab 18 Uhr. Holt den aktuellen Preis sowie die echte
        7-Tage-Historie direkt aus HA (kein eigener Zwischenspeicher) und
        entscheidet deterministisch, ob der Trend erwähnenswert ist — das
        LLM formuliert nur, es erfindet keine Einschätzung."""
        now = datetime.now().astimezone()
        if now.hour < 18:
            return None
        today_str = now.date().isoformat()
        with get_connection() as conn:
            last_run = read_state(conn, "insight_fuel_last_run_date", None)
        if last_run == today_str:
            return None

        fuel_cfg = config.get("fuel_prices") or {}
        fuel_types = fuel_cfg.get("fuel_types") or ["diesel"]
        label = _FUEL_LABELS.get(str(fuel_types[0]).lower(), "Diesel")

        prices = HomeAssistantProvider().get_fuel_prices()
        grouped = (prices or {}).get("grouped") or {}
        entries = grouped.get(label) or []
        if not entries:
            self._mark_fuel_run(today_str)
            return None

        cheapest = entries[0]
        entity_id = cheapest["entity_id"]
        current_price = float(cheapest["price"])

        history = HomeAssistantProvider().get_history(
            entity_id, now - timedelta(days=7), now, chunk_hours=24
        )
        self._mark_fuel_run(today_str)

        prices_7d: list[float] = []
        for row in history:
            try:
                prices_7d.append(float(row.get("state")))
            except (TypeError, ValueError):
                continue
        if not prices_7d:
            return None

        min_7d = min(prices_7d)
        max_7d = max(prices_7d)
        near_low = abs(current_price - min_7d) <= _FUEL_NEAR_LOW_MARGIN_EUR
        down_from_high = (max_7d - current_price) >= _FUEL_TREND_DELTA_EUR
        up_from_low = (current_price - min_7d) >= _FUEL_TREND_DELTA_EUR

        if near_low and down_from_high:
            note = "aktuell nahe dem Wochentief"
        elif up_from_low:
            note = "spürbar teurer als der Wochentiefstwert"
        else:
            return None

        prompt = (
            f"{label}-Preis Beobachtung: aktueller Preis {current_price:.3f} €/L "
            f"(Wochenspanne {min_7d:.3f}–{max_7d:.3f} €/L, {note}). "
            "Formuliere daraus einen kurzen, natürlichen Hinweis für die Familie "
            "(max. 1 Satz, kein Markdown, keine Anführungszeichen, auf Deutsch). "
            "Erfinde keine zusätzlichen Zahlen, nutze nur die genannten."
        )
        fallback = f"{label}: aktuell {current_price:.3f} €/L, {note}."
        message = self._llm_narrate(prompt, avoid=self._recent_messages("fuel_price")) or fallback
        self._record_message("fuel_price", message)
        return message

    @staticmethod
    def _mark_fuel_run(today_str: str) -> None:
        with get_connection() as conn:
            write_state(conn, "insight_fuel_last_run_date", today_str)

    # ── PV-Überschuss ────────────────────────────────────────────

    def _check_pv_surplus(self, config: dict[str, Any], insights_cfg: dict[str, Any]) -> str | None:
        """Läuft bei jedem Loop-Tick. `grid` ist bei PvService bereits
        vorzeichenrichtig (positiv = Einspeisung/Überschuss), Edge-Detection
        + Cooldown verhindern Geflacker bei wechselnder Bewölkung."""
        pv_cfg = config.get("pv") or {}
        if not pv_cfg.get("enabled"):
            return None
        sensors = pv_cfg.get("sensors") or {}
        state = self.pv.get_state(sensors)
        grid_raw = (state.get("grid") or {}).get("value")
        try:
            grid_w = float(grid_raw)
        except (TypeError, ValueError):
            return None  # kein Grid-Sensor konfiguriert/verfügbar

        threshold = float(insights_cfg.get("pv_surplus_threshold_watts", 1500))
        now = datetime.now(timezone.utc)

        with get_connection() as conn:
            active = bool(read_state(conn, "insight_pv_surplus_active", False))
            last_fired_iso = read_state(conn, "insight_pv_surplus_last_fired_at", None)

        if grid_w < threshold:
            if active:
                with get_connection() as conn:
                    write_state(conn, "insight_pv_surplus_active", False)
            return None

        if active:
            return None

        if last_fired_iso:
            try:
                last_fired = datetime.fromisoformat(last_fired_iso)
                if (now - last_fired).total_seconds() < _PV_SURPLUS_COOLDOWN_SECONDS:
                    with get_connection() as conn:
                        write_state(conn, "insight_pv_surplus_active", True)
                    return None
            except ValueError:
                pass

        with get_connection() as conn:
            write_state(conn, "insight_pv_surplus_active", True)
            write_state(conn, "insight_pv_surplus_last_fired_at", now.isoformat())

        prompt = (
            f"PV-Beobachtung: aktuell speist die Solaranlage {grid_w:.0f} Watt Überschuss ins Netz ein "
            f"(Schwelle für 'viel': {threshold:.0f} Watt). "
            "Formuliere daraus einen kurzen, natürlichen Hinweis, dass jetzt ein guter Moment für "
            "stromintensive Aufgaben wäre (z.B. Waschmaschine, Geschirrspüler) "
            "(max. 1 Satz, kein Markdown, keine Anführungszeichen, auf Deutsch)."
        )
        fallback = f"Die PV-Anlage produziert gerade {grid_w:.0f} Watt Überschuss — guter Moment für stromintensive Aufgaben."
        message = self._llm_narrate(prompt, avoid=self._recent_messages("pv_surplus")) or fallback
        self._record_message("pv_surplus", message)
        return message

    # ── Wetter morgen (+ Kalender-Kombi) ─────────────────────────

    def _check_weather_tomorrow(self, config: dict[str, Any]) -> str | None:
        """Läuft 1x/Tag ab 17 Uhr. Prüft zuerst das Zuhause-Wetter für morgen,
        reichert die Meldung automatisch um den Ort eines morgigen Termins an
        (falls einer ein `location`-Feld hat) — ein Toggle deckt beides ab."""
        now = datetime.now().astimezone()
        if now.hour < 17:
            return None
        today_str = now.date().isoformat()
        with get_connection() as conn:
            last_run = read_state(conn, "insight_weather_last_run_date", None)
        if last_run == today_str:
            return None
        with get_connection() as conn:
            write_state(conn, "insight_weather_last_run_date", today_str)

        weather_cls = self._weather_cls
        home_data = weather_cls().get_display_data()
        home_tomorrow = (home_data or {}).get("tomorrow") or {}
        if not home_tomorrow:
            return None

        notable = self._is_notable_weather(home_tomorrow)

        cal_cfg = config.get("calendar") or {}
        selected = cal_cfg.get("selected_calendars") or []
        tomorrow_date = (now + timedelta(days=1)).date()
        dest_location: str | None = None
        dest_summary: str | None = None
        try:
            events = HomeAssistantProvider().get_events_upcoming(days=2, selected_calendars=selected or None)
        except Exception:
            events = []
        for ev in events:
            start = ev.get("start") or {}
            start_raw = start.get("dateTime") or start.get("date")
            if not start_raw:
                continue
            try:
                ev_date = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00")).date()
            except ValueError:
                continue
            if ev_date != tomorrow_date:
                continue
            loc = (ev.get("location") or "").strip()
            if loc:
                dest_location = loc
                dest_summary = ev.get("summary") or "Termin"
                break

        dest_tomorrow = None
        if dest_location:
            try:
                dest_data = weather_cls().get_display_data(location=dest_location)
                dest_tomorrow = (dest_data or {}).get("tomorrow")
            except Exception:
                dest_tomorrow = None
            if dest_tomorrow and self._is_notable_weather(dest_tomorrow):
                notable = True

        if not notable:
            return None

        home_desc = (
            f"Zuhause morgen: {home_tomorrow.get('description', '')}, "
            f"{home_tomorrow.get('temp_min')}–{home_tomorrow.get('temp_max')}°C, "
            f"Niederschlag {home_tomorrow.get('precipitation', 0)}mm."
        )
        dest_block = ""
        if dest_tomorrow:
            dest_block = (
                f" Termin morgen: '{dest_summary}' in {dest_location}, dort: "
                f"{dest_tomorrow.get('description', '')}, "
                f"{dest_tomorrow.get('temp_min')}–{dest_tomorrow.get('temp_max')}°C, "
                f"Niederschlag {dest_tomorrow.get('precipitation', 0)}mm."
            )

        prompt = (
            f"Wetter-Beobachtung für morgen. {home_desc}{dest_block} "
            "Formuliere daraus einen kurzen, natürlichen, hilfreichen Hinweis (z.B. passende Kleidung) "
            "(max. 1 Satz, kein Markdown, keine Anführungszeichen, auf Deutsch)."
        )
        fallback = (
            f"Morgen: {home_tomorrow.get('description', 'wechselhaft')}, "
            f"{home_tomorrow.get('temp_min')}–{home_tomorrow.get('temp_max')}°C."
        )
        message = self._llm_narrate(prompt, avoid=self._recent_messages("weather_tomorrow")) or fallback
        self._record_message("weather_tomorrow", message)
        return message

    @staticmethod
    def _is_notable_weather(day: dict[str, Any]) -> bool:
        try:
            precip = float(day.get("precipitation") or 0)
        except (TypeError, ValueError):
            precip = 0.0
        try:
            tmin = float(day["temp_min"]) if day.get("temp_min") is not None else None
        except (TypeError, ValueError):
            tmin = None
        try:
            tmax = float(day["temp_max"]) if day.get("temp_max") is not None else None
        except (TypeError, ValueError):
            tmax = None
        if precip >= _WEATHER_RAIN_MM:
            return True
        if tmin is not None and tmin < _WEATHER_COLD_C:
            return True
        if tmax is not None and tmax > _WEATHER_HOT_C:
            return True
        return False

    # ── Roboter-Status (Geräte ohne eigene Benachrichtigungsregel) ──

    def _check_robot_status(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Prüft ALLE konfigurierten Roboter (Mäher + Sauger) auf neue
        Warn-/Fehlerzustände — aber nur solche, für die noch keine eigene
        Benachrichtigungsregel existiert (die bleibt die primäre Quelle für
        ihren Roboter). Nutzt die bereits vorhandene, deterministische
        Severity-Klassifizierung aus RobotService — keine LLM-Trigger-
        Entscheidung, das LLM formuliert nur."""
        from app.services.notification_service import NotificationService
        from app.services.robot_service import RobotService

        robot_service = RobotService(ha=self.ha)
        robots = robot_service.list_robots_with_config(config)
        if not robots:
            return []

        covered = NotificationService(ha=self.ha)._entities_with_enabled_rules()

        results: list[dict[str, Any]] = []
        for robot in robots:
            entity_id = robot.get("entity_id") or ""
            if not entity_id or entity_id in covered:
                continue

            raw_state = robot.get("state") or ""
            severity = self._robot_severity(robot_service, entity_id, raw_state, config)
            if severity is None:
                continue  # nicht eindeutig klassifiziert -> nicht proaktiv melden

            state_key = f"insight_robot_status_last_severity:{entity_id}"
            with get_connection() as conn:
                last_severity = read_state(conn, state_key, None)
            if severity == last_severity:
                continue
            with get_connection() as conn:
                write_state(conn, state_key, severity)

            if severity not in ("warning", "error"):
                continue  # nur neue Probleme melden, nicht die Rückkehr zu ok

            label = robot.get("name") or entity_id
            translated = robot_service._translate_error_state(raw_state)
            prompt = (
                f"Roboter-Beobachtung: {label} meldet einen neuen Problemzustand: '{translated}'. "
                "Formuliere daraus eine kurze, natürliche Meldung "
                "(max. 1 Satz, kein Markdown, keine Anführungszeichen, auf Deutsch)."
            )
            fallback = f"{label}: {translated}."
            history_key = f"robot_status:{entity_id}"
            message = self._llm_narrate(prompt, avoid=self._recent_messages(history_key)) or fallback
            self._record_message(history_key, message)
            results.append({"entity_id": entity_id, "title": f"🤖 {label}", "message": message})

        return results

    @staticmethod
    def _robot_severity(robot_service: Any, entity_id: str, raw_state: str, config: dict[str, Any]) -> str | None:
        """Konservativere Variante von RobotService._severity_for_state:
        nur explizit als ok/warn/critical eingestufte Zustände zählen.
        RobotService._severity_for_state() wertet unbekannte Zustände
        standardmäßig als "error" — sinnvoll fürs Fehlerprotokoll (ein
        False-Positive dort ist billig), aber hier würde es zu Fehlalarm-
        Push-Benachrichtigungen führen: harmlose, saugerspezifische Zustände
        wie "charging_completed" oder "drying" stehen nicht in den eher
        mäher-lastigen Default-Listen und würden sonst als Fehler gemeldet.
        Unbekannte Zustände geben hier None zurück und werden nicht gemeldet
        (können aber über robots.state_mappings im Admin-Bereich explizit
        eingeordnet werden, dann greifen sie normal)."""
        normalized = robot_service._normalize_error_state(raw_state)
        rules = robot_service._robot_state_rules(config, entity_id)
        if normalized in rules["no_error"] or normalized in rules["ok"]:
            return "ok"
        if normalized in rules["warn"]:
            return "warning"
        # "error" ist der generische Marker, auf den RobotService._resolve_state()
        # jeden nicht explizit zugeordneten Fehler-Sensor-Wert reduziert (z.B.
        # über sensor.<slug>_error/_fehler) — muss hier wie critical behandelt
        # werden, sonst würden echte Fehler wieder als "unbekannt" durchfallen.
        if normalized in rules["critical"] or normalized == "error":
            return "error"
        return None

    # ── Fahrzeuge (Ladung fertig / Batterie niedrig) ────────────────

    def _check_vehicles(self, config: dict[str, Any], insights_cfg: dict[str, Any]) -> list[dict[str, Any]]:
        """Prüft alle konfigurierten E-Fahrzeuge auf zwei Ereignisse:
        Ladung beendet (noch eingesteckt) und niedriger Akkustand (weder
        ladend noch eingesteckt). Nutzt dieselbe Lade-/Steckererkennung wie
        VehicleService.record_charging() — keine eigene Interpretation der
        markenabhängigen Rohzustände."""
        from app.services.vehicle_service import VehicleService

        vehicle_service = VehicleService(ha=self.ha)
        data = vehicle_service.list_vehicles(config)
        if not data.get("enabled"):
            return []

        threshold = float(insights_cfg.get("vehicle_battery_low_threshold_pct", 20))
        now = datetime.now(timezone.utc)
        results: list[dict[str, Any]] = []

        for vehicle in data.get("vehicles") or []:
            if not vehicle.get("ev_profile_enabled"):
                continue
            battery = vehicle.get("battery")
            if not battery:
                continue
            try:
                battery_pct = float(battery["state"])
            except (TypeError, ValueError):
                continue

            vehicle_id = vehicle.get("id") or vehicle.get("label") or "vehicle"
            label = vehicle.get("label") or vehicle_id

            charging_state = (vehicle.get("charging") or {}).get("state")
            plug_state = (vehicle.get("plug") or {}).get("state")
            is_charging = VehicleService._is_charging_state(charging_state or "")
            plug_connected = (
                VehicleService._is_plug_connected_state(plug_state)
                if plug_state is not None else is_charging
            )

            # ── Ladung fertig ───────────────────────────────────
            if charging_state is not None:
                charge_key = f"insight_vehicle_charging:{vehicle_id}"
                with get_connection() as conn:
                    last_charging = read_state(conn, charge_key, None)
                    write_state(conn, charge_key, is_charging)
                if last_charging is True and not is_charging and plug_connected:
                    prompt = (
                        f"Fahrzeug-Beobachtung: {label} hat den Ladevorgang beendet und ist noch "
                        f"eingesteckt, Akku bei {battery_pct:.0f}%. Formuliere daraus einen kurzen, "
                        "natürlichen Hinweis (max. 1 Satz, kein Markdown, keine Anführungszeichen, "
                        "auf Deutsch)."
                    )
                    fallback = f"{label}: Ladevorgang beendet ({battery_pct:.0f}%), aber noch eingesteckt."
                    history_key = f"vehicle_charged:{vehicle_id}"
                    message = self._llm_narrate(prompt, avoid=self._recent_messages(history_key)) or fallback
                    self._record_message(history_key, message)
                    results.append({
                        "entity_id": vehicle_id, "kind": "vehicle_charged",
                        "title": f"🔌 {label}", "message": message,
                    })

            # ── Batterie niedrig ────────────────────────────────
            low_active_key = f"insight_vehicle_battery_low_active:{vehicle_id}"
            low_fired_key = f"insight_vehicle_battery_low_last_fired_at:{vehicle_id}"
            with get_connection() as conn:
                active = bool(read_state(conn, low_active_key, False))
                last_fired_iso = read_state(conn, low_fired_key, None)

            is_low_and_idle = battery_pct < threshold and not is_charging and not plug_connected
            if not is_low_and_idle:
                if active:
                    with get_connection() as conn:
                        write_state(conn, low_active_key, False)
                continue
            if active:
                continue
            if last_fired_iso:
                try:
                    last_fired = datetime.fromisoformat(last_fired_iso)
                    if (now - last_fired).total_seconds() < _PV_SURPLUS_COOLDOWN_SECONDS:
                        with get_connection() as conn:
                            write_state(conn, low_active_key, True)
                        continue
                except ValueError:
                    pass

            with get_connection() as conn:
                write_state(conn, low_active_key, True)
                write_state(conn, low_fired_key, now.isoformat())

            prompt = (
                f"Fahrzeug-Beobachtung: {label} hat einen niedrigen Akkustand ({battery_pct:.0f}%) "
                "und lädt gerade nicht. Formuliere daraus einen kurzen, natürlichen Hinweis, bevor "
                "man losfährt (max. 1 Satz, kein Markdown, keine Anführungszeichen, auf Deutsch)."
            )
            fallback = f"{label}: Akku bei {battery_pct:.0f}%, aktuell nicht am Laden."
            history_key = f"vehicle_battery_low:{vehicle_id}"
            message = self._llm_narrate(prompt, avoid=self._recent_messages(history_key)) or fallback
            self._record_message(history_key, message)
            results.append({
                "entity_id": vehicle_id, "kind": "vehicle_battery_low",
                "title": f"🔋 {label}", "message": message,
            })

        return results

    # ── Unwetterwarnung (fester Sensor, z.B. DWD Weather Warnings) ──

    def _check_severe_weather(self, insights_cfg: dict[str, Any]) -> str | None:
        """Liest einen vom Nutzer konfigurierten HA-Sensor (z.B. aus der
        offiziellen "DWD Weather Warnings"-Integration) aus — kein eigener
        DWD-Datenabruf, robot-core behandelt ihn wie jeden anderen
        HA-Sensor. Meldet nur ab Stufe 3 (Unwetterwarnung/Extreme
        Unwetterwarnung)."""
        entity_id = str(insights_cfg.get("severe_weather_entity_id") or "").strip()
        if not entity_id:
            return None
        state = self.ha.get_state(entity_id)
        if not state:
            return None

        attrs = state.get("attributes") or {}
        try:
            level = int(state.get("state"))
        except (TypeError, ValueError):
            try:
                level = int(attrs.get("warning_1_level"))
            except (TypeError, ValueError):
                return None

        if level < 3:
            return None

        headline = str(attrs.get("warning_1_headline") or "Unwetterwarnung").strip()
        region = str(attrs.get("region_name") or "").strip()
        description = str(attrs.get("warning_1_description") or "").strip()

        signature = f"{level}|{headline}"
        with get_connection() as conn:
            last_signature = read_state(conn, "insight_severe_weather_last_signature", None)
            write_state(conn, "insight_severe_weather_last_signature", signature)
        if signature == last_signature:
            return None

        region_part = f" für {region}" if region else ""
        prompt = (
            f"Unwetterwarnung{region_part}: '{headline}' (Stufe {level} von 4). "
            f"{('Details: ' + description) if description else ''} "
            "Formuliere daraus einen kurzen, sachlichen Warnhinweis für die Familie — HIER KEIN "
            "Humor oder Sarkasmus, das ist eine echte Sicherheitswarnung, kein beiläufiger Hinweis "
            "(max. 1-2 Sätze, kein Markdown, keine Anführungszeichen, auf Deutsch)."
        )
        fallback = f"⚠️ {headline}{region_part} (Stufe {level})."
        message = self._llm_narrate(prompt, avoid=self._recent_messages("severe_weather")) or fallback
        self._record_message("severe_weather", message)
        return message

    # ── Wiederholungs-Vermeidung ─────────────────────────────────

    def _recent_messages(self, key: str, limit: int = 3) -> list[str]:
        """Letzte generierte Meldungen für dieses Ereignis (z.B. 'pv_surplus'
        oder 'robot_status:vacuum.krumel_knecht') — dienen _llm_narrate als
        Negativbeispiele, damit nicht immer dieselbe Formulierung kommt."""
        with get_connection() as conn:
            history = read_state(conn, f"insight_recent_messages:{key}", [])
        return list(history)[-limit:] if isinstance(history, list) else []

    def _record_message(self, key: str, message: str, keep: int = 5) -> None:
        if not message:
            return
        with get_connection() as conn:
            history = read_state(conn, f"insight_recent_messages:{key}", [])
            history = list(history) if isinstance(history, list) else []
            history.append(message)
            write_state(conn, f"insight_recent_messages:{key}", history[-keep:])

    # ── LLM-Formulierung ─────────────────────────────────────────

    @staticmethod
    def _llm_narrate(prompt: str, avoid: list[str] | None = None) -> str | None:
        try:
            from app.brain.llm_client import LLMRouter
            variety_hint = (
                "Variiere Wortwahl und Satzbau von Meldung zu Meldung — klinge nicht wie eine "
                "feste Vorlage, die nur die Zahlen austauscht. "
            )
            if avoid:
                examples = "\n".join(f"- {m}" for m in avoid[-3:])
                variety_hint += (
                    "Diese Formulierungen wurden für ein ähnliches Ereignis bereits verwendet — "
                    f"NICHT wiederholen, eine erkennbar andere Formulierung finden:\n{examples}\n"
                )
            result = LLMRouter().generate(
                {
                    "messages": [
                        {"role": "system", "content": (
                            "Du bist Erika, ein aufmerksamer Haushaltsassistent. Du beobachtest "
                            "selbständig Sensordaten und gibst hilfreiche, kurze Hinweise — freundlich, "
                            "mit einer Prise trockenem Humor, aber nicht übertrieben, da dies keine "
                            "Fehler- oder Alarmmeldungen sind, sondern beiläufige Beobachtungen. "
                            "Erfinde keine Zahlen oder Fakten, die nicht im Prompt genannt wurden, und "
                            "keine Gegenstände, Werkzeuge, Körperteile oder biologischen Handlungen, die "
                            "zu einem erwähnten Gerät nicht passen. "
                            f"{variety_hint}"
                            "Antworte ausschließlich auf Deutsch, kurz und natürlich."
                        )},
                        {"role": "user", "content": prompt},
                    ],
                    "llm_max_tokens": 60,
                },
                timeout_seconds=8,
            )
            text = (result.get("reply") or "").strip()
            return text or None
        except Exception:
            return None
