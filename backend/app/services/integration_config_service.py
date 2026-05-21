from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.database.db import get_connection, read_state, write_state
from app.services.ev_service import EvService
from app.services.fuel_service import FuelService
from app.services.homeassistant_service import HomeAssistantService
from app.services.homeassistant_runtime_config_service import HomeAssistantRuntimeConfigService
from app.services.light_service import LightService
from app.services.news_feed_service import NewsFeedService
from app.services.robot_service import RobotService
from app.services.vehicle_service import VehicleService


class IntegrationConfigService:
    state_key = "local_admin_integration_config"

    def __init__(
        self,
        ha: HomeAssistantService | None = None,
        lights: LightService | None = None,
        robots: RobotService | None = None,
    ) -> None:
        self.ha = ha or HomeAssistantService()
        self.lights = lights or LightService(self.ha)
        self.robots = robots or RobotService(self.ha)

    def ensure_runtime_state(self) -> None:
        with get_connection() as conn:
            existing = conn.execute("SELECT 1 FROM system_state WHERE key = ?", (self.state_key,)).fetchone()
            if not existing:
                write_state(conn, self.state_key, self.default_config())

    def default_config(self) -> dict[str, Any]:
        news_feeds = NewsFeedService()
        return {
            "lights": {"enabled": True, "selected_entities": []},
            "robots": {"enabled": True, "selected_entities": [], "state_mappings": {}, "vacuum_configs": {}},
            "news": {
                "enabled": False,
                "lookback_hours": 6,
                "selected_sources": [],
                "default_collapsed": False,
                "collapsed_count": 3,
            },
            "fuel_prices": {
                "enabled": True,
                "fuel_types": ["diesel"],
                "selected_station_id": "",
                "selected_entities": [],
            },
            "system": {
                "home_assistant": HomeAssistantRuntimeConfigService.default_config(),
                "site": {
                    "location": "Ostenfeld",
                },
            },
            "weather": {
                "enabled": True,
                "hourly_past_hours": 0,
                "hourly_future_hours": 5,
                "show_feels_like": True,
                "show_wind": True,
                "show_humidity": True,
                "show_precipitation": True,
                "show_minmax": True,
                "show_hourly": True,
            },
            "ev": {
                "enabled": True,
                "vehicles": [],
            },
            "vehicles": {
                "enabled": True,
                "location_history_days": 14,
                "poll_seconds": 30,
                "items": [],
            },
            "cameras": {"enabled": True, "selected_entities": [], "camera_configs": {}},
            "calendar": {
                "enabled": True,
                "days_count": 7,
                "selected_calendars": [],
                "colors": {},
                "open_trigger": "both",
            },
            "attention": {
                "wake_word_enabled": True,
                "wake_word": "erika",
                "face_recognition_enabled": False,
            },
            "printer": {
                "enabled":        False,
                "printer_ip":     "",
                "mqtt_user":      "",
                "mqtt_pass":      "",
                "entity_prefix":  "anycubic_kobra_s1",
                "entity_overrides": {},
            },
            "pv": {
                "enabled": False,
                "provider": "solarman",
                "sensors": {
                    "power":       "sensor.solarman_total_ac_output_power_active",
                    "daily":       "sensor.solarman_daily_production",
                    "temperature": "sensor.solarman_radiator_temperature",
                    "last_update": "sensor.solarman_status_lastupdate",
                },
            },
            "meta": {
                "version": 1,
            },
        }

    def get_config(self) -> dict[str, Any]:
        self.ensure_runtime_state()
        with get_connection() as conn:
            current = read_state(conn, self.state_key, self.default_config())
        current_vehicle_items = (current.get("vehicles") or {}).get("items") if isinstance(current, dict) else None
        current_weather = current.get("weather") if isinstance(current, dict) else None
        current_system_weather = (current.get("system") or {}).get("weather") if isinstance(current, dict) else None
        merged = self._merge_dicts(self.default_config(), current)
        news = merged.setdefault("news", {})
        if "item_count" in news and "lookback_hours" not in news:
            news["lookback_hours"] = news.pop("item_count")
        else:
            news.pop("item_count", None)
        news["lookback_hours"] = self._sanitize_news_lookback_hours(news.get("lookback_hours", 6))
        news["selected_sources"] = self._sanitize_news_selected_sources(news.get("selected_sources"))
        news["default_collapsed"] = bool(news.get("default_collapsed", False))
        news["collapsed_count"] = self._sanitize_news_collapsed_count(news.get("collapsed_count", 3))
        lights_config = merged.setdefault("lights", {})
        lights_config["enabled"] = bool(lights_config.get("enabled", True))
        lights_config["selected_entities"] = self._sanitize_string_list(lights_config.get("selected_entities"))
        robots_config = merged.setdefault("robots", {})
        robots_config["enabled"] = bool(robots_config.get("enabled", True))
        robots_config["selected_entities"] = self._sanitize_string_list(robots_config.get("selected_entities"))
        robots_config["state_mappings"] = self._sanitize_robot_state_mappings(robots_config.get("state_mappings"))
        robots_config["vacuum_configs"] = self._sanitize_vacuum_configs(robots_config.get("vacuum_configs"))
        fuel = merged.setdefault("fuel_prices", {})
        fuel["enabled"] = bool(fuel.get("enabled", True))
        fuel["fuel_types"] = self._sanitize_fuel_types(fuel.get("fuel_types"))
        fuel["selected_station_id"] = str(fuel.get("selected_station_id") or "").strip()
        fuel["selected_station_id"] = fuel["selected_station_id"] or self._default_fuel_station_id()
        fuel["selected_entities"] = self._sanitize_string_list(fuel.get("selected_entities"))
        fuel["fuel_assignments"] = self._sanitize_fuel_assignments(fuel.get("fuel_assignments"))
        system = merged.setdefault("system", {})
        system["home_assistant"] = HomeAssistantRuntimeConfigService.sanitize(system.get("home_assistant"))
        system["site"] = self._sanitize_site_config(system.get("site"))
        weather_source = current_weather or current_system_weather or merged.get("weather") or system.get("weather")
        merged["weather"] = self._sanitize_weather_config(weather_source)
        system.pop("weather", None)
        ev = merged.setdefault("ev", {})
        ev["enabled"] = bool(ev.get("enabled", True))
        ev["vehicles"] = self._sanitize_ev_vehicles(ev.get("vehicles"))
        vehicles = merged.setdefault("vehicles", {})
        vehicles["enabled"] = bool(vehicles.get("enabled", True))
        vehicles["location_history_days"] = self._sanitize_vehicle_history_days(vehicles.get("location_history_days", 14))
        vehicles["poll_seconds"] = self._sanitize_vehicle_poll_seconds(vehicles.get("poll_seconds", 30))
        if not current_vehicle_items and ev["vehicles"]:
            vehicles["items"] = [VehicleService.from_ev_vehicle(item) for item in ev["vehicles"]]
        vehicles["items"] = self._sanitize_vehicles(vehicles.get("items"), ev["vehicles"])
        cameras_config = merged.setdefault("cameras", {})
        cameras_config["enabled"] = bool(cameras_config.get("enabled", True))
        cameras_config["selected_entities"] = self._sanitize_string_list(cameras_config.get("selected_entities"))
        cameras_config["camera_configs"] = self._sanitize_camera_configs(cameras_config.get("camera_configs"))
        calendar = merged.setdefault("calendar", {})
        calendar["enabled"] = bool(calendar.get("enabled", True))
        calendar["days_count"] = max(1, min(30, int(calendar.get("days_count") or 7)))
        calendar["selected_calendars"] = self._sanitize_string_list(calendar.get("selected_calendars"))
        calendar["colors"] = {k: str(v) for k, v in (calendar.get("colors") or {}).items()}
        calendar["open_trigger"] = calendar.get("open_trigger") if calendar.get("open_trigger") in ("nav", "widget", "both") else "both"
        printer = merged.setdefault("printer", {})
        printer["enabled"]       = bool(printer.get("enabled", False))
        printer["printer_ip"]    = str(printer.get("printer_ip") or "").strip()
        printer["mqtt_user"]     = str(printer.get("mqtt_user") or "").strip()
        printer["mqtt_pass"]     = str(printer.get("mqtt_pass") or "")
        printer["entity_prefix"] = str(printer.get("entity_prefix") or "anycubic_kobra_s1").strip()
        printer.setdefault("entity_overrides", {})
        pv = merged.setdefault("pv", {})
        pv["enabled"] = bool(pv.get("enabled", False))
        pv["provider"] = str(pv.get("provider") or "solarman").strip()
        pv_sensors = pv.setdefault("sensors", {})
        for _k in ("power", "daily", "temperature", "last_update"):
            pv_sensors[_k] = str(pv_sensors.get(_k) or "").strip()
        meta = merged.setdefault("meta", {})
        meta["version"] = self._sanitize_config_version(meta.get("version", 1))
        return merged

    def update_config(self, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.get_config()
        updated = self._merge_dicts(current, patch)
        news = updated.setdefault("news", {})
        if "item_count" in news and "lookback_hours" not in news:
            news["lookback_hours"] = news.pop("item_count")
        else:
            news.pop("item_count", None)
        news["lookback_hours"] = self._sanitize_news_lookback_hours(news.get("lookback_hours", 6))
        news["selected_sources"] = self._sanitize_news_selected_sources(news.get("selected_sources"))
        news["default_collapsed"] = bool(news.get("default_collapsed", False))
        news["collapsed_count"] = self._sanitize_news_collapsed_count(news.get("collapsed_count", 3))
        lights_config = updated.setdefault("lights", {})
        lights_config["enabled"] = bool(lights_config.get("enabled", True))
        lights_config["selected_entities"] = self._sanitize_string_list(lights_config.get("selected_entities"))
        robots_config = updated.setdefault("robots", {})
        robots_config["enabled"] = bool(robots_config.get("enabled", True))
        robots_config["selected_entities"] = self._sanitize_string_list(robots_config.get("selected_entities"))
        robots_config["state_mappings"] = self._sanitize_robot_state_mappings(robots_config.get("state_mappings"))
        fuel = updated.setdefault("fuel_prices", {})
        fuel["enabled"] = bool(fuel.get("enabled", True))
        fuel["fuel_types"] = self._sanitize_fuel_types(fuel.get("fuel_types"))
        fuel["selected_station_id"] = str(fuel.get("selected_station_id") or "").strip()
        fuel["selected_entities"] = self._sanitize_string_list(fuel.get("selected_entities"))
        fuel["fuel_assignments"] = self._sanitize_fuel_assignments(fuel.get("fuel_assignments"))
        system = updated.setdefault("system", {})
        system["home_assistant"] = HomeAssistantRuntimeConfigService.sanitize(system.get("home_assistant"))
        system["site"] = self._sanitize_site_config(system.get("site"))
        weather_source = updated.get("weather") or system.get("weather")
        updated["weather"] = self._sanitize_weather_config(weather_source)
        system.pop("weather", None)
        ev = updated.setdefault("ev", {})
        ev["enabled"] = bool(ev.get("enabled", True))
        ev["vehicles"] = self._sanitize_ev_vehicles(ev.get("vehicles"))
        vehicles = updated.setdefault("vehicles", {})
        vehicles["enabled"] = bool(vehicles.get("enabled", True))
        vehicles["location_history_days"] = self._sanitize_vehicle_history_days(vehicles.get("location_history_days", 14))
        vehicles["poll_seconds"] = self._sanitize_vehicle_poll_seconds(vehicles.get("poll_seconds", 30))
        vehicles["items"] = self._sanitize_vehicles(vehicles.get("items"), ev["vehicles"])
        cameras_config = updated.setdefault("cameras", {})
        cameras_config["enabled"] = bool(cameras_config.get("enabled", True))
        cameras_config["selected_entities"] = self._sanitize_string_list(cameras_config.get("selected_entities"))
        cameras_config["camera_configs"] = self._sanitize_camera_configs(cameras_config.get("camera_configs"))
        calendar = updated.setdefault("calendar", {})
        calendar["enabled"] = bool(calendar.get("enabled", True))
        calendar["days_count"] = max(1, min(30, int(calendar.get("days_count") or 7)))
        calendar["selected_calendars"] = self._sanitize_string_list(calendar.get("selected_calendars"))
        calendar["colors"] = {k: str(v) for k, v in (calendar.get("colors") or {}).items()}
        calendar["open_trigger"] = calendar.get("open_trigger") if calendar.get("open_trigger") in ("nav", "widget", "both") else "both"
        printer2 = updated.setdefault("printer", {})
        printer2["enabled"]       = bool(printer2.get("enabled", False))
        printer2["printer_ip"]    = str(printer2.get("printer_ip") or "").strip()
        printer2["mqtt_user"]     = str(printer2.get("mqtt_user") or "").strip()
        printer2["mqtt_pass"]     = str(printer2.get("mqtt_pass") or "")
        printer2["entity_prefix"] = str(printer2.get("entity_prefix") or "anycubic_kobra_s1").strip()
        printer2.setdefault("entity_overrides", {})
        pv = updated.setdefault("pv", {})
        pv["enabled"] = bool(pv.get("enabled", False))
        pv["provider"] = str(pv.get("provider") or "solarman").strip()
        pv_sensors = pv.setdefault("sensors", {})
        for _k in ("power", "daily", "temperature", "last_update"):
            pv_sensors[_k] = str(pv_sensors.get(_k) or "").strip()
        meta = updated.setdefault("meta", {})
        meta["version"] = self._sanitize_config_version(current.get("meta", {}).get("version", 1)) + 1
        with get_connection() as conn:
            write_state(conn, self.state_key, updated)
        return updated

    def get_news_lookback_hours(self) -> int:
        config = self.get_config()
        news = config.get("news", {})
        if "lookback_hours" in news:
            return self._sanitize_news_lookback_hours(news.get("lookback_hours", 6))
        return self._sanitize_news_lookback_hours(news.get("item_count", 6))

    def get_news_selected_sources(self) -> list[str]:
        config = self.get_config()
        return self._sanitize_news_selected_sources(config.get("news", {}).get("selected_sources"))

    def get_news_display_settings(self) -> dict[str, Any]:
        news = self.get_config().get("news", {})
        return {
            "default_collapsed": bool(news.get("default_collapsed", False)),
            "collapsed_count": self._sanitize_news_collapsed_count(news.get("collapsed_count", 3)),
        }

    def get_site_location(self) -> str:
        config = self.get_config()
        location = ((config.get("system") or {}).get("site") or {}).get("location")
        return str(location or "Ostenfeld").strip() or "Ostenfeld"

    def get_weather_config(self) -> dict[str, Any]:
        config = self.get_config()
        return self._sanitize_weather_config(config.get("weather") or ((config.get("system") or {}).get("weather") or {}))

    def get_catalog(self) -> dict[str, Any]:
        lights = [
            {
                "entity_id": item["entity_id"],
                "name": item["name"],
                "is_group": item["is_group"],
                "supports_brightness": item["supports_brightness"],
            }
            for item in self.lights.list_lights()
        ]
        robots = [
            {
                "entity_id": item["entity_id"],
                "name": item["name"],
                "domain": item["domain"],
                "state": item["state"],
            }
            for item in self.robots.list_robots()
        ]
        cameras = []
        for state in self.ha.get_states():
            entity_id = state.get("entity_id", "")
            if not entity_id.startswith("camera."):
                continue
            attrs = state.get("attributes", {})
            cameras.append(
                {
                    "entity_id": entity_id,
                    "name": attrs.get("friendly_name", entity_id),
                    "state": state.get("state", "unknown"),
                }
            )

        return {
            "capabilities": [
                {
                    "key": "lights",
                    "label": "Lichter",
                    "provider": "home_assistant",
                    "selection_mode": "entities",
                },
                {
                    "key": "robots",
                    "label": "Roboter",
                    "provider": "home_assistant",
                    "selection_mode": "entities",
                },
                {
                    "key": "news",
                    "label": "News",
                    "provider": "rss",
                    "selection_mode": "settings",
                },
                {
                    "key": "weather",
                    "label": "Wetter",
                    "provider": "open_meteo",
                    "selection_mode": "settings",
                },
                {
                    "key": "fuel_prices",
                    "label": "Kraftstoffpreise",
                    "provider": "home_assistant",
                    "selection_mode": "entities_and_options",
                    "options": FuelService().type_options(),
                },
                {
                    "key": "cameras",
                    "label": "Kameras",
                    "provider": "home_assistant",
                    "selection_mode": "entities",
                },
                {
                    "key": "ev",
                    "label": "E-Autos",
                    "provider": "home_assistant",
                    "selection_mode": "custom_bindings",
                },
                {
                    "key": "vehicles",
                    "label": "Fahrzeuge",
                    "provider": "home_assistant",
                    "selection_mode": "custom_bindings",
                },
            ],
            "entities": {
                "lights": lights,
                "news_sources": NewsFeedService().list_catalog(),
                "robots": robots,
                "fuel_type_options": FuelService().type_options(),
                "fuel_stations": FuelService(self.ha).station_catalog(),
                "fuel_prices": self._discover_fuel_entities(),
                "cameras": sorted(cameras, key=lambda item: item["name"].lower()),
                "ev": {
                    "field_options": EvService(self.ha).field_options(),
                    "default_vehicle": EvService.default_vehicle(),
                },
                "vehicles": {
                    "field_options": self._vehicle_field_options(),
                    "default_vehicle": VehicleService.default_vehicle(),
                },
                "system": {
                    "home_assistant": {
                        "defaults": HomeAssistantRuntimeConfigService.to_public_payload(),
                        "token_required": True,
                    },
                    "site": {
                        "default_location": "Ostenfeld",
                    },
                },
            },
        }

    def _discover_fuel_entities(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for state in self.ha.get_states():
            entity_id = (state.get("entity_id") or "").lower()
            if not entity_id.startswith("sensor."):
                continue
            attrs = state.get("attributes", {})
            unit = str(attrs.get("unit_of_measurement", "")).lower()
            name = attrs.get("friendly_name", entity_id)
            if (
                "€" not in unit
                and "eur" not in unit
                and "diesel" not in entity_id
                and "e10" not in entity_id
                and "super" not in entity_id
            ):
                continue
            result.append(
                {
                    "entity_id": state.get("entity_id", entity_id),
                    "name": name,
                    "state": state.get("state", ""),
                    "unit": attrs.get("unit_of_measurement", ""),
                }
            )
        return sorted(result, key=lambda item: item["name"].lower())

    def _vehicle_field_options(self) -> dict[str, list[dict[str, Any]]]:
        location_options: list[dict[str, Any]] = []
        sensor_options: list[dict[str, Any]] = []
        button_options: list[dict[str, Any]] = []
        for state in self.ha.get_states():
            entity_id = state.get("entity_id", "")
            attrs = state.get("attributes", {})
            domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
            option = {
                "entity_id": entity_id,
                "name": attrs.get("friendly_name", entity_id),
                "state": state.get("state", ""),
                "domain": domain,
                "unit": attrs.get("unit_of_measurement", ""),
            }
            if attrs.get("latitude") is not None and attrs.get("longitude") is not None:
                location_options.append(option)
            if domain == "device_tracker":
                location_options.append(option)
            if domain in ("sensor", "binary_sensor"):
                sensor_options.append(option)
            if domain == "button":
                button_options.append(option)
        sort_key = lambda item: (item["domain"], item["name"].lower())
        return {
            "location_entity": sorted(location_options, key=sort_key),
            "odometer_entity": sorted(sensor_options, key=sort_key),
            "activity_entity": sorted(sensor_options, key=sort_key),
            "battery_entity": sorted(sensor_options, key=sort_key),
            "range_entity": sorted(sensor_options, key=sort_key),
            "fuel_level_entity": sorted(sensor_options, key=sort_key),
            "adblue_level_entity": sorted(sensor_options, key=sort_key),
            "charging_entity": sorted(sensor_options, key=sort_key),
            "remaining_charge_time_entity": sorted(sensor_options, key=sort_key),
            "stop_charging_button_entity": sorted(button_options, key=sort_key),
            "climate_button_entity": sorted(button_options, key=sort_key),
        }

    def _default_fuel_station_id(self) -> str:
        stations = FuelService(self.ha).station_catalog()
        return str(stations[0]["id"]) if stations else ""

    @staticmethod
    def _sanitize_news_lookback_hours(value: Any) -> int:
        try:
            hours = int(value)
        except (TypeError, ValueError):
            hours = 6
        return max(1, min(hours, 24))

    @staticmethod
    def _sanitize_news_collapsed_count(value: Any) -> int:
        try:
            count = int(value)
        except (TypeError, ValueError):
            count = 3
        return max(1, min(count, 10))

    @staticmethod
    def _sanitize_news_selected_sources(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        allowed = {feed["id"] for feed in NewsFeedService().list_catalog()}
        return [str(item) for item in value if str(item) in allowed]

    @staticmethod
    def _sanitize_fuel_types(value: Any) -> list[str]:
        allowed = {item["id"] for item in FuelService().type_options()}
        if not isinstance(value, list):
            return ["diesel"]
        selected = [str(item) for item in value if str(item) in allowed]
        return selected

    @staticmethod
    def _sanitize_fuel_assignments(value: Any) -> dict[str, str]:
        allowed = {item["id"] for item in FuelService().type_options()}
        if not isinstance(value, dict):
            return {}
        assignments: dict[str, str] = {}
        for key, entity_id in value.items():
            type_id = str(key)
            entity = str(entity_id or "").strip()
            if type_id in allowed and entity:
                assignments[type_id] = entity
        return assignments

    @staticmethod
    def _sanitize_string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item)]

    @staticmethod
    def _sanitize_robot_state_mappings(value: Any) -> dict[str, dict[str, list[str]]]:
        if not isinstance(value, dict):
            return {}

        def _states(raw: Any) -> list[str]:
            if isinstance(raw, str):
                raw = [part.strip() for part in raw.split(",")]
            if not isinstance(raw, list):
                return []
            return [str(item).strip().lower() for item in raw if str(item).strip()]

        mappings: dict[str, dict[str, list[str]]] = {}
        for entity_id, item in value.items():
            if not isinstance(item, dict):
                continue
            entity = str(entity_id or "").strip()
            if not entity:
                continue
            mappings[entity] = {
                "no_error_states": _states(item.get("no_error_states")),
                "ok_states": _states(item.get("ok_states")),
                "warn_states": _states(item.get("warn_states")),
                "critical_states": _states(item.get("critical_states")),
            }
        return mappings

    @staticmethod
    def _sanitize_vacuum_configs(value: Any) -> dict[str, dict[str, Any]]:
        """Vacuum-spezifische Config je entity_id: Räume, Modi, Kamera-Entity."""
        if not isinstance(value, dict):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for entity_id, cfg in value.items():
            entity = str(entity_id or "").strip()
            if not entity or not isinstance(cfg, dict):
                continue
            rooms: list[dict[str, Any]] = []
            for room in cfg.get("rooms") or []:
                if not isinstance(room, dict):
                    continue
                try:
                    rid = int(room.get("id", 0))
                except (TypeError, ValueError):
                    continue
                name = str(room.get("name") or "").strip()
                if rid > 0 and name:
                    rooms.append({"id": rid, "name": name})
            modes: list[dict[str, Any]] = []
            for mode in cfg.get("modes") or []:
                if not isinstance(mode, dict):
                    continue
                key = str(mode.get("key") or "").strip()
                label = str(mode.get("label") or "").strip()
                if not key or not label:
                    continue
                modes.append({
                    "key": key,
                    "label": label,
                    "cleaning_mode_option": str(mode.get("cleaning_mode_option") or "").strip(),
                    "suction_level": int(mode.get("suction_level") or 3),
                    "water_volume": int(mode.get("water_volume") or 0),
                })
            result[entity] = {
                "map_camera": str(cfg.get("map_camera") or "").strip(),
                "rooms": rooms,
                "modes": modes,
                "default_mode": str(cfg.get("default_mode") or "").strip(),
            }
        return result

    @staticmethod
    def _sanitize_camera_configs(value: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for entity_id, cfg in value.items():
            entity = str(entity_id or "").strip()
            if not entity or not isinstance(cfg, dict):
                continue
            duration_raw = cfg.get("doorbell_duration")
            try:
                duration = max(5, min(300, int(duration_raw))) if duration_raw is not None else 30
            except (TypeError, ValueError):
                duration = 30
            result[entity] = {
                "name": str(cfg.get("name") or "").strip(),
                "ring_device_id": str(cfg.get("ring_device_id") or "").strip(),
                "has_live_stream": bool(cfg.get("has_live_stream", True)),
                "doorbell_sensor": str(cfg.get("doorbell_sensor") or "").strip(),
                "doorbell_duration": duration,
            }
        return result

    @staticmethod
    def _sanitize_site_config(value: Any) -> dict[str, Any]:
        data = value if isinstance(value, dict) else {}
        location = str(data.get("location") or "Ostenfeld").strip()
        return {"location": location or "Ostenfeld"}

    @staticmethod
    def _sanitize_weather_config(value: Any) -> dict[str, Any]:
        data = value if isinstance(value, dict) else {}

        def _int(key: str, default: int, minimum: int, maximum: int) -> int:
            try:
                parsed = int(data.get(key, default))
            except (TypeError, ValueError):
                parsed = default
            return max(minimum, min(parsed, maximum))

        return {
            "enabled": bool(data.get("enabled", True)),
            "hourly_past_hours": _int("hourly_past_hours", 0, 0, 12),
            "hourly_future_hours": _int("hourly_future_hours", 5, 1, 24),
            "show_feels_like": bool(data.get("show_feels_like", True)),
            "show_wind": bool(data.get("show_wind", True)),
            "show_humidity": bool(data.get("show_humidity", True)),
            "show_precipitation": bool(data.get("show_precipitation", True)),
            "show_minmax": bool(data.get("show_minmax", True)),
            "show_hourly": bool(data.get("show_hourly", True)),
            "show_hourly_temperature": bool(data.get("show_hourly_temperature", True)),
            "show_hourly_precip_probability": bool(data.get("show_hourly_precip_probability", True)),
            "show_hourly_precipitation": bool(data.get("show_hourly_precipitation", True)),
            "show_hourly_wind": bool(data.get("show_hourly_wind", True)),
        }

    @staticmethod
    def _sanitize_ev_vehicles(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []

        vehicles: list[dict[str, Any]] = []
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or f"E-Fahrzeug {index + 1}").strip()
            vehicle_id = str(item.get("id") or label.lower().replace(" ", "_")).strip() or f"ev_{index + 1}"
            vehicles.append(
                {
                    "id": vehicle_id,
                    "label": label,
                    "battery_entity": str(item.get("battery_entity") or "").strip(),
                    "range_entity": str(item.get("range_entity") or "").strip(),
                    "charging_entity": str(item.get("charging_entity") or "").strip(),
                    "remaining_charge_time_entity": str(item.get("remaining_charge_time_entity") or "").strip(),
                    "stop_charging_button_entity": str(item.get("stop_charging_button_entity") or "").strip(),
                    "climate_button_entity": str(item.get("climate_button_entity") or "").strip(),
                }
            )
        return vehicles

    @staticmethod
    def _sanitize_vehicles(value: Any, ev_vehicles: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            if ev_vehicles:
                return [VehicleService.from_ev_vehicle(item) for item in ev_vehicles]
            return []
        vehicles = [
            VehicleService.sanitize_vehicle(item, index)
            for index, item in enumerate(value)
            if isinstance(item, dict)
        ]
        return vehicles

    @staticmethod
    def _sanitize_vehicle_history_days(value: Any) -> int:
        try:
            days = int(value)
        except (TypeError, ValueError):
            days = 14
        return max(1, min(days, 14))

    @staticmethod
    def _sanitize_vehicle_poll_seconds(value: Any) -> int:
        try:
            seconds = int(value)
        except (TypeError, ValueError):
            seconds = 30
        return max(10, min(seconds, 300))

    @staticmethod
    def _sanitize_config_version(value: Any) -> int:
        try:
            version = int(value)
        except (TypeError, ValueError):
            version = 1
        return max(1, version)

    @staticmethod
    def _merge_dicts(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(base)
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = IntegrationConfigService._merge_dicts(merged[key], value)
            else:
                merged[key] = value
        return merged
