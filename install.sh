#!/bin/bash
set -e

# ── Erika Robot-Core Installations-Script ─────────────────────
# Führe dieses Script auf einem frischen Debian 12 / Raspberry Pi OS System aus:
#   curl -fsSL https://raw.githubusercontent.com/dennis-debaIT/robot-core/main/install.sh | bash
# ─────────────────────────────────────────────────────────────

REPO="https://github.com/dennis-debaIT/robot-core.git"
INSTALL_DIR="$HOME/robot-core"
USER_NAME="${SUDO_USER:-$USER}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[erika]${NC} $1"; }
success() { echo -e "${GREEN}[✓]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }
error()   { echo -e "${RED}[✗]${NC} $1"; exit 1; }
step()    { echo -e "\n${BOLD}── $1 ──${NC}"; }

# Read a value from the terminal — works in curl|bash pipe mode
# Prompts go to /dev/tty (visible), result goes to stdout (captured by $(...))
_read() {
    local msg="$1" default="$2" val
    printf "    ${CYAN}›${NC} %s" "$msg" >/dev/tty
    [ -n "$default" ] && printf " [%s]" "$default" >/dev/tty
    printf ": " >/dev/tty
    IFS= read -r val </dev/tty
    [ -z "$val" ] && val="$default"
    echo "$val"
}

# Read a single menu choice from the terminal
_choose() {
    local val
    IFS= read -r val </dev/tty
    echo "$val"
}

# Detect the HA Supervised machine type from hardware
_detect_machine() {
    local arch machine
    arch=$(uname -m)
    if [ "$arch" = "aarch64" ]; then
        local model
        model=$(cat /proc/device-tree/model 2>/dev/null || echo "")
        if echo "$model" | grep -qi "raspberry pi 5"; then
            machine="raspberrypi5-64"
        elif echo "$model" | grep -qi "raspberry pi 4"; then
            machine="raspberrypi4-64"
        elif echo "$model" | grep -qi "raspberry pi 3"; then
            machine="raspberrypi3-64"
        else
            machine="generic-aarch64"
        fi
    else
        machine="generic-x86-64"
    fi
    echo "$machine"
}

# Install Home Assistant Supervised
_install_ha_supervised() {
    info "Installiere Home Assistant Supervised..."

    local machine
    machine=$(_detect_machine)
    info "Erkannte Maschine: $machine"

    # Dependencies
    sudo apt-get install -y \
        jq curl avahi-daemon apparmor network-manager udisks2 wget dbus > /dev/null

    # NetworkManager muss das Netzwerk verwalten (Konflikt mit dhcpcd vermeiden)
    sudo systemctl enable --now NetworkManager > /dev/null 2>&1 || true
    sudo systemctl disable --now dhcpcd > /dev/null 2>&1 || true

    # AppArmor in Boot-Konfiguration aktivieren
    if [ -f /boot/firmware/cmdline.txt ]; then
        # Raspberry Pi OS (Bookworm)
        if ! grep -q "apparmor=1" /boot/firmware/cmdline.txt; then
            sudo sed -i 's/$/ apparmor=1 security=apparmor/' /boot/firmware/cmdline.txt
            warn "AppArmor zur Boot-Konfiguration hinzugefügt"
        fi
    elif [ -f /boot/cmdline.txt ]; then
        if ! grep -q "apparmor=1" /boot/cmdline.txt; then
            sudo sed -i 's/$/ apparmor=1 security=apparmor/' /boot/cmdline.txt
            warn "AppArmor zur Boot-Konfiguration hinzugefügt"
        fi
    elif [ -f /etc/default/grub ]; then
        if ! grep -q "apparmor=1" /etc/default/grub; then
            sudo sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="/GRUB_CMDLINE_LINUX_DEFAULT="apparmor=1 security=apparmor /' /etc/default/grub
            sudo update-grub > /dev/null 2>&1 || true
            warn "AppArmor zur GRUB-Konfiguration hinzugefügt"
        fi
    fi

    # HA Supervised Installer herunterladen und ausführen
    wget -qO /tmp/ha-supervised.sh \
        https://raw.githubusercontent.com/home-assistant/supervised-installer/main/installer.sh
    chmod +x /tmp/ha-supervised.sh
    sudo bash /tmp/ha-supervised.sh --machine "$machine"
    rm -f /tmp/ha-supervised.sh

    success "Home Assistant Supervised installiert (Port 8123)"
    warn "Ein Neustart wird empfohlen damit AppArmor aktiv wird"
}

echo -e "${BOLD}"
echo "  ███████╗██████╗ ██╗██╗  ██╗ █████╗ "
echo "  ██╔════╝██╔══██╗██║██║ ██╔╝██╔══██╗"
echo "  █████╗  ██████╔╝██║█████╔╝ ███████║"
echo "  ██╔══╝  ██╔══██╗██║██╔═██╗ ██╔══██║"
echo "  ███████╗██║  ██║██║██║  ██╗██║  ██║"
echo "  ╚══════╝╚═╝  ╚═╝╚═╝╚═╝  ╚═╝╚═╝  ╚═╝"
echo -e "${NC}  Robot-Core Installations-Script\n"

# ── 1. System-Voraussetzungen ─────────────────────────────────
step "System aktualisieren"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    curl git ca-certificates gnupg lsb-release openssh-client openssl sqlite3 avahi-daemon > /dev/null
sudo systemctl enable --now avahi-daemon > /dev/null 2>&1 || true
success "Pakete installiert (erreichbar als erika.local)"

# ── 2. Docker ─────────────────────────────────────────────────
step "Docker installieren"
if command -v docker &> /dev/null; then
    success "Docker bereits vorhanden: $(docker --version)"
else
    info "Installiere Docker..."
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/$(. /etc/os-release && echo "$ID")/gpg \
        | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/$(. /etc/os-release && echo "$ID") \
        $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update -qq
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin > /dev/null
    sudo usermod -aG docker "$USER_NAME"
    success "Docker installiert"
fi
sudo systemctl enable --now docker > /dev/null 2>&1 || true

# ── 3. Repo klonen ────────────────────────────────────────────
step "Repository klonen"
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Repo bereits vorhanden — aktualisiere..."
    cd "$INSTALL_DIR" && git pull --ff-only origin main
    success "Repository aktualisiert"
else
    git clone "$REPO" "$INSTALL_DIR"
    success "Repository geklont nach $INSTALL_DIR"
fi
cd "$INSTALL_DIR"

# ── 4. Konfiguration ─────────────────────────────────────────
step "Konfiguration"

# Defaults
_ENV_HA_URL=""; _ENV_HA_TOKEN=""
_ENV_LLM_URL=""; _ENV_LLM_KEY=""; _ENV_LLM_PROVIDER="openai_compat"; _ENV_LLM_MODEL="qwen/qwen3-4b-2507"
_ENV_TTS_PROVIDER="disabled"; _ENV_TTS_VOICE=""
_HA_SUPERVISED=false
_DO_CONFIG=true

if [ -f .env ]; then
    echo -e "  ${YELLOW}Hinweis:${NC} Es existiert bereits eine .env-Datei."
    printf "    Neu konfigurieren? [j/N]: "
    _reconfigure=$(_choose)
    if [[ "$_reconfigure" =~ ^[jJyY]$ ]]; then
        _DO_CONFIG=true
    else
        success ".env unverändert übernommen"
        _DO_CONFIG=false
    fi
fi

if [ "$_DO_CONFIG" = true ]; then

    # ── Home Assistant ────────────────────────────────────────
    echo -e "\n  ${BOLD}Home Assistant${NC}"
    echo "    [1] Ich habe bereits eine HA-Instanz im Netzwerk  (URL + Token eingeben)"
    echo "    [2] HA Supervised hier installieren               (Debian 12 / Raspberry Pi OS)"
    echo "    [3] Später im Admin-Panel konfigurieren"
    printf "    ${CYAN}›${NC} Auswahl [1]: "
    _ha=$(_choose); [ -z "$_ha" ] && _ha=1

    case "$_ha" in
        2)
            _HA_SUPERVISED=true
            _ENV_HA_URL="http://localhost:8123"
            info "HA Supervised wird nach dem Basis-Setup installiert"
            info "Danach: http://localhost:8123 öffnen, Konto anlegen, Token erstellen"
            ;;
        3)
            info "HA kann jederzeit im Admin-Panel unter System → Home Assistant eingetragen werden"
            ;;
        *)
            _ENV_HA_URL=$(_read "HA-URL" "http://192.168.1.x:8123")
            _ENV_HA_TOKEN=$(_read "HA Long-Lived Token (leer = später eintragen)" "")
            ;;
    esac

    # ── LLM ───────────────────────────────────────────────────
    echo -e "\n  ${BOLD}LLM (Sprachmodell)${NC}"
    echo "    [1] LM Studio / Ollama — lokal (URL eingeben)"
    echo "    [2] OpenAI API (Key eingeben)"
    echo "    [3] Später konfigurieren"
    printf "    ${CYAN}›${NC} Auswahl [1]: "
    _llm=$(_choose); [ -z "$_llm" ] && _llm=1

    case "$_llm" in
        2)
            _ENV_LLM_URL="https://api.openai.com/v1/chat/completions"
            _ENV_LLM_KEY=$(_read "OpenAI API-Key" "")
            _ENV_LLM_MODEL=$(_read "Modellname" "gpt-4o-mini")
            _ENV_LLM_PROVIDER="openai_compat"
            ;;
        3)
            info "LLM kann jederzeit im Admin-Panel unter System → LLM konfiguriert werden"
            ;;
        *)
            _ENV_LLM_URL=$(_read "API-URL" "http://192.168.1.x:1234/v1/chat/completions")
            _ENV_LLM_MODEL=$(_read "Modellname" "qwen/qwen3-4b-2507")
            _ENV_LLM_PROVIDER="openai_compat"
            ;;
    esac

    # ── TTS ───────────────────────────────────────────────────
    echo -e "\n  ${BOLD}TTS (Sprachausgabe)${NC}"
    echo "    [1] Edge TTS — Microsoft, kostenlos, Internet nötig"
    echo "    [2] Sherpa ONNX — lokal & offline (Modell muss in models/tts/ liegen)"
    echo "    [3] Deaktiviert (später konfigurieren)"
    printf "    ${CYAN}›${NC} Auswahl [1]: "
    _tts=$(_choose); [ -z "$_tts" ] && _tts=1

    case "$_tts" in
        2)
            _ENV_TTS_PROVIDER="sherpa_onnx"
            _ENV_TTS_VOICE=$(_read "Stimmenlabel (Anzeigename im Admin)" "Kerstin")
            warn "Modell-Dateien müssen unter models/tts/ abgelegt werden — siehe INSTALL_MANUAL.md"
            ;;
        3)
            _ENV_TTS_PROVIDER="disabled"
            ;;
        *)
            _ENV_TTS_PROVIDER="edge_tts"
            _ENV_TTS_VOICE=$(_read "Stimme" "de-DE-KatjaNeural")
            ;;
    esac

    # ── .env schreiben ────────────────────────────────────────
    cat > .env << EOF
# Erika Robot Core — generiert von install.sh am $(date '+%Y-%m-%d %H:%M')
TZ=${TZ:-Europe/Berlin}
SSH_DIR=$HOME/.ssh

# LLM
LLM_API_URL=${_ENV_LLM_URL}
LLM_API_KEY=${_ENV_LLM_KEY}
LLM_PROVIDER=${_ENV_LLM_PROVIDER}
LLM_MODEL=${_ENV_LLM_MODEL}

# Home Assistant
ROBOT_HA_URL=${_ENV_HA_URL}
ROBOT_HA_TOKEN=${_ENV_HA_TOKEN}

# TTS
ROBOT_TTS_PROVIDER=${_ENV_TTS_PROVIDER}
ROBOT_TTS_VOICE_LABEL=${_ENV_TTS_VOICE}
ROBOT_TTS_VITS_MODEL=/models/tts/model.onnx
ROBOT_TTS_TOKENS=/models/tts/tokens.txt
ROBOT_TTS_DATA_DIR=/models/tts/espeak-ng-data
ROBOT_TTS_SPEED=1.0
ROBOT_TTS_SPEAKER_ID=0
ROBOT_TTS_NUM_THREADS=2
EOF
    success ".env geschrieben"

else
    # Bestehende .env: SSH_DIR ergänzen falls fehlend
    if ! grep -q "SSH_DIR" .env; then
        echo "" >> .env
        echo "SSH_DIR=$HOME/.ssh" >> .env
        success ".env: SSH_DIR ergänzt"
    fi
fi

# ── 5. SSL-Zertifikat ─────────────────────────────────────────
step "SSL-Zertifikat erstellen"
mkdir -p ssl
if [ ! -f ssl/cert.pem ]; then
    openssl req -x509 -newkey rsa:4096 \
        -keyout ssl/key.pem -out ssl/cert.pem \
        -days 3650 -nodes \
        -subj "/CN=erika.local" > /dev/null 2>&1
    success "Selbstsigniertes Zertifikat erstellt"
else
    success "Zertifikat bereits vorhanden"
fi

# ── 6. Update-Hilfsdateien ────────────────────────────────────
step "Update-System einrichten"
touch update.flag reboot.flag timezone.flag hostname.flag wlan.flag ha-install.flag components.flag printer-start.flag
[ -f wifi-scan.json ] || echo '{"networks":[]}' > wifi-scan.json
[ -f host-ip.txt ] || hostname -I | awk '{print $1}' > host-ip.txt
mkdir -p ha_config
chmod +x update.sh reboot-watcher.sh setup-watcher.sh
nohup bash "$INSTALL_DIR/reboot-watcher.sh" >> "$INSTALL_DIR/reboot.log" 2>&1 &
nohup bash "$INSTALL_DIR/setup-watcher.sh" >> "$INSTALL_DIR/setup-watcher.log" 2>&1 &
echo "$USER_NAME ALL=(ALL) NOPASSWD: /sbin/reboot" | sudo tee /etc/sudoers.d/erika-reboot > /dev/null
sudo chmod 440 /etc/sudoers.d/erika-reboot

_CRON_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
CRON_DAILY="0 3 * * * bash $INSTALL_DIR/update.sh >> $INSTALL_DIR/update.log 2>&1"
CRON_FLAG="* * * * * grep -q requested_at $INSTALL_DIR/update.flag 2>/dev/null && echo '{}' > $INSTALL_DIR/update.flag && bash $INSTALL_DIR/update.sh >> $INSTALL_DIR/update.log 2>&1 || true"
CRON_REBOOT="@reboot bash $INSTALL_DIR/reboot-watcher.sh >> $INSTALL_DIR/reboot.log 2>&1 &"
CRON_SETUP="@reboot bash $INSTALL_DIR/setup-watcher.sh >> $INSTALL_DIR/setup-watcher.log 2>&1 &"

_CRON_TMP=$(mktemp)
(echo "HOME=$HOME"; \
 echo "PATH=$_CRON_PATH"; \
 echo "$CRON_DAILY"; \
 echo "$CRON_FLAG"; \
 echo "$CRON_REBOOT"; \
 echo "$CRON_SETUP") > "$_CRON_TMP"
crontab - < "$_CRON_TMP"
rm -f "$_CRON_TMP"
success "Cron-Jobs eingerichtet (täglich 03:00 + Install-Trigger + Watcher)"

# ── 7. Container bauen und starten ───────────────────────────
step "Container bauen und starten"
info "Dies kann einige Minuten dauern..."

# Docker-Gruppe ist in der aktuellen Session noch nicht aktiv wenn der Nutzer
# gerade erst hinzugefügt wurde — in diesem Fall sudo verwenden
DOCKER="docker"
if ! docker ps > /dev/null 2>&1; then
    DOCKER="sudo docker"
    warn "Docker-Gruppe noch nicht aktiv — verwende sudo (nach Neuanmeldung nicht mehr nötig)"
fi

GIT_HASH=$(git rev-parse HEAD)
$DOCKER compose build --build-arg GIT_HASH="$GIT_HASH" robot-core
$DOCKER compose up -d robot-core
success "Container gestartet"

# ── 8. Autostart sicherstellen ────────────────────────────────
sudo systemctl enable docker > /dev/null 2>&1 || true

# ── 9. Home Assistant Supervised (falls gewählt) ──────────────
if [ "$_HA_SUPERVISED" = true ]; then
    step "Home Assistant Supervised installieren"
    _install_ha_supervised
fi

# Docker-Gruppen-Hinweis am Ende der Session mitgeben
if [ "$DOCKER" = "sudo docker" ]; then
    warn "Neu einloggen damit Docker ohne sudo nutzbar ist"
fi

# ── 10. Kiosk-Display (Chromium) ─────────────────────────────
step "Kiosk-Display einrichten"
CHROMIUM_BIN=""
if command -v chromium-browser &>/dev/null; then
    CHROMIUM_BIN="chromium-browser"
elif command -v chromium &>/dev/null; then
    CHROMIUM_BIN="chromium"
else
    info "Installiere Chromium..."
    if sudo apt-get install -y chromium-browser > /dev/null 2>&1; then
        CHROMIUM_BIN="chromium-browser"
    elif sudo apt-get install -y chromium > /dev/null 2>&1; then
        CHROMIUM_BIN="chromium"
    fi
fi

if [ -n "$CHROMIUM_BIN" ]; then
    sudo mkdir -p /etc/chromium/policies/managed
    sudo tee /etc/chromium/policies/managed/erika.json > /dev/null << 'POLICY'
{
  "VideoCaptureAllowedUrls": ["https://localhost:8000/*"],
  "AudioCaptureAllowedUrls": ["https://localhost:8000/*"]
}
POLICY

    mkdir -p "$HOME/.config/autostart"
    cat > "$HOME/.config/autostart/erika-kiosk.desktop" << DESKTOP
[Desktop Entry]
Type=Application
Name=Erika Kiosk
Exec=/bin/bash -c "sleep 8 && ${CHROMIUM_BIN} --kiosk --noerrdialogs --disable-infobars --autoplay-policy=no-user-gesture-required --ignore-certificate-errors https://localhost:8000/display"
X-GNOME-Autostart-enabled=true
DESKTOP

    success "Kiosk eingerichtet (${CHROMIUM_BIN}, Kamera + Mikrofon vorab freigegeben)"
else
    warn "Chromium nicht gefunden — Kiosk-Setup übersprungen. Siehe INSTALL_MANUAL.md Schritt 10."
fi

# ── Fertig ────────────────────────────────────────────────────
IP=$(hostname -I | awk '{print $1}')
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  Erika ist einsatzbereit!${NC}"
echo ""
echo -e "  Display-Panel:   ${CYAN}https://${IP}:8000/display${NC}"
echo -e "  Admin-Panel:     ${CYAN}https://${IP}:8000/local-admin${NC}"
if [ "$_HA_SUPERVISED" = true ]; then
    echo -e "  Home Assistant:  ${CYAN}http://${IP}:8123${NC}"
fi
echo ""
echo -e "  ${YELLOW}Hinweis:${NC} Browser-Warnung beim SSL-Zertifikat ist normal"
echo -e "           (selbstsigniert). Einfach bestätigen."
echo ""
if [ "$_HA_SUPERVISED" = true ]; then
    echo -e "  ${YELLOW}Nächste Schritte für Home Assistant:${NC}"
    echo -e "    1. http://${IP}:8123 öffnen und Konto anlegen"
    echo -e "    2. Profil → Sicherheit → Token erstellen"
    echo -e "    3. Token im Erika Admin-Panel unter System → Home Assistant eintragen"
    echo -e "    4. System neu starten (AppArmor aktivieren): sudo reboot"
elif [ -z "$_ENV_HA_TOKEN" ] && [ -z "$(grep ROBOT_HA_TOKEN .env | cut -d= -f2)" ]; then
    echo -e "  ${YELLOW}Noch offen:${NC} HA-Token im Admin-Panel unter System → Home Assistant eintragen"
fi
if [ -z "$_ENV_LLM_URL" ]; then
    echo -e "  ${YELLOW}Noch offen:${NC} LLM im Admin-Panel unter System → LLM konfigurieren"
fi
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
if ! groups "$USER_NAME" | grep -q docker; then
    warn "Bitte neu einloggen damit Docker ohne sudo funktioniert"
fi
