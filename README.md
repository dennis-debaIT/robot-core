# Erika Robot Core v0.3.0

Software-Core für einen sozialen KI-Roboter. FastAPI-Backend, SQLite-Datenbank, Docker-Deployment (Raspberry Pi / VM), vollständige Web-Oberfläche und lokaler Mock-LLM-Fallback.

---

## Was Erika kann

- **Sprachsteuerung** — Wake Word "Erika", kontinuierliche Erkennung, Follow-Up Listening
- **LLM-Begrüßung** — KI-generierte, kontextuelle Begrüßung bei Gesichtserkennung (Tageszeit, Kalender, PV, Themen); konfigurierbarer Kontext, Template-Fallback
- **Gesichtserkennung** — automatische Begrüßung, personenbezogener Kontext
- **Smart Home** — Lichtsteuerung, Szenen, Zeitpläne, Staubsauger- und Mährobotersteuerung via Home Assistant
- **TTS** — Edge TTS (Microsoft, Online) und Sherpa ONNX (lokal, Offline-Fallback)
- **Gedächtnis** — Langzeit-Memory mit Freigabe-Queue, Personenprofile, tägliche Zusammenfassungen, Wochensummaries
- **Persönlichkeit** — Freundlichkeit, Humor, Direktheit u.a. — konfigurierbar und im Gespräch anpassbar
- **Stimmung & Beziehung** — Erika entwickelt eine eigene Stimmung und Beziehungsdynamik zu Personen
- **Fahrzeugabfragen** — Akku, Reichweite, Ladestatus per Sprache
- **PV-Anlage** — Leistung, Hausverbrauch, Netz-Ein-/Einspeiseverfolgung, Batterieladung; konfigurierbare Widget-Felder; Echtzeit-Update alle 5 s; Tages-/Wochen-/Monatsstatistik für Einspeisung und Netzbezug
- **Timer & Erinnerungen** — Labels, mehrere gleichzeitig, per Sprache verwalten
- **Kalender** — Einträge per Sprache, Tagesübersicht, CalDAV-ready via Home Assistant
- **Websuche** — Wikipedia-Provider, erweiterbar
- **Standort via zone.home** — Koordinaten direkt aus Home Assistant übernehmen, kein mehrdeutiges Geocoding
- **LLM-Router** — OpenAI-kompatibel (LM Studio, Ollama, OpenAI), Mock-Fallback wenn offline
- **CI/CD** — GitHub Actions: automatischer Build + Test-Run bei jedem Push

---

## Installation

Vollständige Anleitung: [`INSTALL_MANUAL.md`](INSTALL_MANUAL.md)

Kurzform auf einem frischen **Debian 12** / **Raspberry Pi OS (64-bit)** System:

```bash
curl -fsSL https://raw.githubusercontent.com/dennis-debaIT/robot-core/main/install.sh | bash
```

Das Script fragt interaktiv nach Home Assistant (vorhandene Instanz / HA Supervised neu installieren / später), LLM-Endpunkt und TTS-Provider, befüllt die `.env` automatisch und startet den Container. Vollständige manuelle Anleitung: [`INSTALL_MANUAL.md`](INSTALL_MANUAL.md)

---

## Starten / Stoppen

```bash
# Starten
cd ~/robot-core
docker compose up -d --build

# Stoppen
docker compose down

# Stoppen + Daten löschen
docker compose down -v
```

---

## Weboberfläche

| URL | Beschreibung |
|-----|-------------|
| `https://<ip>:8000/` | Display-Panel (Vollbild) |
| `https://<ip>:8000/local-admin` | Admin-Panel (Konfiguration) |
| `https://<ip>:8000/docs` | API-Dokumentation (Swagger) |

---

## Updates

Erika prüft automatisch alle 6 Stunden auf neue Commits. Im Admin-Panel unter **System → Updates** lässt sich auch manuell prüfen und installieren. Ein Update führt im Hintergrund `git pull` + Docker-Rebuild durch.

---

## Architektur

```text
robot-core/
  backend/
    app/
      main.py              # FastAPI-App, Background-Loops
      api/                 # REST-Endpoints (chat, memory, people, HA-Devices, …)
      brain/               # LLM-Client, Decision-Engine, Memory-System
      integrations/        # RobotCore — Haupt-Orchestrierung
      services/            # Home Assistant, Fahrzeuge, PV, TTS, Wetter, …
      search/              # Such-Provider (Wikipedia, HA, Wetter, …)
      database/            # SQLite-Schema, Verbindung, State-Helpers
      hardware/            # Fake-Adapter (Kamera, Mikrofon, Akku)
    requirements.txt
    Dockerfile
  frontend/
    local-admin.html       # Admin-Panel
    display.html           # Display-Panel
  docker-compose.yml
  VERSION
  install.sh
  update.sh
  INSTALL_MANUAL.md
```

**Kernprinzipien:**

- Das LLM bekommt nur kuratierte Daten: Nutzertext, Personality, freigegebene Memories und Suchkontext.
- Das LLM steuert keine Hardware direkt. Alle Entscheidungen über Aktionen laufen durch die Decision-Engine.
- Chat-Nachrichten durchlaufen zuerst direkte Handler (Timer, Licht, Kalender, …). Erst wenn kein Handler greift, kommt der LLM-Pfad.
- Profilwissen entsteht nur über die Approval-Queue — Erika schreibt nie direkt in ein Profil.
- Fake-Adapter in `backend/app/hardware/` sind Austauschpunkte für echte Hardware (Kamera, Mikrofon, Akku).

---

## LLM konfigurieren

Der Core erwartet eine OpenAI-kompatible HTTP-API. In `.env` oder `docker-compose.yml`:

```bash
LLM_PROVIDER=openai_compat
LLM_API_URL=http://192.168.1.254:1234/v1/chat/completions
LLM_MODEL=qwen/qwen3-4b-2507
LLM_TEMPERATURE=0.4
LLM_MAX_TOKENS=320
LLM_API_KEY=           # optional, leer lassen für lokale Instanzen
```

Empfohlen für lokalen Betrieb: **LM Studio** oder **Ollama** mit `qwen/qwen3-4b-2507`.

Wenn die API nicht erreichbar ist, fällt der Core automatisch auf das Mock-LLM zurück.

---

## TTS konfigurieren

Zwei Provider stehen bereit:

### Edge TTS (Online, Microsoft)

```bash
ROBOT_TTS_PROVIDER=edge_tts
ROBOT_TTS_VOICE_LABEL=de-DE-KatjaNeural
```

### Sherpa ONNX (Lokal, Offline)

Modell ins Projektverzeichnis ablegen:

```text
robot-core/
  models/
    tts/
      model.onnx
      tokens.txt
      espeak-ng-data/
```

```bash
ROBOT_TTS_PROVIDER=sherpa_onnx
ROBOT_TTS_VITS_MODEL=/models/tts/model.onnx
ROBOT_TTS_TOKENS=/models/tts/tokens.txt
ROBOT_TTS_DATA_DIR=/models/tts/espeak-ng-data
ROBOT_TTS_SPEAKER_ID=0
ROBOT_TTS_SPEED=1.0
ROBOT_TTS_NUM_THREADS=2
```

TTS-Stimmen und -Test sind im Admin-Panel unter **Erika → Stimme und Audio** verfügbar.

---

## Wichtige Umgebungsvariablen

```bash
# Verhalten
ROBOT_QUIET_MINUTES=5
ROBOT_CRITICAL_BATTERY_THRESHOLD=20
ROBOT_RESPONSE_STYLE=kurz, freundlich und präzise
ROBOT_EXPLAIN_ONLY_ON_REQUEST=true
ROBOT_LLM_TIMEOUT_SECONDS=45
ROBOT_LLM_MAX_TOKENS=320

# Persönlichkeit (0.0–1.0)
ROBOT_DEFAULT_FRIENDLINESS=0.9
ROBOT_DEFAULT_HUMOR=0.65
ROBOT_DEFAULT_CURIOSITY=0.75
ROBOT_DEFAULT_TALKATIVENESS=0.45
ROBOT_DEFAULT_CAUTION=0.8
ROBOT_DEFAULT_DIRECTNESS=0.7
ROBOT_DEFAULT_SARCASM=0.15
ROBOT_DEFAULT_PATIENCE=0.85

# Home Assistant
ROBOT_HA_URL=http://192.168.1.246:8123
ROBOT_HA_TOKEN=
```

Alle Werte lassen sich auch zur Laufzeit über das Admin-Panel ändern.

---

## PV konfigurieren

Im Admin-Panel unter **PV → Sensoren** werden die Home-Assistant-Entitäten für die Solaranlage eingetragen:

| Feld | Beschreibung |
|---|---|
| `power` | Aktuelle Erzeugungsleistung (W) |
| `daily` | Tagesertrag (kWh) |
| `temperature` | Wechselrichter-Temperatur |
| `battery` | Batterieladung (SOC, %) |
| `grid` | Netz-Sensor (positiv = Einspeisung, negativ = Netzbezug) |
| `battery_power` | Batterie-Leistung — **leer lassen bei DC-gekoppelten Systemen** |

> **Huawei SUN2000 + LUNA2000:** `sensor.wechselrichter_wirkleistung` als `power` verwenden (AC-Ausgang, nettet DC-Batterie-Transaktionen bereits heraus). `battery_power` leer lassen. Als `grid` den `sensor.stromzahler_wirkleistung` eintragen.

Unter **PV → Widget-Anzeige** lässt sich per Checkbox wählen, welche Felder im Display-Widget erscheinen.

---

## Tests

Tests laufen in Docker — keine lokale Python-Installation nötig:

```bash
# Einmalig bauen
docker compose build robot-core-test

# Tests ausführen
docker compose --profile test run --rm robot-core-test
```

CI läuft automatisch via GitHub Actions bei jedem Push auf `main`.

---

## API-Kurzreferenz

```bash
# Health
curl https://localhost:8000/health

# Chat
curl -X POST https://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Hallo, ich heiße Anna","person_name":"Anna"}'

# Memory vorschlagen
curl -X POST https://localhost:8000/memory/propose \
  -H "Content-Type: application/json" \
  -d '{"content":"Anna mag Kaffee.","category":"preference","subject":"Anna"}'

# Memory freigeben / ablehnen
curl -X POST https://localhost:8000/memory/approve/1
curl -X POST https://localhost:8000/memory/reject/1
```

Vollständige API-Dokumentation: `https://<ip>:8000/docs`
