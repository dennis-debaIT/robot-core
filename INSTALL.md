# Erika – Installationsanleitung

## Schnellinstallation (empfohlen)

Auf einem frischen Ubuntu/Debian System einen einzigen Befehl ausführen:

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
