# Erika — Admin- und Einrichtungsanleitung

Diese Anleitung richtet sich an Personen, die eine Erika-Instanz einrichten, konfigurieren oder warten.  
Für die tägliche Nutzung (Sprachbefehle, Display-Funktionen) → [`ANLEITUNG.md`](ANLEITUNG.md)

---

## Inhaltsverzeichnis

1. [Installation](#1-installation)
2. [Starten & Stoppen](#2-starten--stoppen)
3. [Updates](#3-updates)
4. [Wichtige Umgebungsvariablen](#4-wichtige-umgebungsvariablen)
5. [LLM konfigurieren](#5-llm-konfigurieren)
6. [TTS konfigurieren](#6-tts-konfigurieren)
7. [Home Assistant verbinden](#7-home-assistant-verbinden)
8. [PV-Anlage konfigurieren](#8-pv-anlage-konfigurieren)
9. [Sync Server & Auth](#9-sync-server--auth)
10. [Auth-System (v3.0 — E-Mail/Passwort)](#10-auth-system-v30--e-mailpasswort)
11. [Lizenzverwaltung & Tiers](#11-lizenzverwaltung--tiers)
12. [Erika Companion App einrichten](#12-erika-companion-app-einrichten)
13. [Backup & Wiederherstellung](#13-backup--wiederherstellung)
14. [Diagnose & Protokoll](#14-diagnose--protokoll)
15. [Weboberflächen-Referenz](#15-weboberflächen-referenz)
16. [Tests & CI](#16-tests--ci)
17. [Architektur-Übersicht](#17-architektur-übersicht)

---

## 1. Installation

Vollständige Schritt-für-Schritt-Anleitung: [`INSTALL_MANUAL.md`](INSTALL_MANUAL.md)

**Kurzform** auf einem frischen **Debian 12** / **Raspberry Pi OS (64-bit)** System:

```bash
curl -fsSL https://raw.githubusercontent.com/dennis-debaIT/robot-core/main/install.sh | bash
```

Das Script fragt interaktiv nach:
- Home Assistant (vorhandene Instanz / HA Supervised neu installieren / später)
- LLM-Endpunkt und Modell
- TTS-Provider (Edge TTS / Sherpa ONNX)

Es befüllt die `.env` automatisch und startet den Container.

---

## 2. Starten & Stoppen

```bash
# Starten (mit Code-Rebuild)
cd ~/robot-core
docker compose up -d --build

# Stoppen
docker compose down

# Stoppen + alle Daten löschen (!)
docker compose down -v

# Logs live verfolgen
docker compose logs -f robot-core
```

---

## 3. Updates

Erika prüft automatisch alle 6 Stunden auf neue Commits im Repository.  
Im Admin-Panel unter **System → Updates** kann manuell geprüft und installiert werden.

**Manuell per Script:**

```bash
cd ~/robot-core
./update.sh
```

`update.sh` führt automatisch aus:
- `git pull` für den neuesten Code
- Docker-Rebuild (`docker compose up -d --build`)
- Firebase-Credentials-Injektion in `.env` (einmalig, wenn noch nicht vorhanden)
- `restore.env` → `.env` übernehmen falls ein Backup-Restore anhängig ist

---

## 4. Wichtige Umgebungsvariablen

Alle Werte werden in `~/robot-core/.env` gesetzt. Sie können auch zur Laufzeit im Admin-Panel geändert werden (Ausnahme: Sync-Credentials, die aus `license.json` kommen).

```bash
# Verhalten
ROBOT_QUIET_MINUTES=5
ROBOT_CRITICAL_BATTERY_THRESHOLD=20
ROBOT_RESPONSE_STYLE=kurz, freundlich und präzise
ROBOT_LLM_TIMEOUT_SECONDS=45
ROBOT_LLM_MAX_TOKENS=320

# Persönlichkeits-Defaults (0.0–1.0)
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

# Zeitzone
TZ=Europe/Berlin

# CORS (für lokale Entwicklung/mehrere Browser)
ROBOT_CORS_ORIGINS=http://localhost:3000,http://192.168.1.243:8000
```

---

## 5. LLM konfigurieren

Der Core erwartet eine OpenAI-kompatible HTTP-API.

```bash
LLM_PROVIDER=openai_compat
LLM_API_URL=http://192.168.1.254:1234/v1/chat/completions
LLM_MODEL=qwen/qwen3-4b-2507
LLM_TEMPERATURE=0.4
LLM_MAX_TOKENS=320
LLM_API_KEY=           # leer lassen für lokale Instanzen
```

**Empfohlene lokale LLM-Optionen:**
- **LM Studio** — grafische Oberfläche, einfach einzurichten
- **Ollama** — leichtgewichtig, auch auf ARM (Raspberry Pi 5)

Wenn die API nicht erreichbar ist, fällt der Core automatisch auf einen Mock-LLM-Fallback zurück.

Im Admin-Panel unter **Konfiguration → LLM** kann der Endpunkt zur Laufzeit geändert werden. Unter **Konfiguration → LLM → Fallback** lässt sich ein zweiter Endpunkt als Reserve hinterlegen.

---

## 6. TTS konfigurieren

### Edge TTS (Online, Microsoft — Standard)

```bash
ROBOT_TTS_PROVIDER=edge_tts
ROBOT_TTS_VOICE_LABEL=de-DE-KatjaNeural
```

Erfordert Internetverbindung. Stimmen sind kostenlos (Azure-Infrastruktur, no API Key).  
Verfügbare Stimmen testbar im Admin unter **Erika → Stimme und Audio**.

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

Vollständige Modell-Einrichtung: [`project_tts_deployment`-Memory](../memory/project_tts_deployment.md) oder direkt im Admin unter **Erika → Stimme und Audio → Sherpa ONNX**.

---

## 7. Home Assistant verbinden

1. In Home Assistant: **Profil → Langlebige Zugriffstoken → Token erstellen**
2. Token in `.env` als `ROBOT_HA_TOKEN` eintragen (oder im Admin unter **Integrationen → Home Assistant**)
3. `ROBOT_HA_URL` auf die interne HA-Adresse setzen (z.B. `http://192.168.1.246:8123`)
4. Im Admin → System → Diagnose prüfen ob die Verbindung grün ist

**Standort aus HA übernehmen:**  
Im Admin unter **System → Standort** den Button **"Von HA übernehmen"** klicken — liest `zone.home` automatisch aus.

---

## 8. PV-Anlage konfigurieren

Im Admin-Panel unter **PV → Sensoren** werden die Home-Assistant-Entitäten eingetragen:

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

## 9. Sync Server & Auth

Der **Erika Sync Server** (`erika-sync-server`) ist ein separater FastAPI-Dienst, der den bidirektionalen Sync zwischen Erika-Display und Companion App ermöglicht.

### Betrieb

- Läuft als systemd-Service (kein Docker) auf `erika.wdk-it.de`, Port 9000
- Datenbank: `/opt/erika-sync-server/data/sync.db` (SQLite mit WAL-Modus)
- Tägliches Backup: systemd-Timer, 03:00 Uhr, 14 Versionen → `/opt/erika-sync-server/backups/`
- Neuinstallation: `scripts/setup.sh` als root ausführen

### robot-core verbinden

Die Sync-Credentials werden in `~/robot-core/license.json` hinterlegt:

```json
{
  "sync_url": "https://erika.wdk-it.de:9000",
  "sync_email": "dein@email.de",
  "sync_password": "deinPasswort"
}
```

Alternativ als Umgebungsvariablen in `.env`:

```bash
SHOPPING_SYNC_URL=https://erika.wdk-it.de:9000
SYNC_EMAIL=dein@email.de
SYNC_PASSWORD=deinPasswort
```

> **Legacy:** Das ältere statische `SHOPPING_SYNC_TOKEN` wird weiterhin als Fallback akzeptiert, ist aber veraltet. Bei Neueinrichtungen immer E-Mail/Passwort verwenden.

### Wartung

```bash
# Status prüfen
ssh root@erika.wdk-it.de -p 2122
systemctl status erika-sync

# Logs
journalctl -u erika-sync -f

# Health-Check (von außen)
curl -sk https://erika.wdk-it.de:9000/health

# Manuelle Backup-Übersicht
ls -lh /opt/erika-sync-server/backups/
```

---

## 10. Auth-System (v3.0 — E-Mail/Passwort)

Ab Sync Server v3.0 wird die Authentifizierung über E-Mail + Passwort statt einem statischen Lizenz-Token abgewickelt.

### Kernkonzepte

| Konzept | Beschreibung |
|---|---|
| **Tenant** | Eine Erika-Instanz mit ihren zugehörigen Benutzern |
| **Master** | Primärer Account des Tenants, kann weitere Mitglieder einladen |
| **Member** | Zusätzlicher Account im gleichen Tenant (Family-Tier) |
| **Tier** | `community`, `plus`, `family` — steuert verfügbare Features |
| **Activation-based Licensing** | Lizenzlaufzeit startet erst beim **ersten Login**, nicht beim Kauf |

### JWT-Tokens

- **Access-Token**: Gültig 1 Stunde, wird von robot-core und App bei jedem Request mitgeschickt
- **Refresh-Token**: Gültig 30 Tage, rotierend — altes Token wird bei Refresh widerrufen
- robot-core erneuert das Token automatisch (5 Minuten vor Ablauf)

### Admin-Endpoints (X-Admin-Key)

Für die manuelle Verwaltung von Tenants und Accounts (z.B. Tester, neue Kunden):

```bash
# Neuen Account anlegen
curl -X POST https://erika.wdk-it.de:9000/admin/users \
  -H "X-Admin-Key: <admin-schluessel>" \
  -H "Content-Type: application/json" \
  -d '{"email":"kunde@beispiel.de","password":"StartPasswort","tier":"plus"}'

# Account bearbeiten (Tier ändern, Laufzeit verlängern, deaktivieren)
curl -X PATCH https://erika.wdk-it.de:9000/admin/users/1 \
  -H "X-Admin-Key: <admin-schluessel>" \
  -H "Content-Type: application/json" \
  -d '{"tier":"family","expires_at":"2027-01-01T00:00:00Z"}'

# Alle Tenants auflisten
curl -s https://erika.wdk-it.de:9000/admin/users \
  -H "X-Admin-Key: <admin-schluessel>"
```

Der Admin-Key wird in der `.env` des Sync Servers als `ADMIN_API_KEY` hinterlegt.

### Family-Tier: Weitere Benutzer einladen

Ein Master-Account kann weitere Mitglieder über den Sync-Server-Endpoint einladen:

```bash
curl -X POST https://erika.wdk-it.de:9000/auth/invite \
  -H "Authorization: Bearer <access-token>" \
  -H "Content-Type: application/json" \
  -d '{"email":"partner@beispiel.de"}'
```

Das eingeladene Mitglied erhält eine Einladungs-E-Mail (wenn E-Mail-Versand konfiguriert ist) oder der Einladungslink wird direkt zurückgegeben.

### Nachrichten-System

Der Sync Server verfügt über ein internes Nachrichten-System für Erika↔Erika und Erika↔App Kommunikation:

```bash
# Nachricht senden
POST /messages
# Nachrichten abholen (optional: seit Zeitstempel)
GET /messages/inbox?since=2026-07-01T00:00:00Z
# Als gelesen markieren
PATCH /messages/{id}/read
```

FCM Push-Benachrichtigungen werden bei jeder eingehenden Nachricht fire-and-forget gefeuert.

---

## 11. Lizenzverwaltung & Tiers

### Feature-Flags

| Tier | Enthaltene Plus-Features |
|---|---|
| **Community** | Display, Sprachsteuerung, alle Basis-Features kostenlos |
| **Plus** | Hausaufgaben, Zeitabhängiges Design, Kamera-Ereignisliste, Fahrzeug-Verlauf, PV-Statistik & Kosten, Liga Plus (Marktwerte etc.) |
| **Family** | Alle Plus-Features + mehrere Benutzer pro Tenant |

### Lokales Feature-Override (für Tests)

Im Admin unter **System → Edition-Preview** lässt sich ein temporärer Override für das Feature-Set setzen, ohne die Lizenz zu verändern. Der Override wird in der DB gespeichert und ist Cross-Device wirksam.

### BYOK-LLM

Nutzer können einen eigenen LLM-API-Key (z.B. OpenAI) in `.env` hinterlegen. Dieser Key wird niemals an den Sync Server übermittelt.

---

## 12. Erika Companion App einrichten

### Voraussetzungen

- Android-Gerät
- Sync Server erreichbar (HTTPS, Port 9000)
- FCM (Firebase Cloud Messaging) für Push-Notifications konfiguriert:
  - `FIREBASE_CREDENTIALS_B64` in robot-core `.env` — wird automatisch von `update.sh` injiziert
  - `FCM_SERVICE_ACCOUNT_KEY` im Sync Server (in `.env` oder als JSON-Datei)

### Einrichtung auf dem Gerät

1. App installieren
2. Beim ersten Start: **"Mit Lizenz anmelden"** auswählen
3. E-Mail und Passwort des Erika-Accounts eingeben
4. App holt automatisch `sync_url` vom License Server und registriert den FCM-Token

### FCM-Token-Registrierung

Die App sendet ihren FCM-Token automatisch beim Start an den Sync Server (`POST /devices/token`). robot-core holt die Tokens regelmäßig ab (`GET /devices/tokens`) und verwendet sie für Push-Notifications.

---

## 13. Backup & Wiederherstellung

### Cloud-Backup (via Admin-Panel)

Das Cloud-Backup speichert die SQLite-Datenbank **und** alle `.env`-Einstellungen (HA-Token, LLM-Key, Sync-Credentials etc.) verschlüsselt im Sync Server.

- **Verschlüsselung:** Fernet/AES-256, Key abgeleitet vom Sync-Token
- **Speicherort:** Sync Server, Tabelle `backups`, max. 50 MB, ein Slot pro Tenant
- **Backup erstellen:** Admin → System → Cloud-Backup → „☁️ Backup erstellen"
- **Wiederherstellen:** Admin → System → Cloud-Backup → „↩️ Wiederherstellen"

### Sync-Server-Backup (automatisch)

Der Sync Server erstellt täglich um 03:00 Uhr ein lokales SQLite-Backup:

- **Speicherort:** `/opt/erika-sync-server/backups/sync-YYYY-MM-DD.db`
- **Aufbewahrung:** 14 Versionen (ältere werden automatisch gelöscht)
- **Methode:** `sqlite3 .backup` — atomar, kein Service-Stopp nötig (WAL-safe)

```bash
# Letztes Backup prüfen
ls -lh /opt/erika-sync-server/backups/

# Manuelles Backup auslösen
/opt/erika-sync-server/scripts/backup-db.sh

# Timer-Status
systemctl status erika-sync-backup.timer
```

### Wiederherstellung nach Totalausfall

1. Neues System aufsetzen: `install.sh` ausführen
2. `~/robot-core/license.json` anlegen mit Sync-Credentials (E-Mail + Passwort)
3. `./update.sh` ausführen
4. Im Admin → System → Cloud-Backup auf **„↩️ Wiederherstellen"** klicken
5. Erika startet automatisch neu — alle Einstellungen wiederhergestellt

---

## 14. Diagnose & Protokoll

### Diagnose-Check

Im Admin unter **System → Diagnose** werden alle Integrationen auf Verbindbarkeit geprüft:

- Home Assistant (Verbindung + Token-Gültigkeit)
- LLM-Endpunkt (erreichbar + antwortet)
- Sync Server (HTTPS-Verbindung + Auth)
- Internet (DNS-Auflösung)

### Protokoll (Audit-Log)

Im Admin unter **Protokoll** werden alle relevanten Systemereignisse angezeigt.

**Filter-Optionen:**
- **Level:** Alle / Info / Warnung / Fehler
- **Aktionstyp:** Freitext-Suche
- **Anzahl:** 50 / 100 / 200 / 500 Einträge

**Level-Bedeutung:**
- 🟢 `info` — Normale Systemaktivität (Login, Backup, Licht-Erinnerung ausgeführt)
- 🟡 `warning` — Unregelmäßigkeiten ohne Ausfall (falsche PIN, LLM-Fallback)
- 🔴 `error` — Fehler, die eine Reaktion erfordern (LLM nicht erreichbar, Backup-Fehler)

---

## 15. Weboberflächen-Referenz

| URL | Beschreibung |
|---|---|
| `https://<ip>:8000/` | Lokale Konsole (Chat, Status, Diagnose) |
| `https://<ip>:8000/display` | Display-Panel (Vollbild) |
| `https://<ip>:8000/local-admin` | Admin-Panel (Konfiguration) |
| `https://<ip>:8000/docs` | API-Dokumentation (Swagger) |

> Das Zertifikat ist self-signed — Browser-Warnung beim ersten Aufruf ist normal. Im Kiosk-Modus wird es automatisch per Policy-Datei freigegeben.

### Kiosk-Modus (Raspberry Pi)

`install.sh` richtet Chromium automatisch als Vollbild-Kiosk ein:
- Kamera und Mikrofon per Policy-Datei freigegeben (kein Browser-Dialog)
- Autostart via `~/.config/autostart/erika-kiosk.desktop` (8 Sekunden Verzögerung)
- Manuelle Einrichtung: [`INSTALL_MANUAL.md`](INSTALL_MANUAL.md), Schritt 9

---

## 16. Tests & CI

Tests laufen in Docker — keine lokale Python-Installation nötig:

```bash
# Einmalig Test-Image bauen
docker compose build robot-core-test

# Tests ausführen
docker compose --profile test run --rm robot-core-test
```

CI läuft automatisch via GitHub Actions (`.github/workflows/ci.yml`) bei jedem Push auf `main`:
- Docker-Image bauen
- Komplette Test-Suite ausführen

---

## 17. Architektur-Übersicht

```text
robot-core/
  backend/
    app/
      main.py              # FastAPI-App, Background-Loops
      api/                 # REST-Endpoints
        routers/
          chores.py        # Hausaufgaben (Plus — Community-Build entfernt)
          sync.py          # Einkaufslisten-Sync
          content.py       # /display/state (modules-Dict)
          ...
      brain/               # LLM-Client, Decision-Engine, Memory-System
      integrations/        # RobotCore — Haupt-Orchestrierung
      services/
        chore_service.py   # Hausaufgaben-Logik (Plus)
        sync_service.py    # Einkaufslisten-Sync-Logik
        feature_service.py # Feature-Flags (community/plus/family)
        ...
      search/              # Such-Provider (Wikipedia, HA, Wetter, …)
      database/            # SQLite-Schema, Verbindung, State-Helpers
      hardware/            # Fake-Adapter (Kamera, Mikrofon, Akku)
    requirements.txt
    Dockerfile
  frontend/
    local-admin.html       # Admin-Panel
    display.html           # Display-Panel
    display-chores.js      # Hausaufgaben-Modul (Plus — Community-Build entfernt)
  docker-compose.yml
  VERSION
  install.sh
  update.sh
  license.json             # Sync-Credentials (E-Mail/Passwort + sync_url)
  INSTALL_MANUAL.md

erika-sync-server/         # Separates Repo / Deployment
  app/                     # FastAPI-App
  scripts/
    setup.sh               # Einmalige Installation auf dem Server
    backup-db.sh           # Tägliches SQLite-Backup
  systemd/
    erika-sync.service
    erika-sync-backup.service
    erika-sync-backup.timer
```

**Kernprinzipien:**

- Das LLM bekommt nur kuratierte Daten: Nutzertext, Personality, freigegebene Memories und Suchkontext.
- Das LLM steuert keine Hardware direkt. Alle Entscheidungen über Aktionen laufen durch die Decision-Engine.
- Chat-Nachrichten durchlaufen zuerst direkte Handler (Timer, Licht, Kalender, …). Erst wenn kein Handler greift, kommt der LLM-Pfad.
- Profilwissen entsteht nur über die Approval-Queue — Erika schreibt nie direkt in ein Profil.
- Plus/Family-Features werden im Community-Build aus dem Docker-Image entfernt (analog `ha_pv_stats.py`-Muster). Feature-Flags steuern die Sichtbarkeit zur Laufzeit.
- Fake-Adapter in `backend/app/hardware/` sind Austauschpunkte für echte Hardware.
