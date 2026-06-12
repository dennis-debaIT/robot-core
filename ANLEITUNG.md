# Erika — Benutzeranleitung

Erika ist ein KI-gestützter Haushaltsassistent, der per Sprache gesteuert wird.  
Diese Anleitung beschreibt alle Sprachbefehle und wichtigen Funktionen.

---

## Inhaltsverzeichnis

1. [Sprachaktivierung](#1-sprachaktivierung)
2. [Lichtsteuerung](#2-lichtsteuerung)
3. [Timer](#3-timer)
4. [Erinnerungen](#4-erinnerungen)
5. [Notizen](#5-notizen)
6. [Kalender](#6-kalender)
7. [Wetter](#7-wetter)
8. [Fußball](#8-fußball)
9. [Fahrzeuge](#9-fahrzeuge)
10. [Roboter](#10-roboter)
11. [Smart Home](#11-smart-home)
12. [Zusammenfassungen & Briefing](#12-zusammenfassungen--briefing)
13. [Tägliches Fazit](#13-tägliches-fazit)
14. [Persönliches](#14-persönliches)
15. [PV-Anlage](#15-pv-anlage)
16. [System](#16-system)
17. [Design & Layout](#17-design--layout)

---

## 1. Sprachaktivierung

### Wake Word
Erika hört ständig passiv zu und reagiert auf das Auslösewort (Standard: **"Erika"**).

| Befehl | Funktion |
|---|---|
| `Erika, [dein Befehl]` | Aktiviert Erika und startet die Erkennung |
| `Erika stop` / `Erika halt` | Unterbricht laufende Sprachausgabe sofort |

Das Wake Word kann im Admin-Panel unter **Erika → Aufmerksamkeit** geändert werden.

### Manuelle Aktivierung
Am Display kann alternativ ein Mikrofon-Button gedrückt werden.

### Proaktive Ansprache
Wenn Erika erkennt, dass du längere Zeit nichts gesagt hast (Standard: 25 Minuten), spricht sie dich eigenständig an. Das Zeitfenster (z. B. 08:00–22:00 Uhr) ist im Admin konfigurierbar.

### Begrüßung bei Gesichtserkennung
Erkennt Erika eine bekannte Person, begrüßt sie diese automatisch. Die Begrüßung wird per LLM erzeugt und berücksichtigt optional:

| Kontext | Beschreibung |
|---|---|
| **Tageszeit** | Morgen / Mittag / Abend / Nacht |
| **Nächster Kalendertermin** | "Du hast um 14 Uhr ein Meeting" |
| **PV-Tagesertrag** | Aktueller Solarertrag des Tages |
| **Aktive Gesprächsthemen** | Was zuletzt besprochen wurde |

Welche dieser Informationen in die Begrüßung einfließen, lässt sich im Admin-Panel unter **Erika → Begrüßung** per Checkbox steuern. Dort kann auch die KI-generierte Begrüßung komplett deaktiviert werden — Erika verwendet dann feste Templates basierend auf Beziehungsstatus und Abwesenheitsdauer.

---

## 2. Lichtsteuerung

Erika steuert alle in Home Assistant konfigurierten Lichter per Sprache.

### Ein-/Ausschalten

| Befehl | Funktion |
|---|---|
| `Mach das Licht im Wohnzimmer an` | Licht einschalten |
| `Schalte das Licht im Arbeitszimmer aus` | Licht ausschalten |
| `Mach alle Lichter aus` | Alle Lichter ausschalten |
| `Licht an` / `Licht aus` | Alle Lichter ein/aus |

### Helligkeit

| Befehl | Funktion |
|---|---|
| `Licht im Wohnzimmer auf 50%` | Helligkeit auf 50 % setzen |
| `Licht im Arbeitszimmer auf 100 Prozent` | Vollhelligkeit |
| `Mach das Licht heller` / `dunkler` | Relative Anpassung |
| `Dimm das Licht im Schlafzimmer` | Licht dimmen |

> **Hinweis:** Prozentwerte funktionieren auch wenn das Licht gerade ausgeschaltet ist.

### Zeitgesteuert

| Befehl | Funktion |
|---|---|
| `Schalte um 19 Uhr das Licht im Wohnzimmer auf 50% ein` | Licht zu fester Uhrzeit einschalten |
| `Mach um 22 Uhr alle Lichter aus` | Alle Lichter um 22 Uhr ausschalten |
| `Dimm um 20 Uhr das Wohnzimmerlicht auf 30%` | Helligkeit zu bestimmter Uhrzeit |

> Bei vergangener Uhrzeit wird der Befehl automatisch für den nächsten Tag geplant.

> Alle geplanten Lichtbefehle können im Admin-Panel unter **Konfiguration → Zeitpläne** eingesehen und gelöscht werden.

### Szenen

| Befehl | Funktion |
|---|---|
| `Aktiviere Szene Kinoabend` | Gespeicherte Szene laden |
| `Starte Szene Entspannung` | Szene starten |

Szenen können im Admin-Panel unter **Licht → Szenen** gespeichert werden.

---

## 3. Timer

### Setzen

| Befehl | Funktion |
|---|---|
| `Stell einen Timer auf 5 Minuten` | Timer für 5 Minuten |
| `Timer auf 1 Stunde 30 Minuten` | Timer für 90 Minuten |
| `Stell einen Timer für die Nudeln auf 10 Minuten` | Timer mit Label |

### Abfragen

| Befehl | Funktion |
|---|---|
| `Wie lange noch?` | Restzeit aller laufenden Timer |
| `Wie lange noch beim Nudel-Timer?` | Restzeit eines bestimmten Timers |
| `Welche Timer laufen gerade?` | Alle aktiven Timer auflisten |

### Verwalten

| Befehl | Funktion |
|---|---|
| `Nenn den ersten Timer Nudeln` | Timer umbenennen (nach Position: ersten/zweiten/…) |
| `Nenn den Nudel-Timer Pasta` | Timer nach aktuellem Label umbenennen |
| `Stopp den Timer` | Laufenden Timer abbrechen |
| `Alle Timer löschen` | Alle Timer beenden |
| `Stop` / `Ok` / `Fertig` | Fertigen Timer quittieren |

Mehrere Timer gleichzeitig sind möglich. Wenn ein Timer abläuft, ertönt ein Piepton und Erika sagt dir Bescheid.

---

## 4. Erinnerungen

### Erinnerung setzen

| Befehl | Funktion |
|---|---|
| `Erinnere mich in 30 Minuten an die Wäsche` | Relative Erinnerung |
| `Erinnere mich in 2 Stunden an den Arzt` | Erinnerung in 2 Stunden |
| `Erinnere mich um 14:15 Uhr an Kind abholen` | Erinnerung zu fester Uhrzeit |
| `Erinnere mich um 19 Uhr an Müll rausbringen` | Erinnerung am Abend |

> Wenn die angegebene Uhrzeit heute schon verstrichen ist, wird die Erinnerung auf morgen gesetzt.

### Erinnerungen verwalten

| Befehl | Funktion |
|---|---|
| `Welche Erinnerungen habe ich?` | Alle aktiven Erinnerungen auflisten |
| `Lösch alle Erinnerungen` | Alle Erinnerungen löschen |

### Was passiert wenn die Erinnerung fällig ist?
Erika sagt den Erinnerungstext laut an und zeigt ein Overlay auf dem Display.

---

## 5. Notizen

### Notiz speichern

| Befehl | Funktion |
|---|---|
| `Merk dir: WLAN-Passwort ist SuperGeheim123` | Notiz speichern |
| `Notiere: Arzttermin Freitag 10 Uhr` | Notiz mit Titel |
| `Speicher die Notiz Einkaufsliste: Milch, Brot, Käse` | Notiz mit Inhalt |

### Notiz abfragen

| Befehl | Funktion |
|---|---|
| `Wie ist mein WLAN-Passwort?` | Notiz abfragen — Overlay öffnet sich |
| `Was hast du dir zum Arzttermin gemerkt?` | Notiz suchen |
| `Zeig mir die Notiz zur Einkaufsliste` | Notiz anzeigen |

### Alle Notizen

| Befehl | Funktion |
|---|---|
| `Zeig mir alle Notizen` | Alle Notizen auflisten |
| `Was hast du dir alles gemerkt?` | Übersicht aller Notizen |

### Notiz löschen

| Befehl | Funktion |
|---|---|
| `Lösch die Notiz zum WLAN` | Notiz nach Stichwort löschen |

---

## 6. Kalender

### Termin abfragen

| Befehl | Funktion |
|---|---|
| `Was liegt heute an?` | Heutige Termine |
| `Was steht morgen im Kalender?` | Morgige Termine |
| `Was steht diese Woche an?` | Wöchentliche Übersicht |

### Termin eintragen

| Befehl | Funktion |
|---|---|
| `Trag einen Termin für morgen um 15 Uhr ein: Zahnarzt` | Termin anlegen |
| `Erstelle einen Kalendereintrag: Meeting am Dienstag um 10 Uhr` | Termin mit Details |
| `Trag in meinen Kalender ein: Sport am Freitag um 18 Uhr` | Persönlicher Termin |

> Erika nutzt das LLM zur Datums- und Zeitextraktion. Kalender müssen in Home Assistant konfiguriert und im Admin-Panel verknüpft sein.

---

## 7. Wetter

| Befehl | Funktion |
|---|---|
| `Wie ist das Wetter heute?` | Aktuelles Wetter |
| `Wie wird das Wetter morgen?` | Wettervorhersage |
| `Brauche ich heute einen Regenschirm?` | Regenwahrscheinlichkeit |
| `Wie warm wird es heute?` | Temperatur |

Das Wetter-Widget auf dem Display zeigt automatisch aktuelle Daten (Open-Meteo).

---

## 8. Fußball

| Befehl | Funktion |
|---|---|
| `Wie hat Darmstadt gespielt?` | Letztes Spielergebnis |
| `Auf welchem Platz steht Darmstadt?` | Tabellenplatz |
| `Wie sieht die Tabelle aus?` | Aktuelle Bundesliga-Tabelle |
| `Was sind die Ergebnisse vom Wochenende?` | Alle Spielergebnisse |

Der Lieblingsverein kann im Admin-Panel unter dem Personenprofil hinterlegt werden und wird dann automatisch bevorzugt.

---

## 9. Fahrzeuge

| Befehl | Funktion |
|---|---|
| `Wie viel Akku hat der Dacia?` | Ladestand abfragen |
| `Wie weit komme ich noch?` | Reichweite abfragen |
| `Ist das Auto am Laden?` | Ladestatus |
| `Wie ist der Tankstand?` | Tank-Füllstand (Verbrenner) |
| `Status aller Fahrzeuge` | Alle Fahrzeuge anzeigen |

Fahrzeuge werden im Admin-Panel unter **Fahrzeuge** mit HA-Entitäten verknüpft.

---

## 10. Roboter

### Staubsauger

| Befehl | Funktion |
|---|---|
| `Was macht der Staubsauger?` | Status abfragen |
| `Schick den Staubsauger in die Küche` | Raum reinigen |
| `Lass den Staubsauger alles saugen` | Alle Räume saugen |
| `Schick den Staubsauger nach Hause` | Zur Ladestation |

### Mähroboter

| Befehl | Funktion |
|---|---|
| `Was macht der Mähroboter?` | Status abfragen |
| `Starte den Mähroboter` | Mähen beginnen |
| `Robert nach Hause` | Zur Ladestation |
| `Mähroboter pausieren` | Mähen pausieren |

Räume und Roboternamen werden im Admin-Panel konfiguriert.

---

## 11. Smart Home

### Proaktive Benachrichtigungen
Erika kann HA-Entitäten überwachen und bei Zustandsänderungen automatisch informieren (z. B. "Die Waschmaschine ist fertig").  
Regeln werden im Admin-Panel unter **Benachrichtigungen** angelegt.

---

## 12. Zusammenfassungen & Briefing

### Tagesbriefing

| Befehl | Auslöser-Phrase (konfigurierbar) |
|---|---|
| Persönliches Tagesbriefing | Im Admin definierte Phrase, z. B. "Guten Morgen Erika" |

Das Briefing enthält konfigurierbare Module: Wetter, Kalender, Fahrzeugstatus, Roboterstatus etc.  
Die Reihenfolge ist per Drag & Drop im Admin anpassbar.

### Gesprächs-Zusammenfassung

| Befehl | Funktion |
|---|---|
| `Was haben wir heute besprochen?` | Zusammenfassung der heutigen Themen |
| `Worüber haben wir heute geredet?` | Themenübersicht |
| `Fasse unser Gespräch zusammen` | Kompakte Zusammenfassung |

---

## 13. Tägliches Fazit

Erika fragt zu einer konfigurierbaren Abendzeit (Standard: 20:00 Uhr) proaktiv:  
**"Wie war dein Tag heute?"**

Die Antwort wird automatisch als Notiz "Tagesfazit DD.MM.YYYY" gespeichert.

Aktivierung und Uhrzeit im Admin-Panel unter **Erika → Aufmerksamkeit → Tägliches Fazit**.

---

## 14. Persönliches

Erika lernt beim Gespräch Fakten über dich kennen und merkt sie sich.

### Fakten automatisch merken (durch natürliches Gespräch)

| Aussage | Was gespeichert wird |
|---|---|
| `Ich bin 35 Jahre alt` | Alter |
| `Ich wohne in Hamburg` | Wohnort |
| `Ich komme aus München` | Herkunft |
| `Meine Lieblingsfarbe ist Blau` | Lieblingsfarbe |
| `Ich mag keinen Kaffee` | Abneigung |
| `Ich interessiere mich für Fotografie` | Interesse |
| `Ich arbeite als Entwickler` | Beruf |

### Aktiv nachfragen

| Befehl | Funktion |
|---|---|
| `Was weißt du über Dennis?` | Gespeichertes Wissen abfragen |

Alle gespeicherten Informationen können im Admin-Panel unter **Personen** eingesehen und bearbeitet werden.

---

## 15. PV-Anlage

Das PV-Widget auf dem Display zeigt Echtzeitdaten der Solaranlage und aktualisiert sich alle 5 Sekunden.

### Angezeigte Werte (konfigurierbar)

| Feld | Beschreibung |
|---|---|
| **Leistung** | Aktuelle PV-Erzeugungsleistung in Watt |
| **Hausverbrauch** | Berechneter Eigenverbrauch (`PV − Batterie − Netz`) |
| **Netz** | Einspeisung (positiv) oder Netzbezug (negativ) |
| **Tagesertrag** | Gesamt-kWh seit Mitternacht |
| **Batterie** | Ladestand in Prozent |
| **Temperatur** | Wechselrichter-Innentemperatur |

Welche Felder angezeigt werden, lässt sich im Admin-Panel unter **PV → Widget-Anzeige** per Checkbox bestimmen.

### Konfiguration im Admin (PV → Sensoren)

| Feld | Empfohlener HA-Sensor (Huawei SUN2000) |
|---|---|
| **Aktuelle Leistung** | `sensor.wechselrichter_wirkleistung` (AC-Ausgang) |
| **Tagesertrag** | `sensor.wechselrichter_tagesertrag` |
| **Temperatur** | `sensor.wechselrichter_interne_temperatur` |
| **Batterieladung (SOC)** | `sensor.batterien_batterieladung` |
| **Netz-Sensor** | `sensor.stromzahler_wirkleistung` (positiv = Einspeisung) |
| **Batterie-Leistung** | Leer lassen bei DC-gekoppelten Systemen (Huawei LUNA2000) |

> **Wichtig bei DC-gekoppelten Batteriesystemen (Huawei SUN2000 + LUNA2000):** Die Wirkleistung am AC-Ausgang berücksichtigt das Laden der Batterie bereits intern. Das Feld "Batterie-Leistung" muss leer bleiben — sonst wird die Batterieleistung doppelt abgezogen und der Hausverbrauch zeigt 0 W.

### PV-Statistik & Energiekosten (nur Erika Plus)

Über das PV-Widget lässt sich eine ausführliche **PV-Statistik** öffnen (Reiter Fluss / Heute / 7 Tage / Monat / Jahr) mit Diagrammen zu Ertrag, Einspeisung und Netzbezug.

Monat und Jahr greifen auf die Langzeitstatistiken von Home Assistant zu (über dessen WebSocket-API). Die Jahresansicht zeigt daher nur Monate, für die Home Assistant selbst bereits Statistiken aufgezeichnet hat — bei neu eingerichteten Sensoren oder kurz nach der Erika-Installation können ältere Monate fehlen, bis HA entsprechend lange Daten gesammelt hat.

Im Admin-Panel unter **PV → Stromtarife** können zwei Werte hinterlegt werden:

| Feld | Beschreibung |
|---|---|
| **Einspeisevergütung (ct/kWh)** | Vergütung pro eingespeister kWh (z.B. nach EEG) |
| **Strombezugstarif (ct/kWh)** | Preis pro kWh, der für Netzbezug bezahlt wird |

Sind beide Werte hinterlegt und ein **Netz-Sensor** konfiguriert (siehe oben), berechnet die PV-Statistik daraus automatisch:

- **Einspeiseerlös** = Einspeisung (kWh) × Einspeisevergütung
- **Netzbezugskosten** = Netzbezug (kWh) × Strombezugstarif
- **Saldo** = Einspeiseerlös − Netzbezugskosten

Diese Werte erscheinen in der PV-Statistik unter den Einspeisung-/Netzbezug-Balken — für Heute, 7 Tage, Monat und Jahr. Im PV-Widget selbst werden sie nicht angezeigt. Ohne hinterlegte Tarife bleibt die Statistik unverändert (kein Block mit Beträgen).

### Standort für Wetter-Abfragen

Im Admin-Panel unter **System → Standort** können Koordinaten für Wetter- und Standortabfragen gespeichert werden. Mit dem Button **"Von HA übernehmen"** werden die Koordinaten automatisch aus `zone.home` in Home Assistant gelesen — das vermeidet Verwechslungen bei gleichnamigen Orten (z.B. Frankfurt am Main vs. Frankfurt an der Oder).

---

## 16. System

| Befehl | Funktion |
|---|---|
| `Wie ist dein Akkustand?` | Erika-Akku abfragen |
| `Gibt es Updates?` | Update-Status |
| `Was zeigt dein Display gerade an?` | Display-Status |

---

## 17. Design & Layout

Das Aussehen des Displays wird im Admin-Panel unter **Design** angepasst — nicht per Sprache.

### Farben

Unter **Design → Farben** lassen sich alle 12 Farben des Displays anpassen (Hintergrund, Akzent, Text, Ränder usw.). Es gibt 6 fertige Themes zum direkten Anwenden:

- **Cyan** (Standard), **Grün**, **Amber**, **Violett**, **Rot**, **Hell** (helles, freundliches Theme)

Ein Klick auf ein Preset füllt die Farbwähler — gespeichert wird erst über **Speichern**. Die Farben werden beim nächsten Laden des Displays übernommen.

### Layout

Unter **Design → Layout** wird festgelegt, welche Widgets im linken und rechten Panel erscheinen:

- Verfügbare Widgets: **Wetter, Kalender, Kameras, Kraftstoff, PV-Anlage, Fahrzeug**
- Jedes Widget kann nur einmal vorkommen
- Pro Widget einstellbar: **Größe** (Höhengewicht) und **Reihenfolge** (↑↓)
- Kompakte Widgets (PV, Kraftstoff, Fahrzeug) zeigen immer ihren vollen Inhalt; flexible Widgets (Kalender, Wetter, Kameras) füllen den verbleibenden Platz

---

## Admin-Panel

Das Admin-Panel ist erreichbar unter: `http://[erika-ip]/local-admin`

| Bereich | Inhalt |
|---|---|
| **Erika** | Persönlichkeit, TTS, Aufmerksamkeit, Wake Word, Stimmung |
| **Erika → Begrüßung** | LLM-Begrüßung an/aus, Kontext-Checkboxen (Tageszeit, Kalender, PV, Themen) |
| **Personen** | Profile, Fakten, Gedächtnis, Beziehungsstatus, Offenheit |
| **Integrationen** | Home Assistant, Lichter, Roboter, Kameras, Fahrzeuge |
| **PV** | Sensoren konfigurieren, Widget-Felder per Checkbox, Statistiken, Energiefluss |
| **Design → Farben** | Theme-Farben anpassen, 6 Presets (inkl. Light Theme) |
| **Design → Layout** | Widgets auf linkes/rechtes Panel verteilen, Größe & Reihenfolge |
| **System → Standort** | Koordinaten manuell oder via "Von HA übernehmen" (zone.home) |
| **Kalender** | Kalender auswählen, Farben, Schreibkalender |
| **Wetter** | Anzeige-Optionen, Anbieter (Open-Meteo / Yr.no / OpenWeatherMap) |
| **Nachrichten** | RSS-Quellen auswählen, eigene RSS/Atom-Feeds hinzufügen |
| **Zeitpläne** | Aktive Erinnerungen und zeitgesteuerte Lichtbefehle einsehen/löschen |
| **Benachrichtigungen** | Proaktive Regeln (HA-Entitäten) |
| **Licht** | Szenen verwalten |
| **Audit-Log** | Verlauf aller Aktionen, Fehler-Einträge rot hervorgehoben |

---

## Tipps

- **Natürliche Sprache**: Erika versteht natürliche Formulierungen — du musst keine exakten Befehle verwenden.
- **Kontext**: Erika kennt den aktuellen Gesprächskontext und versteht Folgefragen (z. B. "Und morgen?" nach einer Wetterfrage).
- **Personen**: Wenn Erika dich erkennt (Gesichtserkennung oder Auswahl über das Personen-Dropdown), werden Antworten, Notizen und Kalendereinträge personalisiert.
- **Stichwort "Erika"**: Du brauchst nicht jedes Mal das Wake Word — beim aktiven Gespräch hört Erika nach Erikas TTS-Antwort auch kurze Zeit ohne Wake Word zu (Follow-Up Listening).
