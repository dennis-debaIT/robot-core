# Erika Robot Core — Roadmap

> Stand: Juni 2026 · Aktuelle Version: v0.3.0  
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

## ✅ Phase 3 — Stabilisierung & Reife (abgeschlossen)

Ziel: Das, was existiert, wird zuverlässiger, testbarer und wartbarer.

- [x] **Versionierung korrigieren**: v0.3.0 in FastAPI-App gesetzt
- [x] **Testdateien aufräumen**: Veraltete `test_*.py` und alte Quell-Kopien aus dem Repo-Root entfernt
- [x] **`.env.example`** mit allen Variablen und Standardwerten angelegt
- [x] **CI/CD (minimal)**: `.github/workflows/ci.yml` — bei Push automatisch Build + Tests via Docker
- [x] **Fehlerseite im Display**: Offline-Banner wenn Backend nicht erreichbar
- [x] **Audit-Log im Admin** um Fehler-Einträge erweitern
- [x] **Gesichtserkennung Fallback**: Bei Kamera-Fehler Retry nach 60s
- [x] **TTS-Watchdog-Metriken**: Zähler im Admin sichtbar
- [x] **INSTALL_MANUAL.md** fertiggestellt

---

## ✅ Phase 4.1 + 4.2 — Sitzungsübergreifendes Gedächtnis (abgeschlossen)

Ziel: Erika vergisst nach einem Neustart nicht mehr was zuvor besprochen wurde.

- [x] **Gesprächskontext über Sessions**: Conversation-Tabelle wird beim Start geladen (last 40 Nachrichten, bereits vorhanden)
- [x] **Langzeit-Gedächtnis**: Tagesrückblicke (30 Tage), Wochensummaries (6 Monate), aktive Themen (60 Tage Inaktivität) fließen in den Prompt ein
- [x] **MemoryService**: `ensure_todays_daily_summary`, `refresh_active_topics`, `compress_dailies_to_weekly`, `prune_old_summaries`
- [x] **Stündlicher Maintenance-Loop**: Aktualisiert alle Zusammenfassungen für alle Personen automatisch im Hintergrund

---

## ✅ Phase 4 — Persönlichkeit & Gedächtnis (abgeschlossen)

Ziel: Erika wird über Zeit klüger und persönlicher.

- [x] **Stimmungsmodell**: Erika erkennt Gesprächssentiment und entwickelt eine eigene Stimmung; passt Ton und Wortwahl konkret an
- [x] **Beziehungsentwicklung**: Entwickelt sich automatisch aus Gesprächen; Wärme/Anspannung/Offenheit beeinflussen Wortwahl; im Admin manuell kontrollierbar
- [x] **Personenbezogene Briefing-Konfiguration**: Jede Person hat ihr eigenes Briefing-Profil (Reihenfolge, Module)
- [x] **LLM-generierte Begrüßung**: Natürliche, kontextuelle Begrüßung mit Tageszeit, Kalender, PV und Gesprächsthemen; im Admin konfigurierbar

---

## ✅ Phase 4.3 — Integration & Display-Qualität (abgeschlossen)

Ziel: Bestehende Integrationen werden präziser, konfigurierbarer und zuverlässiger.

- [x] **PV-Widget individuell konfigurierbar**: Felder per Checkbox im Admin aktivier-/deaktivierbar
- [x] **PV Netz & Hausverbrauch**: Netz-Sensor + Batterie-Leistungs-Sensor; Hausverbrauchsberechnung
- [x] **PV-Statistiken Einspeisung/Netzbezug**: Separate Balkendiagramme im Statistik-Overlay
- [x] **PV-Echtzeit**: Widget-Aktualisierung alle 5 Sekunden
- [x] **Standort via Koordinaten**: `zone.home` aus HA, kein mehrdeutiges Geocoding
- [x] **TTS + Face-Recognition Race Condition behoben**: Kein ungewolltes Zuhören während Erika spricht
- [x] **Admin-UX Übersicht**: Setup-Checkliste im Übersicht-Tab (HA / LLM / TTS Status mit Direkt-Link)
- [x] **PV-Langzeitstatistik aus Leistungssensor**: Zuverlässige kWh-Ableitung wenn kein Tageszähler konfiguriert
- [x] **Akku-Verlauf des Fahrzeugs mit Jahresübersicht**: Gepflegtes Tages-Aggregat (Min/Max/geladene % pro Tag) baut sich bei jedem Poll selbst auf; "7 Tage"/"Monat"/"Jahr" lesen daraus, lokale DB ist primäre Quelle vor HA-History

---

## ✅ Phase 4.4 — Anpassbares Display (abgeschlossen)

Ziel: Nutzer können das Display optisch und strukturell an ihre Wünsche anpassen.

- [x] **Theme-System**: 12 CSS-Custom-Properties, in der DB gespeichert, beim Start geladen
- [x] **Design-Tab im Admin**: Farbwähler für alle Theme-Farben
- [x] **6 Theme-Presets**: Cyan, Grün, Amber, Violett, Rot, Hell (Light Theme)
- [x] **Widget-Slot-System**: Linkes/rechtes Panel aus frei wählbaren Widgets mit Größengewicht
- [x] **6 Panel-Widgets**: Wetter, Kalender, Kameras, Kraftstoff, PV, Fahrzeug — frei verteilbar, keine Duplikate
- [x] **Slot-Editor**: Größe (+/−) und Reihenfolge (↑↓) pro Widget
- [x] **PV-Energiefluss-Diagramm**: Animierter Fluss mit Glow-Nodes, korrekte Richtungslogik
- [x] **Theme-Konsistenz**: Alle Overlays/Charts nutzen CSS-Variablen (Light Theme vollständig nutzbar)
- [x] **Hausaufgaben-Modul (Plus/Family)**: Admin-verwaltete Aufgabenliste, Erledigungen pro Person über die bestehenden Personenprofile, Statistik je Aufgabe (Woche/Monat/Jahr, „Wochensieger") sowie optionaler Gesamt-Wochensieger über alle Aufgaben. Sprachsteuerung (z. B. "Ich habe gerade gestaubsaugt") ist bewusst noch offen — siehe Ideen-Backlog.

---

## ✅ Phase 4.5 — Liga Plus & News-Reader (abgeschlossen)

Ziel: Liga-Modul mit bezahlten Premiumfunktionen, News-Artikel direkt lesbar im Display.

- [x] **Liga-Modul Plus-Split**: `liga_plus`-Feature-Flag trennt kostenlose Inhalte (Kader-Übersicht, Spielplan) von Plus-Inhalten (Marktwerte, Spielerprofile, letzte 5 Spiele, Mini-Tabelle, TM-Vereinsinfos)
- [x] **Edition-Preview (server-seitig)**: Test-Override für Editionen ohne Lizenz zu entfernen; Cross-Device via DB statt localStorage
- [x] **Liga Live-Spielminute**: Berechnung aus Anstoßzeit; Halbzeit exakt via `status: PAUSED`
- [x] **Liga Event-Ticker**: Live-Tore mit Minute und Nachspielzeit (z. B. `45+2'`), Eigentor/Elfmeter-Kennzeichnung
- [x] **News Reader-Modus**: trafilatura extrahiert Artikeltext serverseitig; Anzeige im Display-Theme ohne Werbung/Cookie-Banner
- [x] **News RSS-Fallback**: `description` und `content:encoded` aus dem Feed werden sofort angezeigt während der Volltext lädt
- [x] **News Iframe-Fallback**: Button „Im Browser öffnen" als letzter Ausweg wenn trafilatura und RSS-Inhalt nicht ausreichen (DSGVO-Consent-Walls)

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

- Mehrsprachigkeit: Englisch als zweite Sprache (Spracherkennung + TTS + LLM-Steuerung)
- Sprachtonanalyse (Stimmung aus Akustik, nicht nur Text)
- Einkaufslisten-Sync mit Bring! oder ähnlichem
- Kalender-Integration über CalDAV (nicht nur HA)
- Schlaferkennung: Erika wird still, wenn sie erkennt dass jemand schläft
- Sprachsteuerung für Hausaufgaben (z. B. "Ich habe gerade gestaubsaugt" loggt eine Erledigung per Sprache, "Wer ist mit Spülmaschine dran?")
- Sprachgesteuerte Foto-Aufnahme + lokale Galerie

---

> Diese Roadmap ist ein lebendes Dokument. Items werden mit dem Changelog synchronisiert wenn sie abgeschlossen sind.
