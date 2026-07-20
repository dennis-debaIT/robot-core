# Erika – Installationsanleitung

## Schnellinstallation (empfohlen)

Auf einem frischen Ubuntu/Debian System — **kein GitHub-Account nötig**:

```bash
curl -fsSL https://raw.githubusercontent.com/dennis-debaIT/robot-core/main/install.sh | bash
```

Das Script übernimmt automatisch:
- System-Updates & Abhängigkeiten
- Docker Installation
- SSH-Key für GitHub generieren (einmalig manuell bei GitHub eintragen)
- Repository klonen
- SSL-Zertifikat erstellen
- Container bauen & starten
- Auto-Update Cron-Jobs einrichten

**Voraussetzung:** Ubuntu 22.04 LTS / Debian 12 oder neuer, SSH-Zugang aktiv.

> **Home Assistant (Option „HA + Mosquitto hier als Container installieren"
> im Skript):** läuft als normaler Docker-Container neben Erika — ohne
> Supervisor, also ohne Add-on-Store (Home Assistant Supervised ist seit
> HA-Release 2025.12 offiziell deprecated und wird deshalb hier nicht mehr
> angeboten). Für Add-ons wie Kamera-/MQTT-Integrationen (z.B. Ring) einen
> eigenen Container ergänzen, der sich mit dem mitinstallierten
> Mosquitto-Broker verbindet — siehe INSTALL_MANUAL.md Schritt 8. Wer den
> vollen Add-on-Store braucht, ist mit HAOS auf eigener Hardware/VM
> weiterhin besser bedient (Option „[1]" verbindet eine bestehende
> HA-Instanz per URL).

---

## Komplett-Installation (Robot-Core + Display-Kiosk)

Für ein einzelnes Gerät, das sowohl das Backend als auch das Touch-Display im
Kiosk-Modus betreiben soll (z.B. ein Tablet oder Mini-PC direkt am Einsatzort):

```bash
curl -fsSL https://raw.githubusercontent.com/dennis-debaIT/robot-core/main/install-complete.sh | bash
```

Zusätzlich zur Schnellinstallation richtet dieses Script einen eigenen
X11/Openbox-Kiosk mit Autologin auf TTY1 ein, der Chromium im Vollbild auf
das Display-Panel startet.

**Voraussetzung: Ubuntu Server** (nicht Desktop) 22.04 LTS oder neuer. Das
Script baut seinen eigenen minimalen Kiosk-Stack auf und deaktiviert dafür
nur `lightdm` — bei der Desktop-Edition ist stattdessen `gdm3` als
Display-Manager aktiv, der mit dem eigenen Autostart kollidiert. Die
Server-Edition hat von Haus aus keinen Display-Manager installiert, daher
gibt es dort keine Konflikte.

Setup danach im Browser unter `https://<IP>:8000/setup` — der Assistent
führt durch Netzwerk, Zeitzone, Home Assistant und Komponenten. Beim
allerersten Aufruf bietet er zusätzlich die Wahl zwischen Neueinrichtung und
Wiederherstellung eines bestehenden Backups (siehe nächster Abschnitt).

---

## Migration auf neue Hardware

Beim Umzug auf ein neues Gerät bietet der Setup-Assistent (`/setup`) direkt
beim ersten Aufruf einen geführten Restore-Einstieg: entweder eine lokal
heruntergeladene Backup-ZIP-Datei hochladen, oder mit Lizenzschlüssel und
Erika-Konto automatisch das letzte Cloud-Backup wiederherstellen
(Plus/Family). Die Konfiguration (Netzwerk, Zeitzone, Home Assistant,
Komponenten) ist danach sofort da — die einzelnen Einrichtungsschritte
entfallen.

> **Hinweis:** War das alte Gerät zuvor unter Admin-Panel → Erika-Konto als
> eigenständiges Gerät gekoppelt (für die Nachrichten-Funktion am Display),
> muss diese Kopplung nach der Wiederherstellung auf der neuen Hardware
> einmalig erneut hergestellt werden — sie ist an die alte Geräte-ID
> gebunden.

---

## Nach der Installation

Nach dem Start ist Erika erreichbar unter:

| URL | Funktion |
|-----|---------|
| `https://<IP>:8000/` | Haupt-Interface |
| `https://<IP>:8000/display` | Display-Panel (Kiosk-Modus) |
| `https://<IP>:8000/local-admin` | Admin-Panel |

> **Hinweis:** Der Browser zeigt eine Warnung für das selbstsignierte SSL-Zertifikat. Einfach bestätigen ("Trotzdem fortfahren").

### Home Assistant konfigurieren

Im **Admin-Panel → System → Home Assistant** die HA-URL und den Token eintragen. Die Konfiguration wird in der Datenbank gespeichert und bleibt bei Updates erhalten.

Alternativ können die Werte vorab in die `.env` geschrieben werden:

```env
ROBOT_HA_URL=http://<HA-IP>:8123
ROBOT_HA_TOKEN=<Long-Lived Access Token>
```

---

## Updates

Updates werden automatisch täglich um 03:00 Uhr geprüft und können manuell über **Admin-Panel → System → Updates** installiert werden.

---

## Manuelle Installation (Schritt für Schritt)

Falls das Install-Script nicht verwendet werden soll, sind alle Schritte im Detail in der Datei [INSTALL_MANUAL.md](INSTALL_MANUAL.md) beschrieben.
