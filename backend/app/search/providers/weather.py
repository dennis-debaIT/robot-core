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

        settings = _get_weather_settings()
        location = self._extract_location(query) or _get_device_location() or _FALLBACK_LOCATION
        data = get_weather_display_data(settings, location)
        if not data or not data.get("current"):
            return None

        resolved_name = data.get("location", location)
        q = query.lower()

        wants_tomorrow  = bool(re.search(r"\bmorgen\b", q))
        wants_day_after = bool(re.search(r"\bübermorgen\b", q))
        target_weekday  = next((i for name, i in self._DE_WEEKDAY_MAP.items() if name in q), None)
        needs_forecast  = wants_tomorrow or wants_day_after or target_weekday is not None

        if needs_forecast:
            today = date.today()
            if wants_day_after:
                target_str = (today + timedelta(days=2)).isoformat()
                day_label = "übermorgen"
            elif wants_tomorrow:
                target_str = (today + timedelta(days=1)).isoformat()
                day_label = "morgen"
            else:
                days_ahead = (target_weekday - today.weekday()) % 7 or 7
                target_str = (today + timedelta(days=days_ahead)).isoformat()
                day_label = self._DE_WEEKDAY_NAMES[target_weekday]

            day_data = None
            if (data.get("tomorrow") or {}).get("iso_date") == target_str:
                day_data = data["tomorrow"]
            else:
                day_data = next((d for d in (data.get("forecast_days") or []) if d.get("iso_date") == target_str), None)
            if not day_data:
                return None

            parts = [f"Wetter {day_label} in {resolved_name}: {day_data.get('description', 'unbekannt')}."]
            if day_data.get("temp_max") is not None:
                parts.append(f"Höchsttemperatur {day_data['temp_max']} °C, Tiefstwert {day_data['temp_min']} °C.")
            if float(day_data.get("precipitation") or 0) > 0:
                parts.append(f"Niederschlag: {day_data['precipitation']} mm.")
            return {
                "snippet": " ".join(parts),
                "title": f"Wetter {day_label} {resolved_name}",
                "url": "https://open-meteo.com/",
                "is_stable": False,
                "resolved_name": resolved_name,
            }

        c = data.get("current", {})
        parts = [
            f"Aktuelles Wetter in {resolved_name}: {c.get('description', 'unbekannt')}.",
            f"Temperatur: {c.get('temperature')} °C (gefühlt {c.get('feels_like')} °C).",
        ]
        if c.get("windspeed") is not None:
            parts.append(f"Wind: {c['windspeed']} km/h.")
        if c.get("humidity") is not None:
            parts.append(f"Luftfeuchtigkeit: {c['humidity']} %.")
        if float(c.get("precipitation") or 0) > 0:
            parts.append(f"Niederschlag: {c['precipitation']} mm.")
        return {
            "snippet": " ".join(parts),
            "title": f"Wetter {resolved_name}",
            "url": "https://open-meteo.com/",
            "is_stable": False,
            "resolved_name": resolved_name,
            "coat_of_arms_url": data.get("coat_of_arms_url"),
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


# ── Yr.no / MET Norway Provider ──────────────────────────────────────────────

_YR_SYMBOL_TO_WMO: dict[str, int] = {
    "clearsky": 0, "fair": 1, "partlycloudy": 2, "cloudy": 3, "fog": 45,
    "lightsleet": 77, "sleet": 77, "heavysleet": 77,
    "lightsleetshowers": 77, "sleetshowers": 77, "heavysleetshowers": 77,
    "lightrain": 61, "rain": 63, "heavyrain": 65,
    "lightrainshowers": 80, "rainshowers": 81, "heavyrainshowers": 82,
    "lightsnow": 71, "snow": 73, "heavysnow": 75,
    "lightsnowshowers": 85, "snowshowers": 85, "heavysnowshowers": 86,
    "lightrainandthunder": 95, "rainandthunder": 95, "heavyrainandthunder": 95,
    "lightrainshowersandthunder": 95, "rainshowersandthunder": 95, "heavyrainshowersandthunder": 95,
    "lightsleetandthunder": 96, "sleetandthunder": 96, "heavysleetandthunder": 99,
    "lightsleetshowersandthunder": 96, "sleetshowersandthunder": 96, "heavysleetshowersandthunder": 99,
    "lightsnowandthunder": 95, "snowandthunder": 95, "heavysnowandthunder": 99,
    "lightsnowshowersandthunder": 95, "snowshowersandthunder": 95, "heavysnowshowersandthunder": 99,
}


def _yr_symbol_to_wmo(symbol: str) -> int:
    s = symbol.lower()
    for suffix in ("_day", "_night", "_polartwilight"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return _YR_SYMBOL_TO_WMO.get(s, 3)


class YrNoWeatherProvider:
    API_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
    USER_AGENT = "robot-core/0.2 github.com/dennis-debaIT/robot-core"

    def get_display_data(self, settings: dict, location: str | None = None) -> "dict | None":
        from datetime import datetime as _dt, timedelta as _td
        from zoneinfo import ZoneInfo

        loc = location or _get_device_location()
        coords = WeatherProvider()._geocode(loc)
        if not coords:
            return None
        lat, lon, name = coords

        url = f"{self.API_URL}?lat={lat:.4f}&lon={lon:.4f}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": self.USER_AGENT})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
        except Exception:
            return None

        timeseries = (data.get("properties") or {}).get("timeseries") or []
        if not timeseries:
            return None

        berlin = ZoneInfo("Europe/Berlin")
        now = _dt.now(berlin)
        now_hour = now.replace(minute=0, second=0, microsecond=0)
        past_start = now_hour - _td(hours=int(settings.get("hourly_past_hours", 0)))
        future_end = now_hour + _td(hours=int(settings.get("hourly_future_hours", 5)))

        current_entry: dict | None = None
        forecast_hours: list[dict] = []
        hourly_by_day: dict[str, list[dict]] = {}

        for entry in timeseries:
            try:
                t_utc = _dt.fromisoformat(entry["time"].replace("Z", "+00:00"))
            except Exception:
                continue
            t_local = t_utc.astimezone(berlin)
            det = ((entry.get("data") or {}).get("instant") or {}).get("details") or {}
            next1 = (entry.get("data") or {}).get("next_1_hours") or {}
            symbol = ((next1.get("summary") or {}).get("symbol_code") or "")
            wmo = _yr_symbol_to_wmo(symbol) if symbol else 3
            n1d = next1.get("details") or {}
            wind_kmh = round(float(det.get("wind_speed", 0)) * 3.6)

            hour_entry: dict = {
                "time": t_local.strftime("%H:%M"),
                "temp": round(float(det.get("air_temperature", 0))),
                "code": wmo,
                "precip_prob": round(float(n1d.get("probability_of_precipitation", 0))),
                "precipitation": round(float(n1d.get("precipitation_amount", 0)), 1),
                "windspeed": wind_kmh,
            }
            date_key = t_local.strftime("%Y-%m-%d")
            hourly_by_day.setdefault(date_key, []).append(hour_entry)

            if current_entry is None and t_local >= now_hour:
                temp = float(det.get("air_temperature", 0))
                current_entry = {
                    "temperature": round(temp),
                    "feels_like": round(self._wind_chill(temp, float(det.get("wind_speed", 0)) * 3.6)),
                    "humidity": round(float(det.get("relative_humidity", 0))),
                    "windspeed": wind_kmh,
                    "winddirection": round(float(det.get("wind_from_direction", 0))),
                    "precipitation": round(float(n1d.get("precipitation_amount", 0)), 1),
                    "weathercode": wmo,
                    "description": _WEATHER_CODES.get(wmo, "unbekannt"),
                }

            is_past = past_start <= t_local < now_hour
            is_future = now_hour < t_local <= future_end
            if is_past or is_future:
                forecast_hours.append({**hour_entry, "is_past": is_past})

        if not current_entry:
            return None

        _DE_WD = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
        _DE_MO = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
        today_str = now.strftime("%Y-%m-%d")
        daily_entries: list[dict] = []

        for day_str, hours in sorted(hourly_by_day.items()):
            temps = [h["temp"] for h in hours if h["temp"] is not None]
            if not temps:
                continue
            midday = next((h for h in hours if h["time"] == "12:00"), hours[len(hours) // 2])
            try:
                dt = _dt.strptime(day_str, "%Y-%m-%d")
                date_label = f"{_DE_WD[dt.weekday()]}, {dt.day:02d}. {_DE_MO[dt.month - 1]}"
                label = "Heute" if day_str == today_str else _DE_WD[dt.weekday()]
            except Exception:
                date_label, label = day_str, day_str
            daily_entries.append({
                "label": label, "iso_date": day_str, "date": date_label,
                "temp_max": max(temps), "temp_min": min(temps),
                "weathercode": midday["code"],
                "description": _WEATHER_CODES.get(midday["code"], "unbekannt"),
                "precipitation": round(sum(h.get("precipitation", 0) for h in hours), 1),
                "windspeed_max": max(h.get("windspeed") or 0 for h in hours),
            })

        today_entry = next((d for d in daily_entries if d["iso_date"] == today_str), daily_entries[0] if daily_entries else None)
        tomorrow_entry = daily_entries[1] if len(daily_entries) > 1 else None
        forecast_days = daily_entries[2:7]
        coat = WeatherProvider()._fetch_coat_of_arms(name)
        return {
            "location": name, "coat_of_arms_url": coat,
            "current": current_entry, "today": today_entry, "tomorrow": tomorrow_entry,
            "forecast_days": forecast_days, "forecast_hours": forecast_hours,
            "hourly_by_day": hourly_by_day, "settings": settings,
        }

    @staticmethod
    def _wind_chill(temp_c: float, wind_kmh: float) -> float:
        if temp_c <= 10.0 and wind_kmh >= 4.8:
            v = wind_kmh ** 0.16
            return 13.12 + 0.6215 * temp_c - 11.37 * v + 0.3965 * temp_c * v
        return temp_c


# ── OpenWeatherMap Provider ───────────────────────────────────────────────────

_OWM_TO_WMO: dict[int, int] = {
    **{i: 95 for i in range(200, 233)}, **{i: 96 for i in range(233, 252)}, **{i: 99 for i in range(252, 300)},
    300: 51, 301: 53, 302: 55, 310: 51, 311: 53, 312: 55, 313: 80, 314: 81, 321: 53,
    500: 61, 501: 63, 502: 65, 503: 65, 504: 65, 511: 77, 520: 80, 521: 81, 522: 82, 531: 81,
    600: 71, 601: 73, 602: 75, 611: 77, 612: 77, 613: 77, 615: 71, 616: 63, 620: 71, 621: 73, 622: 75,
    701: 45, 711: 45, 721: 45, 731: 45, 741: 45, 751: 45, 761: 45, 762: 45, 771: 45, 781: 95,
    800: 0, 801: 1, 802: 2, 803: 3, 804: 3,
}


class OpenWeatherMapProvider:
    CURRENT_URL = "https://api.openweathermap.org/data/2.5/weather"
    FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"

    def get_display_data(self, settings: dict, location: str | None = None) -> "dict | None":
        from datetime import datetime as _dt, timedelta as _td
        from zoneinfo import ZoneInfo
        from collections import Counter

        api_key = str(settings.get("api_key") or "").strip()
        if not api_key:
            return None

        loc = location or _get_device_location()
        coords = WeatherProvider()._geocode(loc)
        if not coords:
            return None
        lat, lon, name = coords

        params = urllib.parse.urlencode({"lat": lat, "lon": lon, "appid": api_key, "units": "metric", "lang": "de"})
        try:
            req = urllib.request.Request(f"{self.CURRENT_URL}?{params}", headers={"User-Agent": "robot-core/0.2"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                cur = json.loads(resp.read().decode())
        except Exception:
            return None

        try:
            req2 = urllib.request.Request(f"{self.FORECAST_URL}?{params}", headers={"User-Agent": "robot-core/0.2"})
            with urllib.request.urlopen(req2, timeout=8) as resp:
                fcast = json.loads(resp.read().decode())
        except Exception:
            fcast = None

        main = cur.get("main") or {}
        wind = cur.get("wind") or {}
        wid = int(((cur.get("weather") or [{}])[0]).get("id", 800))
        wmo = _OWM_TO_WMO.get(wid, 3)
        precip = float(((cur.get("rain") or {}).get("1h") or (cur.get("snow") or {}).get("1h") or 0))

        current_entry = {
            "temperature": round(float(main.get("temp", 0))),
            "feels_like": round(float(main.get("feels_like", 0))),
            "humidity": round(float(main.get("humidity", 0))),
            "windspeed": round(float(wind.get("speed", 0)) * 3.6),
            "winddirection": round(float(wind.get("deg", 0))),
            "precipitation": round(precip, 1),
            "weathercode": wmo,
            "description": _WEATHER_CODES.get(wmo, "unbekannt"),
        }

        berlin = ZoneInfo("Europe/Berlin")
        now = _dt.now(berlin)
        now_hour = now.replace(minute=0, second=0, microsecond=0)
        past_start = now_hour - _td(hours=int(settings.get("hourly_past_hours", 0)))
        future_end = now_hour + _td(hours=int(settings.get("hourly_future_hours", 5)))
        today_str = now.strftime("%Y-%m-%d")
        _DE_WD = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
        _DE_MO = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]

        forecast_hours: list[dict] = []
        hourly_by_day: dict[str, list[dict]] = {}
        daily_agg: dict[str, dict] = {}

        for item in (fcast or {}).get("list") or []:
            try:
                t_local = _dt.fromtimestamp(item["dt"], tz=ZoneInfo("UTC")).astimezone(berlin)
            except Exception:
                continue
            im = item.get("main") or {}
            iw = item.get("wind") or {}
            iwid = int(((item.get("weather") or [{}])[0]).get("id", 800))
            iwmo = _OWM_TO_WMO.get(iwid, 3)
            ip = float(((item.get("rain") or {}).get("3h") or (item.get("snow") or {}).get("3h") or 0))

            he: dict = {
                "time": t_local.strftime("%H:%M"),
                "temp": round(float(im.get("temp", 0))),
                "code": iwmo,
                "precip_prob": round(float(item.get("pop", 0)) * 100),
                "precipitation": round(ip / 3, 1),
                "windspeed": round(float(iw.get("speed", 0)) * 3.6),
            }
            dk = t_local.strftime("%Y-%m-%d")
            hourly_by_day.setdefault(dk, []).append(he)
            if dk not in daily_agg:
                daily_agg[dk] = {"temps": [], "codes": [], "precip": 0.0, "wind": []}
            daily_agg[dk]["temps"].append(float(im.get("temp", 0)))
            daily_agg[dk]["codes"].append(iwmo)
            daily_agg[dk]["precip"] += ip / 3
            daily_agg[dk]["wind"].append(float(iw.get("speed", 0)) * 3.6)
            is_past = past_start <= t_local < now_hour
            is_future = now_hour < t_local <= future_end
            if is_past or is_future:
                forecast_hours.append({**he, "is_past": is_past})

        daily_entries: list[dict] = []
        for day_str in sorted(daily_agg):
            d = daily_agg[day_str]
            if not d["temps"]:
                continue
            top_code = Counter(d["codes"]).most_common(1)[0][0] if d["codes"] else 3
            try:
                dt = _dt.strptime(day_str, "%Y-%m-%d")
                date_label = f"{_DE_WD[dt.weekday()]}, {dt.day:02d}. {_DE_MO[dt.month - 1]}"
                label = "Heute" if day_str == today_str else _DE_WD[dt.weekday()]
            except Exception:
                date_label, label = day_str, day_str
            daily_entries.append({
                "label": label, "iso_date": day_str, "date": date_label,
                "temp_max": round(max(d["temps"])), "temp_min": round(min(d["temps"])),
                "weathercode": top_code, "description": _WEATHER_CODES.get(top_code, "unbekannt"),
                "precipitation": round(d["precip"], 1),
                "windspeed_max": round(max(d["wind"])) if d["wind"] else None,
            })

        today_entry = next((d for d in daily_entries if d["iso_date"] == today_str), daily_entries[0] if daily_entries else None)
        tomorrow_entry = daily_entries[1] if len(daily_entries) > 1 else None
        forecast_days = daily_entries[2:7]
        coat = WeatherProvider()._fetch_coat_of_arms(name)
        return {
            "location": name, "coat_of_arms_url": coat,
            "current": current_entry, "today": today_entry, "tomorrow": tomorrow_entry,
            "forecast_days": forecast_days, "forecast_hours": forecast_hours,
            "hourly_by_day": hourly_by_day, "settings": settings,
        }


# ── Provider-Factory ──────────────────────────────────────────────────────────

def get_weather_display_data(settings: dict | None = None, location: str | None = None) -> "dict | None":
    if settings is None:
        settings = _get_weather_settings()
    provider = str(settings.get("provider") or "open_meteo")
    if provider == "yrno":
        return YrNoWeatherProvider().get_display_data(settings, location)
    if provider == "openweathermap":
        return OpenWeatherMapProvider().get_display_data(settings, location)
    return WeatherProvider().get_display_data(location=location)
