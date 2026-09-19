from __future__ import annotations

import snowballstemmer

_stemmer = snowballstemmer.stemmer("german")


def stem_topic(topic: str) -> str:
    """Normalisiert ein Thema auf seinen Wortstamm (z.B. 'Katzen' -> 'katz'),
    damit Singular-/Pluralformen als dasselbe Thema gezählt werden. Keine
    app-internen Importe (auch von db.py für die Spalten-Migration genutzt,
    sonst zirkulärer Import)."""
    return _stemmer.stemWord(topic.casefold())
