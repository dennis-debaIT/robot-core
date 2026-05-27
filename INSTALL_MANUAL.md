# Erika Robot Core — Manuelle Installation

Diese Anleitung beschreibt alle Schritte für eine manuelle Installation ohne das `install.sh`-Script.  
Empfohlen wenn: das Script fehlschlägt, du ein anderes System nutzt, oder du jeden Schritt selbst kontrollieren möchtest.

**Schnellinstallation (empfohlen):** Siehe [INSTALL.md](INSTALL.md)

---

## Voraussetzungen

| Anforderung | Details |
|---|---|
| **Betriebssystem** | Ubuntu 22.04 LTS / Debian 12 oder neuer |
| **Architektur** | amd64 (x86_64) oder arm64 (Raspberry Pi 4/5) |
| **RAM** | mindestens 1 GB (2 GB empfohlen) |
| **Speicher** | mindestens 8 GB frei |
| **Netzwerk** | SSH-Zugang aktiv, Internetzugang für Docker Pull / Edge TTS |

---

## Schritt 1 — Systempakete installieren

```bash
sudo apt-get update
sudo apt-get install -y curl git ca-certificates gnupg lsb-release openssh-client openssl sqlite3 avahi-daemon
sudo systemctl enable --now avahi-daemon
```

> `avahi-daemon` ermöglicht den Zugriff über `erika.local` im lokalen Netzwerk.

---

## Schritt 2 — Docker installieren

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/$(. /etc/os-release && echo "$ID")/gpg \
    | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/$(. /etc/os-release && echo "$ID") \
    $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Aktuellen Nutzer zur Docker-Gruppe hinzufügen (neu einloggen danach!)
sudo usermod -aG docker $USER
sudo systemctl enable --now docker
```

Nach dem `usermod`-Befehl musst du dich neu einloggen (oder `newgrp docker` ausführen).

---

## Schritt 3 — Repository klonen

```bash
git clone https://github.com/dennis-debaIT/robot-core.git ~/robot-core
cd ~/robot-core
```

---

## Schritt 4 — `.env` konfigurieren

```bash
cp .env.example .env
nano .env
```

Mindestpflichtfelder:

```env
LLM_API_URL=http://<deine-LM-Studio-IP>:1234/v1/chat/completions
LLM_PROVIDER=openai_compat
ROBOT_HA_URL=http://<deine-HA-IP>:8123
ROBOT_HA_TOKEN=<Long-Lived Access Token aus HA>
SSH_DIR=/home/<dein-user>/.ssh
```

Den HA-Token erstellt du in Home Assistant unter: **Profil → Sicherheit → Langlebige Zugriffstoken → Token erstellen**.

---

## Schritt 5 — SSL-Zertifikat erstellen

```bash
mkdir -p ssl
openssl req -x509 -newkey rsa:4096 \
    -keyout ssl/key.pem -out ssl/cert.pem \
    -days 3650 -nodes \
    -subj "/CN=erika.local"
```

---

## Schritt 6 — Hilfsdateien anlegen

```bash
touch update.flag reboot.flag timezone.flag hostname.flag wlan.flag ha-install.flag components.flag
echo '{"networks":[]}' > wifi-scan.json
mkdir -p ha_config
chmod +x update.sh reboot-watcher.sh setup-watcher.sh
```

---

## Schritt 7 — Container bauen und starten

```bash
GIT_HASH=$(git rev-parse HEAD)
docker compose build --build-arg GIT_HASH="$GIT_HASH" robot-core
docker compose up -d robot-core
```

Der Build dauert beim ersten Mal einige Minuten.  
Status prüfen:

```bash
docker compose ps
docker compose logs -f robot-core
```

---

## Schritt 8 — Autostart bei Systemstart

Docker selbst startet automatisch mit dem System (`systemctl enable docker`).  
Der Container ist mit `restart: unless-stopped` konfiguriert und startet ebenfalls automatisch.

Optional: Watcher-Dienste für Updates und Reboot einrichten:

```bash
# Watcher im Hintergrund starten
nohup bash ~/robot-core/reboot-watcher.sh >> ~/robot-core/reboot.log 2>&1 &
nohup bash ~/robot-core/setup-watcher.sh >> ~/robot-core/setup-watcher.log 2>&1 &

# Autostart via Cron
(crontab -l 2>/dev/null; echo "@reboot bash ~/robot-core/reboot-watcher.sh >> ~/robot-core/reboot.log 2>&1 &") | crontab -
(crontab -l 2>/dev/null; echo "@reboot bash ~/robot-core/setup-watcher.sh >> ~/robot-core/setup-watcher.log 2>&1 &") | crontab -

# Tägliches automatisches Update um 03:00 Uhr
(crontab -l 2>/dev/null; echo "0 3 * * * bash ~/robot-core/update.sh >> ~/robot-core/update.log 2>&1") | crontab -
```

Optional: Reboot ohne sudo-Passwort erlauben (für den Update-Prozess):

```bash
echo "$USER ALL=(ALL) NOPASSWD: /sbin/reboot" | sudo tee /etc/sudoers.d/erika-reboot
sudo chmod 440 /etc/sudoers.d/erika-reboot
```

---

## Ergebnis

Nach erfolgreichem Start ist Erika erreichbar unter:

| URL | Funktion |
|---|---|
| `https://<IP>:8000/` | Haupt-Interface |
| `https://<IP>:8000/display` | Display-Panel (Kiosk-Modus) |
| `https://<IP>:8000/local-admin` | Admin-Panel |
| `https://erika.local:8000/` | Über mDNS (wenn avahi läuft) |

> Der Browser zeigt eine Zertifikatswarnung für das selbstsignierte SSL-Zertifikat — einfach bestätigen ("Trotzdem fortfahren").

---

## Häufige Probleme

**Docker-Befehl nicht gefunden nach Installation**  
→ Neu einloggen oder `newgrp docker` ausführen.

**Container startet nicht**  
→ `docker compose logs robot-core` zeigt den Fehler. Häufigste Ursache: fehlende Pflichtfelder in `.env`.

**`erika.local` nicht erreichbar**  
→ `sudo systemctl status avahi-daemon` prüfen. Alternativ direkt über IP ansprechen.

**SSL-Warnung im Browser**  
→ Normal bei selbstsignierten Zertifikaten. Im Browser einmalig als Ausnahme bestätigen.  
→ Für ein vertrauenswürdiges Zertifikat: cert.pem/key.pem durch ein Let's-Encrypt-Zertifikat ersetzen.

**TTS funktioniert nicht**  
→ Bei Edge TTS: Internetzugang erforderlich.  
→ Bei Sherpa ONNX: Modellpfade in `.env` korrekt? Pfade müssen im Container unter `/models/tts/` erreichbar sein (Volume in `docker-compose.yml` prüfen).
