#!/usr/bin/env python3
"""
Erika Terminal Dashboard — vollflächige Konsolenansicht

Anforderungen:  pip install rich   (oder: sudo apt install python3-rich)
Aufruf:         python3 tools/dashboard.py
                python3 tools/dashboard.py --host 192.168.1.243 --refresh 15
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
    from rich.table import Table
    from rich.text import Text
    if not hasattr(Layout(), "split_column"):
        print(
            "rich ist zu alt (split_column fehlt, mindestens Version 10 benötigt).\n"
            "Bitte upgraden:\n"
            "  pip install 'rich>=10.0' --user\n"
            "  # oder: pip install 'rich>=10.0' --break-system-packages",
            file=sys.stderr,
        )
        sys.exit(1)
except ImportError:
    print(
        "rich ist nicht installiert.\n"
        "  sudo apt install python3-rich\n"
        "  pip install rich --user",
        file=sys.stderr,
    )
    sys.exit(1)

_ARGS: argparse.Namespace | None = None
_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE
_EMOJI = True  # wird in main() gesetzt

_SPARK     = "▁▂▃▄▅▆▇█"
_DAYS_DE   = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
_MONTHS_DE = ["Januar","Februar","März","April","Mai","Juni","Juli",
              "August","September","Oktober","November","Dezember"]
_WDAYS_DE  = ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"]

# Wetter-Icons: (emoji, ascii) — ascii immer 2 Zeichen für saubere Ausrichtung
_WICONS: dict[str, tuple[str, str]] = {
    "sun":    ("☀ ", "**"),
    "sun_cl": ("🌤", "*~"),
    "cloud":  ("⛅", "~~"),
    "ocast":  ("☁ ", "oo"),
    "fog":    ("🌫", "fg"),
    "drizzle":("🌦", "dr"),
    "rain":   ("🌧", "//"),
    "snow":   ("❄ ", "**"),
    "storm":  ("⛈ ", "!!"),
    "unk":    ("   ", "  "),
}

def _icon(key: str) -> str:
    pair = _WICONS.get(key, _WICONS["unk"])
    return pair[0] if _EMOJI else pair[1]

def _e(emoji: str, ascii: str) -> str:
    """Gibt Emoji oder 2-Zeichen-ASCII zurück je nach Modus."""
    return emoji if _EMOJI else ascii

def _ptitle(emoji: str, label: str) -> str:
    return f"{emoji}  {label}" if _EMOJI else label


# ── Netzwerk ───────────────────────────────────────────────────────────────────
def _base() -> str:
    return f"https://{_ARGS.host}:{_ARGS.port}" if _ARGS else "https://localhost:8000"


def _get(path: str) -> Any:
    try:
        req = urllib.request.Request(
            f"{_base()}{path}", headers={"Accept": "application/json"}
        )
        with urllib.request.urlopen(req, context=_SSL, timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        return None


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────
def _now() -> datetime:
    return datetime.now(_TZ) if _TZ else datetime.now()


def _flt(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _bar(pct: float, width: int = 14) -> str:
    filled = max(0, min(width, int(pct / 100 * width)))
    return "█" * filled + "░" * (width - filled)


def _spark_line(values: list[float], width: int = 24) -> str:
    if not values:
        return "─" * width
    mn, mx = min(values), max(values)
    if mx <= mn:
        return _SPARK[0] * width
    out = ""
    step = max(1, len(values) // width)
    for i in range(0, len(values), step):
        chunk = values[i: i + step]
        avg = sum(chunk) / len(chunk)
        idx = int((avg - mn) / (mx - mn) * (len(_SPARK) - 1))
        out += _SPARK[idx]
        if len(out) >= width:
            break
    return out.ljust(width, _SPARK[0])


def _wicon(code: int | None) -> str:
    if code is None:
        return _icon("unk")
    c = int(code)
    if c == 0:            return _icon("sun")
    if c == 1:            return _icon("sun_cl")
    if c == 2:            return _icon("cloud")
    if c == 3:            return _icon("ocast")
    if c in (45, 48):     return _icon("fog")
    if c in (51,53,55):   return _icon("drizzle")
    if 61 <= c <= 67:     return _icon("rain")
    if 71 <= c <= 77:     return _icon("snow")
    if 80 <= c <= 82:     return _icon("drizzle")
    if 95 <= c <= 99:     return _icon("storm")
    return _icon("unk")


def _rel_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        ref = _now()
        if dt.tzinfo:
            ref = ref.replace(tzinfo=dt.tzinfo)
        diff = int((ref - dt).total_seconds() / 60)
        if diff < 1:    return "gerade"
        if diff < 60:   return f"vor {diff} Min"
        if diff < 1440: return f"vor {diff // 60} Std"
        return f"vor {diff // 1440}d"
    except Exception:
        return ""


def _robot_label(state: str) -> tuple[str, str, str]:
    """(icon, label, style)"""
    s = (state or "").lower()
    if _EMOJI:
        m = {
            "cleaning":   ("🧹", "Saugt",        "cyan"),
            "sweeping":   ("🧹", "Kehrt",         "cyan"),
            "mopping":    ("🫧", "Wischt",         "cyan"),
            "drying":     ("💨", "Trocknet",       "cyan"),
            "washing":    ("🫧", "Wäscht",         "cyan"),
            "docked":     ("⚡", "Basis",           "dim"),
            "idle":       ("💤", "Bereit",          "dim"),
            "returning":  ("↩ ", "Kehrt zurück",    "yellow"),
            "error":      ("⚠ ", "Fehler",          "red"),
            "charging":   ("⚡", "Lädt",            "green"),
            "paused":     ("⏸ ", "Pausiert",         "yellow"),
            "unavailable":("✗ ", "Offline",          "dim"),
        }
    else:
        m = {
            "cleaning":   (">>", "Saugt",        "cyan"),
            "sweeping":   (">>", "Kehrt",         "cyan"),
            "mopping":    ("~~", "Wischt",         "cyan"),
            "drying":     ("~~", "Trocknet",       "cyan"),
            "washing":    ("~~", "Wäscht",         "cyan"),
            "docked":     ("[]", "Basis",           "dim"),
            "idle":       ("--", "Bereit",          "dim"),
            "returning":  ("<-", "Kehrt zurück",    "yellow"),
            "error":      ("!!", "Fehler",          "red"),
            "charging":   ("+=", "Lädt",            "green"),
            "paused":     ("||", "Pausiert",         "yellow"),
            "unavailable":("xx", "Offline",          "dim"),
        }
    return m.get(s, ("??", state or "?", "dim"))


# ── Panel: Wetter ──────────────────────────────────────────────────────────────
def _panel_weather(data: Any) -> Panel:
    t = Text()
    if not data:
        t.append("  Keine Wetterdaten verfügbar\n", style="dim")
        return Panel(t, title=_ptitle("🌤", "WETTER"), border_style="blue", padding=(0, 1))

    curr  = data.get("current") or {}
    today = data.get("today") or {}

    temp  = curr.get("temperature", "?")
    wspd  = curr.get("windspeed", "?")
    prec  = curr.get("precipitation", 0)
    code  = curr.get("weathercode")
    desc  = curr.get("description", "")
    icon  = _wicon(code)

    t.append(f"  {icon} {temp}°C  {desc}\n", style="bold white")
    t.append(f"  Wind {wspd} km/h", style="dim")
    if prec:
        t.append(f"  ↓ {prec} mm", style="cyan")
    t_max = today.get("temp_max", "?")
    t_min = today.get("temp_min", "?")
    t.append(f"\n  Max {t_max}°  Min {t_min}°\n", style="dim")

    # Stunden-Forecast: hourly_by_day hat alle Tagesstunden, forecast_hours nur konfigurierte
    today_str = _now().strftime("%Y-%m-%d")
    now_h     = _now().hour
    by_day    = data.get("hourly_by_day") or {}
    hours: list = []
    for h in (by_day.get(today_str) or []):
        try:
            if int(str(h.get("time","0"))[:2]) >= now_h:
                hours.append(h)
        except Exception:
            pass
    if not hours:
        hours = data.get("forecast_hours") or []
    if hours:
        t.append("\n  STUNDEN\n", style="bold dim")
        temps = [_flt(h.get("temp")) for h in hours[:14]]
        t_mn  = min(temps) if temps else 0
        t_mx  = max(temps) if temps else 1
        span  = max(t_mx - t_mn, 1)
        for h in hours[:14]:
            htime = h.get("time", "")[:5]
            htemp = _flt(h.get("temp"))
            hcode = h.get("code")
            hicon = _wicon(hcode)
            prob   = h.get("precip_prob", 0) or 0
            precip = _flt(h.get("precipitation", 0))
            filled = max(0, int((htemp - t_mn) / span * 10))
            bar    = "█" * filled + "░" * (10 - filled)
            t.append(f"  {htime} ", style="dim")
            t.append(f"{bar} ", style="yellow")
            t.append(f"{htemp:+3.0f}° {hicon} ", style="white")
            t.append(f"{prob:3.0f}% ", style="blue" if prob >= 20 else "dim")
            t.append(f"{precip:4.1f}mm\n", style="cyan" if precip > 0 else "dim")

    # 5-Tage-Vorschau
    forecast = data.get("forecast_days") or []
    if forecast:
        t.append("\n  5 TAGE\n", style="bold dim")
        for day in forecast[:5]:
            label = day.get("label", "?")[:2]
            fcode = day.get("weathercode")
            ficon = _wicon(fcode)
            fmax  = day.get("temp_max", "?")
            fmin  = day.get("temp_min", "?")
            precip = day.get("precipitation", 0) or 0
            t.append(f"  {label} {ficon} ", style="white")
            t.append(f"{fmax:>3}°", style="bold yellow")
            t.append(f"/{fmin:<3}°", style="dim")
            if precip >= 1:
                t.append(f"  ↓{precip}mm", style="blue")
            t.append("\n")

    return Panel(t, title="🌤  WETTER", border_style="blue", padding=(0, 1))


# ── Panel: Termine ─────────────────────────────────────────────────────────────
def _panel_calendar(data: Any) -> Panel:
    t = Text()
    if not data:
        t.append("  Keine Daten verfügbar\n", style="dim")
        return Panel(t, title=_ptitle("📅", "TERMINE"), border_style="green", padding=(0, 1))

    days  = data.get("days") or []
    shown = 0
    for day in days:
        events = day.get("events") or []
        if not events:
            continue
        label = day.get("label", "")
        date  = day.get("date", "")
        t.append(f"  {label}  {date}\n", style="bold dim")
        for ev in events:
            evtime = ev.get("time", "")
            title  = ev.get("title", "")
            allday = not evtime or evtime.lower() in ("ganztags", "00:00")
            if allday:
                t.append(f"   Ganztags  ", style="dim")
                t.append(f"{title}\n", style="white")
            else:
                t.append(f"   {evtime}  ", style="bold cyan")
                t.append(f"{title}\n", style="white")
        shown += 1
        t.append("\n")

    if not shown:
        t.append("  Keine Termine\n", style="dim")

    return Panel(t, title="📅  TERMINE", border_style="green", padding=(0, 1))


# ── Panel: Kraftstoff ──────────────────────────────────────────────────────────
def _panel_fuel(data: Any) -> Panel:
    t = Text()
    if not data:
        t.append("  Keine Daten verfügbar\n", style="dim")
        return Panel(t, title=_ptitle("⛽", "KRAFTSTOFF"), border_style="yellow", padding=(0, 1))

    cards = data.get("cards") or []
    if not cards:
        t.append("  Kraftstoff nicht konfiguriert\n", style="dim")
        return Panel(t, title=_ptitle("⛽", "KRAFTSTOFF"), border_style="yellow", padding=(0, 1))

    # Stations-Name aus erstem Eintrag
    station = (cards[0].get("primary") or {}).get("_station_name", "")
    if station:
        t.append(f"  {station}\n\n", style="dim")

    for card in cards:
        label   = card.get("label", card.get("id","?"))
        primary = card.get("primary") or {}
        price   = primary.get("price")
        if price is None:
            continue
        t.append(f"  {label:<14}", style="white")
        t.append(f"{float(price):.3f} €\n", style="bold yellow")

    updated_at = data.get("updated_at")
    if updated_at:
        try:
            dt = datetime.fromisoformat(updated_at)
            if _TZ:
                dt = dt.astimezone(_TZ)
            t.append(f"\n  Stand: {dt.strftime('%H:%M')} Uhr\n", style="dim")
        except Exception:
            pass

    return Panel(t, title="⛽  KRAFTSTOFF", border_style="yellow", padding=(0, 1))


# ── Panel: Kamera-Ereignisse ───────────────────────────────────────────────────
def _panel_cameras(data: Any) -> Panel:
    t = Text()
    events: list = []
    if isinstance(data, dict):
        events = data.get("events") or []
    elif isinstance(data, list):
        events = data

    if not events:
        t.append("  Keine Ereignisse\n", style="dim")
        return Panel(t, title=_ptitle("📷", "KAMERA-EREIGNISSE"), border_style="cyan", padding=(0, 1))

    for ev in events[:8]:
        name  = ev.get("name", "")
        etype = ev.get("type", "")
        when  = ev.get("when", "")
        icon  = _e("🔔","[K]") if etype == "ding" else _e("🏃","[B]")
        label = "Klingel" if etype == "ding" else "Bewegung"
        rel   = _rel_time(when)
        t.append(f"  {icon} {name:<14}", style="white")
        t.append(f"{label:<12}", style="dim")
        t.append(f"{rel}\n", style="cyan")

    return Panel(t, title="📷  KAMERA-EREIGNISSE", border_style="cyan", padding=(0, 1))


# ── Panel: Fahrzeuge ───────────────────────────────────────────────────────────
def _panel_vehicles(data: Any, addresses: dict | None = None) -> Panel:
    t = Text()
    vehicles = (data or {}).get("vehicles") or []

    if not vehicles:
        t.append("  Keine Fahrzeuge konfiguriert\n", style="dim")
        return Panel(t, title=_ptitle("🚗", "FAHRZEUGE"), border_style="magenta", padding=(0, 1))

    for v in vehicles:
        label = v.get("label") or v.get("id", "?")
        t.append(f"  {_e('🚗','>>')} {label}\n", style="bold white")

        battery = v.get("battery") or {}
        fuel    = v.get("fuel_level") or {}
        bstate  = battery.get("state") if battery else None
        fstate  = fuel.get("state") if fuel else None

        if bstate not in (None, "unavailable", "unknown", ""):
            pct = _flt(bstate)
            col = "green" if pct > 30 else "red"
            t.append(f"     {_bar(pct, 14)} {pct:.0f}%\n", style=col)
        elif fstate not in (None, "unavailable", "unknown", ""):
            pct = _flt(fstate)
            col = "yellow" if pct > 15 else "red"
            t.append(f"     {_bar(pct, 14)} {pct:.0f}%\n", style=col)

        rng = v.get("range") or {}
        if rng.get("state") not in (None, "unavailable", "unknown", ""):
            t.append(f"     Reichweite  {rng.get('state','?')} {rng.get('unit','km')}\n", style="dim")

        chg = v.get("charging") or {}
        if (chg.get("state") or "").lower() in ("on","charging","in_charge","charge_in_progress"):
            t.append(f"     {_e('⚡','++')} Lädt\n", style="bold yellow")

        # Letzte bekannte Adresse aus Geocoding-Cache
        vid = v.get("id","")
        if addresses and vid in addresses:
            addr_info = addresses[vid]
            addr = addr_info.get("address","")
            when = addr_info.get("from","")
            if addr and addr != f"{addr_info.get('lat','')}, {addr_info.get('lon','')}":
                t.append(f"     {_e('📍','>>')} {addr}\n", style="dim")
            if when:
                t.append(f"     {_e('⏱ ','->')} {_rel_time(when)}\n", style="dim")
        else:
            loc = v.get("location") or {}
            ls  = loc.get("state", "")
            if ls and ls not in ("unavailable", "unknown", ""):
                t.append(f"     {_e('📍','>>')} {ls}\n", style="dim")
        t.append("\n")

    return Panel(t, title="🚗  FAHRZEUGE", border_style="magenta", padding=(0, 1))


# ── Panel: Roboter ─────────────────────────────────────────────────────────────
def _panel_robots(data: Any) -> Panel:
    t = Text()
    robots = (data or {}).get("robots") or []

    if not robots:
        t.append("  Keine Roboter konfiguriert\n", style="dim")
        return Panel(t, title=_ptitle("🤖", "ROBOTER"), border_style="yellow", padding=(0, 1))

    for r in robots:
        name    = r.get("name", "?")
        state   = r.get("state", "")
        battery = r.get("battery_level")
        icon, label, style = _robot_label(state)
        t.append(f"  {icon} {name:<16}", style="bold white")
        t.append(f"{label}", style=style)
        if battery is not None:
            pct  = int(_flt(battery))
            col2 = "green" if pct > 20 else "red"
            t.append(f"  {pct}%", style=col2)
        t.append("\n")

    return Panel(t, title="🤖  ROBOTER", border_style="yellow", padding=(0, 1))


# ── Panel: News ────────────────────────────────────────────────────────────────
def _news_text(items: list, start: int, count: int) -> Text:
    t = Text()
    for item in items[start: start + count]:
        title  = item.get("title") or ""
        source = item.get("source_label") or item.get("source") or item.get("feed_label", "")
        pub    = item.get("pub_date") or ""
        rel    = _rel_time(pub) if pub else ""
        t.append(f" {title}\n", style="white")
        meta = " "
        if source:
            meta += source
        if rel:
            meta += f"  ·  {rel}"
        t.append(f"{meta}\n\n", style="dim")
    return t


def _panel_news(data: Any) -> Panel:
    raw = (data or {}).get("items") or []
    # Neueste zuerst
    try:
        items = sorted(raw, key=lambda x: x.get("pub_date",""), reverse=True)
    except Exception:
        items = raw
    if not items:
        t = Text()
        t.append("  Keine Neuigkeiten verfügbar\n", style="dim")
        return Panel(t, title=_ptitle("📰", "NACHRICHTEN"), border_style="white", padding=(0, 1))

    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(ratio=10)
    grid.add_column(width=1)
    grid.add_column(ratio=10)

    sep = Text("\n".join(["│"] * 9), style="dim")
    grid.add_row(_news_text(items, 0, 3), sep, _news_text(items, 3, 3))

    return Panel(grid, title="📰  NACHRICHTEN", border_style="white", padding=(0, 1))


# ── Panel: PV-Anlage ───────────────────────────────────────────────────────────
def _pv_val(st: dict, key: str) -> float | None:
    entry = st.get(key)
    if entry is None:
        return None
    v = entry.get("value") if isinstance(entry, dict) else entry
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _panel_pv(state_data: Any, history_data: Any) -> Panel:
    t = Text()
    if not state_data:
        t.append("  Keine Daten verfügbar\n", style="dim")
        return Panel(t, title=_ptitle("☀", "PV-ANLAGE"), border_style="yellow", padding=(0, 1))

    st    = state_data.get("state") or {}
    power = _pv_val(st, "power")
    daily = _pv_val(st, "daily")
    bat   = _pv_val(st, "battery")
    grid  = _pv_val(st, "grid")
    house = _pv_val(st, "house_consumption")

    if power is not None:
        t.append(f"  {_e('☀ ','PV')} Leistung    {power:>7.0f} W\n", style="bold yellow")
    if daily is not None:
        t.append(f"  {_e('📊','=>') } Heute       {daily:>7.1f} kWh\n", style="white")
    if house is not None and house > 0:
        t.append(f"  {_e('🏠','Hs')} Verbrauch   {house:>7.0f} W\n", style="dim")
    if bat is not None:
        col = "green" if bat > 20 else "red"
        t.append(f"  {_e('🔋','Bt')} Batterie    {_bar(bat, 12)} {bat:.0f}%\n", style=col)
    if grid is not None:
        if grid >= 0:
            t.append(f"  {_e('⬆ ','^^')} Einspeisung {grid:>6.0f} W\n", style="green")
        else:
            t.append(f"  {_e('⬇ ','vv')} Bezug       {abs(grid):>6.0f} W\n", style="red")

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
        spark = _spark_line(points, width=26)
        mx    = max(points)
        t.append("\n  TAGESVERLAUF\n", style="bold dim")
        t.append(f"  {spark}\n", style="yellow")
        t.append(f"  0{'':>20}{mx:.0f} W\n", style="dim")

    return Panel(t, title="☀   PV-ANLAGE", border_style="yellow", padding=(0, 1))


# ── Header ─────────────────────────────────────────────────────────────────────
def _header() -> Panel:
    now = _now()
    t   = Text(justify="center")
    t.append("E R I K A", style="bold cyan")
    t.append("   ", style="white")
    t.append(now.strftime("%H:%M"), style="bold white")
    t.append("  ·  ", style="dim")
    t.append(f"{_WDAYS_DE[now.weekday()]}, {now.day}. {_MONTHS_DE[now.month - 1]} {now.year}", style="dim")
    return Panel(t, border_style="cyan", padding=(0, 2))


# ── Daten laden ────────────────────────────────────────────────────────────────
def _fetch() -> dict[str, Any]:
    d: dict[str, Any] = {
        "weather":    _get("/weather"),
        "calendar":   _get("/calendar"),
        "vehicles":   _get("/vehicles"),
        "fuel":       _get("/fuel"),
        "cameras":    _get("/ha/cameras/events"),
        "robots":     _get("/ha/robots"),
        "pv_state":   _get("/ha/pv/state"),
        "pv_history": _get("/ha/pv/history?view=today"),
        "news":       _get("/news"),
        "addresses":  {},
    }
    # Letzte bekannte Adresse pro Fahrzeug (aus Geocoding-Cache, fast wenn gecacht)
    vehicles = (d["vehicles"] or {}).get("vehicles") or []
    for v in vehicles:
        vid = v.get("id","")
        if not vid:
            continue
        hist = _get(f"/vehicles/{vid}/location-history/addresses?days=1")
        locs = (hist or {}).get("locations") or []
        if locs:
            d["addresses"][vid] = locs[0]  # neuester Standort (absteigend sortiert)
    return d


# ── Layout ─────────────────────────────────────────────────────────────────────
def _build(d: dict[str, Any]) -> Layout:
    root = Layout()
    root.split_column(
        Layout(name="header", size=3),
        Layout(name="body",   ratio=9),
        Layout(name="news",   size=10),
    )
    root["body"].split_row(
        Layout(name="left",  ratio=4),
        Layout(name="mid",   ratio=3),
        Layout(name="right", ratio=3),
    )

    root["header"].update(_header())

    # Links: Wetter oben, Kraftstoff unten
    left = Layout()
    left.split_column(
        Layout(name="weather", ratio=7),
        Layout(name="fuel",    ratio=3),
    )
    left["weather"].update(_panel_weather(d["weather"]))
    left["fuel"].update(_panel_fuel(d["fuel"]))
    root["left"].update(left)

    # Mitte: Termine (groß) + Kamera-Ereignisse (klein)
    mid = Layout()
    mid.split_column(
        Layout(name="cal",    ratio=8),
        Layout(name="camera", ratio=2),
    )
    mid["cal"].update(_panel_calendar(d["calendar"]))
    mid["camera"].update(_panel_cameras(d["cameras"]))
    root["mid"].update(mid)

    right = Layout()
    right.split_column(
        Layout(name="veh",    ratio=5),
        Layout(name="robots", ratio=2),
        Layout(name="pv",     ratio=2),
    )
    right["veh"].update(_panel_vehicles(d["vehicles"], d.get("addresses")))
    right["robots"].update(_panel_robots(d["robots"]))
    right["pv"].update(_panel_pv(d["pv_state"], d["pv_history"]))
    root["right"].update(right)

    root["news"].update(_panel_news(d["news"]))

    return root


# ── Einstiegspunkt ─────────────────────────────────────────────────────────────
def main() -> None:
    global _ARGS
    parser = argparse.ArgumentParser(description="Erika Terminal Dashboard")
    parser.add_argument("--host",     default="localhost",  help="Erika-Host  (default: localhost)")
    parser.add_argument("--port",     default=8000, type=int, help="Port       (default: 8000)")
    parser.add_argument("--refresh",  default=30,  type=int, help="Refresh (s) (default: 30)")
    parser.add_argument("--no-emoji", dest="no_emoji", action="store_true",
                        help="ASCII-Modus: keine Emojis (für Terminals ohne Emoji-Schriftart)")
    _ARGS = parser.parse_args()

    global _EMOJI
    _EMOJI = not _ARGS.no_emoji

    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))

    console    = Console()
    data       = _fetch()
    layout     = _build(data)
    last_fetch = time.time()

    with Live(layout, console=console, screen=True, refresh_per_second=2) as live:
        while True:
            if time.time() - last_fetch >= _ARGS.refresh:
                data       = _fetch()
                last_fetch = time.time()
            layout["header"].update(_header())
            live.update(layout)
            time.sleep(0.5)


if __name__ == "__main__":
    main()
