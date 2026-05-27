# Erika Robot Core — Roadmap

> Stand: Mai 2026 · Aktuelle Version: v0.2-alpha  
> Format: abgeschlossene Phasen oben, geplante unten. Innerhalb jeder Phase sind Items nach Priorität geordnet.

---

## ✅ Phase 0 — Fundament (abgeschlossen)

Ziel: Lauffähige Basis, die auf dem Raspberry Pi / einer VM stabil läuft.

- FastAPI Backend, SQLite Datenbank, Docker-Deployment
- Mock-LLM-Fallback (kein externer Dienst nötig)
- Persönlichkeitssystem (Freundlichkeit, Humor, Direktheit, …)
- Memory-System: Vorschläge, Freigabe-Queue, Profil-Materialisierung
- Personenprofile: Fakten, Vorlieben, Abneigungen, Beziehungsstatus
- Admin-Panel (local-admin) und Display-Panel
- Home Assistant Integration: Lichtsteuerung, Entitäten, Zustände
- LLM-Router (OpenAI-kompatibel, Mock-Fallback)
- Erstes Install-Script (`install.sh`)

---

## ✅ Phase 1 — Sprache & Interaktion (abgeschlossen)

Ziel: Erika hört zu, antwortet und handelt per Stimme.

- Wake Word "Erika" (kontinuierliche Erkennung)
- Gesichtserkennung & automatische Begrüßung
- Kontextuelle Begrüßung (Tonlage nach Beziehungsstatus, Abwesenheitskontext)
- TTS: Edge TTS (Microsoft) + Sherpa ONNX (lokal, offline)
- Follow-Up Listening nach Erikas Antworten
- Proaktive Ansprache nach Stille (konfigurierbares Zeitfenster)
- Timer per Sprache (Labels, mehrere gleichzeitig, Umbenennen, Restzeit-Abfrage)
- Erinnerungen per Sprache (relativ + absolute Uhrzeit)
- Zeitgesteuerte Lichtbefehle per Sprache
- Kalendereinträge per Sprache (LLM-gestützte Extraktion)
- Websuche (Wikipedia-Provider)
- Interesse-Tracking aus Gesprächen

---

## ✅ Phase 2 — Smart Home & Integrationen (abgeschlossen)

Ziel: Erika kennt und steuert die Wohnung.

- Fahrzeugabfragen (Akku, Reichweite, Ladestatus)
- Staubsauger- und Mähroboter-Steuerung per Sprache
- Licht-Szenen (speichern, abrufen, löschen)
- Proaktive HA-Benachrichtigungen (regelbasiert)
- PV-Anlage, Drucker, Kraftstoffpreise, Fußball-Ergebnisse
- Wetter (Open-Meteo, Yr.no, OpenWeatherMap — wählbar)
- Eigene RSS-Quellen im Admin (mit Favicon-Erkennung)
- Zeitpläne-Tab im Admin (Erinnerungen + Lichtbefehle einsehen/löschen)
- Personenspezifische Notizen mit Overlay
- Gesprächs-Zusammenfassung & tägliches Fazit
- TZ-Fix: Zeitgesteuerte Befehle laufen jetzt in Europe/Berlin

---

## 🔧 Phase 3 — Stabilisierung & Reife (aktuell / kurzfristig)

Ziel: Das, was existiert, wird zuverlässiger, testbarer und wartbarer.

### Pflicht
- [x] **Versionierung korrigieren**: v0.3.0 in FastAPI-App gesetzt
- [x] **Testdateien aufräumen**: Veraltete `test_*.py` und alte Quell-Kopien aus dem Repo-Root entfernt
- [x] **`.env.example`** mit allen Variablen und Standardwerten angelegt
- [x] **CI/CD (minimal)**: `.github/workflows/ci.yml` — bei Push automatisch Build + Tests via Docker
- [x] **Fehlerseite im Display**: Offline-Banner wenn Backend nicht erreichbar

### Sinnvoll
- [x] **Audit-Log im Admin** um Fehler-Einträge erweitern: `system.error`-Einträge aus Hintergrund-Loops, rot hervorgehoben im Protokoll-Tab
- [x] **Gesichtserkennung Fallback**: Bei Kamera-Fehler wird Status ans Backend gemeldet und nach 60s automatisch neu versucht
- [x] **TTS-Watchdog-Metriken**: Zähler wird bei jedem 30s-Timeout ans Backend gesendet; Anzeige im Admin unter Erika → TTS
- [x] **INSTALL_MANUAL.md** fertiggestellt — vollständige Schritt-für-Schritt-Anleitung

---

## ✅ Phase 4.1 + 4.2 — Sitzungsübergreifendes Gedächtnis (abgeschlossen)

Ziel: Erika vergisst nach einem Neustart nicht mehr was zuvor besprochen wurde.

- [x] **Gesprächskontext über Sessions**: Conversation-Tabelle wird beim Start geladen (last 40 Nachrichten, bereits vorhanden)
- [x] **Langzeit-Gedächtnis**: Tagesrückblicke (30 Tage), Wochensummaries (6 Monate), aktive Themen (60 Tage Inaktivität) fließen in den Prompt ein
- [x] **MemoryService**: `ensure_todays_daily_summary`, `refresh_active_topics`, `compress_dailies_to_weekly`, `prune_old_summaries`
- [x] **Stündlicher Maintenance-Loop**: Aktualisiert alle Zusammenfassungen für alle Personen automatisch im Hintergrund

---

## 🗓️ Phase 4 — Persönlichkeit & Gedächtnis (mittelfristig)

Ziel: Erika wird über Zeit klüger und persönlicher.

- [ ] **Stimmungsmodell**: Erika erkennt aus Sprachmuster oder Uhrzeitkontext, ob jemand gestresst/müde ist und passt Ton an
- [ ] **Beziehungsentwicklung**: Beziehungsstatus entwickelt sich automatisch (nicht nur manuell im Admin)
- [ ] **Mehrsprachigkeit**: Erste Schritte Richtung Englisch als zweite Sprache (Spracherkennung + TTS)
- [ ] **Personenbezogene Briefing-Konfiguration**: Jede Person hat ihr eigenes Briefing-Profil (Reihenfolge, Module)

---

## 🛠️ Phase 5 — Hardware-Abstraktion (mittelfristig)

Ziel: Die Fake-Adapter aus Phase 0 werden durch echte Hardware ersetzt — ohne den Core zu ändern.

- [ ] **Echter Kamera-Adapter**: `fake_camera.py` durch echten Adapter ersetzen (USB-Kamera / Pi Camera)
- [ ] **Echtes Mikrofon**: Adapter für Mikrofon-Arrays (z.B. ReSpeaker) — Wake Word robuster machen
- [ ] **Akku-Management**: Echter Batterie-Adapter für physischen Roboter-Akku
- [ ] **Hardware-Abstractions-Layer dokumentieren**: Klare Anleitung wie Dritte eigene Adapter schreiben können
- [ ] **Display auf dedizierter Hardware**: Kiosk-Modus auf Touchscreen (z.B. offizielles Pi-Display) getestet und dokumentiert

---

## 🔐 Phase 6 — Offline-Fähigkeit & Datenschutz (mittelfristig)

Ziel: Erika funktioniert vollständig ohne Cloud.

- [ ] **Lokales LLM als Standardempfehlung**: Setup-Guide für LM Studio / Ollama als primären LLM-Pfad
- [ ] **Lokale Spracherkennung**: Whisper.cpp oder Vosk als Alternative zu cloud-basierten Diensten
- [ ] **Edge TTS Fallback auf Sherpa**: Wenn Internet fehlt, automatisch auf lokalen TTS wechseln
- [ ] **Datenschutz-Dokumentation**: Klare Übersicht welche Daten wohin gehen (HA, LLM, TTS, Wetter-APIs)
- [ ] **Optional: vollständig air-gapped Setup** (alle Dienste lokal, kein externer Traffic)

---

## 🔭 Phase 7 — Erweiterbarkeit (langfristig)

Ziel: Andere können Erika erweitern und anpassen.

- [ ] **Plugin-System**: Eigene Skill-Module (ähnlich wie HA-Integrationen) ohne Core zu ändern
- [ ] **Webhook-API**: Externe Systeme können Events an Erika schicken ("Paket angekommen")
- [ ] **Mehrere Roboter / Standorte**: Erika-Instanzen pro Raum oder Wohnung koordinieren
- [ ] **Mobile Companion App** (Minimal): Push-Benachrichtigungen an Handy wenn Erinnerung fällig
- [ ] **Community-Dokumentation**: Wie baut man einen eigenen Adapter? Wie schreibt man einen Skill?

---

## 💡 Ideen-Backlog (nicht priorisiert)

Dinge, die interessant sein könnten — kein Commitment.

- Sprachtonanalyse (Stimmung aus Akustik, nicht nur Text)
- Einkaufslisten-Sync mit Bring! oder ähnlichem
- Kalender-Integration über CalDAV (nicht nur HA)
- Schlaferkennung: Erika wird still, wenn sie erkennt dass jemand schläft
- Haushaltsaufgaben-Tracking ("Wann habe ich zuletzt gestaubsaugt?")
- Sprachgesteuerte Foto-Aufnahme + lokale Galerie

---

> Diese Roadmap ist ein lebendes Dokument. Items werden mit dem Changelog synchronisiert wenn sie abgeschlossen sind.
