# Erika Robot Core — Manuelle Installation

Diese Anleitung beschreibt alle Schritte für eine manuelle Installation ohne das `install.sh`-Script.  
Empfohlen wenn: das Script fehlschlägt, du ein anderes System nutzt, oder du jeden Schritt selbst kontrollieren möchtest.

**Schnellinstallation (empfohlen):** `curl -fsSL https://raw.githubusercontent.com/dennis-debaIT/robot-core/main/install.sh | bash`

---

## Voraussetzungen

| Anforderung | Details |
|---|---|
| **Betriebssystem** | **Debian 12 (Bookworm)** oder Raspberry Pi OS (64-bit, Bookworm-basiert) |
| **Architektur** | amd64 (x86_64) oder arm64 (Raspberry Pi 3/4/5) |
| **RAM** | mindestens 1 GB für Erika allein; 2 GB empfohlen; 4 GB wenn HA zusätzlich als Container mitläuft |
| **Speicher** | mindestens 8 GB frei; 16 GB empfohlen wenn HA zusätzlich als Container mitläuft |
| **Netzwerk** | SSH-Zugang aktiv, Internetzugang für Docker Pull / Edge TTS |

> **Keine Desktop-Umgebung nötig.**  
> Erika nutzt eine eigene Kiosk-Session (openbox + Chromium). `install.sh` installiert alles Nötige selbst — LightDM, openbox, feh, Chromium. Bei der Debian-Grundinstallation reicht es, nur **SSH server** und **Standard-Systemwerkzeuge** auszuwählen. LXDE, GNOME oder andere Desktop-Umgebungen werden nicht benötigt und verschwenden Ressourcen.

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
```

Den HA-Token erstellt du in Home Assistant unter: **Profil → Sicherheit → Langlebige Zugriffstoken → Token erstellen**.

### LLM-Optionen

Erika bringt **kein eigenes Sprachmodell** mit — du wählst eine der folgenden Quellen (BYOK, „Bring Your Own Key"):

| Quelle | `LLM_API_URL` | Kosten |
|---|---|---|
| **LM Studio / Ollama** (lokal) | `http://<ip>:1234/v1/chat/completions` | kostenlos, läuft lokal |
| **Groq Cloud** | `https://api.groq.com/openai/v1/chat/completions` | kostenloser API-Key (console.groq.com) |
| **OpenAI** | `https://api.openai.com/v1/chat/completions` | kostenpflichtig (eigener Key) |

Für Cloud-Anbieter zusätzlich `LLM_API_KEY=<dein-key>` setzen. Alle nutzen `LLM_PROVIDER=openai_compat`.

> **Tipp:** Das `install.sh`-Script führt diesen Schritt interaktiv durch — du wirst nach HA-URL, HA-Token, LLM (LM Studio / Groq / OpenAI) und TTS gefragt und die `.env` wird automatisch befüllt.

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
touch update.flag reboot.flag timezone.flag hostname.flag wlan.flag ha-install.flag components.flag printer-start.flag
[ -f wifi-scan.json ] || echo '{"networks":[]}' > wifi-scan.json
[ -f host-ip.txt ] || hostname -I | awk '{print $1}' > host-ip.txt
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

## Schritt 8 — Home Assistant als Container installieren (optional)

Dieser Schritt ist nur nötig wenn **kein eigenes HA** im Netzwerk vorhanden ist.
HA läuft dabei als normaler Docker-Container neben robot-core (kein Supervisor,
kein Add-on-Store — Home Assistant Supervised ist seit HA-Release 2025.12
offiziell deprecated). Add-ons wie z.B. `ring-mqtt` werden stattdessen als
eigene Container ergänzt, die sich mit demselben Mosquitto-Broker verbinden.
Wer den vollen Add-on-Store braucht, ist mit [Home Assistant OS](https://www.home-assistant.io/installation/)
auf eigener Hardware/VM weiterhin besser bedient.

### 8a — Verzeichnisse und Mosquitto-Konfiguration anlegen

```bash
cd ~/robot-core
mkdir -p ha_config mosquitto_config mosquitto_data mosquitto_log
cat > mosquitto_config/mosquitto.conf << 'EOF'
listener 1883
allow_anonymous true
persistence true
persistence_location /mosquitto/data/
log_dest file /mosquitto/log/mosquitto.log
EOF
```

### 8b — Container starten

```bash
docker compose --profile ha up -d homeassistant mosquitto
```

### 8c — HA einrichten und Token erstellen

1. Browser öffnen: `http://<IP>:8123`
2. HA-Onboarding abschließen (Konto anlegen, Standort, Zeitzone)
3. **Profil → Sicherheit → Langlebige Zugriffstoken → Token erstellen**
4. Token kopieren und im Erika Admin-Panel unter **System → Home Assistant** eintragen

Mosquitto läuft direkt mit auf Port 1883 (z.B. für die Anycubic-Druckerbrücke).

---

## Schritt 9 — Autostart bei Systemstart

Docker selbst startet automatisch mit dem System (`systemctl enable docker`).  
Der Container ist mit `restart: unless-stopped` konfiguriert und startet ebenfalls automatisch.

Watcher-Dienste für Updates und Reboot einrichten:

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

Reboot ohne sudo-Passwort erlauben (für den Update-Prozess):

```bash
echo "$USER ALL=(ALL) NOPASSWD: /sbin/reboot" | sudo tee /etc/sudoers.d/erika-reboot
sudo chmod 440 /etc/sudoers.d/erika-reboot
```

---

## Schritt 10 — Kiosk-Display einrichten (Raspberry Pi mit Bildschirm)

Dieser Schritt richtet Chromium als Vollbild-Kiosk für das Display-Panel ein.  
Kein Display-Manager nötig — TTY1-Autologin via systemd startet X und Chromium direkt.

### Pakete installieren

```bash
sudo apt-get install -y chromium-browser xinit openbox unclutter feh x11-xserver-utils xdotool
# Falls chromium-browser nicht verfügbar:
sudo apt-get install -y chromium
```

### TTY1-Autologin einrichten

```bash
# Autologin für TTY1 (kein Display-Manager nötig)
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf << 'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin DEIN_USER --noclear %I $TERM
EOF
sudo systemctl daemon-reload

# Bestehende Display-Manager deaktivieren
sudo systemctl disable lightdm gdm3 nodm 2>/dev/null || true
```

Ersetze `DEIN_USER` durch deinen Benutzernamen (z.B. `dennis`).

### startx beim Login automatisch starten

```bash
cat >> ~/.bash_profile << 'EOF'

if [[ -z "$DISPLAY" ]] && [[ "$(tty)" == "/dev/tty1" ]]; then
    exec startx ~/robot-core/kiosk-session.sh
fi
EOF
```

### Kamera, Mikrofon und Übersetzung per Policy konfigurieren

```bash
sudo mkdir -p /etc/chromium/policies/managed
sudo tee /etc/chromium/policies/managed/erika.json << 'EOF'
{
  "VideoCaptureAllowedUrls": ["https://localhost:8000/*"],
  "AudioCaptureAllowedUrls": ["https://localhost:8000/*"],
  "TranslateEnabled": false
}
EOF
```

### Openbox-Konfiguration (Tastenkürzel)

```bash
mkdir -p ~/.config/openbox
cat > ~/.config/openbox/erika-rc.xml << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_config xmlns="http://openbox.org/3.4/rc"
                xmlns:xi="http://www.w3.org/2001/XInclude">
  <keyboard>
    <keybind key="Super_L-h">
      <action name="Execute">
        <command>pkill -f chromium-browser; pkill -f "chromium --kiosk"</command>
      </action>
    </keybind>
    <keybind key="F2">
      <action name="Execute">
        <command>pkill -f chromium-browser; pkill -f "chromium --kiosk"</command>
      </action>
    </keybind>
  </keyboard>
</openbox_config>
EOF
```

**F2** oder **Super+H** (Windows-Taste+H) beendet Chromium — `kiosk-session.sh` startet es automatisch neu mit der Erika-URL.

### Wisch-Gesten für Touchscreen (optional)

```bash
sudo apt-get install -y libinput-tools python3-libevdev xdotool git
sudo gpasswd -a $USER input
git clone https://github.com/bulletmark/libinput-gestures.git /tmp/lig
cd /tmp/lig && sudo make install && cd ~

cat > ~/.config/libinput-gestures.conf << 'EOF'
gesture swipe right 3 sh -c "pkill -f 'chromium --kiosk' || pkill chromium"
gesture swipe left 3 xdotool key alt+Left
EOF
libinput-gestures-setup install
libinput-gestures-setup start
```

3-Finger-Wisch rechts → zurück zu Erika. Erfordert Neu-Login damit die `input`-Gruppe aktiv ist.

### Neustart

```bash
sudo reboot
```

Nach dem Neustart startet Erika ohne Login-Dialog direkt im Kiosk-Modus.

---

## Ergebnis

Nach erfolgreichem Start ist Erika erreichbar unter:

| URL | Funktion |
|---|---|
| `https://<IP>:8000/display` | Display-Panel (Kiosk-Modus) |
| `https://<IP>:8000/local-admin` | Admin-Panel |
| `https://erika.local:8000/` | Über mDNS (wenn avahi läuft) |
| `http://<IP>:8123` | Home Assistant (nur wenn Schritt 8 ausgeführt) |

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
→ Für ein vertrauenswürdiges Zertifikat: `cert.pem`/`key.pem` durch ein Let's-Encrypt-Zertifikat ersetzen.

**TTS funktioniert nicht**  
→ Bei Edge TTS: Internetzugang erforderlich.  
→ Bei Sherpa ONNX: Modelle lassen sich unter Admin-Panel → Sprachausgabe auswählen — Download und Aktivierung laufen dann automatisch, kein manueller Schritt mehr nötig. Für Modelle, die dort nicht gelistet sind, weiterhin manuell prüfen: Modellpfade in `.env` korrekt? Pfade müssen im Container unter `/models/tts/` erreichbar sein (Volume in `docker-compose.yml` prüfen).

**HA-Container startet nicht**  
→ `docker compose --profile ha logs homeassistant` prüfen. Häufigste Ursache: `network_mode: host` kollidiert mit einem bereits belegten Port (z.B. 8123 durch eine andere HA-Instanz im Netzwerk).

**Mosquitto nimmt keine Verbindungen an**  
→ `mosquitto_config/mosquitto.conf` muss vor dem ersten Start existieren (siehe Schritt 8a) — ohne eigene Config verweigert das offizielle Image anonyme Verbindungen.
