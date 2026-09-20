from app.search.providers.web import WebProvider


class _FakeDDGS:
    """Simuliert duckduckgo_search.DDGS — pro Suchanfrage konfigurierbare
    Ergebnislisten, damit search() ohne echten Netzwerkzugriff getestet
    werden kann."""

    responses: dict[str, list[dict]] = {}
    calls: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def text(self, query, region=None, safesearch=None, max_results=4):
        self.calls.append(query)
        return self.responses.get(query, [])


def _install_fake_ddgs(monkeypatch, responses: dict[str, list[dict]]):
    import duckduckgo_search

    _FakeDDGS.responses = responses
    _FakeDDGS.calls = []
    monkeypatch.setattr(duckduckgo_search, "DDGS", _FakeDDGS)
    return _FakeDDGS


def test_is_sports_query_detects_league_and_rank_and_table_words():
    provider = WebProvider()
    assert provider._is_sports_query("Wer steht in der 1. Bundesliga auf Platz 3?")
    assert provider._is_sports_query("Bundesliga Tabelle heute")
    assert provider._is_sports_query("Champions League Spielstand")
    assert not provider._is_sports_query("Aus was besteht ein Papier?")
    assert not provider._is_sports_query("Wer hat den Eiffelturm gebaut?")


def test_general_knowledge_query_searches_only_once_without_year_bias(monkeypatch, temp_db):
    """Regression: 'Aus was besteht ein Papier?' lieferte einen irrelevanten
    Treffer (Branchenbericht 'PAPIER 2026'), weil die Jahres-Erweiterung und
    die 'aktuelles Jahr gewinnt'-Priorisierung auf jede Anfrage angewendet
    wurden, nicht nur auf Fußball-Anfragen."""
    fake = _install_fake_ddgs(monkeypatch, {
        # DuckDuckGo liefert die thematisch passende Wikipedia-Antwort an
        # erster Stelle (wie in der Realität für so eine Faktenfrage zu
        # erwarten) — der Branchenbericht mit der Jahreszahl kommt erst
        # danach. Die alte year-biased Logik hätte trotzdem den
        # Branchenbericht bevorzugt, nur weil er "2026" enthält.
        "Zusammensetzung und Rohstoffe von Papier": [
            {
                "title": "Papier – Wikipedia",
                "href": "https://de.wikipedia.org/wiki/Papier",
                "body": "Papier besteht überwiegend aus Zellstofffasern, die aus Holz gewonnen werden.",
            },
            {
                "title": "PAPIER 2026 – Leistungsbericht der Branche",
                "href": "https://example.com/papier-2026",
                "body": "Der Leistungsbericht beschreibt Fortschritte der Branche in Sachen Nachhaltigkeit 2026.",
            },
        ],
    })

    provider = WebProvider()
    result = provider.search("Zusammensetzung und Rohstoffe von Papier")

    # nur EIN DDGS-Aufruf (kein Jahres-/"aktuell"-Suffix angehängt)
    assert fake.calls == ["Zusammensetzung und Rohstoffe von Papier"]
    # der erste, thematisch brauchbare Treffer gewinnt (Wikipedia), nicht
    # der PR-Bericht, nur weil er die Jahreszahl enthält
    assert result is not None
    assert "Zellstofffasern" in result["snippet"]


def test_sports_query_still_expands_with_year_and_prefers_current_league_hit(monkeypatch, temp_db):
    """Bestehendes Verhalten für Fußball-Anfragen darf sich nicht ändern."""
    import datetime as _dt
    current_year = str(_dt.datetime.now().year)

    fake = _install_fake_ddgs(monkeypatch, {
        f"Tabelle 1. Bundesliga {current_year}": [
            {
                "title": "Alte Tabelle",
                "href": "https://example.com/alt",
                "body": "Veraltete Tabelle ohne Jahresangabe, aber mit ausreichend Text für den Snippet-Test.",
            },
        ],
        f"Tabelle 1. Bundesliga aktuell {current_year}": [],
        "Tabelle 1. Bundesliga": [
            {
                "title": "Aktuelle Tabelle",
                "href": "https://example.com/aktuell",
                "body": f"1. Bundesliga Tabelle {current_year}: Bayern München auf 1. Platz.",
            },
        ],
    })

    provider = WebProvider()
    result = provider.search("Tabelle 1. Bundesliga")

    assert len(fake.calls) == 3
    assert result is not None
    assert "Bayern München" in result["snippet"]


def test_pick_first_substantial_skips_short_snippets():
    provider = WebProvider()
    results = [
        {"href": "https://a", "body": "kurz"},
        {"href": "https://b", "body": "Dies ist ein ausreichend langer und brauchbarer Such-Snippet."},
    ]

    best = provider._pick_first_substantial(results)

    assert best["href"] == "https://b"


def test_pick_first_substantial_falls_back_to_first_result_when_all_short():
    provider = WebProvider()
    results = [{"href": "https://a", "body": "kurz"}]

    best = provider._pick_first_substantial(results)

    assert best["href"] == "https://a"
