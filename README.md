# Robot Core v0.2-alpha

Ein lauffähiger Startpunkt für den Software-Core eines sozialen KI-Roboters mit FastAPI, SQLite, Web-Control-Panel, Mock-LLM-Fallback, Personality-System, Memory-Approval-Queue und simulierten Hardware-Events.

## Start

Voraussetzung auf `erika`:

- Docker
- Docker Compose

Projekt nach `~/robot-core` kopieren und dann starten:

```bash
cd ~/robot-core
docker compose up --build -d
```

Danach:

- Weboberfläche: `http://localhost:8000/`
- API-Docs: `http://localhost:8000/docs`

## Stop

```bash
cd ~/robot-core
docker compose down
```

Mit Daten-Löschung:

```bash
cd ~/robot-core
docker compose down -v
```

## Python-Tests

Tests laufen über Docker, damit keine lokale Python-Installation nötig ist.

Einmalig bauen:

```bash
cd ~/robot-core
docker compose build robot-core-test
```

Tests ausführen:

```bash
cd ~/robot-core
docker compose run --rm robot-core-test
```

## Test-Endpunkte

Health:

```bash
curl http://localhost:8000/health
```

Status:

```bash
curl http://localhost:8000/status
```

Konfiguration lesen:

```bash
curl http://localhost:8000/config
```

Konfiguration zur Laufzeit ändern:

```bash
curl -X PATCH http://localhost:8000/config \
  -H "Content-Type: application/json" \
  -d '{"quiet_minutes":2,"response_style":"kurz und direkt","llm_timeout_seconds":10}'
```

Chat mit Mock-LLM oder externem LLM:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Hallo, ich heiße Anna","person_name":"Anna"}'
```

Memory vorschlagen:

```bash
curl -X POST http://localhost:8000/memory/propose \
  -H "Content-Type: application/json" \
  -d '{"content":"Anna ist Stammgast.","category":"person_profile","subject":"Anna"}'
```

Memory freigeben:

```bash
curl -X POST http://localhost:8000/memory/approve/1
```

Memory ablehnen:

```bash
curl -X POST http://localhost:8000/memory/reject/1
```

Bekannte Person simulieren:

```bash
curl -X POST http://localhost:8000/simulate/person \
  -H "Content-Type: application/json" \
  -d '{"person_name":"Anna"}'
```

Akku simulieren:

```bash
curl -X POST http://localhost:8000/simulate/battery \
  -H "Content-Type: application/json" \
  -d '{"level":55}'
```

Sprache simulieren:

```bash
curl -X POST http://localhost:8000/simulate/speech \
  -H "Content-Type: application/json" \
  -d '{"text":"Ich mag Kaffee","person_name":"Anna"}'
```

Display simulieren:

```bash
curl -X POST http://localhost:8000/simulate/display \
  -H "Content-Type: application/json" \
  -d '{"status":"ready"}'
```

Persönlichkeit lesen:

```bash
curl http://localhost:8000/personality
```

Profile lesen:

```bash
curl http://localhost:8000/profiles
```

TTS-Status lesen:

```bash
curl http://localhost:8000/tts/status
```

TTS-Audio erzeugen:

```bash
curl -X POST http://localhost:8000/tts/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text":"Hallo, ich bin Erika."}' \
  --output erika.wav
```

Persönlichkeit ändern:

```bash
curl -X PATCH http://localhost:8000/personality \
  -H "Content-Type: application/json" \
  -d '{"humor":0.8,"talkativeness":0.35}'
```

## Projektstruktur

```text
robot-core/
  backend/
    app/
      main.py
      api/
      brain/
      memory/
      integrations/
      simulator/
      hardware/
      database/
    requirements.txt
    Dockerfile
  frontend/
  docker-compose.yml
  README.md
```

## Architekturhinweise

- Das LLM bekommt nur kuratierte Kontextdaten: Nutzertext, Personality und freigegebene Memories.
- Das LLM steuert keine Hardware direkt. Entscheidungen über Status, Simulation und spätere Hardware-Aktionen bleiben im Robot-Core.
- Die zentrale Konfiguration kommt aus zwei Quellen:
  - Environment-Defaults beim Containerstart
  - Runtime-Overrides per `PATCH /config`, gespeichert im Core
- Chat-Inhalte laufen zuerst durch eine Decision-Engine:
  - sie entscheidet, ob etwas nur Gespräch ist
  - ob ein Memory-Kandidat entsteht
  - ob etwas profilrelevant ist
  - erst danach wird ein Vorschlag in die Approval-Queue geschrieben
- Freigegebene profilrelevante Memories werden zusätzlich in ein strukturiertes Personenprofil materialisiert.
- Die Fake-Adapter in `backend/app/hardware/` sind als Austauschpunkte gedacht:
  - `fake_camera.py`
  - `fake_microphone.py`
  - `fake_battery.py`
- Echte Adapter können später dieselben Schnittstellen implementieren und vom Core statt der Fake-Varianten instanziiert werden.

## Wichtige Konfigurationsvariablen

```bash
ROBOT_QUIET_MINUTES=5
ROBOT_CRITICAL_BATTERY_THRESHOLD=20
ROBOT_RESPONSE_STYLE=kurz, freundlich und präzise
ROBOT_EXPLAIN_ONLY_ON_REQUEST=true
ROBOT_GREETING_SUGGESTION_TEMPLATE=Kurze Begrüßung für {person_name} vorschlagen.
ROBOT_LLM_TIMEOUT_SECONDS=15
ROBOT_DEFAULT_FRIENDLINESS=0.9
ROBOT_DEFAULT_HUMOR=0.65
ROBOT_DEFAULT_CURIOSITY=0.75
ROBOT_DEFAULT_TALKATIVENESS=0.45
ROBOT_DEFAULT_CAUTION=0.8
ROBOT_DEFAULT_DIRECTNESS=0.7
ROBOT_DEFAULT_SARCASM=0.15
ROBOT_DEFAULT_PATIENCE=0.85
ROBOT_TTS_PROVIDER=disabled
ROBOT_TTS_VOICE_LABEL=Milly
ROBOT_TTS_SPEED=1.0
ROBOT_TTS_SPEAKER_ID=0
ROBOT_TTS_NUM_THREADS=2
ROBOT_TTS_VITS_MODEL=/models/tts/model.onnx
ROBOT_TTS_TOKENS=/models/tts/tokens.txt
ROBOT_TTS_DATA_DIR=/models/tts/espeak-ng-data
ROBOT_TTS_LEXICON=
ROBOT_TTS_RULE_FSTS=
```

Die Runtime-Konfiguration lässt sich zusätzlich direkt über die Weboberfläche steuern.

## Lokales TTS mit sherpa-onnx

Für den ersten lokalen TTS-Pfad ist `sherpa-onnx` vorbereitet. Der aktuelle Build erwartet ein VITS-/Piper-kompatibles Modell mit:

- `model.onnx`
- `tokens.txt`
- `espeak-ng-data/`

Empfohlene Ablage im Projekt:

```text
robot-core/
  models/
    tts/
      model.onnx
      tokens.txt
      espeak-ng-data/
```

Dann in `.env` oder `docker-compose.yml` aktivieren:

```bash
ROBOT_TTS_PROVIDER=sherpa_onnx
ROBOT_TTS_VOICE_LABEL=Milly
ROBOT_TTS_VITS_MODEL=/models/tts/model.onnx
ROBOT_TTS_TOKENS=/models/tts/tokens.txt
ROBOT_TTS_DATA_DIR=/models/tts/espeak-ng-data
ROBOT_TTS_SPEAKER_ID=0
ROBOT_TTS_SPEED=1.0
ROBOT_TTS_NUM_THREADS=2
```

Die Weboberfläche bietet dafür unter `System -> Stimme und Audio` einen direkten Testpfad.

## Wie später ein echtes LLM angebunden wird

Der Core erwartet später eine HTTP-API. In `backend/app/brain/llm_client.py` ist bereits ein externer Client vorbereitet.

1. Eine externe LLM-API bereitstellen, die `POST` mit JSON entgegennimmt.
2. Das Antwortformat sollte mindestens eines der Felder `reply`, `message` oder `text` liefern.
3. In `docker-compose.yml` oder einer `.env` setzen:

```bash
LLM_PROVIDER=openai_compat
LLM_API_URL=http://192.168.1.254:1234/v1/chat/completions
LLM_MODEL=qwen/qwen3-4b-2507
LLM_TEMPERATURE=0.4
LLM_MAX_TOKENS=320
LLM_API_KEY=optional
```

4. Container neu starten:

```bash
docker compose up --build -d
```

Wenn die externe API nicht gesetzt ist oder fehlschlägt, fällt der Core automatisch auf das Mock-LLM zurück.

Für LM Studio mit OpenAI-kompatibler API ist `qwen/qwen3-4b-2507` aktuell der empfohlene Standard für schnelle Alltagsgespräche.
# v1.0.1
