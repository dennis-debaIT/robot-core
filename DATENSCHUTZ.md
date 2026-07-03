# Datenschutz — Welche Daten gehen wohin?

> Stand: Juli 2026 · Version v0.3.0  
> Dieses Dokument beschreibt, welche Daten Erika an externe Dienste übermittelt — abhängig von der gewählten Konfiguration.

---

## Überblick

| Dienst | Daten die gesendet werden | Netzwerk | Pflicht? |
|--------|--------------------------|----------|----------|
| **Home Assistant** | Entity-IDs, Service-Calls | lokal | ja |
| **LLM (lokal)** | Gesprächstext, Persönlichkeit, Profildaten | lokal | empfohlen |
| **LLM (extern, z.B. OpenAI)** | Gesprächstext, Persönlichkeit, Profildaten | Internet | alternativ |
| **Edge TTS (Microsoft)** | Erikas Antworttext | Internet | nur wenn aktiviert |
| **Sherpa ONNX (TTS)** | nichts — alles lokal | lokal | nur wenn aktiviert |
| **Open-Meteo** | Ortsname | Internet | nur bei Wetter-Nutzung |
| **Yr.no (met.no)** | GPS-Koordinaten | Internet | nur wenn ausgewählt |
| **OpenWeatherMap** | Ortsname, API-Key | Internet | nur wenn ausgewählt |
| **Wikipedia** | Suchbegriff aus Nutzeranfrage | Internet | nur bei passenden Fragen |
| **DuckDuckGo** | Suchbegriff aus Nutzeranfrage | Internet | nur bei passenden Fragen |
| **GitHub** | nichts (nur pull/fetch) | Internet | für Updates |
| **RSS-Feeds** | nichts (nur fetch) | Internet | nur wenn konfiguriert |
| **Erika Sync Server** | Sync-Daten, FCM-Token, verschlüsseltes Backup | Internet (eigener Server) | nur wenn Companion App genutzt wird |
| **Firebase (FCM)** | FCM-Token, Benachrichtigungsinhalt (Titel + Text) | Internet | nur wenn Push-Benachrichtigungen aktiviert |

---

## Details

---

### Home Assistant

**Was wird gesendet:**
- HTTP-Anfragen an die lokale HA-Instanz (konfigurierbare IP, Standard `http://192.168.1.246:8123`)
- Entity-IDs beim Lesen von Zuständen (Lichter, Fahrzeuge, PV, Roboter, Kameras, Kalender, Sensoren)
- Service-Calls beim Steuern (z.B. `light.turn_on`, `vacuum.start`, `button.press`)
- HA-Token im Authorization-Header

**Was NICHT gesendet wird:**
- Gesprächsinhalte oder Nutzerdaten
- Persönlichkeitsdaten oder Memories

**Datenspeicherung bei HA:**
- HA führt eigene Logs. Was HA mit den Service-Calls protokolliert, richtet sich nach der HA-Konfiguration.

**Netzwerk:** Ausschließlich lokales Heimnetz. Kein Traffic ins Internet.

---

### LLM — lokale Instanz (LM Studio / Ollama)

**Was wird gesendet:**
- System-Prompt, der enthält:
  - Erikas Persönlichkeitsparameter (Freundlichkeit, Humor usw.)
  - Stimmung und aktueller Beziehungszustand zur Person
  - Freigegebene Profil-Fakten der erkannten Person (Name, Alter, Wohnort, Vorlieben usw.)
  - Freigegebene Memories (kategoriebezogene Kurznotizen)
  - Aktuelle Gesprächszusammenfassungen (Tages- und Wochensummaries)
- Gesprächshistorie (letzte ~40 Nachrichten)
- Aktuelle Nutzeranfrage
- Optional: Suchergebnis-Snippet (Wikipedia / DuckDuckGo), wenn Erika eine Recherche durchgeführt hat

**Was NICHT gesendet wird:**
- Rohe Audiodaten
- Kamerabilder / Gesichtserkennungsdaten
- Nicht freigegebene (pending) Memory-Vorschläge
- Passwörter oder API-Keys

**Netzwerk:** Lokales Heimnetz (keine Internetverbindung nötig). Empfohlen für datenschutzsensible Nutzung.

---

### LLM — externer Dienst (OpenAI o.ä.)

**Was wird gesendet:** Identisch zur lokalen Instanz (siehe oben), jedoch über das Internet an den externen Anbieter.

**Hinweis:** Gesprächsinhalte, Personenprofile und Memories verlassen dabei das Heimnetz und werden an den Anbieter (z.B. OpenAI, Anthropic) übertragen. Deren Datenschutzrichtlinien gelten zusätzlich.

**Netzwerk:** Internet. Nur verwenden, wenn die Datenschutzanforderungen des Anbieters akzeptiert werden.

---

### TTS — Edge TTS (Microsoft)

**Was wird gesendet:**
- Erikas fertige Antwort als Klartext (kein Nutzertext, keine Fragen)
- Name der gewählten Stimme (z.B. `de-DE-KatjaNeural`)

**Technisch:** Die `edge-tts`-Bibliothek nutzt die öffentliche Microsoft Azure Speech-Infrastruktur. Es wird kein Microsoft-Konto oder API-Key benötigt.

**Was NICHT gesendet wird:**
- Nutzeranfragen
- Persönlichkeits- oder Profildaten

**Netzwerk:** Internetverbindung erforderlich.

**Alternative:** Sherpa ONNX verwenden für vollständig lokale Sprachausgabe.

---

### TTS — Sherpa ONNX (lokal)

Alle Verarbeitung findet lokal im Container statt. Es werden keine Daten übertragen.

---

### Wetter — Open-Meteo

**Was wird gesendet:**
- Geocoding-Anfrage: konfigurierter Ortsname (z.B. "Ostenfeld")  
  → `https://geocoding-api.open-meteo.com/v1/search?name=Ostenfeld`
- Wetteranfrage: GPS-Koordinaten (aus dem Geocoding-Ergebnis), Zeitzone, gewünschte Felder  
  → `https://api.open-meteo.com/v1/forecast?latitude=…&longitude=…`

**Kein API-Key** erforderlich. Open-Meteo ist ein Open-Source-Projekt (Lizenz: CC BY 4.0).

**Netzwerk:** Internet.

---

### Wetter — Yr.no (met.no)

**Was wird gesendet:**
- GPS-Koordinaten (Breiten- und Längengrad des konfigurierten Orts)  
  → `https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=…&lon=…`
- User-Agent-Header mit Projektname und GitHub-URL

**Betreiber:** Norwegischer Wetterdienst (Meteorologisk institutt). Kein API-Key erforderlich.

**Netzwerk:** Internet.

---

### Wetter — OpenWeatherMap

**Was wird gesendet:**
- Ortsname oder GPS-Koordinaten
- API-Key (im Query-Parameter)

**Betreiber:** OpenWeather Ltd. (kommerzielle API). API-Key in der `.env` konfiguriert.

**Netzwerk:** Internet.

---

### Wikipedia

**Was wird gesendet:**
- Suchbegriff, der aus der Nutzeranfrage extrahiert wurde (z.B. "Albert Einstein")  
  → `https://de.wikipedia.org/api/rest_v1/page/summary/{Begriff}`
- User-Agent-Header: `ErikaRobot/1.0`

**Kein Account, kein API-Key** erforderlich. Wikipedia REST API ist öffentlich.

**Wann wird Wikipedia gefragt:** Nur bei Faktenfragen ("Wer ist …", "Was ist …", "Wie funktioniert …"). Nicht bei jedem Gespräch.

**Netzwerk:** Internet.

---

### DuckDuckGo (Web-Suche)

**Was wird gesendet:**
- Suchbegriff, der aus der Nutzeranfrage abgeleitet wurde
- Region `de-de`, SafeSearch `moderate`

**Technisch:** Die `duckduckgo_search`-Bibliothek fragt die DuckDuckGo-API ab. Kein API-Key, kein Account.

**Wann:** Als Fallback bei Fragen, die Wikipedia nicht abdeckt (Sportergebnisse, aktuelle Ereignisse usw.).

**Netzwerk:** Internet.

---

### GitHub (Update-Mechanismus)

**Was wird gesendet:**
- `git fetch` zum Herunterladen neuer Commits
- Keine Nutzerdaten, keine Gesprächsinhalte

**Was passiert:** Erika prüft, ob neue Commits auf `main` verfügbar sind und lädt diese herunter. Der Rebuild geschieht lokal.

**Netzwerk:** Internet, aber ausschließlich lesend (kein Push, keine Authentifizierung für den öffentlichen Repo-Zugriff nötig).

---

### RSS-Feeds (Nachrichten)

**Was wird gesendet:**
- HTTP-GET-Anfrage an die konfigurierten Feed-URLs (z.B. `https://www.tagesschau.de/xml/rss2/`)

**Was NICHT gesendet wird:**
- Nutzerinteraktionen
- Welche Artikel gelesen wurden

**Netzwerk:** Internet, nur wenn Feeds konfiguriert sind.

---

### Erika Sync Server (`erika.wdk-it.de:9000`)

Der Erika Sync Server ist ein externer Server, der vom Erika-Entwickler betrieben wird. Er ermöglicht die Synchronisation zwischen dem Erika-System und der Android Companion App sowie das optionale Cloud-Backup.

**Was wird im normalen Sync gespeichert:**
- **Sync-Daten**: Einkaufsliste, Kalender-Snapshots, Erinnerungen, Hausaufgaben-Erledigungen, Personennamen, Notizen, Abfallkalender — alle Kategorien, die über das Admin-Panel zur Synchronisation freigegeben sind
- **FCM-Token**: Gerätespezifischer Identifikator für Push-Benachrichtigungen (gerätebezogener Identifikator, wird serverseitig dem Tenant zugeordnet)

**Was im normalen Sync NICHT gespeichert wird:**
- Gesprächsinhalte oder Memories (nur strukturierte Sync-Kategorien)
- Rohe Audioaufnahmen
- Zugangsschlüssel oder API-Keys

> **Hinweis Cloud-Backup:** Wenn der Nutzer das optionale Cloud-Backup manuell erstellt, enthält das verschlüsselte Backup auf dem Sync Server auch die vollständige Datenbank — inklusive Gesprächshistorie, Memories und aller Konfigurationsschlüssel. Siehe eigenen Abschnitt unten.

**Mandanten-Trennung:** Alle gespeicherten Daten sind durch eine `tenant_id` (= Sync-Token-Fingerabdruck) getrennt. Eine Vermischung zwischen Tenants ist technisch nicht vorgesehen.

**Serverstandort:** Deutschland (Hetzner Online GmbH). Administrativen Zugriff hat ausschließlich der Erika-Entwickler.

**Server-Logs:** Aus technischen Gründen können Server-Logs IP-Adressen, Zeitpunkte und aufgerufene Endpunkte enthalten. Gesprächsinhalte oder Benachrichtigungsinhalte werden nicht in Server-Logs geschrieben.

**Wann aktiv:** Nur wenn eine Erika Companion Android-App mit diesem System verbunden ist.

**Netzwerk:** Internet. Server: `erika.wdk-it.de`, Port 9000, betrieben vom Erika-Entwickler.

---

### Firebase Cloud Messaging (FCM, Google)

FCM wird genutzt, um Push-Benachrichtigungen direkt auf das Smartphone zu senden — z.B. bei fälligen Erinnerungen oder der Müllabfuhr-Vorab-Benachrichtigung.

**Was wird an Google übermittelt:**
- **FCM-Device-Token**: Ein gerätespezifischer Identifikator, der von der Android-App generiert wird; enthält nach unserem Kenntnisstand keine direkt lesbaren personenbezogenen Daten, ist aber einem Gerät zuordenbar und wird serverseitig einem Tenant zugeordnet
- **Benachrichtigungsinhalt**: Titel und Text der Benachrichtigung (z.B. "Erinnerung fällig: Zahnarzt um 15:00" oder "Morgen: Gelbe Tonne"), Kanal-ID

**Technisch:** Der Erika-Server (robot-core) nutzt das Firebase Admin SDK und kommuniziert dabei mit Google-/Firebase-Diensten. Die Android-App empfängt Benachrichtigungen über den auf dem Gerät installierten Firebase-Dienst.

**Firebase-Datenschutzrichtlinie:** https://firebase.google.com/support/privacy

**Wann aktiv:** Nur wenn Push-Benachrichtigungen im Admin aktiviert sind und mindestens ein Android-Gerät die Companion App mit aktivierten Benachrichtigungen verwendet.

**Netzwerk:** Internet. Betreiber: Google LLC.

---

### Cloud-Backup (Sync Server)

> ⚠️ **Das Cloud-Backup ist eine hochsensible Funktion.** Es enthält nicht nur Nutzerdaten, sondern auch den vollständigen Schlüsselbund des Systems — HA-Token, LLM-API-Key, Sync-Token und alle weiteren konfigurierten Zugangsdaten. Nur verwenden, wenn dem Sync-Server-Betreiber vertraut wird und das Sync-Token sicher verwahrt wird.

Das Cloud-Backup speichert eine vollständig verschlüsselte Kopie des Erika-Systems auf dem Erika Sync Server, um bei einem Gerätedefekt die Wiederherstellung zu ermöglichen.

**Was wird gesichert:**
- `robot_core.db` — vollständige SQLite-Datenbank (Gesprächshistorie, Profile, Memories, Konfiguration, alle Integrationen)
- `.env` — alle Konfigurationsschlüssel: HA-Token, LLM-API-Key, Sync-Token, TTS-Einstellungen, Firebase-Credentials

**Verschlüsselung:**
- Fernet-Verschlüsselung (AES-256-CBC + HMAC-SHA256)
- Schlüssel wird aus dem Sync-Token des Nutzers abgeleitet (SHA-256 → Base64url)
- Der Schlüssel verlässt das lokale Gerät nie — der Sync Server speichert nur den verschlüsselten Blob, nicht den Schlüssel
- Entschlüsselung ist ausschließlich mit dem eigenen Sync-Token möglich
- **Das Sync-Token wirkt damit gleichzeitig als Zugriffsschlüssel für Sync und als Grundlage für die Backup-Verschlüsselung. Es muss wie ein Passwort behandelt werden.**

**Wo gespeichert:** Erika Sync Server (`erika.wdk-it.de`), mandantengetrennt per `tenant_id`.

**Wann aktiv:** Nur wenn das Backup im Admin-Panel unter **System → Cloud-Backup** manuell ausgelöst wird. Es gibt keine automatische Sicherung.

**Netzwerk:** Internet. Betrieben vom Erika-Entwickler.

---

## Was lokal gespeichert wird

Alle folgenden Daten liegen primär auf dem Gerät (SQLite-Datenbank unter `/data/robot_core.db`). Wenn das Cloud-Backup manuell erstellt wurde, enthält das verschlüsselte Backup auf dem Sync Server diese Daten ebenfalls.

| Datenkategorie | Details |
|----------------|---------|
| **Gesprächshistorie** | Alle Nutzer- und Erika-Nachrichten mit Zeitstempel |
| **Personenprofile** | Name, Alter, Wohnort, Beruf, Vorlieben, Abneigungen, Beziehungen — nur freigegebene Fakten |
| **Memories** | Freigegebene und ausstehende Erinnerungen aus Gesprächen |
| **Tages- / Wochensummaries** | Automatisch erzeugte Zusammenfassungen (lokal) |
| **Persönlichkeitswerte** | Freundlichkeit, Humor, Direktheit usw. |
| **Stimmung & Beziehungsstatus** | Pro Person, nur intern |
| **Fahrzeugdaten** | Ladekurven, Standortverläufe (aus HA-Sensoren) |
| **Audit-Log** | System-Events und Fehler |
| **Config** | Admin-Panel-Einstellungen, HA-Token, LLM-API-Key, alle Integrationsschlüssel |

---

## Speicherdauer & Löschung

| Datenart | Speicherdauer | Wie löschen |
|----------|--------------|-------------|
| **Lokale Datenbank** | Unbegrenzt, solange Erika läuft | `docker compose down -v` entfernt alle Daten |
| **Sync-Daten (Sync Server)** | Bis Sync deaktiviert oder Gerät entkoppelt wird | Admin-Panel → Sync → Gerät entfernen |
| **FCM-Token** | Bis Gerät aus dem Admin-Panel entfernt wird | Admin-Panel → Geräte → Gerät löschen |
| **Cloud-Backup** | Bis manuell gelöscht oder durch neues Backup überschrieben | Admin-Panel → System → Cloud-Backup → Backup löschen |
| **Server-Logs** | Abhängig vom Hosting-Provider; typisch 7–30 Tage | Kein direkter Zugriff für Nutzer |

---

## Externe Dienste deaktivieren

Alle externen Funktionen sind optional und einzeln abschaltbar:

- **Push-Benachrichtigungen (FCM)**: Admin-Panel → Abfall → Push-Benachrichtigungen deaktivieren
- **Sync & Companion App**: Admin-Panel → Sync → Synchronisation deaktivieren
- **Cloud-Backup**: Wird nur auf explizite Aktion hin erstellt; kein automatischer Prozess
- **Wetter-APIs**: Admin-Panel → Wetter → Provider auf "deaktiviert" setzen
- **Edge TTS**: Admin-Panel → Stimme → Provider auf "Sherpa ONNX (lokal)" wechseln
- **Websuche**: Admin-Panel → Suche → deaktivieren

---

## Vollständig offline betreiben

Erika kann ohne Internetverbindung betrieben werden, wenn:

- LLM: LM Studio oder Ollama lokal (`LLM_API_URL=http://localhost:1234/…`)
- TTS: Sherpa ONNX (`ROBOT_TTS_PROVIDER=sherpa_onnx`)
- Wetter: Open-Meteo über lokalen Proxy oder deaktiviert
- Nachrichten: Keine RSS-Feeds konfiguriert
- Companion App / Sync: Nicht eingerichtet
- Updates: Manuell per `git pull` + `docker compose up --build`

In dieser Konfiguration verlässt kein Datenbyte das Heimnetz (außer dem HA-Traffic, der ebenfalls lokal bleibt).
