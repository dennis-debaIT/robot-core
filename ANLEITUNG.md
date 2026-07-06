# Erika — Benutzeranleitung

Erika ist ein KI-gestützter Haushaltsassistent, der per Sprache gesteuert wird.  
Diese Anleitung beschreibt alle Sprachbefehle und wichtigen Funktionen für den täglichen Einsatz.

> Für Installation, Konfiguration und technische Einrichtung → [`ADMIN_ANLEITUNG.md`](ADMIN_ANLEITUNG.md)

---

## Inhaltsverzeichnis

1. [Sprachaktivierung](#1-sprachaktivierung)
2. [Lichtsteuerung](#2-lichtsteuerung)
3. [Timer](#3-timer)
4. [Erinnerungen](#4-erinnerungen)
5. [Einkaufsliste](#5-einkaufsliste)
6. [Hausaufgaben *(Plus/Family)*](#6-hausaufgaben-plusfamily)
7. [Notizen](#7-notizen)
8. [Kalender](#8-kalender)
9. [Wetter](#9-wetter)
10. [Fußball](#10-fußball)
11. [Fahrzeuge](#11-fahrzeuge)
12. [Roboter](#12-roboter)
13. [Smart Home](#13-smart-home)
14. [Zusammenfassungen & Briefing](#14-zusammenfassungen--briefing)
15. [Tägliches Fazit](#15-tägliches-fazit)
16. [Persönliches](#16-persönliches)
17. [PV-Anlage](#17-pv-anlage)
18. [Push-Benachrichtigungen](#18-push-benachrichtigungen)
19. [System & Backup](#19-system--backup)
20. [Design & Layout](#20-design--layout)
21. [Erika Companion App](#21-erika-companion-app)
22. [Admin-Panel Übersicht](#22-admin-panel-übersicht)

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
Erika sagt den Erinnerungstext laut an, zeigt ein Overlay auf dem Display und sendet eine Push-Benachrichtigung auf dein Smartphone (wenn die Companion App eingerichtet ist).

---

## 5. Einkaufsliste

Die Einkaufsliste ist auf dem Display über den 🛒-Button erreichbar und wird automatisch mit der Erika Companion App synchronisiert.

### Artikel hinzufügen

| Befehl | Funktion |
|---|---|
| `Füge Milch zur Einkaufsliste hinzu` | Artikel hinzufügen |
| `Pack Brot auf den Einkaufszettel` | Artikel hinzufügen |
| `Schreib Käse auf die Einkaufsliste` | Artikel hinzufügen |
| `Notiere Butter zur Einkaufsliste` | Artikel hinzufügen |
| `Setze Joghurt auf die Einkaufsliste` | Artikel hinzufügen |

### Artikel entfernen

| Befehl | Funktion |
|---|---|
| `Lösche Milch von der Einkaufsliste` | Artikel löschen |
| `Entferne Brot von der Einkaufsliste` | Artikel löschen |
| `Streiche Käse von der Einkaufsliste` | Artikel löschen |

> Nach jedem Sprachbefehl wechselt das Display automatisch zur Einkaufsliste und Erika bestätigt die Aktion per Sprache.

> Artikel, die am Display hinzugefügt werden, erscheinen innerhalb von 60 Sekunden in der Companion App — und umgekehrt.

---

## 6. Hausaufgaben *(Plus/Family)*

Das Hausaufgaben-Modul verwaltet wiederkehrende Haushaltsaufgaben (z. B. Staubsaugen, Spülmaschine ausräumen) und zeigt pro Aufgabe eine Statistik, wer sie wie oft erledigt hat.

> Dieses Feature ist in **Erika Plus** und **Erika Family** enthalten.

### Aufgaben im Display

Das Hausaufgaben-Modul ist über den 🧹-Button in der Navigation erreichbar (zwischen „Start" und „Fahrzeuge").

- **Linkes Panel**: Alle angelegten Aufgaben als Liste — Klick wählt die Aufgabe aus
- **Rechtes Panel**: Alle Personen aus den Profilen — Klick auf eine Person loggt sofort eine Erledigung für die ausgewählte Aufgabe
- **Center**: Statistik der ausgewählten Aufgabe (Tabs: Woche / Monat / Jahr) mit Balkendiagramm (Erledigungen pro Person) und Wochensieger

Oben im Center wird optional ein **Gesamt-Wochensieger** über alle Aufgaben hinweg angezeigt (in der Admin konfigurierbar).

### Verwaltung im Admin
Aufgaben werden im Admin-Panel unter **Hausaufgaben** angelegt:

- Aufgabe hinzufügen: Name + optionales Emoji-Icon
- Reihenfolge anpassen: ↑↓-Buttons
- Aufgabe löschen: Soft-Delete (Erledigungs-Historie bleibt erhalten)

---

## 7. Notizen

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

## 8. Kalender

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

## 9. Wetter

| Befehl | Funktion |
|---|---|
| `Wie ist das Wetter heute?` | Aktuelles Wetter |
| `Wie wird das Wetter morgen?` | Wettervorhersage |
| `Brauche ich heute einen Regenschirm?` | Regenwahrscheinlichkeit |
| `Wie warm wird es heute?` | Temperatur |

Das Wetter-Widget auf dem Display zeigt automatisch aktuelle Daten (Open-Meteo). Den Wetter-Anbieter (Open-Meteo / Yr.no / OpenWeatherMap) kann man im Admin unter **Wetter → Datenquelle** wählen.

---

## 10. Fußball

| Befehl | Funktion |
|---|---|
| `Wie hat Darmstadt gespielt?` | Letztes Spielergebnis |
| `Auf welchem Platz steht Darmstadt?` | Tabellenplatz |
| `Wie sieht die Tabelle aus?` | Aktuelle Bundesliga-Tabelle |
| `Was sind die Ergebnisse vom Wochenende?` | Alle Spielergebnisse |

Der Lieblingsverein kann im Admin-Panel unter dem Personenprofil hinterlegt werden und wird dann automatisch bevorzugt.

---

## 11. Fahrzeuge

| Befehl | Funktion |
|---|---|
| `Wie viel Akku hat der Dacia?` | Ladestand abfragen |
| `Wie weit komme ich noch?` | Reichweite abfragen |
| `Ist das Auto am Laden?` | Ladestatus |
| `Wie ist der Tankstand?` | Tank-Füllstand (Verbrenner) |
| `Status aller Fahrzeuge` | Alle Fahrzeuge anzeigen |

Fahrzeuge werden im Admin-Panel unter **Fahrzeuge** mit HA-Entitäten verknüpft.

---

## 12. Roboter

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

## 13. Smart Home

### Proaktive Benachrichtigungen
Erika kann HA-Entitäten überwachen und bei Zustandsänderungen automatisch informieren (z. B. "Die Waschmaschine ist fertig").  
Regeln werden im Admin-Panel unter **Benachrichtigungen** angelegt.

---

## 14. Zusammenfassungen & Briefing

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

## 15. Tägliches Fazit

Erika fragt zu einer konfigurierbaren Abendzeit (Standard: 20:00 Uhr) proaktiv:  
**"Wie war dein Tag heute?"**

Die Antwort wird automatisch als Notiz "Tagesfazit DD.MM.YYYY" gespeichert.

Aktivierung und Uhrzeit im Admin-Panel unter **Erika → Aufmerksamkeit → Tägliches Fazit**.

---

## 16. Persönliches

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

## 17. PV-Anlage

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

### PV-Statistik & Energiekosten *(Erika Plus)*

Über das PV-Widget lässt sich eine ausführliche **PV-Statistik** öffnen (Reiter Fluss / Heute / 7 Tage / Monat / Jahr) mit Diagrammen zu Ertrag, Einspeisung und Netzbezug.

Im Admin-Panel unter **PV → Stromtarife** können zwei Werte hinterlegt werden:

| Feld | Beschreibung |
|---|---|
| **Einspeisevergütung (ct/kWh)** | Vergütung pro eingespeister kWh (z.B. nach EEG) |
| **Strombezugstarif (ct/kWh)** | Preis pro kWh, der für Netzbezug bezahlt wird |

Sind beide Werte hinterlegt, berechnet die PV-Statistik daraus automatisch Einspeiseerlös, Netzbezugskosten und Saldo.

> **Hinweis:** Die Jahresansicht zeigt nur Monate, für die Home Assistant bereits Langzeitstatistiken aufgezeichnet hat — bei neu eingerichteten Sensoren können ältere Monate fehlen.

---

## 18. Push-Benachrichtigungen

Erika kann Benachrichtigungen direkt auf dein Smartphone senden — auch wenn die Companion App nicht geöffnet ist.

### Voraussetzungen

- **Erika Companion App** installiert und eingerichtet (Android)
- Beim ersten App-Start: Benachrichtigungen im System-Dialog **erlauben**
- App muss mindestens einmal geöffnet und mit dem Sync Server verbunden gewesen sein (Token-Registrierung)

### Was wird benachrichtigt?

| Ereignis | Kanal | Priorität |
|---|---|---|
| Fällige Erinnerung | Erinnerungen | Hoch (mit Ton) |
| Müllabfuhr morgen | Mülltonnen | Normal |

### Müllabfuhr-Benachrichtigung konfigurieren

Im Admin-Panel unter **Abfall → Push-Benachrichtigung**:

- **Aktivieren/Deaktivieren**: Checkbox
- **Uhrzeit**: Zeitfeld, zu der die Benachrichtigung am Vorabend gesendet wird (Standard: 18:00 Uhr)

> Erika prüft täglich zur eingestellten Uhrzeit ob am nächsten Tag eine Tonne abgeholt wird. Ist das der Fall, erhalten alle registrierten Geräte eine Benachrichtigung mit den betroffenen Tonnen.

---

## 19. System & Backup

| Befehl | Funktion |
|---|---|
| `Wie ist dein Akkustand?` | Erika-Akku abfragen |
| `Gibt es Updates?` | Update-Status |
| `Was zeigt dein Display gerade an?` | Display-Status |

### Cloud-Backup

Im Admin-Panel unter **System → Cloud-Backup** kann ein verschlüsseltes Backup erstellt werden, das Datenbank und alle Einstellungen (inkl. HA-Token, LLM-Konfiguration usw.) enthält.

**Backup erstellen:**
1. Im Admin → System → Cloud-Backup auf **„☁️ Backup erstellen"** klicken
2. Das Backup wird verschlüsselt im Sync Server gespeichert
3. Datum und Größe des letzten Backups werden angezeigt

**Wiederherstellen nach Gerätedefekt:**
1. Neues System aufsetzen (`install.sh` ausführen)
2. Sync-Zugangsdaten in `license.json` eintragen (E-Mail + Passwort)
3. `update.sh` ausführen — lädt den aktuellen Code
4. Im Admin → System → Cloud-Backup auf **„↩️ Wiederherstellen"** klicken
5. Erika startet automatisch neu — alle Einstellungen sind wie vorher

> Das Backup ist mit deinem Sync-Token verschlüsselt (AES-256). Ohne diesen Token kann niemand das Backup entschlüsseln.

---

## 20. Design & Layout

Das Aussehen des Displays wird im Admin-Panel unter **Design** angepasst — nicht per Sprache.

### Farben

Unter **Design → Farben** lassen sich alle 12 Farben des Displays anpassen (Hintergrund, Akzent, Text, Ränder usw.). Es gibt 6 fertige Themes zum direkten Anwenden:

- **Cyan** (Standard), **Grün**, **Amber**, **Violett**, **Rot**, **Hell** (helles, freundliches Theme)

Ein Klick auf ein Preset füllt die Farbwähler — gespeichert wird erst über **Speichern**. Die Farben werden beim nächsten Laden des Displays übernommen.

### Zeitabhängiges Design *(Plus)*

Unter **Design → Zeitabhängiges Design** kann ein automatischer Tag/Nacht-Wechsel aktiviert werden:

- **Tag ab** / **Nacht ab**: Uhrzeiten, zu denen zwischen dem normalen Theme und einem separaten, gedämpften **Nacht-Theme** gewechselt wird
- Das Nacht-Theme wird genauso wie das Tag-Theme über Presets oder die 12 Farbwähler eingestellt
- Das Display übernimmt einen Wechsel innerhalb von ca. 10 Sekunden

### Layout

Unter **Design → Layout** wird festgelegt, welche Widgets im linken und rechten Panel erscheinen:

- Verfügbare Widgets: **Wetter, Kalender, Kameras, Kraftstoff, PV-Anlage, Fahrzeug**
- Jedes Widget kann nur einmal vorkommen
- Pro Widget einstellbar: **Größe** (Höhengewicht) und **Reihenfolge** (↑↓)
- Kompakte Widgets (PV, Kraftstoff, Fahrzeug) zeigen immer ihren vollen Inhalt; flexible Widgets (Kalender, Wetter, Kameras) füllen den verbleibenden Platz

---

## 21. Erika Companion App

Die **Erika Companion App** (Android) ist die mobile Ergänzung zum Display — ohne externe Cloud. Alle Daten laufen direkt über den Erika Sync Server.

### Funktionen

| Funktion | Beschreibung |
|---|---|
| **Einkaufsliste** | Artikel hinzufügen, abhaken, löschen — synchronisiert bidirektional mit dem Display |
| **Kalender** | Nächster Termin direkt auf der Startseite sichtbar |
| **Hausaufgaben** *(Plus)* | Aufgaben einsehen und Erledigungen loggen |
| **Erinnerungen** | Übersicht aller aktiven Erinnerungen |
| **Push-Benachrichtigungen** | Fällige Erinnerungen und Müllabfuhr-Vorabnachricht direkt aufs Smartphone |

### Einrichtung

1. App installieren (APK oder Play Store)
2. Beim ersten Start: **Mit Lizenz anmelden**
3. E-Mail-Adresse und Passwort des Erika-Accounts eingeben
4. App verbindet sich automatisch mit dem Sync Server

### Sync-Verhalten

- Die Einkaufsliste wird alle **60 Sekunden** automatisch synchronisiert
- Artikel, die am Display per Sprache hinzugefügt werden, erscheinen innerhalb von 60 Sekunden in der App
- Artikel, die in der App eingetragen werden, landen innerhalb von 60 Sekunden auf dem Display
- Offline-Betrieb: Die App speichert Änderungen lokal und synchronisiert beim nächsten Online-Kontakt

---

## 22. Admin-Panel Übersicht

Das Admin-Panel ist erreichbar unter: `https://[erika-ip]:8000/local-admin`

| Bereich | Inhalt |
|---|---|
| **Erika** | Persönlichkeit, TTS, Aufmerksamkeit, Wake Word, Stimmung |
| **Erika → Begrüßung** | LLM-Begrüßung an/aus, Kontext-Checkboxen (Tageszeit, Kalender, PV, Themen) |
| **Personen** | Profile, Fakten, Gedächtnis, Beziehungsstatus, Offenheit, Rolle (Erwachsener/Kind ♂/♀), eigenes Emoji |
| **Integrationen** | Home Assistant, Lichter, Roboter, Kameras, Fahrzeuge |
| **Hausaufgaben** *(Plus)* | Aufgaben anlegen/sortieren/löschen, Gesamt-Wochenstatistik ein/aus |
| **PV** | Sensoren konfigurieren, Widget-Felder per Checkbox, Statistiken, Energiefluss |
| **Strom** | Verbrauchssensoren (Waschmaschine etc.), Gesamt-Netzbezugssensor, Tarife |
| **Design → Farben** | Theme-Farben anpassen, 6 Presets (inkl. Light Theme) |
| **Design → Zeitabhängiges Design** *(Plus)* | Automatischer Tag/Nacht-Theme-Wechsel |
| **Design → Layout** | Widgets auf linkes/rechtes Panel verteilen, Größe & Reihenfolge |
| **System → Standort** | Koordinaten manuell oder via "Von HA übernehmen" (zone.home) |
| **System → Cloud-Backup** | Verschlüsseltes Backup erstellen oder wiederherstellen |
| **System → Admin-PIN** | Admin-Bereich mit 4–8-stelliger PIN schützen |
| **System → Diagnose** | Verbindungsstatus aller Integrationen prüfen (HA, LLM, Sync-Server, Internet) |
| **Kalender** | Kalender auswählen, Farben, Schreibkalender |
| **Wetter** | Anzeige-Optionen, Anbieter (Open-Meteo / Yr.no / OpenWeatherMap) |
| **Abfall → Push-Benachrichtigung** | Müllabfuhr-Benachrichtigung aktivieren, Uhrzeit einstellen |
| **Nachrichten** | RSS-Quellen auswählen, eigene RSS/Atom-Feeds hinzufügen, Stichwort-Filter |
| **Zeitpläne** | Aktive Erinnerungen und zeitgesteuerte Lichtbefehle einsehen/löschen |
| **Benachrichtigungen** | Proaktive Regeln (HA-Entitäten) |
| **Licht** | Szenen verwalten |
| **Protokoll** | Vollständiger Verlauf aller Systemereignisse. Filterbar nach Level (Info / Warnung / Fehler), Aktionstyp und Anzahl. Level-Badges: grün = info, gelb = warning, rot = error. |

---

## Tipps

- **Natürliche Sprache**: Erika versteht natürliche Formulierungen — du musst keine exakten Befehle verwenden.
- **Kontext**: Erika kennt den aktuellen Gesprächskontext und versteht Folgefragen (z. B. "Und morgen?" nach einer Wetterfrage).
- **Personen**: Wenn Erika dich erkennt (Gesichtserkennung oder Auswahl über das Personen-Dropdown), werden Antworten, Notizen und Kalendereinträge personalisiert.
- **Stichwort "Erika"**: Du brauchst nicht jedes Mal das Wake Word — beim aktiven Gespräch hört Erika nach Erikas TTS-Antwort auch kurze Zeit ohne Wake Word zu (Follow-Up Listening).
- **Strom-Modul**: Unter **⚡ Strom** im Display lässt sich der Energieverbrauch aller konfigurierten Geräte einsehen (Heute / 7 Tage / Monat / Jahr).
