from __future__ import annotations

import concurrent.futures as _cf
import json as _json
import time as _t
import urllib.request as _req
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from app.api.deps import DISPLAY_CSS, DISPLAY_INDEX
from app.database.db import get_connection, read_state
from app.services.integration_config_service import IntegrationConfigService
from app.services.news_feed_service import NewsFeedService


router = APIRouter()

_news_cache: dict[str, Any] = {"items": [], "fetched_at": 0.0, "source_ids": []}
_NEWS_TTL = 60


def _fetch_feed(feed: dict[str, Any]) -> list[dict[str, str]]:
    try:
        req = _req.Request(feed["url"], headers={"User-Agent": "Mozilla/5.0"})
        with _req.urlopen(req, timeout=10) as resp:
            root = ET.fromstring(resp.read())
    except Exception:
        return []

    items: list[dict[str, str]] = []
    if feed["fmt"] == "rss":
        channel = root.find("channel")
        for item in (channel.findall("item") if channel is not None else [])[:25]:
            title = (item.findtext("title") or "").strip()
            if not title:
                continue
            if feed.get("kicker"):
                kicker = (item.findtext("kicker") or "").strip()
                if kicker:
                    title = f"{kicker} - {title}"
            pub_raw = (item.findtext("pubDate") or "").strip()
            pub_iso = ""
            try:
                pub_iso = parsedate_to_datetime(pub_raw).isoformat()
            except Exception:
                try:
                    pub_iso = datetime.fromisoformat(pub_raw.replace("Z", "+00:00")).isoformat()
                except Exception:
                    pass
            items.append(
                {
                    "title": title,
                    "pub_date": pub_iso,
                    "source": feed["label"],
                    "source_key": feed["id"],
                    "icon_url": feed.get("icon_url"),
                }
            )
    else:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("a:entry", ns)[:25]:
            title = (entry.findtext("a:title", namespaces=ns) or "").strip()
            if not title:
                continue
            if any(title.lower().startswith(prefix) for prefix in feed.get("exclude_title_prefixes", [])):
                continue
            pub_raw = (
                entry.findtext("a:published", namespaces=ns)
                or entry.findtext("a:updated", namespaces=ns)
                or ""
            )
            try:
                pub_iso = datetime.fromisoformat(pub_raw.replace("Z", "+00:00")).isoformat()
            except Exception:
                pub_iso = ""
            items.append(
                {
                    "title": title,
                    "pub_date": pub_iso,
                    "source": feed["label"],
                    "source_key": feed["id"],
                    "icon_url": feed.get("icon_url"),
                }
            )
    return items


def _news_response(items: list[dict[str, Any]], cached: bool) -> dict[str, Any]:
    settings = IntegrationConfigService()
    lookback_hours = settings.get_news_lookback_hours()
    selected_sources = settings.get_news_selected_sources()
    display_settings = settings.get_news_display_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    def _pd(value: str) -> datetime:
        try:
            dt = datetime.fromisoformat(value)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)

    filtered = [item for item in items if _pd(item["pub_date"]) >= cutoff]
    return {
        "items": filtered,
        "cached": cached,
        "lookback_hours": lookback_hours,
        "display": display_settings,
        "sources": NewsFeedService().active_sources_payload(selected_sources),
    }


@router.get("/news")
def get_news() -> dict[str, Any]:
    now = _t.time()
    selected_source_ids = IntegrationConfigService().get_news_selected_sources()
    if (
        now - _news_cache["fetched_at"] < _NEWS_TTL
        and _news_cache["items"]
        and _news_cache.get("source_ids") == selected_source_ids
    ):
        return _news_response(_news_cache["items"], cached=True)

    try:
        feeds = NewsFeedService().active_feeds(selected_source_ids)
        with _cf.ThreadPoolExecutor(max_workers=2) as ex:
            results = list(ex.map(_fetch_feed, feeds))
        combined = [item for feed_items in results for item in feed_items]

        def _pd(value: str) -> datetime:
            try:
                dt = datetime.fromisoformat(value)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                return datetime.min.replace(tzinfo=timezone.utc)

        combined.sort(key=lambda item: _pd(item["pub_date"]), reverse=True)
        _news_cache["items"] = combined
        _news_cache["fetched_at"] = now
        _news_cache["source_ids"] = selected_source_ids
        return _news_response(combined, cached=False)
    except Exception as exc:
        if _news_cache["items"]:
            return _news_response(_news_cache["items"], cached=True)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/weather")
def get_weather_display(location: str | None = None) -> dict[str, Any]:
    from app.search.providers.weather import WeatherProvider

    if not IntegrationConfigService().get_weather_config().get("enabled", True):
        return {"enabled": False}
    result = WeatherProvider().get_display_data(location=location)
    if not result:
        raise HTTPException(status_code=503, detail="Wetterdaten nicht verfügbar")
    return result


@router.get("/display/state")
def get_display_state() -> dict[str, Any]:
    config = IntegrationConfigService().get_config()
    config_version = config.get("meta", {}).get("version", 1)
    def _has_entities(key: str) -> bool:
        return bool((config.get(key) or {}).get("selected_entities"))

    def _has_vehicles() -> bool:
        items = (config.get("vehicles") or {}).get("items") or []
        return any(
            v.get("location_entity") or v.get("battery_entity") or v.get("odometer_entity")
            for v in items
        )

    def _has_news() -> bool:
        news = config.get("news") or {}
        return bool(news.get("enabled")) and bool(news.get("selected_sources"))

    modules = {
        "news":     _has_news(),
        "lights":   bool((config.get("lights")   or {}).get("enabled", True)) and _has_entities("lights"),
        "vehicles": bool((config.get("vehicles") or {}).get("enabled", True)) and _has_vehicles(),
        "robots":   bool((config.get("robots")   or {}).get("enabled", True)) and _has_entities("robots"),
        "cameras":  bool((config.get("cameras")  or {}).get("enabled", True)) and _has_entities("cameras"),
    }
    with get_connection() as conn:
        raw = read_state(conn, "display_intent")
    if not raw:
        return {"mode": "idle", "config_version": config_version, "modules": modules}
    try:
        intent = _json.loads(raw) if isinstance(raw, str) else raw
        intent["config_version"] = config_version
        intent["modules"] = modules
        expires = intent.get("expires_at")
        if expires and datetime.now(timezone.utc) > datetime.fromisoformat(expires):
            return {"mode": "idle", "config_version": config_version, "modules": modules}
        return intent
    except Exception:
        return {"mode": "idle", "config_version": config_version, "modules": modules}


@router.get("/display")
def display_panel() -> FileResponse | RedirectResponse:
    with get_connection() as conn:
        state = read_state(conn, "setup_state", {}) or {}
    if not state.get("completed"):
        return RedirectResponse(url="/setup", status_code=302)
    return FileResponse(
        DISPLAY_INDEX,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/display.css")
def display_styles() -> FileResponse:
    return FileResponse(
        DISPLAY_CSS,
        media_type="text/css",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/calendar")
def get_calendar() -> dict[str, Any]:
    from app.search.providers.homeassistant import HomeAssistantProvider

    result = HomeAssistantProvider().get_display_data()
    if not result:
        raise HTTPException(status_code=503, detail="Kalender nicht verfügbar")
    return result


@router.get("/reply/latest")
def get_reply_latest() -> dict[str, Any]:
    with get_connection() as conn:
        raw = read_state(conn, "last_reply_text")
    if not raw or not isinstance(raw, dict):
        return {"text": None, "done": True}
    expires = raw.get("expires_at")
    if expires:
        try:
            if datetime.now(timezone.utc) > datetime.fromisoformat(expires):
                return {"text": None, "done": True}
        except Exception:
            pass
    return {"text": raw.get("text"), "done": raw.get("done", True)}


@router.get("/speech/latest")
def get_speech_latest() -> dict[str, Any]:
    with get_connection() as conn:
        raw = read_state(conn, "last_speech_text")
    if not raw:
        return {"text": None}
    expires = raw.get("expires_at") if isinstance(raw, dict) else None
    if expires:
        try:
            if datetime.now(timezone.utc) > datetime.fromisoformat(expires):
                return {"text": None}
        except Exception:
            pass
    return {"text": raw.get("text") if isinstance(raw, dict) else None}


@router.get("/football/league/{league_id}")
def get_league_table(league_id: str) -> dict[str, Any]:
    from app.search.providers.football import FootballProvider

    fp = FootballProvider()
    season = fp._season_year()
    league_names = {"bl1": "1. Bundesliga", "bl2": "2. Bundesliga", "bl3": "3. Liga"}
    league_name = league_names.get(league_id, league_id)
    table = fp._fetch_table(league_id, season)
    if not table:
        raise HTTPException(status_code=503, detail="Tabelle nicht verfügbar")
    full_table = [
        {
            "rank": i + 1,
            "teamName": row.get("teamName", ""),
            "shortName": row.get("shortName", ""),
            "iconUrl": row.get("teamIconUrl", ""),
            "points": row.get("points", 0),
            "matches": row.get("matches", 0),
            "wins": row.get("wins", 0),
            "draws": row.get("draws", 0),
            "losses": row.get("losses", 0),
            "goals": row.get("goals", 0),
            "opponentGoals": row.get("opponentGoals", 0),
            "isHighlighted": False,
        }
        for i, row in enumerate(table)
    ]
    return {
        "league": {"name": league_name, "leagueId": league_id, "season": f"{season}/{season + 1}"},
        "table": {"full_table": full_table},
        "updatedAt": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/football/{team_name}")
def get_football_data(team_name: str) -> dict[str, Any]:
    from app.search.providers.football import FootballProvider

    result = FootballProvider().get_team_display_data(team_name)
    if not result:
        raise HTTPException(status_code=404, detail=f"Team '{team_name}' nicht gefunden")
    return result
