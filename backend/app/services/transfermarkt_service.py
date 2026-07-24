"""Transfermarkt-Vereinsdaten via community API (transfermarkt-api.fly.dev).

Scraping-basiert — externe Abhängigkeit.
Disk-Cache unter /data/tm_cache/ überlebt Container-Neustarts.

Cache-Strategie:
- Spieler-Einzel-Profile: 30 Tage Disk-Cache
- Vereinsprofile + Kaderlisten: Disk-Cache ohne feste TTL — Invalidierung
  nur wenn sich `lastUpdate` im TM-Response ändert. Stale-while-revalidate:
  Rückgabe aus Cache, Refresh im Hintergrund nach CHECK_INTERVAL.
"""
from __future__ import annotations

import gzip
import html.parser
import json
import pathlib
import re
import threading
import time
import urllib.parse
import urllib.request
from typing import Any

_TM_BASE = "https://transfermarkt-api.fly.dev"

_SEARCH_TTL      = 7 * 86_400   # TM-IDs: 7 Tage
_PLAYER_DISK_TTL = 30 * 86_400  # Spieler-Einzel-Profil: 30 Tage
_CLUB_CHECK_INTERVAL = 24 * 3_600  # Vereinsdaten: nach 24h im Hintergrund prüfen ob lastUpdate neu
_STALE_RETRY_BACKOFF = 3_600     # Nach Rückfall auf abgelaufenen Cache: 1h Pause vor erneutem Netzwerkversuch

_cache: dict[str, dict[str, Any]] = {}

_PLAYER_CACHE_DIR    = pathlib.Path("/data/tm_cache/players")
_SEARCH_CACHE_DIR    = pathlib.Path("/data/tm_cache/searches")
_CLUB_CACHE_DIR      = pathlib.Path("/data/tm_cache/clubs")
_TRANSFERS_CACHE_DIR = pathlib.Path("/data/tm_cache/player_transfers")
_TMDE_CACHE_DIR      = pathlib.Path("/data/tm_cache/tmde")

# Max. 5 gleichzeitige Profil-API-Calls — verhindert Burst-Rate-Limiting bei der Anreicherung
_PROFILE_API_SEM = threading.BoundedSemaphore(5)

_TM_DE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Cache-Control": "max-age=0",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Referer": "https://www.transfermarkt.de/",
}


def _tmde_get(url: str, timeout: int = 30) -> str | None:
    try:
        headers = {**_TM_DE_HEADERS, "Accept-Encoding": "gzip, deflate"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            enc = resp.headers.get("Content-Encoding", "")
            if "gzip" in enc:
                raw = gzip.decompress(raw)
            return raw.decode("utf-8", errors="replace")
    except Exception:
        return None


class _TMTransferParser(html.parser.HTMLParser):
    """Parst TM.de /alletransfers/ Seite in strukturierte Saison-Dicts."""

    def __init__(self) -> None:
        super().__init__()
        self.seasons: dict[str, dict] = {}
        self._season: str | None = None
        self._direction: str | None = None  # 'arrivals' | 'departures'
        self._in_h2 = False
        self._h2_buf: list[str] = []
        self._in_tbody = False
        self._tbody_depth = 0
        self._in_tr = False
        self._cells: list[dict] = []
        self._in_td = False
        self._td_buf: list[str] = []
        self._td_links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = dict(attrs)
        if tag == "h2" and "content-box-headline" in a.get("class", ""):
            self._in_h2 = True; self._h2_buf = []
        elif tag == "tbody":
            self._tbody_depth += 1; self._in_tbody = True
        elif tag == "tr" and self._in_tbody:
            self._in_tr = True; self._cells = []
        elif tag == "td" and self._in_tr:
            self._in_td = True; self._td_buf = []; self._td_links = []
        elif tag == "a" and self._in_td:
            if h := a.get("href", ""):
                self._td_links.append(h)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2" and self._in_h2:
            self._in_h2 = False
            text = "".join(self._h2_buf).strip()
            m = re.match(r"(Zug.nge|Abg.nge)\s+(\d{2}/\d{2})", text)
            if m:
                self._direction = "arrivals" if "Zug" in m.group(1) else "departures"
                self._season = m.group(2)
                if self._season not in self.seasons:
                    self.seasons[self._season] = {"arrivals": [], "departures": []}
            # Tbody-Tracking pro Saison-Abschnitt neu anfangen: ein irgendwo
            # weiter oben auf der (sehr langen) Seite nicht sauber geschlossenes
            # <tbody> (z.B. in einem Werbe-/Empfehlungs-Widget) verschiebt sonst
            # den globalen Tiefenzähler dauerhaft — jede nachfolgende Tabelle
            # (inkl. aktueller Saisons!) würde dann still als leer geparst.
            self._tbody_depth = 0
            self._in_tbody = False
            self._in_tr = False
            self._cells = []
        elif tag == "tbody":
            self._tbody_depth -= 1
            if self._tbody_depth == 0:
                self._in_tbody = False
            self._in_tr = False
        elif tag == "td" and self._in_td:
            self._in_td = False
            self._cells.append({"t": " ".join(self._td_buf).strip(), "l": list(self._td_links)})
        elif tag == "tr" and self._in_tr:
            self._in_tr = False
            self._flush_row()

    def handle_data(self, data: str) -> None:
        if self._in_h2:
            self._h2_buf.append(data)
        elif self._in_td:
            s = data.strip()
            if s:
                self._td_buf.append(s)

    def _flush_row(self) -> None:
        if not (self._season and self._direction and len(self._cells) >= 4):
            return
        player_cell = self._cells[0]
        club_cell   = self._cells[2]
        fee_cell    = self._cells[3]
        name = player_cell["t"]
        if not name or name == "-":
            return
        player_id = next(
            (m.group(1) for h in player_cell["l"] if (m := re.search(r"/spieler/(\d+)", h))), None
        )
        club_name = club_cell["t"] or None
        fee_raw   = fee_cell["t"] if fee_cell["t"] not in ("", "-") else None
        self.seasons[self._season][self._direction].append({
            "player_id": player_id,
            "name":      name,
            "club":      club_name,
            "fee_text":  fee_raw,
            "fee":       self._parse_fee(fee_raw),
        })

    @staticmethod
    def _parse_fee(text: str | None) -> int | None:
        if not text:
            return None
        t = text.lower()
        if "ablösefrei" in t or "free" in t:
            return 0
        if "leihe" in t or "loan" in t:
            return -1   # Leihe-Marker
        m = re.search(r"([\d,.]+)\s*(mio|tsd)", t)
        if m:
            val = float(m.group(1).replace(".", "").replace(",", "."))
            return int(val * (1_000_000 if m.group(2) == "mio" else 1_000))
        return None


def _cached(key: str, ttl: float) -> Any | None:
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < ttl:
        return entry["data"]
    return None


def _store(key: str, data: Any) -> None:
    _cache[key] = {"data": data, "ts": time.time()}


def _club_disk_read(path: pathlib.Path) -> dict | None:
    """Liest Club-Cache-Eintrag {data, last_update, ts} von Disk. Gibt None bei Fehler."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _club_disk_write(path: pathlib.Path, data: Any, last_update: str | None) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"data": data, "last_update": last_update, "ts": time.time()}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _club_disk_touch(path: pathlib.Path) -> None:
    """Aktualisiert nur den Zeitstempel — Inhalt bleibt unverändert."""
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
        entry["ts"] = time.time()
        path.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _get(path: str) -> dict | None:
    url = f"{_TM_BASE}{path}"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "robot-core/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=14) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _name_candidates(name: str) -> list[str]:
    """Alternative Suchbegriffe falls der exakte Vereinsname keine Treffer liefert:
    1. Original ("1. FC Heidenheim 1846")
    2. Ohne führende "N. " ("FC Heidenheim 1846")
    3. Ohne abschließende Jahreszahl ("FC Heidenheim")
    """
    base = name.strip()
    candidates: list[str] = [base]
    c1 = re.sub(r'^\d+\.\s+', '', base)
    if c1 != base:
        candidates.append(c1)
    c2 = re.sub(r'\s+\d{4}$', '', candidates[-1])
    if c2 != candidates[-1]:
        candidates.append(c2)
    return candidates


class TransfermarktService:
    def search_club_id(self, name: str) -> str | None:
        """TM-ID per Namenssuche — 7 Tage Disk-Cache (überlebt Restarts).

        Probiert mehrere Suchbegriffe falls der exakte Name keine Treffer liefert
        (siehe _name_candidates).
        """
        key = f"tm_search:{name.lower().strip()}"
        cached = _cached(key, _SEARCH_TTL)
        if cached is not None:
            return cached

        # Disk-Cache
        slug = re.sub(r'[^a-z0-9]', '_', name.lower().strip())
        cache_path = _SEARCH_CACHE_DIR / f"club_{slug}.json"
        stale_id: str | None = None
        if cache_path.exists():
            try:
                stale_id = json.loads(cache_path.read_text(encoding="utf-8"))
                if time.time() - cache_path.stat().st_mtime < _SEARCH_TTL:
                    _store(key, stale_id)
                    return stale_id
            except Exception:
                stale_id = None

        # War der letzte Rückfall auf den Stale-Wert erst vor Kurzem (externer
        # Dienst vermutlich weiterhin down) → nicht bei jedem Aufruf erneut
        # anfragen, sondern direkt den Stale-Wert liefern.
        backoff_key = f"{key}:stale_backoff"
        if stale_id is not None and _cached(backoff_key, _STALE_RETRY_BACKOFF) is not None:
            return stale_id

        candidates = _name_candidates(name)
        tm_id = None
        for candidate in candidates:
            data = _get(f"/clubs/search/{urllib.parse.quote(candidate)}")
            results: list[dict] = (data or {}).get("results") or []
            for r in results:
                if str(r.get("country") or "").lower() in ("germany", "deutschland"):
                    tm_id = str(r["id"])
                    break
            if tm_id is None and results:
                tm_id = str(results[0]["id"])
            if tm_id:
                break

        if tm_id:
            _store(key, tm_id)
            try:
                _SEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(tm_id, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            return tm_id

        # Frische Suche fehlgeschlagen (z.B. externer Dienst down) — abgelaufenen
        # Cache-Wert weiterverwenden statt komplett auszufallen. Weder Datei-
        # Zeitstempel noch der reguläre Cache-Key (7 Tage) werden aufgefrischt,
        # nur der kurze Backoff-Marker — damit ein Wiederanlaufen des externen
        # Diensts innerhalb einer Stunde wieder einen echten Refresh versucht.
        if stale_id:
            _store(backoff_key, True)
        return stale_id

    def get_club_image_by_id(self, tm_club_id: str) -> str | None:
        """Club-Wappen-URL direkt per TM-Club-ID."""
        key = f"tm_profile:{tm_club_id}"
        mem = _cached(key, _CLUB_CHECK_INTERVAL)
        if mem is not None:
            return (mem or {}).get("image")
        disk = _club_disk_read(_CLUB_CACHE_DIR / f"{tm_club_id}_profile.json")
        if disk:
            _store(key, disk["data"])
            return (disk["data"] or {}).get("image")
        data = _get(f"/clubs/{tm_club_id}/profile")
        if data:
            _club_disk_write(_CLUB_CACHE_DIR / f"{tm_club_id}_profile.json", data, data.get("lastUpdate"))
            _store(key, data)
            return data.get("image")
        return None

    def get_club_profile(self, team_name: str) -> dict | None:
        """Vereinsprofil — Disk-Cache ohne feste TTL, Invalidierung per lastUpdate."""
        tm_id = self.search_club_id(team_name)
        if not tm_id:
            return None
        key = f"tm_profile:{tm_id}"
        # 1. In-Memory (gültig für CHECK_INTERVAL ohne Disk-Hit)
        mem = _cached(key, _CLUB_CHECK_INTERVAL)
        if mem is not None:
            return mem
        # 2. Disk-Cache
        cache_path = _CLUB_CACHE_DIR / f"{tm_id}_profile.json"
        disk = _club_disk_read(cache_path)
        if disk:
            cached_lu = disk.get("last_update")
            age = time.time() - disk.get("ts", 0)
            _store(key, disk["data"])
            if age < _CLUB_CHECK_INTERVAL:
                return disk["data"]
            # CHECK_INTERVAL abgelaufen → Refresh im Hintergrund
            def _bg_refresh_profile(tid: str, path: pathlib.Path, old_lu: str | None, mem_key: str) -> None:
                fresh = _get(f"/clubs/{tid}/profile")
                if not fresh:
                    _club_disk_touch(path)
                    return
                new_lu = fresh.get("lastUpdate")
                if new_lu and new_lu == old_lu:
                    _club_disk_touch(path)  # Daten unverändert → nur Timestamp aktualisieren
                else:
                    _club_disk_write(path, fresh, new_lu)
                _store(mem_key, fresh if fresh else disk["data"])
            threading.Thread(target=_bg_refresh_profile, args=(tm_id, cache_path, cached_lu, key), daemon=True).start()
            return disk["data"]
        # 3. Kein Cache → synchron laden; bei Fehler Suche-Cache invalidieren + Retry
        data = _get(f"/clubs/{tm_id}/profile")
        if data is None:
            slug = re.sub(r'[^a-z0-9]', '_', team_name.strip().lower())
            try:
                (_SEARCH_CACHE_DIR / f"club_{slug}.json").unlink(missing_ok=True)
            except Exception:
                pass
            _cache.pop(f"tm_search:{team_name.lower().strip()}", None)
            fresh_id = self.search_club_id(team_name)
            if fresh_id and fresh_id != tm_id:
                data = _get(f"/clubs/{fresh_id}/profile")
        if data:
            _club_disk_write(cache_path, data, data.get("lastUpdate"))
            _store(key, data)
        return data

    def get_club_players(self, team_name: str) -> list[dict] | None:
        """Kaderliste mit Marktwerten — Disk-Cache, Invalidierung per lastUpdate."""
        tm_id = self.search_club_id(team_name)
        if not tm_id:
            return None
        key = f"tm_players:{tm_id}"
        mem = _cached(key, _CLUB_CHECK_INTERVAL)
        if mem is not None:
            return mem
        cache_path = _CLUB_CACHE_DIR / f"{tm_id}_players.json"
        disk = _club_disk_read(cache_path)
        if disk:
            cached_lu = disk.get("last_update")
            age = time.time() - disk.get("ts", 0)
            _store(key, disk["data"])
            if age < _CLUB_CHECK_INTERVAL:
                return disk["data"]
            def _bg_refresh_players(tid: str, path: pathlib.Path, old_lu: str | None, mem_key: str) -> None:
                fresh_raw = _get(f"/clubs/{tid}/players")
                if not fresh_raw:
                    _club_disk_touch(path)
                    return
                new_lu = fresh_raw.get("lastUpdate")
                players = fresh_raw.get("players") or []
                if new_lu and new_lu == old_lu:
                    _club_disk_touch(path)
                else:
                    _club_disk_write(path, players, new_lu)
                _store(mem_key, players if players else disk["data"])
            threading.Thread(target=_bg_refresh_players, args=(tm_id, cache_path, cached_lu, key), daemon=True).start()
            return disk["data"]
        data = _get(f"/clubs/{tm_id}/players")
        if data is None:
            # Veraltete TM-ID im Suche-Cache (z.B. 4453 statt 105) → Cache löschen + einmal neu suchen
            slug = re.sub(r'[^a-z0-9]', '_', team_name.strip().lower())
            try:
                (_SEARCH_CACHE_DIR / f"club_{slug}.json").unlink(missing_ok=True)
            except Exception:
                pass
            _cache.pop(f"tm_search:{team_name.lower().strip()}", None)
            fresh_id = self.search_club_id(team_name)
            if fresh_id and fresh_id != tm_id:
                data = _get(f"/clubs/{fresh_id}/players")
        players: list[dict] = (data or {}).get("players") or []
        if players:
            _club_disk_write(cache_path, players, (data or {}).get("lastUpdate"))
            _store(key, players)
        return players or None

    def search_player(self, name: str) -> dict | None:
        """Spieler per Name auf TM suchen — liefert id, marketValue, club, position, age, nationalities.

        7 Tage gecacht: In-Memory (verloren bei Restart) + Disk /data/tm_cache/searches/
        (überlebt Restarts — wichtig für Nationalspieler ohne TM-Vereinskader).
        """
        slug = re.sub(r'[^a-z0-9]', '_', name.lower().strip())
        key = f"tm_player_search:{name.lower().strip()}"
        # 1. In-Memory-Cache
        cached = _cached(key, _SEARCH_TTL)
        if cached is not None:
            return cached
        # 2. Disk-Cache (überlebt Container-Restarts)
        try:
            _SEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        cache_path = _SEARCH_CACHE_DIR / f"{slug}.json"
        if cache_path.exists():
            try:
                if time.time() - cache_path.stat().st_mtime < _SEARCH_TTL:
                    data = json.loads(cache_path.read_text(encoding="utf-8"))
                    _store(key, data)
                    return data
            except Exception:
                pass
        # 3. API-Abfrage
        data = _get(f"/players/search/{urllib.parse.quote(name)}")
        results: list[dict] = (data or {}).get("results") or []
        if not results:
            return None
        r = results[0]
        result = {
            "tm_id":         str(r["id"]),
            "name":          r.get("name"),
            "position":      r.get("position"),
            "club":          r.get("club"),
            "age":           r.get("age"),
            "nationalities": r.get("nationalities"),
            "marketValue":   r.get("marketValue"),
        }
        _store(key, result)
        try:
            cache_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        return result

    def get_player_profile(self, player_id: str) -> dict | None:
        """Einzelnes Spieler-Profil mit 30-Tage-Disk-Cache.

        Reihenfolge: In-Memory → Disk → API. Schreibt beim Abruf sofort
        auf Disk, sodass der Cache Container-Neustarts überlebt.
        """
        key = f"tm_player:{player_id}"
        # 1. In-Memory-Cache
        cached = _cached(key, _PLAYER_DISK_TTL)
        if cached is not None:
            return cached
        # 2. Disk-Cache
        try:
            _PLAYER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        cache_path = _PLAYER_CACHE_DIR / f"{player_id}.json"
        if cache_path.exists():
            try:
                age = time.time() - cache_path.stat().st_mtime
                if age < _PLAYER_DISK_TTL:
                    data = json.loads(cache_path.read_text(encoding="utf-8"))
                    _store(key, data)
                    return data
            except Exception:
                pass
        # 3. API-Abfrage — serialisiert, kein Burst (Semaphore verhindert Parallelität)
        with _PROFILE_API_SEM:
            data = _get(f"/players/{player_id}/profile")
        if data:
            _store(key, data)
            try:
                cache_path.write_text(
                    json.dumps(data, ensure_ascii=False), encoding="utf-8"
                )
            except Exception:
                pass
        return data

    def get_player_transfers(self, player_id: str) -> list[dict] | None:
        """Transferhistorie eines Spielers — 7-Tage Disk-Cache."""
        key = f"tm_ptransfers:{player_id}"
        cached = _cached(key, 7 * 86_400)
        if cached is not None:
            return cached
        cache_path = _TRANSFERS_CACHE_DIR / f"{player_id}.json"
        if cache_path.exists():
            try:
                if time.time() - cache_path.stat().st_mtime < 7 * 86_400:
                    data = json.loads(cache_path.read_text(encoding="utf-8"))
                    _store(key, data)
                    return data
            except Exception:
                pass
        raw = _get(f"/players/{player_id}/transfers")
        transfers: list[dict] = (raw or {}).get("transfers") or []
        if raw is not None:
            _store(key, transfers)
            try:
                _TRANSFERS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(transfers, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
        return transfers or None

    def _tmde_search_club(self, name: str) -> tuple[str, str] | None:
        """TM.de Vereins-Slug + ID via Schnellsuche — 7-Tage Disk-Cache.

        Probiert mehrere Suchbegriffe falls der exakte Name keine Treffer liefert
        (siehe _name_candidates) — z.B. findet die Schnellsuche "1. FC Heidenheim
        1846" oft nicht, "FC Heidenheim 1846" aber schon.
        """
        slug_key = re.sub(r"[^a-z0-9]", "_", name.lower().strip())
        cache_path = _TMDE_CACHE_DIR / f"search_{slug_key}.json"
        if cache_path.exists():
            try:
                if time.time() - cache_path.stat().st_mtime < 7 * 86_400:
                    d = json.loads(cache_path.read_text(encoding="utf-8"))
                    return d["slug"], d["de_id"]
            except Exception:
                pass

        m = None
        for candidate in _name_candidates(name):
            page = _tmde_get(
                f"https://www.transfermarkt.de/schnellsuche/ergebnis/schnellsuche?query={urllib.parse.quote(candidate)}"
            )
            if not page:
                continue
            m = re.search(r"/([a-z0-9-]+)/startseite/verein/(\d+)", page)
            if m:
                break
        if not m:
            return None
        slug, de_id = m.group(1), m.group(2)
        try:
            _TMDE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({"slug": slug, "de_id": de_id}), encoding="utf-8")
        except Exception:
            pass
        return slug, de_id

    def _get_club_transfers_by_id(self, tm_id: str) -> dict | None:
        """Zugänge der aktuellen Saison aus der Kaderliste (joinedOn + signedFrom).

        /clubs/{id}/transfers existiert nicht auf fly.io — stattdessen liefert
        /clubs/{id}/players joinedOn + signedFrom + marketValue pro Spieler.
        Kein TM.de-Scraping, kein IP-Block. Nutzt dieselbe Cache-Datei wie
        get_club_players() (_CLUB_CACHE_DIR/{id}_players.json).
        """
        import datetime

        # Kaderliste: In-Memory → Disk → API
        key = f"tm_players:{tm_id}"
        players = _cached(key, _CLUB_CHECK_INTERVAL)
        if players is None:
            disk = _club_disk_read(_CLUB_CACHE_DIR / f"{tm_id}_players.json")
            if disk:
                players = disk["data"]
                _store(key, players)
            else:
                raw = _get(f"/clubs/{tm_id}/players")
                if not raw:
                    return None
                players = raw.get("players") or []
                if players:
                    _club_disk_write(_CLUB_CACHE_DIR / f"{tm_id}_players.json", players, raw.get("lastUpdate"))
                    _store(key, players)

        if not players:
            return None

        now = datetime.date.today()
        season_start_year = now.year - 1 if now.month < 7 else now.year
        season_label = f"{str(season_start_year)[2:]}/{str(season_start_year + 1)[2:]}"
        season_start = datetime.date(season_start_year, 7, 1)

        arrivals = []
        for p in players:
            joined_str = (p.get("joinedOn") or "")[:10]
            if not joined_str:
                continue
            try:
                joined = datetime.date.fromisoformat(joined_str)
            except ValueError:
                continue
            if joined < season_start:
                continue
            arrivals.append({
                "name":         p.get("name") or "",
                "position":     p.get("position"),
                "from_club":    p.get("signedFrom"),
                "to_club":      None,
                "market_value": p.get("marketValue"),
                "fee":          None,
                "fee_text":     None,
                "date":         joined_str,
            })

        if not arrivals:
            return None  # Keine Evidenz für Transfers -> TM.de-Scraping als nächste Stufe versuchen
        arrivals.sort(key=lambda x: x.get("date") or "", reverse=True)
        return {"season": season_label, "arrivals": arrivals, "departures": []}

    @staticmethod
    def _transfers_from_kader_cache(team_name: str) -> dict | None:
        """Liest Zugänge direkt aus dem Kader-Disk-Cache (kein API-Call).

        Der Daemon wärmt den Kader vor — für Bundesliga-Teams ist die Datei
        in der Regel schon da. joinedOn + signedFrom kommen aus TM-Profil-Enrichment.
        """
        import datetime as _dt
        slug = re.sub(r"[^a-z0-9]", "_", team_name.strip().lower())[:80]
        kader_path = pathlib.Path("/data/tm_cache/kader") / f"{slug}.json"
        if not kader_path.exists():
            return None
        try:
            data = json.loads(kader_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        squad = data.get("squad") or []
        if not squad:
            return None
        now = _dt.date.today()
        season_start_year = now.year - 1 if now.month < 7 else now.year
        season_label = f"{str(season_start_year)[2:]}/{str(season_start_year + 1)[2:]}"
        season_start = _dt.date(season_start_year, 7, 1)
        arrivals = []
        for p in squad:
            joined_str = (p.get("joinedOn") or "")[:10]
            if not joined_str:
                continue
            try:
                joined = _dt.date.fromisoformat(joined_str)
            except ValueError:
                continue
            if joined < season_start:
                continue
            arrivals.append({
                "name":         p.get("name") or "",
                "position":     p.get("position"),
                "from_club":    p.get("signedFrom"),
                "to_club":      None,
                "market_value": p.get("marketValue"),
                "fee":          None,
                "fee_text":     None,
                "date":         joined_str,
            })
        if not arrivals:
            return None  # Kader da, aber keine Saison-Zugänge → andere Quelle versuchen
        arrivals.sort(key=lambda x: x.get("date") or "", reverse=True)
        return {"season": season_label, "arrivals": arrivals, "departures": []}

    def get_club_transfers(self, team_name: str) -> dict | None:
        """Zugänge + Abgänge.

        1. TM.de Disk-Cache (tmde/ — überlebt DELETE /liga/cache, schnell)
        2. TM.de Scraping live — beste Datenqualität (echte Ablösesummen + Abgänge)
        3. Kader-Disk-Cache — Fallback nur wenn Scraping fehlschlägt (nur Zugänge,
           keine Ablösesummen, keine Abgänge — die Kaderliste enthält nur wer
           aktuell da ist, nicht wer gegangen ist)
        4. Community API fly.io — letzter Ausweg, gleiche Einschränkung wie 3

        Scraping zuerst statt zuletzt: die günstigeren Quellen (3+4) liefern nur
        eine Teilmenge (Zugänge ohne Ablöse, nie Abgänge) und würden — kämen sie
        zuerst dran — den vollständigeren Scrape-Treffer permanent verdecken,
        sobald sie irgendein (auch unvollständiges) Ergebnis finden.
        """
        # ── 1. TM.de Disk-Cache (sofortiger Treffer wenn Daten vom letzten Scrape da) ──
        slug: str | None = None
        de_id: str | None = None
        tmde = self._tmde_search_club(team_name)
        if tmde:
            slug, de_id = tmde
            tmde_cache = _TMDE_CACHE_DIR / f"transfers_{de_id}.json"
            disk = _club_disk_read(tmde_cache)
            if disk:
                age = time.time() - disk.get("ts", 0)
                if age < _CLUB_CHECK_INTERVAL:
                    return disk["data"]

            # ── 2. TM.de Scraping live ────────────────────────────────────────
            result = self._scrape_club_transfers(slug, de_id, team_name)
            if result:
                _club_disk_write(tmde_cache, result, None)
                return result

        # Scraping nicht möglich (kein Slug gefunden) oder fehlgeschlagen
        # (Cloudflare-Block o.ä.) → auf unvollständigere Quellen ausweichen.

        # ── 3. Kader-Disk-Cache (daemon hat ihn vorgewärmt — kein API-Call) ──────
        kader_result = self._transfers_from_kader_cache(team_name)
        if kader_result:
            return kader_result

        # ── 4. Community API (fly.io) — synchron laden, in Clubs-Cache speichern ──
        tm_id = self.search_club_id(team_name)
        if tm_id:
            api_cache = _CLUB_CACHE_DIR / f"transfers_{tm_id}.json"
            api_disk = _club_disk_read(api_cache)
            if api_disk:
                age = time.time() - api_disk.get("ts", 0)
                if age < _CLUB_CHECK_INTERVAL:
                    return api_disk["data"]
            result = self._get_club_transfers_by_id(tm_id)
            if result:
                _club_disk_write(api_cache, result, None)
                return result

        return None

    def _scrape_club_transfers(self, slug: str, de_id: str, team_name: str) -> dict | None:
        """Scrapt TM.de /alletransfers/, gibt aktuelle Saison zurück.

        Enrichment ohne extra API-Calls: Zugänge werden per Name mit der
        gecachten Kaderliste abgeglichen (Position + Marktwert).
        """
        import datetime

        page = _tmde_get(f"https://www.transfermarkt.de/{slug}/alletransfers/verein/{de_id}")
        if not page:
            return None
        parser = _TMTransferParser()
        parser.feed(page)
        if not parser.seasons:
            return None

        # Kaderliste als Lookup (name → Spielerdaten) — bereits disk-gecacht
        kader_by_name = {p["name"]: p for p in (self.get_club_players(team_name) or [])}

        def _season_year(s: str) -> int:
            # Jahrhundert-Grenze relativ zum aktuellen Jahr statt fest verdrahtet:
            # TM listet die kommende Saison bereits (z.B. "27/28" im Jahr 2026), daher
            # +1 Jahr Puffer. Ohne das würde z.B. "49/50" als 2049 statt 1949 einsortiert
            # (fixe Grenze "yy < 50" behandelt 49 fälschlich als 2000er) und beim
            # Rückwärts-Sortieren vor der echten aktuellen Saison landen.
            m = re.match(r"(\d{2})/", s)
            if not m:
                return 0
            yy = int(m.group(1))
            current_yy = datetime.date.today().year % 100
            return (2000 + yy) if yy <= current_yy + 1 else (1900 + yy)

        for season in sorted(parser.seasons, key=_season_year, reverse=True):
            data = parser.seasons[season]
            if not (data["arrivals"] or data["departures"]):
                continue

            arrivals = []
            for p in data["arrivals"]:
                kp = kader_by_name.get(p["name"]) or {}
                arrivals.append({
                    "name":         p["name"],
                    "position":     kp.get("position"),
                    "from_club":    p["club"],
                    "to_club":      None,
                    "market_value": kp.get("marketValue"),
                    "fee":          p["fee"],
                    "fee_text":     p["fee_text"],
                })

            departures = []
            for p in data["departures"]:
                departures.append({
                    "name":         p["name"],
                    "position":     None,
                    "from_club":    None,
                    "to_club":      p["club"],
                    "market_value": None,
                    "fee":          p["fee"],
                    "fee_text":     p["fee_text"],
                })

            return {"season": season, "arrivals": arrivals, "departures": departures}
        return None
