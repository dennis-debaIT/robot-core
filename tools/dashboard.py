#!/usr/bin/env python3
"""
Erika Terminal Dashboard — vollflächige Konsolenansicht

Anforderungen:
    pip install rich

Aufruf:
    python3 tools/dashboard.py           # Standard (localhost:8000, Refresh 30s)
    python3 tools/dashboard.py --host 192.168.1.100 --refresh 10
    python3 tools/dashboard.py --help
"""
from __future__ import annotations

import argparse
import json
import signal
import ssl
import sys
import time
import urllib.request
from datetime import datetime
from typing import Any

try:
    from zoneinfo import ZoneInfo
    _TZ: Any = ZoneInfo("Europe/Berlin")
except Exception:
    _TZ = None

try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text
except ImportError:
    print("Bitte 'pip install rich' ausführen.", file=sys.stderr)
    sys.exit(1)

# ── Konfiguration ──────────────────────────────────────────────────────────────
_ARGS: argparse.Namespace | None = None
_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE

_SPARK = "▁▂▃▄▅▆▇█"
_DAYS_DE  = ["Mo","Di","Mi","Do","Fr","Sa","So"]
_MONTHS_DE = ["Januar","Februar","März","April","Mai","Juni","Juli",
              "August","September","Oktober","November","Dezember"]
_WEEKDAYS_DE = ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"]


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────
def _base() -> str:
    return f"https://{_ARGS.host}:{_ARGS.port}" if _ARGS else "https://localhost:8000"


def _get(path: str) -> Any:
    try:
        req = urllib.request.Request(
            f"{_base()}{path}",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, context=_SSL, timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _now() -> datetime:
    return datetime.now(_TZ) if _TZ else datetime.now()


def _bar(pct: float, width: int = 14) -> str:
    filled = max(0, min(width, int(pct / 100 * width)))
    return "█" * filled + "░" * (width - filled)


def _spark_line(values: list[float], width: int = 20) -> str:
    if not values:
        return "─" * width
    mn, mx = min(values), max(values)
    if mx <= mn:
        return _SPARK[0] * width
    step = max(1, len(values) // width)
    result = ""
    for i in range(0, len(values), step):
        chunk = values[i : i + step]
        avg = sum(chunk) / len(chunk)
        idx = int((avg - mn) / (mx - mn) * (len(_SPARK) - 1))
        result += _SPARK[idx]
        if len(result) >= width:
            break
    return result.ljust(width, _SPARK[0])


def _weather_icon(code: int | None) -> str:
    if code is None:
        return " "
    if code == 0:            return "☀ "
    if code in (1,):         return "🌤"
    if code in (2,):         return "⛅"
    if code in (3,):         return "☁ "
    if code in (45, 48):     return "🌫"
    if code in (51,53,55):   return "🌦"
    if 61 <= code <= 67:     return "🌧"
    if 71 <= code <= 77:     return "❄ "
    if 80 <= code <= 82:     return "🌦"
    if 95 <= code <= 99:     return "⛈ "
    return "  "


def _rel_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        if _TZ:
            dt = dt.astimezone(_TZ)
        diff = int((_now().replace(tzinfo=dt.tzinfo) - dt).total_seconds() / 60)
        if diff < 1:   return "gerade"
        if diff < 60:  return f"vor {diff} Min"
        if diff < 1440: return f"vor {diff//60} Std"
        return f"vor {diff//1440}d"
    except Exception:
        return ""


def _robot_state_label(state: str) -> tuple[str, str]:
    s = (state or "").lower()
    mapping = {
        "cleaning": ("🧹", "Saugt"),
        "docked":   ("⚡", "Basis"),
        "idle":     ("💤", "Bereit"),
        "returning":("↩ ", "Kehrt zurück"),
        "error":    ("⚠ ", "Fehler"),
        "charging": ("⚡", "Lädt"),
        "paused":   ("⏸ ", "Pausiert"),
        "unavailable": ("✗ ", "Offline"),
    }
    return mapping.get(s, ("  ", state or "?"))


# ── Panel-Builder ──────────────────────────────────────────────────────────────
def _panel_weather(data: Any) -> Panel:
    t = Text()
    if not data:
        t.append("  Keine Daten verfügbar", style="dim")
        return Panel(t, title="[bold blue]🌤  WETTER[/]", border_style="blue", padding=(0, 1))

    curr  = data.get("current") or {}
    today = data.get("today") or {}
    icon  = _weather_icon(curr.get("weather_code"))
    temp  = curr.get("temperature", "?")
    cond  = curr.get("condition", "")
    wind  = curr.get("wind_speed", "?")
    rain  = curr.get("precipitation") or 0

    t.append(f"  {icon} {temp}°C  {cond}\n", style="bold white")
    t.append(f"  Wind {wind} km/h", style="dim")
    if rain:
        t.append(f"  ↓ {rain} mm", style="cyan")
    t.append(f"\n  Max {today.get('max_temp','?')}°  Min {today.get('min_temp','?')}°\n", style="dim")

    # Stunden-Forecast
    hourly = data.get("hourly") or []
    now_h  = _now().hour
    upcoming = [h for h in hourly if h.get("hour", -1) >= now_h][:10]
    if upcoming:
        t.append("\n  [bold dim]STUNDEN[/]\n")
        temps  = [h.get("temperature", 0) for h in upcoming]
        t_min, t_max = min(temps), max(temps)
        span   = max(t_max - t_min, 1)
        for h in upcoming:
            hour  = h.get("hour", 0)
            htemp = h.get("temperature", 0)
            hicon = _weather_icon(h.get("weather_code"))
            filled = max(0, int((htemp - t_min) / span * 12))
            bar    = "█" * filled + "░" * (12 - filled)
            rain_h = h.get("precipitation_probability") or 0
            t.append(f"  {hour:02d}h ", style="dim")
            t.append(f"{bar} ", style="cyan")
            t.append(f"{htemp:+.0f}° ", style="bold white")
            t.append(f"{hicon}", style="white")
            if rain_h >= 20:
                t.append(f" {rain_h:2.0f}%", style="blue")
            t.append("\n")

    # 5-Tage-Vorschau
    forecast = data.get("forecast_days") or []
    if forecast:
        t.append("\n  [bold dim]5 TAGE[/]\n")
        for day in forecast[:5]:
            try:
                dt    = datetime.fromisoformat(day.get("date",""))
                label = _DAYS_DE[dt.weekday()]
            except Exception:
                label = "??"
            ficon = _weather_icon(day.get("weather_code"))
            fmax  = day.get("max_temp","?")
            fmin  = day.get("min_temp","?")
            rain_d = day.get("precipitation_probability_max") or 0
            t.append(f"  {label} {ficon}  ", style="white")
            t.append(f"{fmax:>3}°", style="bold yellow")
            t.append(f"/{fmin:<3}°", style="dim")
            if rain_d >= 20:
                t.append(f"  {rain_d:.0f}%🌧", style="blue")
            t.append("\n")

    return Panel(t, title="[bold blue]🌤  WETTER[/]", border_style="blue", padding=(0, 1))


def _panel_calendar(data: Any) -> Panel:
    t = Text()
    if not data:
        t.append("  Keine Daten verfügbar", style="dim")
        return Panel(t, title="[bold green]📅  TERMINE[/]", border_style="green", padding=(0, 1))

    days   = data.get("days") or []
    shown  = 0
    for day in days[:4]:
        events = day.get("events") or []
        if not events:
            continue
        label = day.get("label","")
        date  = day.get("date","")
        t.append(f"  [bold dim]{label}  {date}[/]\n")
        for ev in events:
            evtime = ev.get("time","")
            title  = ev.get("title","")
            allday = not evtime or evtime.lower() in ("ganztags","00:00")
            if allday:
                t.append(f"   Ganztags  ", style="dim")
                t.append(f"{title}\n", style="white")
            else:
                t.append(f"   {evtime}  ", style="bold cyan")
                t.append(f"{title}\n", style="white")
        shown += 1
        if shown < 3:
            t.append("\n")

    if not shown:
        t.append("  Keine Termine", style="dim")

    return Panel(t, title="[bold green]📅  TERMINE[/]", border_style="green", padding=(0, 1))


def _panel_fuel(data: Any) -> Panel:
    t = Text()
    if not data:
        t.append("  Keine Daten verfügbar", style="dim")
        return Panel(t, title="[bold yellow]⛽  KRAFTSTOFF[/]", border_style="yellow", padding=(0, 1))

    station = (data.get("station") or {}).get("name","")
    if station:
        t.append(f"  {station}\n\n", style="dim")

    prices = data.get("prices") or {}
    LABELS = {"diesel":"Diesel","super":"Super E5","e10":"E10","super_e5":"Super E5"}
    for key, info in prices.items():
        if not isinstance(info, dict):
            continue
        price = info.get("price")
        if price is None:
            continue
        trend = info.get("trend","")
        tsym  = "▲" if trend == "up" else ("▼" if trend == "down" else " ")
        tstyle= "red" if trend == "up" else ("green" if trend == "down" else "dim")
        label = LABELS.get(key, key.capitalize())
        t.append(f"  {label:<12}", style="white")
        t.append(f"{price:.3f} €  ", style="bold yellow")
        t.append(f"{tsym}\n", style=tstyle)

    return Panel(t, title="[bold yellow]⛽  KRAFTSTOFF[/]", border_style="yellow", padding=(0, 1))


def _panel_cameras(data: Any) -> Panel:
    t = Text()
    events = []
    if isinstance(data, dict):
        events = data.get("events") or []
    elif isinstance(data, list):
        events = data

    if not events:
        t.append("  Keine Ereignisse", style="dim")
        return Panel(t, title="[bold cyan]📷  KAMERA-EREIGNISSE[/]", border_style="cyan", padding=(0, 1))

    for ev in events[:7]:
        name  = ev.get("name","")
        etype = ev.get("type","")
        when  = ev.get("when","")
        icon  = "🔔" if etype == "ding" else "🏃"
        label = "Klingel" if etype == "ding" else "Bewegung"
        rel   = _rel_time(when)
        t.append(f"  {icon} {name:<14}", style="white")
        t.append(f"{label:<12}", style="dim")
        t.append(f"{rel}\n", style="cyan")

    return Panel(t, title="[bold cyan]📷  KAMERA-EREIGNISSE[/]", border_style="cyan", padding=(0, 1))


def _panel_vehicles(data: Any) -> Panel:
    t = Text()
    vehicles = (data or {}).get("vehicles") or []

    if not vehicles:
        t.append("  Keine Fahrzeuge konfiguriert", style="dim")
        return Panel(t, title="[bold magenta]🚗  FAHRZEUGE[/]", border_style="magenta", padding=(0, 1))

    for v in vehicles:
        label = v.get("label") or v.get("id","?")
        t.append(f"  🚗 {label}\n", style="bold white")

        # Energie (EV-Batterie oder Tank)
        battery = v.get("battery") or {}
        fuel    = v.get("fuel_level") or {}
        if battery and battery.get("state") not in (None,"unavailable","unknown"):
            pct = float(battery.get("state",0) or 0)
            col = "green" if pct > 30 else "red"
            t.append(f"     {_bar(pct,14)} {pct:.0f}%\n", style=col)
        elif fuel and fuel.get("state") not in (None,"unavailable","unknown"):
            pct = float(fuel.get("state",0) or 0)
            col = "yellow" if pct > 15 else "red"
            t.append(f"     {_bar(pct,14)} {pct:.0f}%\n", style=col)

        # Reichweite
        rng = v.get("range") or {}
        if rng.get("state") not in (None,"unavailable","unknown"):
            t.append(f"     Reichweite  {rng.get('state','?')} {rng.get('unit','km')}\n", style="dim")

        # Ladestatus
        chg = v.get("charging") or {}
        if (chg.get("state") or "").lower() in ("on","charging","in_charge","charge_in_progress"):
            t.append("     ⚡ Lädt\n", style="bold yellow")

        # Standort
        loc = v.get("location") or {}
        loc_s = loc.get("state","")
        if loc_s and loc_s not in ("unavailable","unknown",""):
            t.append(f"     📍 {loc_s}\n", style="dim")

        t.append("\n")

    return Panel(t, title="[bold magenta]🚗  FAHRZEUGE[/]", border_style="magenta", padding=(0, 1))


def _panel_robots(data: Any) -> Panel:
    t = Text()
    robots = (data or {}).get("robots") or []

    if not robots:
        t.append("  Keine Roboter konfiguriert", style="dim")
        return Panel(t, title="[bold yellow]🤖  ROBOTER[/]", border_style="yellow", padding=(0, 1))

    for r in robots:
        name    = r.get("name","?")
        state   = r.get("state","")
        battery = r.get("battery_level")
        icon, label = _robot_state_label(state)
        col = "cyan" if "saug" in label.lower() or state.lower()=="cleaning" else "dim"
        t.append(f"  {icon} {name:<16}", style="bold white")
        t.append(f"{label}", style=col)
        if battery is not None:
            pct = int(battery or 0)
            col2 = "green" if pct > 20 else "red"
            t.append(f"  {pct}%", style=col2)
        t.append("\n")

    return Panel(t, title="[bold yellow]🤖  ROBOTER[/]", border_style="yellow", padding=(0, 1))


def _pv_val(st: dict, key: str) -> float | None:
    """Extrahiert float-Wert aus PV-State-Struktur: {"power": {"value": "3400", ...}}"""
    entry = st.get(key)
    if entry is None:
        return None
    if isinstance(entry, dict):
        v = entry.get("value")
    else:
        v = entry
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _panel_pv(state_data: Any, history_data: Any) -> Panel:
    t = Text()
    if not state_data:
        t.append("  Keine Daten verfügbar", style="dim")
        return Panel(t, title="[bold yellow]☀   PV-ANLAGE[/]", border_style="yellow", padding=(0, 1))

    st    = (state_data.get("state") or {})
    power = _pv_val(st, "power")
    daily = _pv_val(st, "daily")
    bat   = _pv_val(st, "battery")
    grid  = _pv_val(st, "grid")
    house = _pv_val(st, "house_consumption")

    if power is not None:
        t.append(f"  ☀  Leistung    {power:>7.0f} W\n", style="bold yellow")
    if daily is not None:
        t.append(f"  📊 Heute       {daily:>7.1f} kWh\n", style="white")
    if house is not None and house > 0:
        t.append(f"  🏠 Verbrauch   {house:>7.0f} W\n", style="dim")

    if bat is not None:
        col = "green" if bat > 20 else "red"
        t.append(f"  🔋 Batterie    {_bar(bat,12)} {bat:.0f}%\n", style=col)

    if grid is not None:
        if grid >= 0:
            t.append(f"  ⬆  Einspeisung {grid:>6.0f} W\n", style="green")
        else:
            t.append(f"  ⬇  Bezug       {abs(grid):>6.0f} W\n", style="red")

    # Sparkline aus Tagesverlauf
    points: list[float] = []
    if isinstance(history_data, dict):
        for entry in (history_data.get("points") or []):
            v = entry.get("power_w") or entry.get("value") or entry.get("power")
            if v is not None:
                try:
                    points.append(float(v))
                except Exception:
                    pass

    if len(points) >= 4:
        spark = _spark_line(points, width=28)
        mx = max(points)
        t.append(f"\n  [dim]TAGESVERLAUF[/]\n")
        t.append(f"  [yellow]{spark}[/]\n")
        t.append(f"  [dim]0{'':>20}{mx:.0f} W[/]\n")

    return Panel(t, title="[bold yellow]☀   PV-ANLAGE[/]", border_style="yellow", padding=(0, 1))


def _header() -> Panel:
    now = _now()
    t = Text(justify="center")
    t.append("E R I K A", style="bold cyan")
    t.append("   ", style="white")
    t.append(now.strftime("%H:%M"), style="bold white")
    t.append("  ·  ", style="dim")
    t.append(f"{_WEEKDAYS_DE[now.weekday()]}, {now.day}. {_MONTHS_DE[now.month-1]} {now.year}", style="dim")
    return Panel(t, border_style="cyan", padding=(0, 2))


# ── Daten laden ────────────────────────────────────────────────────────────────
def _fetch() -> dict[str, Any]:
    return {
        "weather":   _get("/weather"),
        "calendar":  _get("/calendar"),
        "vehicles":  _get("/vehicles"),
        "fuel":      _get("/fuel"),
        "cameras":   _get("/ha/cameras/events"),
        "robots":    _get("/ha/robots"),
        "pv_state":  _get("/ha/pv/state"),
        "pv_history":_get("/ha/pv/history?view=today"),
    }


# ── Layout zusammenbauen ───────────────────────────────────────────────────────
def _build(d: dict[str, Any]) -> Layout:
    root = Layout()
    root.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
    )
    root["body"].split_row(
        Layout(name="col_left",   ratio=4),
        Layout(name="col_mid",    ratio=3),
        Layout(name="col_right",  ratio=3),
    )

    # Spalte links: Wetter (voll)
    root["header"].update(_header())
    root["col_left"].update(_panel_weather(d["weather"]))

    # Spalte mitte: Termine + Kraftstoff + Kamera
    col_mid = Layout()
    col_mid.split_column(
        Layout(name="cal",    ratio=5),
        Layout(name="fuel",   ratio=2),
        Layout(name="camera", ratio=4),
    )
    col_mid["cal"].update(_panel_calendar(d["calendar"]))
    col_mid["fuel"].update(_panel_fuel(d["fuel"]))
    col_mid["camera"].update(_panel_cameras(d["cameras"]))
    root["col_mid"].update(col_mid)

    # Spalte rechts: Fahrzeuge + Roboter + PV
    col_right = Layout()
    col_right.split_column(
        Layout(name="veh",    ratio=4),
        Layout(name="robots", ratio=2),
        Layout(name="pv",     ratio=4),
    )
    col_right["veh"].update(_panel_vehicles(d["vehicles"]))
    col_right["robots"].update(_panel_robots(d["robots"]))
    col_right["pv"].update(_panel_pv(d["pv_state"], d["pv_history"]))
    root["col_right"].update(col_right)

    return root


# ── Einstiegspunkt ─────────────────────────────────────────────────────────────
def main() -> None:
    global _ARGS
    parser = argparse.ArgumentParser(description="Erika Terminal Dashboard")
    parser.add_argument("--host",    default="localhost", help="Erika-Host (default: localhost)")
    parser.add_argument("--port",    default=8000, type=int, help="Port (default: 8000)")
    parser.add_argument("--refresh", default=30,   type=int, help="Refresh in Sekunden (default: 30)")
    _ARGS = parser.parse_args()

    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))

    console = Console()
    data    = _fetch()
    layout  = _build(data)
    last_fetch = time.time()

    with Live(layout, console=console, screen=True, refresh_per_second=2) as live:
        while True:
            elapsed = time.time() - last_fetch
            if elapsed >= _ARGS.refresh:
                data       = _fetch()
                last_fetch = time.time()

            # Header jede Sekunde aktualisieren (Uhrzeit)
            layout["header"].update(_header())
            live.update(layout)
            time.sleep(0.5)


if __name__ == "__main__":
    main()
