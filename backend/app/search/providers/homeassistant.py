"""
Home Assistant Provider — Kalender und Gerätestatus.

Liest Umgebungsvariablen:
  ROBOT_HA_URL       z.B. http://192.168.1.246:8123
  ROBOT_HA_TOKEN     Long-Lived Access Token (empfohlen)
  ROBOT_HA_USERNAME  (veraltet, wird ignoriert)
  ROBOT_HA_PASSWORD  (veraltet, wird ignoriert)
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.homeassistant_runtime_config_service import HomeAssistantRuntimeConfigService

_DE_WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
_DE_MONTHS   = ["Januar", "Februar", "März", "April", "Mai", "Juni",
                 "Juli", "August", "September", "Oktober", "November", "Dezember"]


def _de_date(dt: datetime) -> str:
    return f"{_DE_WEEKDAYS[dt.weekday()]}, {dt.day:02d}. {_DE_MONTHS[dt.month - 1]}"


class HomeAssistantProvider:
    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        runtime = HomeAssistantRuntimeConfigService.to_public_payload()
        self._base_url: str = base_url or runtime["base_url"]
        self._token: str | None = token or runtime["token"] or None

    # ── Auth ────────────────────────────────────────────────

    def _get(self, path: str) -> Any | None:
        if not self._token:
            return None
        url = f"{self._base_url}/api{path}"
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            return None

    def _post(self, path: str, payload: Any) -> Any | None:
        if not self._token:
            return None
        url = f"{self._base_url}/api{path}"
        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            return None

    # ── Lichtsteuerung ───────────────────────────────────────

    def get_lights(self) -> list[dict]:
        """Alle Licht- und Schalter-Entities + Gruppen mit aktuellem Status."""
        states = self._get("/states")
        if not isinstance(states, list):
            return []
        lights = []
        for s in states:
            eid = s.get("entity_id", "")
            is_light  = eid.startswith("light.")
            is_switch = eid.startswith("switch.")
            if not is_light and not is_switch:
                continue
            # Kamera/Sicherheits/Roboter-Switches ausschließen (keine Lichtsteuerung)
            _SWITCH_EXCLUDE = (
                "ring", "camera", "doorbell",
                "motion_detection", "bewegungserkennung",
                "siren", "alarm", "chime", "live_ansicht",
                # ring-mqtt Switches
                "ding_sound", "motion_sound", "motion_warning",
                "event_stream", "live_stream", "snooze",
                "garten", "haustur", "terrasse",  # Ring-Kamera-Namen
                # Roboter (Landroid + Saugroboter)
                "robert", "carsten", "kruemel", "krumel", "krümel", "knecht",
                "landroid", "worx", "mower", "vacuum", "robot",
            )
            if is_switch and any(kw in eid.lower() for kw in _SWITCH_EXCLUDE):
                continue
            attrs = s.get("attributes", {})
            members = attrs.get("entity_id")  # Nur bei Gruppen vorhanden
            brightness = attrs.get("brightness") if is_light else None
            color_modes = attrs.get("supported_color_modes", [])
            lights.append({
                "entity_id": eid,
                "name": attrs.get("friendly_name", eid.split(".", 1)[-1]),
                "state": s.get("state", "off"),
                "brightness_pct": round(brightness / 255 * 100) if brightness else 0,
                "is_group": isinstance(members, list),
                "members": members if isinstance(members, list) else [],
                "supports_brightness": is_light and "brightness" in attrs,
                "supports_color": is_light and any(m in color_modes for m in ("hs", "rgb", "xy", "rgbw", "rgbww")),
                "supports_color_temp": is_light and "color_temp" in color_modes,
                "color_mode": attrs.get("color_mode"),
                "rgb_color": attrs.get("rgb_color"),
                "color_temp": attrs.get("color_temp"),
                "color_temp_kelvin": attrs.get("color_temp_kelvin"),
                "min_mireds": attrs.get("min_mireds"),
                "max_mireds": attrs.get("max_mireds"),
                "min_color_temp_kelvin": attrs.get("min_color_temp_kelvin"),
                "max_color_temp_kelvin": attrs.get("max_color_temp_kelvin"),
            })
        # Gruppen zuerst, dann Einzellampen alphabetisch
        lights.sort(key=lambda x: (not x["is_group"], x["name"].lower()))
        return lights

    _LIGHT_CMD = re.compile(
        r"\b(?:schalte?|mach[e]?|dreh[e]?|tu[e]?|dimm[e]?|stell[e]?)\b.{0,40}\b(?:licht(?:er)?|lampe[n]?)\b"
        r"|\b(?:licht(?:er)?|lampe[n]?)\b.{0,40}\b(?:an|ein|aus|\d+\s*(?:%|prozent))\b"
        r"|\ball[e]?\s+(?:licht(?:er)?|lampe[n]?)\b",
        re.IGNORECASE | re.DOTALL,
    )
    _BRIGHTNESS_RE = re.compile(r"(\d+)\s*(?:%|prozent)", re.IGNORECASE)

    def execute_light_command(self, query: str) -> str | None:
        """
        Erkennt Sprachbefehle für Lichtsteuerung und führt sie direkt aus.
        Unterstützt: ein/aus sowie Helligkeit in Prozent.
        """
        if not self._LIGHT_CMD.search(query):
            return None

        q = query.lower()

        # Helligkeit extrahieren (z.B. "50%", "30 Prozent")
        bri_match = self._BRIGHTNESS_RE.search(q)
        brightness_pct = int(bri_match.group(1)) if bri_match else None

        # Aktion bestimmen: explizit oder aus Helligkeit ableiten
        is_off = bool(re.search(r"\b(aus|ausschalten|ausmachen|abschalten)\b", q)) \
                 or brightness_pct == 0
        is_on  = bool(re.search(r"\b(ein|an|einschalten|anmachen|anschalten)\b", q)) \
                 or (brightness_pct is not None and brightness_pct > 0)

        if not is_on and not is_off:
            return None

        service = "turn_off" if is_off else "turn_on"

        # Service-Daten zusammenbauen
        data: dict = {}
        if is_on and brightness_pct:
            data["brightness_pct"] = brightness_pct
            action = f"auf {brightness_pct}% eingestellt"
        elif is_on:
            action = "eingeschaltet"
        else:
            action = "ausgeschaltet"

        lights = self.get_lights()
        groups = [l for l in lights if l["is_group"]]

        # "alle Lichter/Lampen"
        if re.search(r"\ball[e]?\b", q):
            for g in groups:
                domain = g["entity_id"].split(".")[0]
                svc_data = {"entity_id": g["entity_id"]}
                if domain == "light":
                    svc_data.update(data)
                self.call_service(domain, service, svc_data)
            return f"Alle Lichter {action}."

        # Spezifischen Raum suchen
        _STOP = {"schalte", "mach", "mache", "dreh", "stell", "stelle", "dimm",
                 "dimme", "das", "die", "der", "im", "in", "von", "licht",
                 "lampe", "lampen", "lichter", "ein", "an", "aus", "auf",
                 "bitte", "mal", "doch", "den", "dem", "prozent"}
        words = [w for w in re.findall(r"[A-Za-zÄÖÜäöüß]{3,}", q) if w not in _STOP]

        best_group = None
        best_score = 0
        for g in groups:
            name_lower = (g["name"] or "").lower()
            score = sum(1 for w in words if w in name_lower)
            if score > best_score:
                best_score = score
                best_group = g

        if best_group and best_score > 0:
            domain = best_group["entity_id"].split(".")[0]
            # Switches unterstützen keine Helligkeit
            svc_data = {"entity_id": best_group["entity_id"]}
            if domain == "light":
                svc_data.update(data)
            self.call_service(domain, service, svc_data)
            return f"Licht {best_group['name']} {action}."

        return None

    def call_service(self, domain: str, service: str, data: dict) -> bool:
        """Ruft einen HA-Service auf (z.B. light.turn_on)."""
        if not self._token:
            return False
        url = f"{self._base_url}/api/services/{domain}/{service}"
        try:
            body = json.dumps(data).encode()
            req = urllib.request.Request(
                url, data=body,
                headers={"Authorization": f"Bearer {self._token}",
                         "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                return resp.status in (200, 201)
        except Exception:
            return False

    # ── Search-Provider Interface ────────────────────────────

    _CALENDAR_PATTERN = re.compile(
        r"\b(was\s+liegt\s+(heute|morgen|diese\s+woche)?\s*an"
        r"|liegt\s+(?:\w+\s+){0,5}an\b"
        r"|was\s+(?:haben\s+wir|passiert|ist|steht)\s+(?:heute|morgen|diese\s+woche|am\s+wochenende)"
        r"|steht\s+(?:\w+\s+){0,5}an\b"
        r"|ansteh\w+"                              # "ansteht", "anstehend", "anstehen"
        r"|(?:\w+\s+){0,3}(?:heute|morgen)\s+(?:\w+\s+){0,3}an\b"
        r"|anstehende?\s+termine?"
        r"|(?:meine\s+)?termine?(?:\s+(?:heute|morgen|diese\s+woche))?"
        r"|kalender|verabredung|geburtstag"
        r"|was\s+(?:gibt\s+es|gibt'?s|kommt)\s+(?:heute|morgen|diese\s+woche|als\s+nächstes)"
        r"|nächste[rn]?\s+termin"
        r"|hab(?:e)?\s+ich\s+(?:heute|morgen|diese\s+woche)\s+(?:etwas|was|einen?\s+termin))\b",
        re.IGNORECASE,
    )

    def can_handle(self, query: str) -> bool:
        return bool(self._CALENDAR_PATTERN.search(query))

    def search(self, query: str) -> dict[str, Any] | None:
        """Liefert Kalendereinträge aus HA als Suchkontext für den LLM."""
        data = self.get_display_data()
        if not data:
            return None

        days = data.get("days", [])
        date_str = data.get("date", "heute")

        # Zeitbezug aus Query erkennen
        q = query.lower()
        focus_tomorrow = bool(re.search(r"\bmorgen\b", q))
        focus_week = bool(re.search(r"\bwoche\b|\bwochenende\b", q))

        if not days:
            snippet = (
                f"Laut Home-Assistant-Kalender gibt es in den nächsten 7 Tagen "
                f"keine eingetragenen Termine."
            )
        else:
            parts: list[str] = []
            for day in days[:7]:
                # Bei "morgen"-Anfrage nur Morgen hervorheben, Rest als Info
                label = day["label"]
                for ev in day.get("events", []):
                    loc = f" in {ev['location']}" if ev.get("location") else ""
                    parts.append(
                        f"{label} ({day['date']}): "
                        f"{ev['time']} Uhr — {ev['title']}{loc}"
                    )

            if focus_tomorrow:
                tomorrow_parts = [p for p in parts if p.startswith("Morgen")]
                other_parts = [p for p in parts if not p.startswith("Morgen")]
                if tomorrow_parts:
                    snippet = "Morgen: " + " | ".join(tomorrow_parts)
                    if other_parts:
                        snippet += f". Weitere Termine diese Woche: " + " | ".join(other_parts[:4])
                else:
                    snippet = f"Morgen ({days[1]['date'] if len(days) > 1 else 'morgen'}) sind keine Termine eingetragen."
                    if parts:
                        snippet += " Diese Woche: " + " | ".join(parts[:4])
            else:
                snippet = f"Kalender ab heute ({date_str}): " + " | ".join(parts[:8])

        next_ev = data.get("next_event")
        if next_ev and not focus_tomorrow:
            snippet += (
                f" Nächster zukünftiger Termin: {next_ev['weekday']}, {next_ev['date']}"
                f" um {next_ev['time']} Uhr — {next_ev['title']}."
            )

        return {
            "snippet": snippet,
            "title": f"Kalender {date_str}",
            "url": f"{self._base_url}/lovelace",
            "is_stable": False,
            "provider": "calendar",
            "focus": "tomorrow" if focus_tomorrow else ("week" if focus_week else "today"),
        }

    # ── Kraftstoffpreise (Tankerkönig via HA) ────────────────

    def get_fuel_prices(self) -> dict[str, Any] | None:
        """
        Liest Kraftstoffpreise aus HA-Sensoren (Tankerkönig-Integration).
        Sucht automatisch nach Sensoren mit 'diesel', 'e10', 'super' im Entity-ID
        oder 'tankerkoenig' und numerischem State mit Einheit €/L.
        """
        states = self._get("/states")
        if not isinstance(states, list):
            return None

        _FUEL_KEYWORDS = {
            "diesel", "e10", "e5", "super", "benzin", "lpg", "autogas",
            "adblue", "ad_blue", "tankerkoenig", "tanke",
        }
        _FUEL_TYPES = {
            "diesel": "Diesel",
            "e10":    "E10",
            "e5":     "E5",
            "lpg":    "LPG",
            "autogas": "LPG",
            "adblue": "AdBlue",
            "ad_blue": "AdBlue",
            "super":  "Super",
            "benzin": "Benzin",
        }

        entries: list[dict] = []
        for state in states:
            entity_id = (state.get("entity_id") or "").lower()
            attrs = state.get("attributes") or {}
            unit = (attrs.get("unit_of_measurement") or "").lower()
            name = attrs.get("friendly_name") or entity_id

            # Filter: Preis-Sensor mit €/L Einheit oder bekanntem Keyword
            has_keyword = any(kw in entity_id for kw in _FUEL_KEYWORDS)
            has_unit = "€" in unit or "eur" in unit
            if not (has_keyword or has_unit):
                continue

            raw = state.get("state", "")
            try:
                price = round(float(raw), 3)
            except (ValueError, TypeError):
                continue
            if price <= 0 or price > 5.0:  # Plausibilitätscheck
                continue

            # Kraftstofftyp erkennen
            fuel_type = "Kraftstoff"
            for key, label in _FUEL_TYPES.items():
                if key in entity_id or key in name.lower():
                    fuel_type = label
                    break

            entries.append({
                "entity_id": entity_id,
                "name": name,
                "fuel_type": fuel_type,
                "price": price,
                "unit": "€/L",
                "last_changed": state.get("last_changed", ""),
            })

        if not entries:
            return None

        # Nach Kraftstofftyp gruppieren, dann nach Preis sortieren
        grouped: dict[str, list[dict]] = {}
        for e in entries:
            grouped.setdefault(e["fuel_type"], []).append(e)
        for lst in grouped.values():
            lst.sort(key=lambda x: x["price"])

        # Diesel bevorzugt anzeigen
        diesel = grouped.get("Diesel", [])
        cheapest_diesel = diesel[0] if diesel else None

        return {
            "grouped": grouped,
            "diesel": diesel,
            "cheapest_diesel": cheapest_diesel,
            "updated_at": (cheapest_diesel or (diesel[0] if diesel else entries[0])).get("last_changed", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        }

    # ── Kalender ─────────────────────────────────────────────

    def list_calendars(self) -> list[dict]:
        result = self._get("/calendars")
        return result if isinstance(result, list) else []

    def get_events_upcoming(self, days: int = 7, selected_calendars: list[str] | None = None) -> list[dict]:
        calendars = self.list_calendars()
        if not calendars:
            return []
        if selected_calendars:
            calendars = [c for c in calendars if c.get("entity_id") in selected_calendars]
        if not calendars:
            return []

        now   = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end   = start + timedelta(days=days)
        fmt   = "%Y-%m-%dT%H:%M:%S"

        all_events: list[dict] = []
        for cal in calendars:
            entity = cal.get("entity_id", "")
            if not entity:
                continue
            params = urllib.parse.urlencode({
                "start": start.strftime(fmt),
                "end":   end.strftime(fmt),
            })
            data = self._get(f"/calendars/{entity}?{params}")
            if not isinstance(data, list):
                continue
            for ev in data:
                ev["_calendar"] = cal.get("name", entity)
                all_events.append(ev)

        def sort_key(ev: dict) -> str:
            s = ev.get("start", {})
            return s.get("dateTime", s.get("date", ""))

        all_events.sort(key=sort_key)
        return all_events

    def get_display_data(self, days: int = 7, selected_calendars: list[str] | None = None) -> dict[str, Any] | None:
        """Strukturierte Kalender-Daten für Display-Ausgabe."""
        events    = self.get_events_upcoming(days=days, selected_calendars=selected_calendars)
        now_local = datetime.now()
        today     = now_local.date()
        tomorrow  = today + timedelta(days=1)

        next_event: dict | None = None
        days_dict: dict[str, dict] = {}

        for ev in events:
            start_raw = ev.get("start", {})
            is_allday = "date" in start_raw and "dateTime" not in start_raw

            if is_allday:
                date_str = start_raw.get("date", "")[:10]
                try:
                    ev_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except Exception:
                    continue
                start_str = "Ganztags"
            else:
                try:
                    dt_str = start_raw["dateTime"][:19]
                    dt     = datetime.fromisoformat(dt_str)
                    ev_date   = dt.date()
                    start_str = dt.strftime("%H:%M")
                    if dt > now_local and next_event is None:
                        next_event = {
                            "time":     start_str,
                            "title":    ev.get("summary", "–"),
                            "location": ev.get("location") or "",
                            "calendar": ev.get("_calendar", ""),
                            "weekday":  _DE_WEEKDAYS[dt.weekday()],
                            "date":     f"{dt.day:02d}. {_DE_MONTHS[dt.month - 1]}",
                        }
                except Exception:
                    continue

            date_key = ev_date.isoformat()
            if date_key not in days_dict:
                if ev_date == today:
                    label = "Heute"
                elif ev_date == tomorrow:
                    label = "Morgen"
                else:
                    label = _DE_WEEKDAYS[ev_date.weekday()]
                days_dict[date_key] = {
                    "date_key": date_key,
                    "label":    label,
                    "date":     f"{ev_date.day:02d}. {_DE_MONTHS[ev_date.month - 1]}",
                    "weekday":  _DE_WEEKDAYS[ev_date.weekday()],
                    "events":   [],
                }

            # Endzeit
            end_raw = ev.get("end", {})
            end_str = ""
            if not is_allday and "dateTime" in end_raw:
                try:
                    end_dt = datetime.fromisoformat(end_raw["dateTime"][:19])
                    end_str = end_dt.strftime("%H:%M")
                except Exception:
                    pass

            days_dict[date_key]["events"].append({
                "time":        start_str,
                "end_time":    end_str,
                "title":       ev.get("summary", "–"),
                "location":    ev.get("location") or "",
                "description": ev.get("description") or "",
                "calendar":    ev.get("_calendar", ""),
                "is_allday":   is_allday,
            })

        days = [days_dict[k] for k in sorted(days_dict.keys())]
        total = sum(len(d["events"]) for d in days)

        return {
            "date":        _de_date(now_local),
            "days":        days,
            "next_event":  next_event,
            "total_count": total,
        }

    # ── PV Statistiken ──────────────────────────────────────────

    def get_pv_statistics(
        self,
        statistic_ids: list[str],
        start: datetime,
        end: datetime,
        period: str,
        types: list[str],
    ) -> dict[str, list[dict]]:
        payload = {
            "start_time": start.isoformat(),
            "end_time":   end.isoformat(),
            "statistic_ids": statistic_ids,
            "period": period,
            "types": types,
        }
        result = self._post("/statistics_during_period", payload)
        return result if isinstance(result, dict) else {}

    def get_history(self, entity_id: str, start: datetime, end: datetime) -> list[dict]:
        """Rohe Zustandshistorie eines Sensors (Fallback wenn Statistics API leer)."""
        fmt = "%Y-%m-%dT%H:%M:%S"
        params = urllib.parse.urlencode({
            "filter_entity_id": entity_id,
            "end_time": end.strftime(fmt),
            "minimal_response": "true",
            "no_attributes": "true",
        })
        path = f"/history/period/{start.strftime(fmt)}?{params}"
        result = self._get(path)
        if isinstance(result, list) and result:
            return result[0] if isinstance(result[0], list) else result
        return []

    # ── Kameras (Ring) ──────────────────────────────────────────

    def get_cameras(self) -> list[dict]:
        """Alle camera.* Entities mit MJPEG-Stream- und Snapshot-URL."""
        states = self._get("/states")
        if not isinstance(states, list):
            return []
        cameras = []
        for s in states:
            eid = s.get("entity_id", "")
            if not eid.startswith("camera."):
                continue
            attrs  = s.get("attributes", {})
            token  = attrs.get("access_token", "")
            cameras.append({
                "entity_id":    eid,
                "name":         attrs.get("friendly_name", eid.split(".", 1)[-1]),
                "state":        s.get("state", "unavailable"),
                "stream_url":   f"{self._base_url}/api/camera_proxy_stream/{eid}?token={token}" if token else None,
                "snapshot_url": f"{self._base_url}/api/camera_proxy/{eid}?token={token}" if token else None,
                "last_changed": s.get("last_changed", ""),
            })
        cameras.sort(key=lambda x: x["name"].lower())
        return cameras

    # Kamera-Namen → Device-ID Mapping (für Event-Erkennung)
    _CAM_NAMES = {
        "haustur": "Haustür",
        "garten":  "Garten",
        "terrasse": "Terrasse",
    }

    # ring-mqtt: _ding / _motion  |  native Ring (DE): _klingeln / _bewegung
    _DING_WORDS   = ("ding", "klingeln", "klingel")
    _MOTION_WORDS = ("motion", "bewegung")

    # Kameranamen normalisiert (Umlaute → ASCII) für Entity-Matching
    _CAM_NAMES_NORM = {
        "haustur":  "Haustür",   # ring-mqtt
        "haustür":  "Haustür",   # native Ring (Umlaut)
        "garten":   "Garten",
        "terrasse": "Terrasse",
    }

    def get_camera_events(self, limit: int = 50) -> list[dict]:
        """
        Letzte Ring-Events via HA Logbook (24h).
        Unterstützt ring-mqtt (motion/ding) und native Ring Integration (bewegung/klingeln).
        """
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        data  = self._get(f"/logbook/{since}")
        if not isinstance(data, list):
            return []

        events = []
        for e in data:
            eid   = (e.get("entity_id") or "").lower()
            state = e.get("state", "")
            if not eid.startswith("binary_sensor.") or state != "on":
                continue
            cam_name = next(
                (label for key, label in self._CAM_NAMES_NORM.items() if key in eid),
                None,
            )
            if not cam_name:
                continue
            if any(w in eid for w in self._DING_WORDS):
                event_type = "ding"
            elif any(w in eid for w in self._MOTION_WORDS):
                event_type = "motion"
            else:
                continue
            events.append({
                "entity_id": eid,
                "name":      cam_name,
                "state":     state,
                "when":      e.get("when", ""),
                "type":      event_type,
            })

        events.sort(key=lambda x: x["when"], reverse=True)
        return events[:limit]

    def get_doorbell_sensors(self) -> list[dict]:
        """Ring Klingel-Sensoren für Echtzeit-Erkennung (ring-mqtt + native Ring Integration)."""
        states = self._get("/states")
        if not isinstance(states, list):
            return []
        result = []
        for s in states:
            eid = s.get("entity_id", "")
            is_ding = (
                any(w in eid.lower() for w in self._DING_WORDS)
                and eid.startswith("binary_sensor.")
            )
            if not is_ding:
                continue
            attrs = s.get("attributes", {})
            result.append({
                "entity_id":    eid,
                "name":         attrs.get("friendly_name", eid),
                "state":        s.get("state", "off"),
                "last_changed": s.get("last_changed", ""),
            })
        return result
