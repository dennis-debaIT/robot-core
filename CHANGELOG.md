# Changelog — Erika Robot Core

Alle nennenswerten Änderungen am Projekt werden hier dokumentiert.  
Format: neueste Einträge oben.

---

## [Unreleased]

---

## 2026-05-26 (5)

### Neu
- **Timer per Sprache auflisten**: "Welche Timer laufen gerade?" gibt alle aktiven Timer mit Restzeit aus
- **Timer umbenennen per Sprache**: "Nenn den ersten Timer Nudeln" — erkennt Ordinalzahl, vorhandenes Label oder (bei einem Timer) automatisch den einzigen laufenden Timer
- **Eigene RSS-Quellen im Admin**: Unter News → Eigene RSS-Quellen können beliebige RSS- oder Atom-Feed-URLs hinzugefügt werden; erscheinen danach in der Quellenliste und können aktiviert werden

### Behoben
- **Timer-Fehlerresistenz**: `_try_timer_command()` fängt nun alle Exceptions ab — kein stiller Crash mehr wenn der Timer-Router-Import fehlschlägt

---

## 2026-05-26 (4)

### Neu
- **Timer-Restzeit per Sprache**: "Wie lange noch beim Nudel-Timer?" liefert die verbleibende Zeit; bei mehreren Timern ohne Namensangabe werden alle aufgelistet

### Behoben
- **Timer-Label "Nudeln auf"**: `_TIMER_LABEL_RE` fing im `für`-Zweig fälschlich zwei Wörter ein — jetzt wird nur ein Wort extrahiert (kein nachfolgendes "auf", "ein" o.ä.)
- **Wetter-Sprachbefehle**: `WeatherProvider.search()` rief Open-Meteo direkt auf statt den konfigurierten Provider zu nutzen — jetzt wird `get_weather_display_data()` gerufen (gleicher Pfad wie `/weather`-Endpoint)

---

## 2026-05-26 (3)

### Neu
- **Wetter-Anbieter auswählbar**: Im Admin unter Wetter → Datenquelle kann zwischen drei Anbietern gewählt werden:
  - **Open-Meteo** (Standard, kein API-Key, open-meteo.com)
  - **Yr.no / MET Norway** (kein API-Key, Norwegischer Wetterdienst, sehr zuverlässig)
  - **OpenWeatherMap** (kostenloser API-Key nötig, 1M Calls/Monat gratis)
  - Geocoding (Ortsauflösung) läuft weiterhin über Open-Meteo bei allen Anbietern

## 2026-05-26 (2)

### Behoben
- **Wetter-Widget verschwindet bei API-Fehler**: Wenn Open-Meteo nicht erreichbar ist, wurde das Wetter-Widget komplett ausgeblendet. Jetzt zeigt es einen Platzhalter "Wetterdaten nicht verfügbar" statt ganz zu verschwinden. Backend gibt bei Fehler JSON zurück statt HTTP 503 (kein Browser-Fehler mehr).

---

## 2026-05-26

### Neu
- **Zeitgesteuerte Lichtbefehle per Sprache**: "Schalte um 19 Uhr das Licht im Wohnzimmer auf 50% ein" — Erika legt einen internen Zeitplan an (nutzt das Reminder-System mit `light_command`-Feld). Der Watcher-Loop führt den HA-Lichtbefehl zur angegebenen Uhrzeit still aus; bei vergangener Uhrzeit automatisch auf morgen verschoben.
- **Gesprächs-Zusammenfassung**: Sprachbefehl "Was haben wir heute besprochen?" liefert eine kompakte Zusammenfassung der heutigen Konversationsthemen (ohne LLM-Aufruf, direkt aus `conversation_messages`)
- **Tägliches Fazit**: Erika fragt abends proaktiv "Wie war dein Tag heute?" — Uhrzeit im Admin konfigurierbar; Antwort wird automatisch als Notiz ("Tagesfazit DD.MM.YYYY") gespeichert; LocalStorage verhindert mehrfaches Fragen pro Tag
- **`/chat/log` Endpoint**: Interner Endpoint zum Loggen von Assistenten-Nachrichten (für Kontext-Erkennung im Backend)

---

## 2026-05-25

### Neu
- **Zeitgesteuerte Erinnerungen per Uhrzeit**: "Erinnere mich um 14:15 Uhr an Kind abholen" — neben relativer Dauer ("in 30 Minuten") wird jetzt auch eine Uhrzeit erkannt; bei vergangener Uhrzeit automatisch auf den nächsten Tag verschoben
- **Notizen-Overlay per Sprache**: Beim Abfragen einer Notiz ("Was ist mein WLAN-Passwort?") wird das Overlay automatisch geöffnet
- **Notizen-Button entfernt**: Notizen sind nur noch über Sprache abrufbar (kein Nav-Button mehr)

### Behoben
- Notizen-Overlay zeigte globale statt personenspezifische Notizen (`_greetingPersonId` wurde nicht gesetzt)
- Notizen-Overlay las `data.notes` statt `data.items` (falsches API-Feld)
- Lichthelligkeitsbefehl bei ausgeschaltetem Licht schlug still fehl (`\b` nach `%` ist keine Wortgrenze)

### Verbessert
- Dunkle Scrollbalken global im Display (vorher nur rechte Kalender-Spalte)
- Dunkle Scrollbalken im Admin-Panel

---

## 2026-05-24

### Neu
- **Proaktive Ansprache Zeitfenster**: Im Admin (Tab "Erika") konfigurierbar von welcher Uhrzeit bis wann Erika proaktiv ansprechen darf (mit Mitternacht-Wrap-Around-Support)

### Neu (früher in diesem Zeitraum)
- **Personenspezifische Notizen**: Notizen werden einer Person zugeordnet; Abfragen zeigen nur Notizen der aktiven Person
- **Notizen im LLM-Kontext**: Gespeicherte Notizen fließen in den LLM-Prompt ein

---

## 2026-05 (früh)

### Neu
- **Wake Word "Erika"**: Kontinuierliche Spracherkennung; "Erika stop/halt" bricht TTS ab
- **Gesichtserkennung**: Personenidentifikation via Kamera; automatische Begrüßung bei Erkennung
- **Kontextuelle Begrüßung**: Ton (warm/freundlich/neutral/reserviert) und Abwesenheitskontext (kurz/mittel/lang) basierend auf Beziehungsstatus
- **Proaktive Ansprache**: Erika spricht nach 25 Minuten Stille von sich aus
- **Follow-Up Listening**: Nach Erikas TTS-Antwort mit Fragezeichen hört Erika 7 Sekunden automatisch zu
- **Timer per Sprache**: "Stell einen Timer auf 5 Minuten", Mehrere Timer gleichzeitig, Labels ("Timer für die Nudeln"), Abbrechen per Sprache
- **Erinnerungen per Sprache**: "Erinnere mich in 30 Minuten an X" — Piepton + TTS + Overlay bei Fälligkeit
- **Kalendertermine per Sprache eintragen**: LLM-gestützte Datum/Zeit-Extraktion, pro Person konfigurierbar
- **Licht-Szenen**: Szenen speichern/abrufen/löschen, per Sprache aktivieren
- **Proaktive Benachrichtigungen**: Regelbasiert (HA-Entitäten), Glocke, Overlay, TTS
- **Fahrzeugabfrage per Sprache**: Akku, Reichweite, Ladestatus, alle Autos
- **Roboter-Statusabfragen per Sprache**: Staubsauger und Mähroboter
- **Mähroboter per Sprache steuern**: Starten, zur Basis, pausieren
- **Tageszusammenfassung**: Modularer Tagesbriefing-Block (Wetter, Kalender, Roboter etc.), pro Person konfigurierbar, Drag&Drop Reihenfolge
- **Edge TTS**: Microsoft Azure TTS-Provider (kostenlos, Internet), konfigurierbare Stimme und Geschwindigkeit
- **Sherpa ONNX TTS**: Vollständig lokaler TTS-Provider
- **Websuche**: Wikipedia-Provider + breite Trigger-Logik; Affirmations-Handler ("ja" nach LLM-Angebot)
- **Interesse-Tracking**: Wiederholte Themen werden als Interessen erkannt und dem Profil zugeordnet

### Behoben (Auswahl)
- TTS-Ruckeln: kurze Antworten als ein Request; Chunks vorab synthetisieren
- TTS-Watchdog: nach 30 s Timeout wird `done()` erzwungen
- Wake Word Stuck-Detection via Heartbeat
- Kalender-Pattern zu aggressiv ("ich habe morgen Termin" triggert nicht mehr Kalender-Eintrag)
- Ladestatus-Erkennung robuster (charge_in_progress, Fallback auf rct>0)
- Gesichtserkennung Video robuster für Android/iOS

---

## Frühere Basis-Features (initiale Implementierung)

- FastAPI Backend, SQLite Datenbank, Docker-Deployment auf Erika (Raspberry Pi / VM)
- Home Assistant Integration: Lichtsteuerung, Entitäten, Zustände
- LLM-Router (LM Studio / OpenAI-kompatibel, Mock-Fallback)
- Persönlichkeitssystem: Freundlichkeit, Geduld, Direktheit, Humor etc.
- Personenprofile: Fakten, Vorlieben, Abneigungen, Beziehungsstatus
- Memory-System: Vorschläge, Freigabe, Profil-Materialisierung
- Konversationsverlauf mit Themen-Tracking
- Admin-Panel (local-admin.html): vollständige Konfiguration aller Module
- Display-Panel (display.html): Statusleiste, Wetter, Kalender, Fußball, Licht, Kamera, Karte
- Kraftstoffpreise (tankerkoenig.de via HA)
- Fußballergebnisse und Tabelle (football-data.org)
- Wetter (Open-Meteo)
- PV-Anlage Statusanzeige (Solarman)
- Drucker-Status (AnyPrint/MQTT)
- Fahrzeug-Tracking mit Karte (HA Device Tracker)
