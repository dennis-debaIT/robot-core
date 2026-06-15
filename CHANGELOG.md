# Changelog — Erika Robot Core

Alle nennenswerten Änderungen am Projekt werden hier dokumentiert.  
Format: neueste Einträge oben.

---

## [Unreleased]

### Neu
- **Akku-Verlauf des Fahrzeugs: gepflegte Statistik mit Jahresübersicht**: Neben „7 Tage" und „Monat" gibt es jetzt einen dritten Tab „Jahr" im Ladeverlauf des Fahrzeugs, der den Akku-Verlauf (Min/Max je Monat) über das laufende Jahr zeigt. Dafür wird bei jedem Poll ein kleines Tages-Aggregat (`vehicle_charging_daily`, min/max/geladene % pro Tag, ohne Lösch-Frist) fortgeschrieben und einmalig aus der vorhandenen 35-Tage-Rohhistorie befüllt — die Jahresübersicht baut sich dadurch von Monat zu Monat von selbst auf. „7 Tage"/„Monat" lesen jetzt ebenfalls aus diesem Aggregat (statt die Rohdaten bei jeder Anfrage neu zu gruppieren), mit unverändertem HA-History-Fallback für Tage ohne lokales Aggregat.

### Behoben
- **Ladeverlauf des Fahrzeugs zeigte Lücken in „Monat"**: `charging_history()` nutzte HA-History als primäre Quelle und fiel nur bei komplett leerem Ergebnis auf die lokale DB zurück. Da Home Assistant rohe History standardmäßig nur ~10 Tage aufbewahrt, fehlten ältere Tage der Monatsansicht. Die lokale DB (35 Tage, dichter erfasst) ist jetzt primär; HA-History dient nur noch als Fallback für Tage, die lokal noch nicht erfasst sind.
- **Strom-Migration jetzt wirklich einmalig**: Die automatische Übernahme von `pv.sensors.grid`/`pv.tariffs` in den neuen `energy`-Bereich wurde bisher bei jedem Config-Aufruf neu berechnet statt einmalig gespeichert — spätere Änderungen an den PV-Einstellungen hätten die migrierten Strom-Werte sonst weiter überschrieben, solange im Strom-Tab nie gespeichert wurde. Wird jetzt sofort persistiert.

### Tests
- Neue Tests für den Akku-Verlauf des Fahrzeugs (`test_vehicle_charging_history.py`): Backfill und inkrementelle Fortschreibung des Tages-Aggregats, „7 Tage"/„Monat" aus dem Aggregat inkl. HA-Fallback für fehlende Tage, sowie die neue Jahresübersicht (Monatsaggregation, leeres Jahr).
- Neue Tests für den Strom-Bereich: Sanitizing von Sensor-Liste und Tarifen, die einmalige PV→Strom-Migration (inkl. Persistenz) sowie `/ha/energy/history` (Saldo/Kosten-Berechnung, Netzbezugs- vs. Gerätesensoren).
- Neue Tests für die PV-Langzeitstatistik (`/ha/pv/history`): kWh-Ableitung aus dem Leistungssensor via History (inkl. Lücken-/Negativwert-Behandlung) und Langzeitstatistik, Stats→History-Fallback und -Merge für den heutigen Tag, sowie die Endpoint-Views today/7days/year mit und ohne Tagesertrags-Sensor.
- `test_openai_compatible_request_body` setzt `LLM_MAX_TOKENS` jetzt explizit und ist damit unabhängig von der Docker-Compose-Umgebung lauffähig (vorher schlug der Test bei direktem `pytest`-Lauf fehl, weil der erwartete Wert 320 nur per Compose-Env-Var injiziert wurde).

### Geändert
- **`max_tokens`-Default vereinheitlicht (220 → 320)**: Der Code-Fallback in `llm_client.py`, `core/settings.py` und den `/llm/config`-Defaults entsprach nicht dem in `.env.example`/`docker-compose.yml` dokumentierten Standard von 320. Jetzt überall 320, damit Anzeige und effektiver Wert auch ohne gesetzte Env-Variablen übereinstimmen.
- **`topic_interest_threshold`/`-window_days`-Defaults in `CoreSettings` korrigiert**: Die Field-Defaults (8/30, `le=20`) waren praktisch nie wirksam (immer durch `load_env_defaults()` überschrieben: 3/14) und widersprachen den tatsächlichen Grenzen aus `schemas.py`/Admin-UI (`le=10`). Jetzt 3/14 mit `le=10`, passend zu den real genutzten Werten.

### Sonstiges
- **`CameraStreamService._HLS_DIR.mkdir`** nutzt jetzt `parents=True`, damit das Modul auch importierbar ist, wenn `/tmp` selbst noch nicht existiert (z. B. lokale Entwicklung auf Windows).

---

## 2026-06-14

### Neu
- **Strom-Bereich: Verbrauch je Sensor (frei) + Kostenauswertung für Gerätesensoren (Plus)**: Im Admin gibt es einen neuen Bereich „Strom" mit einer frei konfigurierbaren Liste von Verbrauchssensoren (z. B. Waschmaschine, Trockner) mit eigenem Anzeigenamen, sowie optional einem „Gesamt-Netzbezug"-Sensor, und einem „Modul aktiv"-Schalter (analog PV/Kalender) zum Ein-/Ausblenden des Navigationspunkts. Im Display zeigt der neue Navigationspunkt „⚡ Strom" für Heute/7 Tage/Monat/Jahr den Verbrauch (kWh) aller konfigurierten Sensoren, inkl. Einspeisung/Netzbezug des Gesamt-Netzbezugssensors — das bleibt für alle Editionen kostenlos. Die Kostenauswertung (€) der selbst angelegten Gerätesensoren ist Teil von Erika Plus; ohne Plus-Lizenz erscheint dort ein Hinweis auf das Upgrade. Saldo & anteiliger Grundpreis des Gesamt-Netzbezugssensors erscheinen weiterhin (wie bisher) in der PV-Statistik. Bestehende PV-Stromtarife und der bisherige PV-Netzbezugssensor wurden automatisch in die neue Strom-Konfiguration übernommen (inkl. „Modul aktiv" = an).

### Geändert
- **PV-Statistik: Netzbezug/Saldo jetzt aus dem neuen Strom-Bereich**: Die Einspeisung-/Netzbezug-/Saldo-Anzeige in der PV-Statistik (Erika Plus) zeigt weiterhin den Gesamt-Netzbezugssensor mit Saldo & Grundpreis — die Daten kommen jetzt aus `/ha/energy/history` statt dem entfernten `/ha/pv/grid-history`. Die „Stromtarife"-Sektion im PV-Admin wurde entfernt und lebt als „Strom"-Tab weiter (siehe oben). Im „⚡ Strom"-Overlay zeigt der Gesamt-Netzbezugssensor dagegen nur noch Einspeisung/Netzbezug in kWh (alle Editionen, ohne Saldo/Kosten) — die Kostenanzeige dort ist den selbst angelegten Gerätesensoren (Waschmaschine etc., Erika Plus) vorbehalten.
- **Kamera-Ereignisliste & Fahrzeug-Verlauf jetzt korrekt Erika Plus**: Beide Features waren in der Feature-Registry bereits als „Plus" hinterlegt, im Display aber ungated und damit für alle Editionen frei nutzbar. Die Ereignis-/Türklingel-Historie im Kamera-Bereich sowie der Standort-/Ladeverlauf der letzten 14 Tage bei Fahrzeugen zeigen ohne Plus-Lizenz jetzt eine Upgrade-Box; Live-Kamerabild, Schnappschuss und der aktuelle Fahrzeug-Status bleiben wie gewohnt kostenlos.

---

## 2026-06-13

### Neu
- **PV-Energiekosten (Plus): Grundpreis & weitere Gebühren**: Im Admin (PV → Stromtarife) können zusätzlich zu Einspeisevergütung und Strombezugstarif jetzt ein jährlicher Grundpreis und weitere feste Jahresgebühren hinterlegt werden (jeweils brutto inkl. 19% USt). Beide Beträge werden tagesgenau (inkl. Schaltjahr-Berücksichtigung) auf den jeweiligen Statistik-Zeitraum (Heute/7 Tage/Monat/Jahr) umgelegt und im Saldo der PV-Statistik als „Grundpreis & Gebühren" ausgewiesen.

---

## 2026-06-12

### Neu
- **PV-Energiekosten (Plus)**: Im Admin (PV → Stromtarife) können Einspeisevergütung und Strombezugstarif (ct/kWh) hinterlegt werden. In der PV-Statistik (Heute/7 Tage/Monat/Jahr) werden daraus Einspeiseerlös, Netzbezugskosten und Saldo berechnet und unter den Einspeisung-/Netzbezug-Werten angezeigt — nicht im Widget. Erfordert konfigurierten Netz-Sensor; ohne hinterlegte Tarife bleibt die Anzeige unverändert.
- **Zeitabhängiges Design (Plus)**: Im Admin (Design → Zeitabhängiges Design) kann ein automatischer Tag/Nacht-Theme-Wechsel aktiviert werden — eigenes, gedämpftes Nacht-Theme (per Presets oder Farbwähler) plus konfigurierbare Uhrzeiten für Tag-/Nachtbeginn. Manuelle Theme-Wahl unter Design → Farben bleibt Community und unverändert; das Display übernimmt einen Wechsel innerhalb von ~10 Sekunden über den neuen Endpunkt `GET /display/theme/effective`. Ohne Plus-Lizenz bleibt unabhängig vom gespeicherten Zeitplan immer das manuelle Theme aktiv.

### Verbessert
- **PV-Statistik Ladezeit (7 Tage/Monat/Jahr)**: Einspeisung/Netzbezug und Tagesertrag (Fallback ohne Tagesertrags-Sensor) werden für Zeiträume über ~1,5 Tage jetzt aus der HA-Langzeitstatistik (1 WebSocket-Aufruf `recorder/statistics_during_period`) statt einer Anfrage pro Tag berechnet — deutlich kürzere Ladezeiten bei Monats- und Jahresansicht. Der heutige Tag wird für den Leistungssensor-Fallback weiterhin per History nachgeladen.

### Behoben
- **PV-Statistik Monats-/Jahresansicht begann am 2. statt am 1. / Jahresansicht unvollständig oder mit Dopplern**: Zwei Ursachen behoben. (1) Der Zeitraumstart wurde aus der bereits nach UTC konvertierten Mitternacht abgeleitet (`.replace(day=1)`), was bei Zeitzonen-Offset auf den 2. lokalen Tag verschob — Start wird jetzt korrekt aus der lokalen Zeit berechnet. (2) Die Langzeitstatistik-Abfrage nutzte einen nicht existierenden REST-Endpunkt (`/api/statistics_during_period`, 404) und fiel dadurch immer auf die rohe History zurück, die Home Assistant standardmäßig nur ~10 Tage aufbewahrt — ältere Monats-/Jahresdaten fehlten oder waren durch einen Mitternachts-Rundungsfehler in der History-Auswertung verdoppelt. Statistiken werden jetzt über die HA-WebSocket-API (`recorder/statistics_during_period`) abgerufen, die dauerhaft gespeicherte Tages-/Stundenwerte liefert. Hinweis: Die Jahresansicht zeigt weiterhin nur Monate, für die Home Assistant selbst Langzeitstatistiken gespeichert hat.
- **Abfall-Widget (Plus) zeigte nach einem Backend-Neustart/Update vorübergehend „Kein Abfalltermin"**: Fragt `/ha/waste` ausgerechnet während des Neustarts ab (z. B. unmittelbares Laden beim Seitenaufruf oder der 15-Minuten-Kalender-Refresh), liefert die Anfrage eine leere Liste, die bis zum nächsten Kalender-Refresh (bis zu 15 Minuten) unverändert angezeigt blieb. Das Abfall-Widget aktualisiert sich jetzt zusätzlich alle 60 Sekunden im Hintergrund und überschreibt die Anzeige nur bei einem gültigen (nicht-leeren) Ergebnis — ein leerer Zwischenzustand korrigiert sich dadurch innerhalb einer Minute selbst, ohne die zuvor angezeigten Termine zwischenzeitlich zu löschen.

### Sicherheit
- **CORS eingeschränkt**: Die API erlaubte bisher Cross-Origin-Zugriffe von jeder Webseite (`allow_origins="*"` + `allow_credentials=True`). Da Admin-Panel und Display-Panel same-origin von dieser API ausgeliefert werden, ist Cross-Origin-Zugriff im Normalfall nicht nötig — er ist jetzt standardmäßig deaktiviert. Über `ROBOT_CORS_ORIGINS` (kommagetrennte Liste) kann er für lokale Entwicklung gezielt wieder freigegeben werden. Verhindert, dass eine im selben Netzwerk geöffnete fremde Webseite per Browser-JS Antworten dieser API (z. B. `/llm/config`, `/audit-log`) auslesen kann.
- **Backup-Restore ohne Zip-Extract**: `/system/backup/restore` hat das hochgeladene ZIP bisher vollständig in ein temporäres Verzeichnis entpackt, bevor nur `robot_core.db` übernommen wurde. Jetzt wird ausschließlich dieser eine Eintrag direkt gelesen und geschrieben — verhindert Zip-Slip-Pfadtraversal über manipulierte Dateinamen in anderen Zip-Einträgen.
- **SSH-Key nicht mehr im Laufzeit-Container**: Der Update-Check (`/system/update/check`) hat bisher `~/.ssh` des Hosts read-only in den `robot-core`-Container gemountet, um per SSH von GitHub zu fetchen. Da das Repo öffentlich ist, läuft der Fetch jetzt über HTTPS — der SSH-Mount entfällt vollständig. Reduziert die Angriffsfläche: ein RCE im laufenden App-Container hätte keinen Zugriff mehr auf den privaten SSH-Key des Hosts. Der eigentliche Update-Rebuild (`update.sh`, auf dem Host) ist davon unberührt.
- **Aufgeräumt**: Verwaiste Altdateien `backend/llm_client.py` / `backend/test_llm_client.py` entfernt (Vorgänger von `backend/app/brain/llm_client.py`, nirgends mehr referenziert). README/ANLEITUNG korrigiert: `/` ist die lokale Konsole, nicht das Display-Panel (`/display`); Admin-Panel-URL einheitlich mit `https://` + Port dokumentiert.
- **Audit-Log für sicherheitsrelevante System-Aktionen**: Neustart, Update-Installation, Backup erstellen/herunterladen/wiederherstellen, Änderungen an der LLM-Konfiguration sowie Lizenz-Aktivierung/-Installation/-Entfernung werden jetzt im Audit-Log (`/audit-log`) protokolliert — sichtbar im Admin-Panel, auch ohne dass diese Aktionen aktuell durch eine Anmeldung geschützt sind.

---

## 2026-06-08

### Neu
- **Theme-System**: Vollständiges CSS-Custom-Property-System für das Display. 12 konfigurierbare Farbvariablen (Hintergrund, Oberfläche, Akzent, Text, Rand usw.) — gespeichert in der DB (`display_theme`), beim Display-Start geladen. Admin-Tab "Design" mit Farbwählern. Endpunkte `GET/POST /display/theme`, `POST /display/theme/reset`.
- **6 vorgefertigte Themes**: Cyan (Standard), Grün, Amber, Violett, Rot, Hell (Light Theme). Klick auf Preset befüllt die Farbwähler — Speichern erst auf Knopfdruck.
- **Widget-Slot-System**: Panel-Layout vollständig konfigurierbar im Admin (Design → Layout). Linkes und rechtes Panel bestehen aus frei wählbaren Widgets mit Größengewicht. Kompakte Widgets (PV, Fuel, EV) nehmen natürliche Höhe und scrollen nie; flexible Widgets (Kalender, Wetter, Kameras) füllen verbleibenden Raum und scrollen intern. Endpunkte `GET/POST /display/layout`, `POST /display/layout/reset`.
- **6 Panel-Widgets**: Wetter, Kalender, Kameras, Kraftstoff, PV-Anlage, Fahrzeug/EV — frei auf linkes/rechtes Panel verteilbar, jedes Widget nur einmal verwendbar.
- **Kamera-Widget**: Neues Panel-Widget zeigt Snapshot der ersten konfigurierten Kamera (ab Größe ≥2) sowie die letzten Kamera-Ereignisse. Klick öffnet Kameraansicht.
- **PV-Energiefluss-Tab**: Neuer Tab "Fluss" (Standard beim Öffnen der PV-Statistiken). Visualisiert den Energiefluss als Diagramm mit runden Nodes (PV, Haus, Netz, Batterie), Glow-Effekten, SVG-Ikonen und animierten fließenden Strichen. Aktualisiert alle 5 Sekunden. Batterie zeigt Ladestand-Grafik und aktuell geladene/entladene Leistung.
- **Slot-Editor ↑↓**: Widgets im Admin-Layout-Editor können per Pfeil-Buttons umsortiert werden, ohne löschen und neu hinzufügen zu müssen.
- **Setup-Checkliste im Admin**: Übersicht-Tab zeigt Einrichtungs-Status für Home Assistant, KI/LLM und Sprachausgabe (TTS) mit ✅/❌/⚠️ und direktem Link zum jeweiligen Tab.
- **Groq als LLM-Option in `install.sh`**: Option [2] konfiguriert Groq Cloud direkt (kostenloser API-Key unter console.groq.com, vorausgefüllter Endpunkt + `llama-3.3-70b-versatile`).

### Verbessert
- **`install.sh` Abschluss-Meldung**: Klarer Fokus auf Admin-Panel als einzige Anlaufstelle. Verweis auf Setup-Checkliste. HA-Schritte nur wenn tatsächlich installiert.
- **PV-Statistik-Charts**: SVG-viewBox-Fix — Charts wurden vorher auf schmalen Displays rechts abgeschnitten.
- **Theme-Farben in Overlays**: Monatskalender, Drucker-Overlay, PV-Statistiken, Wetter-Übersicht, Erinnerungs-Overlay und alle SVG-Charts nutzen jetzt CSS-Variablen statt hardkodierter Hex-Werte — alle funktionieren korrekt im Light Theme.

### Behoben
- **Batterie-Fließrichtung im PV-Fluss**: War immer als "lädt" animiert — korrigiert durch korrekte Energiebilanz (`Batterie = PV − Verbrauch − Netz`). Negatives Ergebnis = Entladen → Pfeil von Batterie zu Haus.
- **PV-Fluss Netzbezug-/Einspeise-Richtung**: Beim Netzbezug floss die Animation fälschlich zu PV. Korrekt: nur Netz → Haus bei Netzbezug, nur PV → Netz bei Einspeisung.
- **Widget-Slots scrollen nicht mehr**: Kompakte Widgets (PV, Fuel, EV) zeigen immer den vollständigen Inhalt, unabhängig von der zugewiesenen Größe.
- **Wetter-Übersicht Tageskarten**: Dunkler Hintergrund durch `var(--surface2)` ersetzt — korrekte Darstellung im Light Theme.

---

## 2026-05-29

### Neu
- **LLM-generierte Begrüßung**: Begrüßungstext wird per KI erzeugt statt aus statischen Templates; deutlich natürlicher und variabler. Fallback auf Templates bei LLM-Timeout (8s)
- **Konfigurierbarer Begrüßungskontext**: Im Admin (Erika → Begrüßung) per Checkbox steuerbar: Tageszeit ("Guten Morgen"), nächster Kalendertermin, PV-Tagesertrag, aktive Gesprächsthemen
- **PV-Widget konfigurierbar**: Im Admin (PV → Widget-Anzeige) kann per Checkbox bestimmt werden welche Felder im Widget angezeigt werden (Leistung, Hausverbrauch, Netz, Tagesertrag, Batterie, Temperatur)
- **PV Netz-Einspeisung / Netzbezug**: Netz-Sensor und Batterie-Leistungs-Sensor konfigurierbar; Hausverbrauch wird daraus berechnet (`PV − Batterie − Netz`)
- **PV-Statistiken: Einspeisung & Netzbezug**: Separates `GET /ha/pv/grid-history` liefert tages-/wochen-/monats-/jahresaufgelöste Einspeisung und Netzbezug; in Statistik-Overlay als eigene Balkendiagramme sichtbar (nur wenn Netz-Sensor konfiguriert)
- **PV-Widget Aktualisierungsintervall**: Auf 5 Sekunden reduziert (vorher 60s) für nahezu-Echtzeit-Anzeige
- **Standort via Koordinaten (zone.home)**: Im Admin (System → Standort) können Koordinaten direkt gespeichert werden — kein mehrdeutiges Geocoding mehr. Button "Von HA übernehmen" liest `zone.home` aus Home Assistant automatisch aus (`GET /ha/zone-home`)
- **Kraftstoff-Widget**: Header "KRAFTSTOFFE" und Stationsname entfernt für kompaktere Darstellung

### Behoben
- **TTS + Gesichtserkennung Race Condition**: Wenn Erika noch sprach, wurde durch Gesichtserkennung das Zuhören bereits gestartet — Erikas Sprache wurde als Nutzereingabe gewertet. Guard um `_ttsPlaying` und `_ttsQueue.length` erweitert
- **PV Hausverbrauch zeigte 0 W**: Netz-Vorzeichen-Konvention bei Huawei korrigiert (positiv = Einspeisung, nicht Netzbezug); Formel `Haus = PV − Batterie − Netz` korrekt dokumentiert

---

## 2026-05-28

### Neu
- **Stimmungsmodell**: Erika hat eine eigene Stimmung (sehr gut / gut / neutral / müde / gereizt) die sich nach jedem Gespräch automatisch entwickelt. Ton und Wortwahl passen sich konkret an — z.B. "Erika ist müde" → kürzere Antworten; "sehr gut drauf" → herzlicher, lebhafter
- **Beziehungsentwicklung mit Wortwahl**: Per-Person Beziehungshinweise sind jetzt konkret formuliert (Wärme ≥ 0.55: "natürlich, sehr gerne klingen authentisch"; Anspannung ≥ 0.55: direkt zur Antwort, keine persönlichen Anmerkungen); Gesprächsanzahl-Schwelle: nach 30+ Gesprächen direkter Ton
- **Admin — Stimmung & Beziehung vollständig kontrollierbar**:
  - Neue Sektion "Aktuelle Stimmung" im Erika-Tab: farbiger Chip, Balken, manueller Slider, Reset
  - Globaler Beziehungsstatus jetzt editierbar (Slider für Wärme/Anspannung/Offenheit + Speichern)
  - Per-Person: Offenheit und Gesprächsanzahl sichtbar; alle 3 Werte manuell setzbar
- **API**: `GET/POST /mood`, `/mood/reset`, `/mood/set`, `/relationship/global/set`, `/profiles/{id}/relationship/set`
- **Sitzungsübergreifendes Gedächtnis**: Erika "vergisst" nach einem Docker-Neustart nicht mehr — die letzten 7 Tagesrückblicke, alle aktiven Gesprächsthemen (bis 60 Tage Inaktivität) und Wochenzusammenfassungen (6 Monate) fließen beim Start automatisch in den LLM-Prompt ein
- **Langzeit-Gedächtnis (Phase 4.1 + 4.2)**:
  - Neue DB-Tabellen: `daily_summaries`, `weekly_summaries`, `active_topics`
  - `MemoryService`: baut Session-Kontext, erstellt/aktualisiert Tageszusammenfassungen, komprimiert 30 Tage alte Tageseinträge zu Wochensummaries, archiviert inaktive Themen nach 60 Tagen, löscht Wochen älter als 6 Monate
  - Stündlicher Hintergrund-Loop `_memory_maintenance_loop` aktualisiert alle Zusammenfassungen für jede bekannte Person
  - System-Prompt enthält jetzt: aktive Themen, Tagesrückblick (letzte 7 Tage), Wochengedächtnis
- **Kiosk-Display mit Kamera & Mikrofon**: `install.sh` richtet Chromium automatisch als Vollbild-Kiosk ein; Kamera und Mikrofon werden per Policy-Datei (`/etc/chromium/policies/managed/erika.json`) vorab freigegeben — kein Browser-Berechtigungsdialog beim Start; Autostart via `~/.config/autostart/erika-kiosk.desktop` mit 8-Sekunden Verzögerung; `INSTALL_MANUAL.md` Schritt 9 vollständig dokumentiert

---

## 2026-05-27

### Neu
- **`.env.example`**: Vollständige Vorlage mit allen Umgebungsvariablen und Standardwerten
- **CI/CD**: GitHub Actions Workflow (`.github/workflows/ci.yml`) — bei jedem Push wird automatisch das Test-Image gebaut und die Testsuite ausgeführt
- **Offline-Banner im Display**: Wenn das Backend nicht erreichbar ist, zeigt das Display einen roten Banner mit Spinner statt still zu versagen
- **Audit-Log Fehler-Einträge**: Hintergrund-Loops (Reminder, Notifications) schreiben Exceptions als `system.error` ins Audit-Log; im Admin-Protokoll-Tab rot hervorgehoben
- **TTS-Watchdog-Metriken**: Jedes Mal wenn der 30s-Watchdog im Frontend auslöst, wird ein Zähler ans Backend gesendet; sichtbar im Admin unter Erika → TTS (nur wenn > 0)
- **Gesichtserkennung Fallback**: Bei Kamera-Fehler (z.B. kein Zugriff) wird der Fehler ans Backend gemeldet und nach 60s automatisch neu versucht — kein stilles Versagen mehr
- **INSTALL_MANUAL.md**: Vollständige manuelle Installationsanleitung Schritt für Schritt

### Verbessert
- **Version**: 0.1.0 → 0.3.0

### Aufgeräumt
- Veraltete `test_*.py` und alte Quell-Kopien (`main.py`, `robot_core.py` usw.) aus dem Repo-Root entfernt

---

## 2026-05-26

### Neu
- **Zeitgesteuerte Lichtbefehle per Sprache**: "Schalte um 19 Uhr das Licht im Wohnzimmer auf 50% ein" — Erika legt einen internen Zeitplan an. Der Watcher-Loop führt den HA-Lichtbefehl zur angegebenen Uhrzeit still aus; bei vergangener Uhrzeit automatisch auf morgen verschoben.
- **Timer-Restzeit per Sprache**: "Wie lange noch beim Nudel-Timer?" liefert die verbleibende Zeit; ohne Namensangabe werden alle laufenden Timer aufgelistet.
- **Timer per Sprache auflisten**: "Welche Timer laufen gerade?" gibt alle aktiven Timer mit Restzeit aus.
- **Timer umbenennen per Sprache**: "Nenn den ersten Timer Nudeln" — erkennt Ordinalzahl, vorhandenes Label oder (bei einem Timer) automatisch den einzigen laufenden.
- **Eigene RSS-Quellen im Admin**: Unter News → Eigene RSS-Quellen können beliebige RSS- oder Atom-Feed-URLs hinzugefügt werden; Favicon wird automatisch befüllt; erscheinen danach in der Quellenliste und können aktiviert werden.
- **Wetter-Anbieter auswählbar**: Im Admin unter Wetter → Datenquelle kann zwischen Open-Meteo (Standard, kein Key), Yr.no/MET Norway (kein Key) und OpenWeatherMap (kostenloser Key) gewählt werden.
- **Gesprächs-Zusammenfassung**: "Was haben wir heute besprochen?" liefert eine kompakte Zusammenfassung der heutigen Konversationsthemen.
- **Tägliches Fazit**: Erika fragt abends proaktiv "Wie war dein Tag heute?" — Uhrzeit im Admin konfigurierbar; Antwort wird als Notiz gespeichert.
- **Zeitpläne-Tab im Admin**: Unter Konfiguration → Zeitpläne sind alle aktiven Erinnerungen und zeitgesteuerten Lichtbefehle sichtbar — mit Feuerzeitpunkt, Status und Lösch-Button.

### Behoben
- **Zeitgesteuerte Befehle 2 Stunden zu spät**: `robot-core`-Container lief in UTC (keine `TZ`-Variable gesetzt). Zeiten wie "19 Uhr" wurden als 19:00 UTC statt 17:00 UTC gespeichert. Behoben durch `TZ: ${TZ:-Europe/Berlin}` im Docker-Compose. Betrifft Lichtpläne und reguläre Erinnerungen.
- **Timer-Label "Nudeln auf"**: `_TIMER_LABEL_RE` extrahierte fälschlich zwei Wörter im `für`-Zweig — jetzt nur ein Wort (kein nachfolgendes "auf", "ein" o.ä.).
- **Wetter-Sprachbefehle**: `WeatherProvider.search()` rief Open-Meteo direkt auf statt den konfigurierten Provider zu nutzen.
- **Wetter-Widget verschwindet bei API-Fehler**: Zeigt jetzt einen Platzhalter statt das Widget komplett auszublenden.
- **Timer-Fehlerresistenz**: `_try_timer_command()` fängt nun alle Exceptions ab.
- **`/chat/log` Endpoint**: Interner Endpoint zum Loggen von Assistenten-Nachrichten.

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
