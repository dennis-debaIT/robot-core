from __future__ import annotations

from typing import Any


class NewsFeedService:
    _FEEDS: list[dict[str, Any]] = [
        {
            "id": "ntv",
            "label": "NTV",
            "url": "https://www.n-tv.de/rss",
            "fmt": "rss",
            "icon_url": "https://www.n-tv.de/favicon.ico",
            "default_selected": True,
        },
        {
            "id": "heise",
            "label": "Heise",
            "url": "https://www.heise.de/rss/heise-atom.xml",
            "fmt": "atom",
            "icon_url": "https://www.heise.de/favicon.ico",
            "exclude_title_prefixes": ["heise+", "heise-angebot:"],
            "default_selected": True,
        },
        {
            "id": "tagesschau",
            "label": "Tagesschau",
            "url": "https://www.tagesschau.de/xml/rss2",
            "fmt": "rss",
            "icon_url": "https://www.tagesschau.de/favicon.ico",
            "default_selected": True,
        },
        {
            "id": "shz",
            "label": "SHZ",
            "url": "https://www.shz.de/rss",
            "fmt": "rss",
            "icon_url": "https://www.shz.de/favicon.ico",
            "kicker": True,
            "default_selected": True,
        },
        {
            "id": "spiegel",
            "label": "Spiegel",
            "url": "https://www.spiegel.de/schlagzeilen/index.rss",
            "fmt": "rss",
            "icon_url": "https://www.spiegel.de/favicon.ico",
            "default_selected": True,
        },
        {
            "id": "stern",
            "label": "Stern",
            "url": "https://www.stern.de/feed/standard/all",
            "fmt": "rss",
            "icon_url": "https://www.stern.de/favicon.ico",
            "default_selected": True,
        },
        {
            "id": "faz",
            "label": "FAZ",
            "url": "https://www.faz.net/rss/aktuell",
            "fmt": "rss",
            "icon_url": "https://www.faz.net/favicon.ico",
            "default_selected": True,
        },
        {
            "id": "abendblatt",
            "label": "Abendblatt",
            "url": "https://www.abendblatt.de/rss",
            "fmt": "rss",
            "icon_url": "https://www.abendblatt.de/favicon.ico",
            "default_selected": True,
        },
        {
            "id": "zeit",
            "label": "ZEIT",
            "url": "https://newsfeed.zeit.de/all",
            "fmt": "rss",
            "icon_url": "https://www.zeit.de/favicon.ico",
            "default_selected": False,
        },
        {
            "id": "sueddeutsche",
            "label": "SZ",
            "url": "https://www.sueddeutsche.de/news/rss",
            "fmt": "rss",
            "icon_url": "https://www.sueddeutsche.de/favicon.ico",
            "default_selected": False,
        },
        {
            "id": "handelsblatt",
            "label": "Handelsblatt",
            "url": "https://www.handelsblatt.com/contentexport/feed/schlagzeilen",
            "fmt": "rss",
            "icon_url": "https://www.handelsblatt.com/favicon.ico",
            "default_selected": False,
        },
        {
            "id": "tagesspiegel",
            "label": "Tagesspiegel",
            "url": "https://www.tagesspiegel.de/contentexport/feed/home",
            "fmt": "rss",
            "icon_url": "https://www.tagesspiegel.de/favicon.ico",
            "default_selected": False,
        },
        {
            "id": "deutschlandfunk",
            "label": "DLF",
            "url": "https://www.deutschlandfunk.de/die-nachrichten.353.de.rss",
            "fmt": "rss",
            "icon_url": "https://www.deutschlandfunk.de/favicon.ico",
            "default_selected": False,
        },
        {
            "id": "rbb24",
            "label": "rbb24",
            "url": "https://www.rbb24.de/aktuell/index.xml/allitems=true/feed=rss",
            "fmt": "rss",
            "icon_url": "https://www.rbb24.de/favicon.ico",
            "default_selected": False,
        },
        {
            "id": "wdr",
            "label": "WDR",
            "url": "https://www1.wdr.de/uebersicht-100.feed",
            "fmt": "rss",
            "icon_url": "https://www1.wdr.de/favicon.ico",
            "default_selected": False,
        },
        {
            "id": "euronews",
            "label": "Euronews",
            "url": "https://feeds.feedburner.com/euronews/de/home/",
            "fmt": "rss",
            "icon_url": "https://de.euronews.com/favicon.ico",
            "default_selected": False,
        },
        {
            "id": "hessenschau_mittelhessen",
            "label": "Hessenschau Mittelhessen",
            "url": "https://www.hessenschau.de/mittelhessen/index.rss",
            "fmt": "rss",
            "icon_url": "https://www.hessenschau.de/favicon.ico",
            "default_selected": False,
        },
        {
            "id": "hessenschau_darmstadt98",
            "label": "Hessenschau Darmstadt 98",
            "url": "https://www.hessenschau.de/sport/fussball/darmstadt-98/index.rss",
            "fmt": "rss",
            "icon_url": "https://www.hessenschau.de/favicon.ico",
            "default_selected": False,
        },
    ]

    def __init__(self, custom_feeds: list[dict[str, Any]] | None = None) -> None:
        self._all_feeds = list(self._FEEDS)
        for cf in (custom_feeds or []):
            url = (cf.get("url") or "").strip()
            label = (cf.get("label") or "").strip()
            if not url or not label:
                continue
            feed_id = f"custom_{url}"
            fmt = cf.get("fmt", "rss") if cf.get("fmt") in ("rss", "atom") else "rss"
            self._all_feeds.append({
                "id": feed_id,
                "label": label,
                "url": url,
                "fmt": fmt,
                "icon_url": cf.get("icon_url") or "",
                "default_selected": False,
                "custom": True,
            })

    def list_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "id": feed["id"],
                "label": feed["label"],
                "url": feed["url"],
                "icon_url": feed.get("icon_url"),
                "default_selected": feed.get("default_selected", False),
                "custom": feed.get("custom", False),
            }
            for feed in self._all_feeds
        ]

    def default_selected_source_ids(self) -> list[str]:
        return [feed["id"] for feed in self._all_feeds if feed.get("default_selected")]

    def active_feeds(self, selected_source_ids: list[str] | None) -> list[dict[str, Any]]:
        selected = {value for value in (selected_source_ids or self.default_selected_source_ids()) if value}
        active = [feed for feed in self._all_feeds if feed["id"] in selected]
        return active or [feed for feed in self._all_feeds if feed.get("default_selected")]

    def active_sources_payload(self, selected_source_ids: list[str] | None) -> list[dict[str, Any]]:
        return [
            {"id": feed["id"], "label": feed["label"], "icon_url": feed.get("icon_url")}
            for feed in self.active_feeds(selected_source_ids)
        ]
