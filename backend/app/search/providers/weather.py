"""
Open-Meteo Provider — aktuelles Wetter ohne API-Key.

Nutzt Open-Meteo (https://open-meteo.com) für Wetterdaten und die
Open-Meteo Geocoding API für Ortsauflösung.

Fallback-Ort: ROBOT_WEATHER_LOCATION Env-Variable (Standard: Darmstadt).
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
import urllib.parse
from typing import Any


def _get_device_location() -> str:
    """Liest den Wohnort aus system_state (site_label). Fallback: Env-Var oder 'Darmstadt'."""
    try:
        from app.services.integration_config_service import IntegrationConfigService

        location = IntegrationConfigService().get_site_location()
        if location:
            return location
    except Exception:
        pass

    try:
        import json as _json
        from app.database.db import get_connection
        with get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM system_state WHERE key = 'site_label' LIMIT 1"
            ).fetchone()
            if row and row["value"]:
                value = _json.loads(row["value"])  # JSON-dekodieren ("Ostenfeld" → Ostenfeld)
                if value and str(value).strip():
                    return str(value).strip()
    except Exception:
        pass
    return os.environ.get("ROBOT_WEATHER_LOCATION", "Darmstadt")


def _get_weather_settings() -> dict[str, Any]:
    try:
        from app.services.integration_config_service import IntegrationConfigService

        return IntegrationConfigService().get_weather_config()
    except Exception:
        return {
            "enabled": True,
            "hourly_past_hours": 0,
            "hourly_future_hours": 5,
            "show_feels_like": True,
            "show_wind": True,
            "show_humidity": True,
            "show_precipitation": True,
            "show_minmax": True,
            "show_hourly": True,
        }


_WEATHER_CODES: dict[int, str] = {
    0: "klarer Himmel",
    1: "überwiegend klar",
    2: "teilweise bewölkt",
    3: "bewölkt",
    45: "Nebel",
    48: "Nebel mit Raureif",
    51: "leichter Nieselregen",
    53: "Nieselregen",
    55: "starker Nieselregen",
    61: "leichter Regen",
    63: "Regen",
    65: "starker Regen",
    71: "leichter Schneefall",
    73: "Schneefall",
    75: "starker Schneefall",
    77: "Schneekörner",
    80: "leichte Schauer",
    81: "Schauer",
    82: "starke Schauer",
    85: "leichte Schneeschauer",
    86: "starke Schneeschauer",
    95: "Gewitter",
    96: "Gewitter mit Hagel",
    99: "Gewitter mit schwerem Hagel",
}

_FALLBACK_LOCATION = os.environ.get("ROBOT_WEATHER_LOCATION", "Darmstadt")


class WeatherProvider:
    GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
    WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

    _PATTERN = re.compile(
        r"\b(wetter|temperatur|warm|kalt|regen|schnee|wind|sonnig|bewölkt"
        r"|nebel|gewitter|wie\s+warm|wie\s+kalt|grad|celsius|draußen"
        r"|heute\s+(?:warm|kalt|regnet|scheint)|brauche\s+(?:einen\s+schirm|jacke))\b",
        re.IGNORECASE,
    )

    # Ortsnamen aus Anfragen extrahieren
    _LOCATION_PATTERN = re.compile(
        r"\bin\s+([A-Za-zÄÖÜäöüß][a-zA-ZÄÖÜäöüß\s\-]{2,20}?)(?:\s+(?:ist|sind|war|wird|das|heute|aktuell|gerade))?\b"
        r"|\bfür\s+([A-Za-zÄÖÜäöüß][a-zA-ZÄÖÜäöüß\s\-]{2,20}?)(?:\s+(?:ist|das|heute))?\b",
    )

    def can_handle(self, query: str) -> bool:
        return bool(self._PATTERN.search(query))

    def get_display_data(self, location: str | None = None) -> dict[str, Any] | None:
        """Strukturierte Wetterdaten für Display-Ausgabe inkl. Stundenprognose."""
        settings = _get_weather_settings()
        if not settings.get("enabled", True):
            return None
        location = location or _get_device_location()
        coords = self._geocode(location)
        if not coords:
            return None
        lat, lon, name = coords

        params = urllib.parse.urlencode({
            "latitude": lat,
            "longitude": lon,
            "current": ",".join([
                "temperature_2m", "apparent_temperature",
                "relative_humidity_2m", "precipitation",
                "weathercode", "windspeed_10m", "winddirection_10m",
            ]),
            "hourly": "temperature_2m,weathercode,precipitation_probability,precipitation,windspeed_10m",
            "daily": ",".join([
                "weathercode", "temperature_2m_max", "temperature_2m_min",
                "precipitation_sum", "windspeed_10m_max",
            ]),
            "timezone": "Europe/Berlin",
            "past_hours": int(settings.get("hourly_past_hours", 0)),
            "forecast_days": 7,
        })
        url = f"{self.WEATHER_URL}?{params}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "robot-core/0.2"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode())
        except Exception:
            return None

        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo
        current = data.get("current", {})
        hourly = data.get("hourly", {})
        daily = data.get("daily", {})
        from datetime import timedelta as _td

        now = _dt.now(ZoneInfo("Europe/Berlin")).replace(tzinfo=None)
        now_hour = now.replace(minute=0, second=0, microsecond=0)
        past_hours = int(settings.get("hourly_past_hours", 0))
        future_hours = int(settings.get("hourly_future_hours", 5))
        past_start = now_hour - _td(hours=past_hours)
        future_end = now_hour + _td(hours=future_hours)

        # Nächste 6 Stunden
        times = hourly.get("time", [])
        h_temps = hourly.get("temperature_2m", [])
        h_codes = hourly.get("weathercode", [])
        h_probs = hourly.get("precipitation_probability", [])
        h_precip = hourly.get("precipitation", [])
        h_wind = hourly.get("windspeed_10m", [])
        forecast_hours = []
        hourly_by_day: dict[str, list[dict[str, Any]]] = {}

        def _round_or_none(values: list[Any], index: int) -> int | None:
            if index >= len(values) or values[index] is None:
                return None
            return round(values[index])

        def _round1_or_zero(values: list[Any], index: int) -> float:
            if index >= len(values) or values[index] is None:
                return 0
            return round(values[index], 1)

        def _int_or_zero(values: list[Any], index: int) -> int:
            if index >= len(values) or values[index] is None:
                return 0
            return int(values[index])

        for i, t in enumerate(times):
            try:
                hour_dt = _dt.strptime(t, "%Y-%m-%dT%H:%M")
            except Exception:
                continue
            hour_entry = {
                "time": t[11:16],
                "temp": _round_or_none(h_temps, i),
                "code": _int_or_zero(h_codes, i),
                "precip_prob": _int_or_zero(h_probs, i),
                "precipitation": _round1_or_zero(h_precip, i),
                "windspeed": _round_or_none(h_wind, i),
            }
            hourly_by_day.setdefault(t[:10], []).append(hour_entry)
            is_past = past_start <= hour_dt < now_hour
            is_future = now_hour < hour_dt <= future_end
            if not (is_past or is_future):
                continue
            forecast_hours.append({**hour_entry, "is_past": is_past})

        _DE_WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag",
                        "Freitag", "Samstag", "Sonntag"]
        _DE_MONTHS = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
                      "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]

        d_times   = daily.get("time", [])
        d_max     = daily.get("temperature_2m_max", [])
        d_min     = daily.get("temperature_2m_min", [])
        d_codes   = daily.get("weathercode", [])
        d_precip  = daily.get("precipitation_sum", [])
        d_wind    = daily.get("windspeed_10m_max", [])

        def _day_entry(i: int, label: str) -> dict:
            code = int(d_codes[i]) if i < len(d_codes) else 0
            dt_str = d_times[i] if i < len(d_times) else ""
            try:
                dt = _dt.strptime(dt_str, "%Y-%m-%d")
                date_label = f"{_DE_WEEKDAYS[dt.weekday()]}, {dt.day:02d}. {_DE_MONTHS[dt.month-1]}"
            except Exception:
                date_label = label
            return {
                "label": label,
                "iso_date": dt_str,
                "date": date_label,
                "temp_max": round(d_max[i]) if i < len(d_max) else None,
                "temp_min": round(d_min[i]) if i < len(d_min) else None,
                "weathercode": code,
                "description": _WEATHER_CODES.get(code, "unbekannt"),
                "precipitation": round(d_precip[i], 1) if i < len(d_precip) else 0,
                "windspeed_max": round(d_wind[i]) if i < len(d_wind) else None,
            }

        today_entry    = _day_entry(0, "Heute")
        tomorrow_entry = _day_entry(1, "Morgen") if len(d_times) > 1 else None
        forecast_days  = [_day_entry(i, _DE_WEEKDAYS[_dt.strptime(d_times[i], "%Y-%m-%d").weekday()])
                          for i in range(2, min(7, len(d_times)))]

        coat = self._fetch_coat_of_arms(name)
        return {
            "location": name,
            "coat_of_arms_url": coat,
            "current": {
                "temperature": round(current.get("temperature_2m", 0)),
                "feels_like": round(current.get("apparent_temperature", 0)),
                "humidity": round(current.get("relative_humidity_2m", 0)),
                "windspeed": round(current.get("windspeed_10m", 0)),
                "winddirection": round(current.get("winddirection_10m", 0)),
                "precipitation": round(current.get("precipitation", 0), 1),
                "weathercode": int(current.get("weathercode", 0)),
                "description": _WEATHER_CODES.get(int(current.get("weathercode", 0)), "unbekannt"),
            },
            "today": today_entry,
            "tomorrow": tomorrow_entry,
            "forecast_days": forecast_days,
            "forecast_hours": forecast_hours,
            "hourly_by_day": hourly_by_day,
            "settings": settings,
        }

    _DE_WEEKDAY_NAMES = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
    _DE_WEEKDAY_MAP   = {d.lower(): i for i, d in enumerate(_DE_WEEKDAY_NAMES)}

    def search(self, query: str) -> dict[str, Any] | None:
        from datetime import date, timedelta

        location = self._extract_location(query) or _get_device_location() or _FALLBACK_LOCATION
        coords = self._geocode(location)
        if not coords:
            return None

        lat, lon, resolved_name = coords
        q = query.lower()

        # Tages-Erkennung: morgen / übermorgen / Wochentag
        wants_tomorrow   = bool(re.search(r"\bmorgen\b", q))
        wants_day_after  = bool(re.search(r"\bübermorgen\b", q))
        target_weekday   = next((i for name, i in self._DE_WEEKDAY_MAP.items() if name in q), None)

        needs_forecast = wants_tomorrow or wants_day_after or target_weekday is not None

        if needs_forecast:
            weather = self._fetch_weather_forecast(lat, lon, days=8)
            if not weather:
                return None
            daily = weather.get("daily", {})
            times = daily.get("time", [])

            today = date.today()
            if wants_day_after:
                target_date = today + timedelta(days=2)
                day_label = "übermorgen"
            elif wants_tomorrow:
                target_date = today + timedelta(days=1)
                day_label = "morgen"
            else:
                days_ahead = (target_weekday - today.weekday()) % 7 or 7
                target_date = today + timedelta(days=days_ahead)
                day_label = self._DE_WEEKDAY_NAMES[target_weekday]

            target_str = target_date.isoformat()
            idx = next((i for i, t in enumerate(times) if t == target_str), None)
            if idx is None:
                return None

            t_max  = daily.get("temperature_2m_max", [])[idx] if idx < len(daily.get("temperature_2m_max", [])) else None
            t_min  = daily.get("temperature_2m_min", [])[idx] if idx < len(daily.get("temperature_2m_min", [])) else None
            code   = int(daily.get("weathercode", [])[idx]) if idx < len(daily.get("weathercode", [])) else 0
            rain   = daily.get("precipitation_sum", [])[idx] if idx < len(daily.get("precipitation_sum", [])) else 0
            desc   = _WEATHER_CODES.get(code, "unbekannt")

            parts = [f"Wetter {day_label} in {resolved_name}: {desc}."]
            if t_max is not None:
                parts.append(f"Höchsttemperatur {round(t_max)} °C, Tiefstwert {round(t_min)} °C.")
            if rain and float(rain) > 0:
                parts.append(f"Niederschlag: {round(float(rain), 1)} mm.")
            return {
                "snippet": " ".join(parts),
                "title": f"Wetter {day_label} {resolved_name}",
                "url": "https://open-meteo.com/",
                "is_stable": False,
                "resolved_name": resolved_name,
            }

        # Aktuelles Wetter
        weather = self._fetch_weather(lat, lon)
        if not weather:
            return None

        current = weather.get("current", {})
        temp    = current.get("temperature_2m")
        feels   = current.get("apparent_temperature")
        wind    = current.get("windspeed_10m")
        humidity = current.get("relative_humidity_2m")
        precip  = current.get("precipitation")
        code    = current.get("weathercode", 0)
        desc    = _WEATHER_CODES.get(int(code), "unbekannt")

        parts = [
            f"Aktuelles Wetter in {resolved_name}: {desc}.",
            f"Temperatur: {temp} °C (gefühlt {feels} °C).",
        ]
        if wind is not None:
            parts.append(f"Wind: {wind} km/h.")
        if humidity is not None:
            parts.append(f"Luftfeuchtigkeit: {humidity} %.")
        if precip is not None and float(precip) > 0:
            parts.append(f"Niederschlag: {precip} mm.")

        coat = self._fetch_coat_of_arms(resolved_name)
        return {
            "snippet": " ".join(parts),
            "title": f"Wetter {resolved_name}",
            "url": "https://open-meteo.com/",
            "is_stable": False,
            "resolved_name": resolved_name,
            "coat_of_arms_url": coat,
        }

    # ── Stadtwappen via Wikidata ─────────────────────────────────────────────

    _coat_cache: dict[str, str | None] = {}

    def _fetch_coat_of_arms(self, city: str) -> str | None:
        """Lädt das Stadtwappen-URL von Wikidata (P94). Ergebnis wird gecacht."""
        key = city.lower().strip()
        if key in self._coat_cache:
            return self._coat_cache[key]
        url = None
        try:
            # 1. Wikidata-Entity für Stadt suchen
            search_url = (
                "https://www.wikidata.org/w/api.php?action=wbsearchentities"
                f"&search={urllib.parse.quote(city)}&language=de&type=item&format=json&limit=1"
            )
            req = urllib.request.Request(search_url, headers={"User-Agent": "robot-core/0.2"})
            with urllib.request.urlopen(req, timeout=5) as r:
                results = json.loads(r.read().decode()).get("search", [])
            if not results:
                self._coat_cache[key] = None
                return None
            qid = results[0]["id"]

            # 2. Entity-Daten laden und P94 (coat of arms) extrahieren
            entity_url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
            req2 = urllib.request.Request(entity_url, headers={"User-Agent": "robot-core/0.2"})
            with urllib.request.urlopen(req2, timeout=5) as r2:
                entity = json.loads(r2.read().decode())
            claims = entity.get("entities", {}).get(qid, {}).get("claims", {})
            p94 = claims.get("P94", [])
            if not p94:
                self._coat_cache[key] = None
                return None
            filename = (
                p94[0].get("mainsnak", {})
                .get("datavalue", {})
                .get("value", "")
            )
            if not filename:
                self._coat_cache[key] = None
                return None

            # 3. Wikimedia Commons URL aufbauen
            filename_encoded = urllib.parse.quote(filename.replace(" ", "_"))
            url = f"https://commons.wikimedia.org/wiki/Special:FilePath/{filename_encoded}?width=120"
        except Exception:
            url = None
        self._coat_cache[key] = url
        return url

    # ── Interne Hilfsmethoden ────────────────────────────────────────────────

    # Wörter die nie als Ortsname gelten
    _LOCATION_STOPWORDS = frozenset([
        "wetter", "temperatur", "regen", "wind", "schnee", "frost", "nebel",
        "morgen", "heute", "gestern", "übermorgen", "wochenende",
        "montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag",
        "aktuell", "gerade", "jetzt", "wie", "wird", "wird's", "ist", "war", "sind", "bin",
        # Deutsche Artikel (STT schreibt sie oft groß)
        "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer",
        # Häufige Verben / Wörter die kein Ort sind
        "kannst", "sagen", "mir", "bitte", "gibt", "gibt's", "haben", "weißt",
        "magst", "schau", "schau mal", "sag", "zeig", "zeige",
        "du", "ich", "er", "sie", "es", "wir", "ihr",
        "bitte", "mal", "doch", "noch", "schon", "auch",
    ])

    def _extract_location(self, query: str) -> str | None:
        # 1. Regex: "in X" oder "für X" (jetzt case-insensitiv)
        m = self._LOCATION_PATTERN.search(query)
        if m:
            loc = (m.group(1) or m.group(2) or "").strip()
            if len(loc) >= 3 and loc.lower() not in self._LOCATION_STOPWORDS:
                return loc.capitalize()
        # 2. Letztes großgeschriebenes Wort
        words = re.sub(r"[^\w\s]", "", query).split()
        for word in reversed(words):
            if len(word) >= 3 and word[0].isupper() and word.lower() not in self._LOCATION_STOPWORDS:
                return word
        # 3. Fallback: letztes Wort ≥ 3 Zeichen das kein Stopwort ist
        for word in reversed(words):
            if len(word) >= 3 and word.lower() not in self._LOCATION_STOPWORDS:
                return word.capitalize()
        return None

    def _geocode(self, location: str) -> tuple[float, float, str] | None:
        # Klammerzusätze entfernen ("Ostenfeld (Husum)" → "Ostenfeld"), dann Varianten versuchen
        cleaned = re.sub(r"\s*\(.*?\)", "", location).strip()
        # Fallback-Orte: Hauptname, dann letztes Wort (z.B. Bezirksstadt), dann Original
        candidates = [cleaned]
        if " " in cleaned:
            candidates.append(cleaned.split()[-1])  # letztes Wort = oft Bezirksstadt
        candidates.append(location)
        seen: set[str] = set()
        for candidate in candidates:
            if candidate in seen or not candidate:
                continue
            seen.add(candidate)
            result = self._geocode_single(candidate)
            if result:
                return result
        return None

    def _geocode_single(self, location: str) -> tuple[float, float, str] | None:
        params = urllib.parse.urlencode({
            "name": location,
            "count": 1,
            "language": "de",
            "format": "json",
        })
        url = f"{self.GEO_URL}?{params}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "robot-core/0.2"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode())
            results = data.get("results", [])
            if not results:
                return None
            r = results[0]
            return float(r["latitude"]), float(r["longitude"]), r.get("name", location)
        except Exception:
            return None

    def _fetch_weather_forecast(self, lat: float, lon: float, days: int = 8) -> dict | None:
        params = urllib.parse.urlencode({
            "latitude": lat, "longitude": lon,
            "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum",
            "timezone": "Europe/Berlin", "forecast_days": days,
        })
        url = f"{self.WEATHER_URL}?{params}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "robot-core/0.2"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            return None

    def _fetch_weather_daily(self, lat: float, lon: float) -> dict | None:
        params = urllib.parse.urlencode({
            "latitude": lat, "longitude": lon,
            "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum",
            "timezone": "Europe/Berlin", "forecast_days": 2,
        })
        url = f"{self.WEATHER_URL}?{params}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "robot-core/0.2"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            return None

    def _fetch_weather(self, lat: float, lon: float) -> dict | None:
        params = urllib.parse.urlencode({
            "latitude": lat,
            "longitude": lon,
            "current": ",".join([
                "temperature_2m",
                "apparent_temperature",
                "relative_humidity_2m",
                "precipitation",
                "weathercode",
                "windspeed_10m",
            ]),
            "timezone": "Europe/Berlin",
            "forecast_days": 1,
        })
        url = f"{self.WEATHER_URL}?{params}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "robot-core/0.2"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            return None
