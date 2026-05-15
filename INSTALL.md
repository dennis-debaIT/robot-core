# Erika – Installationsanleitung

Anleitung zur Ersteinrichtung des robot-core Systems auf einem neuen Erika-Gerät.

---

## Voraussetzungen

### Hardware
- Raspberry Pi 4 (empfohlen: 4 GB RAM) oder vergleichbarer Linux-Rechner
- MicroSD-Karte (min. 32 GB) oder SSD
- Stabiles Netzwerk (LAN oder WLAN)

### Betriebssystem
- Ubuntu Server 22.04 LTS oder Raspberry Pi OS (64-bit, Lite)
- SSH-Zugang muss aktiviert sein

---

## 1. Systemvorbereitung

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl ca-certificates gnupg lsb-release
```

---

## 2. Docker installieren

```bash
# Docker GPG-Key und Repository hinzufügen
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Docker installieren
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Aktuellen Nutzer zur Docker-Gruppe hinzufügen (kein sudo nötig)
sudo usermod -aG docker $USER
newgrp docker
```

Überprüfen:
```bash
docker --version
docker compose version
```

---

## 3. SSH-Key für GitHub einrichten

Wird benötigt damit Erika automatische Updates aus dem privaten GitHub-Repo ziehen kann.

```bash
# SSH-Key generieren (falls noch nicht vorhanden)
ssh-keygen -t ed25519 -C "erika-gerät" -f ~/.ssh/id_ed25519 -N ""

# Öffentlichen Key anzeigen – diesen bei GitHub hinterlegen
cat ~/.ssh/id_ed25519.pub
```

Den angezeigten Key unter **github.com → Settings → SSH and GPG keys → New SSH key** eintragen.

Verbindung testen:
```bash
ssh -T git@github.com
# Erwartete Ausgabe: "Hi dennis-debaIT! You've successfully authenticated..."
```

---

## 4. Repo klonen

```bash
cd ~
git clone git@github.com:dennis-debaIT/robot-core.git
cd robot-core
```

---

## 5. Konfiguration (.env)

```bash
cp .env.example .env   # falls vorhanden, sonst manuell anlegen
nano .env
```

Mindest-Konfiguration:

```env
# Home Assistant
ROBOT_HA_URL=http://<HA-IP>:8123
ROBOT_HA_TOKEN=<Dein HA Long-Lived Access Token>

# TTS (optional, Standard: deaktiviert)
ROBOT_TTS_PROVIDER=disabled

# LLM (optional)
LLM_API_URL=
LLM_PROVIDER=generic
```

> Die `.env`-Datei wird **nie** ins Git eingecheckt und bleibt bei Updates erhalten.

---

## 6. SSL-Zertifikat erstellen

Robot-core läuft per HTTPS. Für den lokalen Betrieb reicht ein selbstsigniertes Zertifikat:

```bash
mkdir -p ~/robot-core/ssl
openssl req -x509 -newkey rsa:4096 -keyout ~/robot-core/ssl/key.pem \
  -out ~/robot-core/ssl/cert.pem -days 3650 -nodes \
  -subj "/CN=erika.local"
```

---

## 7. Container starten

```bash
cd ~/robot-core

# Ersten Build ausführen (dauert einige Minuten)
GIT_HASH=$(git rev-parse HEAD)
docker compose build --build-arg GIT_HASH=$GIT_HASH robot-core
docker compose up -d robot-core
```

Überprüfen ob der Container läuft:
```bash
docker ps
docker logs --tail 20 robot-core
```

Die Web-Oberfläche ist erreichbar unter: `https://<Geräte-IP>:8000`

---

## 8. Automatische Updates einrichten

```bash
# Update-Script ausführbar machen
chmod +x ~/robot-core/update.sh

# Cron-Jobs einrichten
(crontab -l 2>/dev/null; \
 echo "0 3 * * * /home/$USER/robot-core/update.sh >> /home/$USER/robot-core/update.log 2>&1"; \
 echo "* * * * * [ -f /home/$USER/robot-core/update.flag ] && cat /home/$USER/robot-core/update.flag | grep -q requested_at && echo '{}' > /home/$USER/robot-core/update.flag && /home/$USER/robot-core/update.sh >> /home/$USER/robot-core/update.log 2>&1 || true" \
) | crontab -
```

Updates können danach auch manuell über das Admin-Panel unter **System → Updates** ausgelöst werden.

---

## 9. Autostart beim Booten

Docker startet Container automatisch neu (`restart: unless-stopped` ist bereits in der `docker-compose.yml` gesetzt). Um sicherzustellen dass Docker selbst beim Boot startet:

```bash
sudo systemctl enable docker
```

---

## Fertig

Erika ist einsatzbereit. Beim ersten Start werden alle Datenbank-Tabellen automatisch angelegt.

| URL | Funktion |
|-----|---------|
| `https://<IP>:8000/` | Haupt-Interface |
| `https://<IP>:8000/display` | Display-Panel (Kiosk-Modus) |
| `https://<IP>:8000/local-admin` | Admin-Panel |
