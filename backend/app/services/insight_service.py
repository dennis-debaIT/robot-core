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
        return self._llm_narrate(prompt) or fallback

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
        return self._llm_narrate(prompt) or fallback

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
        return self._llm_narrate(prompt) or fallback

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
            severity = robot_service._severity_for_state(entity_id, raw_state, config)

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
            message = self._llm_narrate(prompt) or fallback
            results.append({"entity_id": entity_id, "title": f"🤖 {label}", "message": message})

        return results

    # ── LLM-Formulierung ─────────────────────────────────────────

    @staticmethod
    def _llm_narrate(prompt: str) -> str | None:
        try:
            from app.brain.llm_client import LLMRouter
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
