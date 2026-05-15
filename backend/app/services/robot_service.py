from __future__ import annotations

import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database.db import get_connection
from app.services.homeassistant_service import HomeAssistantService


class RobotService:
    _HA_ERROR_LOOKBACK_DAYS = 2
    _NO_ERROR_STATES = {"kein fehler", "no_error", "none", "ok", "", "unknown", "unavailable"}
    _OK_STATUS_STATES = {"mowing", "docked", "charging", "idle", "paused", "returning", "returning_to_charge", "edgecut"}
    _WARN_ERROR_STATES = {"rain_delay", "rain_delayed"}
    _CRITICAL_ERROR_STATES = {
        "lifted",
        "lifted_during_mowing",
        "outside_wire",
        "wire_missing",
        "trapped",
        "blade_motor_blocked",
        "wheel_motor_blocked",
        "ultrasonic_sensor",
        "tilted",
        "battery_low",
        "battery_temp_low",
        "battery_temp_high",
        "no_home_signal",
        "obstacle",
    }
    _ROBOT_EXTRA_KEYS = [
        "batterie",
        "fehler",
        "ladevorgang",
        "taglicher_fortschritt",
        "verbleibende_regenverzogerung",
        "batterietemperatur",
        "batteriespannung",
        "gesamte_laufzeit_des_mahers",
        "signalstarke",
        "batterieladezyklen_gesamt",
        "total_cleaning_time",
        "total_cleaned_area",
        "state",
        "battery_level",
        "charging_status",
        "charging_state",
    ]
    _ERROR_TRANSLATIONS = {
        "lifted": "Angehoben",
        "trapped": "Blockiert",
        "wire_missing": "Begrenzungsdraht fehlt",
        "outside_wire": "Außerhalb Begrenzungsdraht",
        "rain_delay": "Regenverzögerung",
        "rain_delayed": "Regenverzögerung",
        "mowing": "Mähen",
        "docked": "In Basisstation",
        "charging": "Lädt",
        "idle": "Bereit",
        "paused": "Pausiert",
        "returning": "Kehrt zurück",
        "returning_to_charge": "Kehrt zur Basis zurück",
        "edgecut": "Kantenschnitt",
        "error": "Fehler",
        "seeking_charger": "Sucht Ladestation",
        "blade_motor_blocked": "Klingenmotor blockiert",
        "wheel_motor_blocked": "Radmotor blockiert",
        "ultrasonic_sensor": "Ultraschallsensor-Fehler",
        "tilted": "Gekippt",
        "battery_low": "Batterie schwach",
        "battery_temp_low": "Batterie zu kalt",
        "battery_temp_high": "Batterie zu heiß",
        "no_home_signal": "Kein Heimatsignal",
        "obstacle": "Hindernis erkannt",
        "lifted_during_mowing": "Angehoben während Mähens",
    }
    _LAWN_COMMANDS = {"start_mowing", "dock", "pause"}
    _VACUUM_COMMANDS = {"start", "pause", "stop", "return_to_base", "clean_spot"}

    def __init__(self, ha: HomeAssistantService | None = None) -> None:
        self.ha = ha or HomeAssistantService()

    def _normalize_error_state(self, state: str) -> str:
        normalized = (state or "").strip().lower()
        return "rain_delay" if normalized == "rain_delayed" else normalized

    def _translate_error_state(self, state: str) -> str:
        normalized = self._normalize_error_state(state)
        explicit = {
            "no_error": "Kein Fehler",
            "rain_delay": "Regenverzögerung",
            "outside_wire": "Außerhalb Begrenzungsdraht",
            "lifted_during_mowing": "Angehoben während Mähens",
            "upside_down": "Mäher liegt auf dem Kopf",
        }
        if normalized in explicit:
            return explicit[normalized]
        return self._ERROR_TRANSLATIONS.get(state, self._ERROR_TRANSLATIONS.get(normalized, state))

    def _robot_state_rules(self, config: dict[str, Any] | None, entity_id: str) -> dict[str, set[str]]:
        mapping = (((config or {}).get("robots") or {}).get("state_mappings") or {}).get(entity_id) or {}

        def _state_set(key: str, defaults: set[str]) -> set[str]:
            values = mapping.get(key)
            if not isinstance(values, list):
                return set(defaults)
            normalized = {self._normalize_error_state(str(item)) for item in values if str(item).strip()}
            return normalized or set(defaults)

        return {
            "no_error": _state_set("no_error_states", self._NO_ERROR_STATES),
            "ok": _state_set("ok_states", self._OK_STATUS_STATES),
            "warn": _state_set("warn_states", self._WARN_ERROR_STATES),
            "critical": _state_set("critical_states", self._CRITICAL_ERROR_STATES),
        }

    def _severity_for_state(self, entity_id: str, raw_state: str, config: dict[str, Any] | None = None) -> str:
        normalized = self._normalize_error_state(raw_state)
        rules = self._robot_state_rules(config, entity_id)
        if normalized in rules["no_error"]:
            return "hidden"
        if normalized in rules["warn"]:
            return "warning"
        if normalized in rules["critical"] or normalized == "error":
            return "error"
        if normalized in rules["ok"]:
            return "ok"
        return "error"

    def _store_error_entry(
        self,
        entity_id: str,
        source_entity_id: str,
        raw_state: str,
        when: str,
        source: str,
    ) -> None:
        normalized = self._normalize_error_state(raw_state)
        if normalized in self._NO_ERROR_STATES or not when:
            return
        label = self._translate_error_state(raw_state)
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO robot_error_history(
                    entity_id, source_entity_id, raw_state, label, occurred_at, source, imported_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity_id,
                    source_entity_id,
                    normalized,
                    label,
                    when,
                    source,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def _record_current_errors(
        self,
        entity_id: str,
        base_state: str,
        base_last_changed: str,
        extras: dict[str, dict[str, Any]],
    ) -> None:
        error_extra = extras.get("fehler") or {}
        error_state = (error_extra.get("state") or "").strip()
        error_changed = error_extra.get("last_changed") or base_last_changed
        if error_state:
            self._store_error_entry(
                entity_id,
                f"sensor.{entity_id.split('.', 1)[-1]}_fehler",
                error_state,
                error_changed,
                "ha_sensor",
            )
            return

        normalized_base = self._normalize_error_state(base_state)
        if normalized_base in self._WARN_ERROR_STATES or normalized_base in self._CRITICAL_ERROR_STATES:
            self._store_error_entry(entity_id, entity_id, base_state, base_last_changed, "ha_state")

    def _sync_error_history_from_ha(self, entity_id: str) -> None:
        robot_name = entity_id.split(".", 1)[-1]
        sensor_entity_id = f"sensor.{robot_name}_fehler"
        since = urllib.parse.quote(
            (datetime.now(timezone.utc) - timedelta(days=self._HA_ERROR_LOOKBACK_DAYS)).isoformat(),
            safe="",
        )
        params = urllib.parse.urlencode(
            {
                "filter_entity_id": sensor_entity_id,
                "minimal_response": "true",
                "no_attributes": "true",
            }
        )
        raw = self.ha.get_history(f"/history/period/{since}?{params}") or []
        history: list[dict[str, Any]] = raw[0] if raw else []
        for item in history:
            state = (item.get("state") or "").strip()
            when = item.get("last_changed", "")
            if not when:
                continue
            self._store_error_entry(entity_id, sensor_entity_id, state, when, "ha_history")

        logbook_raw = self.ha.get_history(f"/logbook/{since}") or []
        if isinstance(logbook_raw, list):
            for item in logbook_raw:
                if (item.get("entity_id") or "") != sensor_entity_id:
                    continue
                state = (item.get("state") or "").strip()
                when = item.get("when", "")
                if not when:
                    continue
                self._store_error_entry(entity_id, sensor_entity_id, state, when, "ha_logbook")

    def bootstrap_error_history(self) -> None:
        robots = self.list_robots()
        for robot in robots:
            if robot.get("domain") != "lawn_mower":
                continue
            self._sync_error_history_from_ha(robot["entity_id"])

    def _read_local_error_history(
        self,
        entity_id: str,
        limit: int = 20,
        config: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT occurred_at, label, raw_state
                FROM robot_error_history
                WHERE entity_id = ?
                ORDER BY occurred_at DESC
                LIMIT ?
                """,
                (entity_id, limit),
            ).fetchall()
        entries = [
            {
                "when": row["occurred_at"],
                "state": self._translate_error_state(row["raw_state"]),
                "raw_state": row["raw_state"],
                "severity": self._severity_for_state(entity_id, row["raw_state"], config),
            }
            for row in rows
        ]
        return [entry for entry in entries if entry["severity"] != "hidden"]

    def list_robots(self) -> list[dict[str, Any]]:
        return self.list_robots_with_config(None)

    def list_robots_with_config(self, config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        states = self.ha.get_states()
        robots_config = (config or {}).get("robots") or {}
        all_sensors = {
            state.get("entity_id", ""): state
            for state in states
            if state.get("entity_id", "").startswith(("sensor.", "binary_sensor."))
        }

        all_sensor_ids = set(all_sensors.keys())

        robots: list[dict[str, Any]] = []
        for state in states:
            entity_id = state.get("entity_id", "")
            if not entity_id.startswith(("lawn_mower.", "vacuum.")):
                continue

            attrs = state.get("attributes", {})
            raw_slug = entity_id.split(".", 1)[-1]
            robot_name = self._resolve_robot_slug(raw_slug, all_sensor_ids)
            extras = self._collect_extras(robot_name, all_sensors)
            battery = self._resolve_battery(attrs, extras)
            name = self._display_name(attrs.get("friendly_name", robot_name))
            robot_state = self._resolve_state(entity_id, state.get("state", "unknown"), extras, config)
            self._record_current_errors(
                entity_id,
                state.get("state", "unknown"),
                state.get("last_changed", ""),
                extras,
            )
            vacuum_cfg = (robots_config.get("vacuum_configs") or {}).get(entity_id) or {}
            robots.append(
                {
                    "entity_id": entity_id,
                    "sensor_slug": robot_name,  # aufgelöster Prefix für Sensor-Lookups
                    "domain": entity_id.split(".")[0],
                    "name": name,
                    "state": robot_state,
                    "battery": battery,
                    "extras": extras,
                    "last_changed": state.get("last_changed", ""),
                    "attributes": attrs,
                    "config": vacuum_cfg,
                }
            )

        all_entity_ids = {state.get("entity_id", "") for state in states}
        for robot in robots:
            slug = robot["entity_id"].split(".", 1)[-1]
            robot["_score"] = sum(1 for entity_id in all_entity_ids if slug in entity_id)

        seen: dict[str, dict[str, Any]] = {}
        for robot in sorted(robots, key=lambda item: item.get("_score", 0)):
            seen[robot["name"]] = robot
        result = sorted(seen.values(), key=lambda item: item["name"].lower())
        if config is not None:
            if robots_config.get("enabled") is False:
                return []
            selected = [str(item) for item in robots_config.get("selected_entities") or [] if str(item)]
            if selected:
                selected_set = set(selected)
                result = [robot for robot in result if robot.get("entity_id") in selected_set]
        return result

    def get_error_log(self, entity_id: str, config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        robot_name = entity_id.split(".", 1)[-1]
        sensor_entity_id = f"sensor.{robot_name}_fehler"
        self._sync_error_history_from_ha(entity_id)

        mower_state = self.ha.get_state(entity_id)
        if isinstance(mower_state, dict):
            self._store_error_entry(
                entity_id,
                entity_id,
                (mower_state.get("state") or "").strip(),
                mower_state.get("last_changed", ""),
                "ha_state",
            )

        sensor_state = self.ha.get_state(sensor_entity_id)
        if isinstance(sensor_state, dict):
            self._store_error_entry(
                entity_id,
                sensor_entity_id,
                (sensor_state.get("state") or "").strip(),
                sensor_state.get("last_changed", ""),
                "ha_sensor",
            )

        return self._read_local_error_history(entity_id, limit=20, config=config)

    def command(self, entity_id: str, command: str) -> dict[str, Any]:
        domain = entity_id.split(".")[0]
        allowed = self._LAWN_COMMANDS if domain == "lawn_mower" else self._VACUUM_COMMANDS
        if command not in allowed:
            raise ValueError(f"Unbekannter Befehl: {command}")
        ok = self.ha.call_service(domain, command, {"entity_id": entity_id})
        return {"ok": ok, "entity_id": entity_id, "command": command}

    def clean_segments(self, body: dict[str, Any]) -> dict[str, Any]:
        entity_id = body.get("entity_id", "vacuum.krumel_knecht")
        segments = body.get("segments", [])
        mode_option    = body.get("cleaning_mode_option", "")
        cleaning_times = int(body.get("cleaning_times") or 1)
        if not segments:
            raise ValueError("Keine Räume ausgewählt")

        raw_slug = entity_id.split(".", 1)[-1]
        states = self.ha.get_states()
        state_map = {s.get("entity_id", ""): s for s in states}
        slug = self._resolve_robot_slug(raw_slug, set(state_map.keys()))

        if mode_option:
            self.ha.call_service(
                "select",
                "select_option",
                {"entity_id": f"select.{slug}_cleaning_mode", "option": mode_option},
            )
            time.sleep(2)

        service_data: dict[str, Any] = {
            "entity_id": entity_id,
            "segments":  segments,
        }
        if cleaning_times > 1:
            service_data["repeats"] = cleaning_times

        ok = self.ha.call_service("dreame_vacuum", "vacuum_clean_segment", service_data)
        return {"ok": ok, "segments": segments, "mode": mode_option}

    def detect_vacuum_config(self, entity_id: str) -> dict[str, Any]:
        """Liest Räume, Kamera und Modi automatisch aus HA-Entities."""
        import re as _re

        raw_slug = entity_id.split(".", 1)[-1]
        states = self.ha.get_states()
        state_map = {s.get("entity_id", ""): s for s in states}

        slug = self._resolve_robot_slug(raw_slug, set(state_map.keys()))

        # Räume: select.{slug}_room_N_name
        rooms: list[dict[str, Any]] = []
        for eid, s in state_map.items():
            m = _re.match(rf"select\.{_re.escape(slug)}_room_(\d+)_name$", eid)
            if not m:
                continue
            room_id = int(m.group(1))
            name = (s.get("state") or "").strip()
            if state_map.get(f"select.{slug}_room_{room_id}_visibility", {}).get("state") == "invisible":
                continue
            if name and name not in ("unknown", "unavailable"):
                rooms.append({"id": room_id, "name": name})
        rooms.sort(key=lambda r: r["id"])

        # Kamera
        map_camera = ""
        for candidate in [f"camera.{slug}_map", f"camera.{slug}_current_map"]:
            if candidate in state_map:
                map_camera = candidate
                break

        # Modi
        _MODE_DEFAULTS: dict[str, dict[str, Any]] = {
            "sweeping":               {"label": "🧹 Nur saugen",              "suction_level": 3, "water_volume": 0},
            "mopping":                {"label": "💧 Nur wischen",             "suction_level": 0, "water_volume": 3},
            "sweeping_and_mopping":   {"label": "🧹+💧 Saugen & Wischen",     "suction_level": 3, "water_volume": 3},
            "sweeping_then_mopping":  {"label": "🧹→💧 Saugen, dann Wischen", "suction_level": 3, "water_volume": 3},
            "mopping_after_sweeping": {"label": "🧹→💧 Wischen nach Saugen",  "suction_level": 3, "water_volume": 3},
        }

        # 1. Versuch: globaler cleaning_mode Select
        raw_options: list[str] = []
        mode_select = state_map.get(f"select.{slug}_cleaning_mode")
        if mode_select:
            raw_options = mode_select.get("attributes", {}).get("options") or []

        # 2. Fallback: eindeutige Werte aus per-Raum cleaning_mode Selects
        if not raw_options:
            seen: set[str] = set()
            for eid, s in state_map.items():
                if not _re.match(rf"select\.{_re.escape(slug)}_room_\d+_cleaning_mode$", eid):
                    continue
                opt = (s.get("state") or "").strip()
                if opt and opt not in ("unknown", "unavailable") and opt not in seen:
                    seen.add(opt)
                    raw_options.append(opt)

        modes: list[dict[str, Any]] = []
        for opt in raw_options:
            key = opt.lower().replace(" ", "_")
            defaults = _MODE_DEFAULTS.get(key, {})
            modes.append({
                "key":                  key,
                "label":                defaults.get("label", opt),
                "cleaning_mode_option": opt,
                "suction_level":        defaults.get("suction_level", 3),
                "water_volume":         defaults.get("water_volume", 0),
            })

        return {
            "entity_id":    entity_id,
            "slug":         slug,
            "map_camera":   map_camera,
            "rooms":        rooms,
            "modes":        modes,
            "default_mode": modes[0]["key"] if modes else "",
        }

    def get_robot_sensors(self, robot_name: str) -> dict[str, dict[str, Any]]:
        states = self.ha.get_states()
        all_ids = {s.get("entity_id", "") for s in states}
        slug = self._resolve_robot_slug(robot_name, all_ids)
        sensors: dict[str, dict[str, Any]] = {}
        selects: dict[str, dict[str, Any]] = {}
        for state in states:
            entity_id = state.get("entity_id", "")
            if not entity_id.startswith(("sensor.", "select.")):
                continue
            if not entity_id.startswith((f"sensor.{slug}_", f"select.{slug}_")):
                continue
            attrs = state.get("attributes", {})
            entry = {
                "state": state.get("state", ""),
                "unit": attrs.get("unit_of_measurement", ""),
                "name": attrs.get("friendly_name", entity_id),
                "options": attrs.get("options", []),
            }
            if entity_id.startswith("sensor."):
                sensors[entity_id] = entry
            else:
                selects[entity_id] = entry
        return {"sensors": sensors, "selects": selects}

    @staticmethod
    def _resolve_robot_slug(raw_slug: str, all_entity_ids: set[str]) -> str:
        """vacuum.carsten_carsten hat Entities mit Prefix 'carsten', nicht 'carsten_carsten'.
        Probiert progressiv kürzere Prefixe bis einer auf tatsächliche Entities passt."""
        parts = raw_slug.split("_")
        for length in range(len(parts), 0, -1):
            candidate = "_".join(parts[:length])
            if (any(eid.startswith(f"sensor.{candidate}_") for eid in all_entity_ids)
                    or any(eid.startswith(f"select.{candidate}_room_") for eid in all_entity_ids)
                    or f"camera.{candidate}_map" in all_entity_ids):
                return candidate
        return raw_slug

    def _collect_extras(
        self,
        robot_name: str,
        all_sensors: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        extras: dict[str, dict[str, Any]] = {}
        for key in self._ROBOT_EXTRA_KEYS:
            for prefix in (f"sensor.{robot_name}", f"binary_sensor.{robot_name}"):
                sensor_data = all_sensors.get(f"{prefix}_{key}")
                if not sensor_data:
                    continue
                raw = (sensor_data.get("state") or "").strip()
                if raw in ("unavailable", "unknown", ""):
                    break
                attrs = sensor_data.get("attributes", {})
                extras[key] = {
                    "state": raw,
                    "unit": attrs.get("unit_of_measurement", ""),
                    "name": attrs.get("friendly_name", key),
                    "last_changed": sensor_data.get("last_changed", ""),
                }
                break
        return extras

    @staticmethod
    def _resolve_battery(attrs: dict[str, Any], extras: dict[str, dict[str, Any]]) -> float | int | None:
        battery = attrs.get("battery_level") or attrs.get("battery")
        for key in ("batterie", "battery_level"):
            if battery is None and key in extras:
                try:
                    battery = float(extras[key]["state"])
                except ValueError:
                    pass
        return battery

    @staticmethod
    def _display_name(raw_name: str) -> str:
        words = raw_name.split()
        midpoint = len(words) // 2
        if len(words) >= 2 and len(words) % 2 == 0 and words[:midpoint] == words[midpoint:]:
            return " ".join(words[:midpoint])
        return raw_name

    def _resolve_state(
        self,
        entity_id: str,
        base_state: str,
        extras: dict[str, dict[str, Any]],
        config: dict[str, Any] | None = None,
    ) -> str:
        robot_state = base_state
        detailed_state = (extras.get("state", {}).get("state") or "").strip().lower()
        if entity_id.startswith("vacuum.") and detailed_state not in ("", "unknown", "unavailable"):
            robot_state = detailed_state

        rules = self._robot_state_rules(config, entity_id)
        error_state = self._normalize_error_state(extras.get("fehler", {}).get("state") or "")
        if error_state in rules["warn"]:
            return error_state
        if error_state in rules["critical"]:
            return "error"
        if error_state and error_state not in rules["no_error"]:
            return "error"
        return robot_state
