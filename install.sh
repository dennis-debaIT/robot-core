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
# Neue Methode (2024+): OS-Agent .deb + homeassistant-supervised .deb
# Kein installer.sh mehr — https://github.com/home-assistant/supervised-installer
_install_ha_supervised() {
    info "Installiere Home Assistant Supervised..."

    local machine arch
    machine=$(_detect_machine)
    arch=$(uname -m)
    info "Erkannte Maschine: $machine | Architektur: $arch"

    # Abhängigkeiten
    # udisks2 + dbus: Pflicht für HA Supervised
    # apparmor-utils: aa-status wird vom HA-Paket geprüft
    # jq: für OS-Agent Versions-Lookup
    # nfs-common: liefert nfs-utils.service — das HA-Postinstall-Script startet
    #             diesen Dienst; ohne das Paket schlägt systemctl start mit Exit 4 fehl
    # systemd-journal-remote: liefert systemd-journal-gatewayd.socket (HA-Abhängigkeit)
    sudo apt-get install -y \
        curl wget jq udisks2 dbus \
        apparmor apparmor-utils \
        network-manager avahi-daemon \
        nfs-common systemd-journal-remote > /dev/null

    # NetworkManager muss das Netzwerk verwalten
    # Raspberry Pi OS nutzt dhcpcd — muss deaktiviert werden
    sudo systemctl enable --now NetworkManager > /dev/null 2>&1 || true
    if systemctl is-active --quiet dhcpcd 2>/dev/null; then
        warn "Wechsel von dhcpcd auf NetworkManager — kurzer Netzwerk-Unterbruch möglich"
        sudo systemctl disable --now dhcpcd > /dev/null 2>&1 || true
        sleep 4
    fi

    # AppArmor sofort im laufenden Kernel aktivieren (kein Reboot nötig)
    sudo modprobe apparmor > /dev/null 2>&1 || true
    sudo systemctl enable --now apparmor > /dev/null 2>&1 || true

    # AppArmor dauerhaft in Boot-Konfiguration eintragen
    # Raspberry Pi OS (Bookworm): /boot/firmware/cmdline.txt
    # Ältere Pi-Systeme:          /boot/cmdline.txt
    # Debian 12/13 x86 / VM:      /etc/default/grub
    if [ -f /boot/firmware/cmdline.txt ]; then
        grep -q "apparmor=1" /boot/firmware/cmdline.txt || \
            sudo sed -i 's/$/ apparmor=1 security=apparmor/' /boot/firmware/cmdline.txt
    elif [ -f /boot/cmdline.txt ]; then
        grep -q "apparmor=1" /boot/cmdline.txt || \
            sudo sed -i 's/$/ apparmor=1 security=apparmor/' /boot/cmdline.txt
    elif [ -f /etc/default/grub ]; then
        if ! grep -q "apparmor=1" /etc/default/grub; then
            sudo sed -i '/^GRUB_CMDLINE_LINUX_DEFAULT=/ s/"$/ apparmor=1 security=apparmor"/' /etc/default/grub
            sudo update-grub > /dev/null 2>&1 || true
            warn "AppArmor zu GRUB hinzugefügt (dauerhaft ab nächstem Neustart)"
        fi
    fi

    # ── OS-Agent installieren (Voraussetzung für HA Supervised) ──
    info "Installiere OS-Agent..."
    local os_agent_ver
    os_agent_ver=$(curl -fsSL \
        https://api.github.com/repos/home-assistant/os-agent/releases/latest \
        | jq -r '.tag_name' | tr -d 'v')

    if [ -z "$os_agent_ver" ]; then
        warn "OS-Agent Version nicht ermittelbar — überspringe"
    else
        wget -O /tmp/os-agent.deb \
            "https://github.com/home-assistant/os-agent/releases/download/${os_agent_ver}/os-agent_${os_agent_ver}_linux_${arch}.deb"
        sudo dpkg -i /tmp/os-agent.deb > /dev/null
        rm -f /tmp/os-agent.deb
        success "OS-Agent ${os_agent_ver} installiert"
    fi

    # ── Home Assistant Supervised .deb installieren ───────────────
    info "Lade homeassistant-supervised.deb herunter..."
    wget -O /tmp/homeassistant-supervised.deb \
        "https://github.com/home-assistant/supervised-installer/releases/latest/download/homeassistant-supervised.deb"

    # Maschinentyp per debconf vorbelegen — verhindert Exit-Code 4 im Postinstall-Script
    # (das Paket fragt den Maschinentyp interaktiv per debconf; bei -y scheitert das)
    echo "homeassistant-supervised homeassistant-supervised/machine-type select $machine" \
        | sudo debconf-set-selections

    set +e
    sudo apt-get install -y /tmp/homeassistant-supervised.deb
    _HA_EXIT=$?
    set -e
    rm -f /tmp/homeassistant-supervised.deb

    if [ "$_HA_EXIT" -eq 0 ]; then
        success "Home Assistant Supervised installiert"
        info "HA startet im Hintergrund — erreichbar unter http://$(hostname -I | awk '{print $1}'):8123"
        info "Beim ersten Start kann HA 5–10 Minuten zum Initialisieren benötigen"
    else
        warn "Installation mit Fehlercode $_HA_EXIT beendet — Log prüfen:"
        warn "  journalctl -u hassio-supervisor -n 50"
    fi
    warn "Neustart empfohlen damit AppArmor dauerhaft aktiv ist (sudo reboot)"
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

# HA Supervised wird immer separat gefragt — unabhängig von der .env
# (wird bei Re-Runs nur übersprungen wenn Supervisor bereits läuft)
_HA_ALREADY_INSTALLED=false
if systemctl is-active --quiet hassio-supervisor 2>/dev/null || \
   sudo docker ps 2>/dev/null | grep -q "homeassistant/home-assistant"; then
    _HA_ALREADY_INSTALLED=true
fi

echo -e "\n  ${BOLD}Home Assistant${NC}"
if [ "$_HA_ALREADY_INSTALLED" = true ]; then
    success "Home Assistant Supervised läuft bereits — wird übersprungen"
else
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
fi

if [ -f .env ]; then
    echo -e "\n  ${YELLOW}Hinweis:${NC} Es existiert bereits eine .env-Datei."
    printf "    LLM und TTS neu konfigurieren? [j/N]: "
    _reconfigure=$(_choose)
    if [[ "$_reconfigure" =~ ^[jJyY]$ ]]; then
        _DO_CONFIG=true
    else
        success ".env unverändert übernommen"
        _DO_CONFIG=false
    fi
fi

if [ "$_DO_CONFIG" = true ]; then

    # ── LLM ───────────────────────────────────────────────────
    echo -e "\n  ${BOLD}LLM (Sprachmodell)${NC}"
    echo "    [1] LM Studio / Ollama — lokal (URL eingeben)"
    echo "    [2] Groq Cloud — kostenlos, schnell (API-Key von console.groq.com)"
    echo "    [3] OpenAI API (Key eingeben)"
    echo "    [4] Später im Admin-Panel konfigurieren"
    printf "    ${CYAN}›${NC} Auswahl [1]: "
    _llm=$(_choose); [ -z "$_llm" ] && _llm=1

    case "$_llm" in
        2)
            _ENV_LLM_URL="https://api.groq.com/openai/v1/chat/completions"
            _ENV_LLM_KEY=$(_read "Groq API-Key (console.groq.com)" "")
            _ENV_LLM_MODEL=$(_read "Modellname" "llama-3.3-70b-versatile")
            _ENV_LLM_PROVIDER="openai_compat"
            ;;
        3)
            _ENV_LLM_URL="https://api.openai.com/v1/chat/completions"
            _ENV_LLM_KEY=$(_read "OpenAI API-Key" "")
            _ENV_LLM_MODEL=$(_read "Modellname" "gpt-4o-mini")
            _ENV_LLM_PROVIDER="openai_compat"
            ;;
        4)
            info "LLM kann jederzeit im Admin-Panel unter KI / LLM konfiguriert werden"
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
    # HA-URL/Token aus bestehender .env übernehmen wenn nicht neu gesetzt
    _WRITE_HA_URL="${_ENV_HA_URL}"
    _WRITE_HA_TOKEN="${_ENV_HA_TOKEN}"
    if [ -f .env ] && [ -z "$_WRITE_HA_URL" ]; then
        _WRITE_HA_URL=$(grep "^ROBOT_HA_URL=" .env | cut -d= -f2- || echo "")
        _WRITE_HA_TOKEN=$(grep "^ROBOT_HA_TOKEN=" .env | cut -d= -f2- || echo "")
    fi

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
ROBOT_HA_URL=${_WRITE_HA_URL}
ROBOT_HA_TOKEN=${_WRITE_HA_TOKEN}

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
# Log-Dateien dürfen keine Verzeichnisse sein (kann bei git pull passieren)
for _log in update.log reboot.log setup-watcher.log; do
    [ -d "$_log" ] && rm -rf "$_log"
    touch "$_log"
done
touch update.flag reboot.flag timezone.flag hostname.flag wlan.flag ha-install.flag components.flag printer-start.flag
[ -f wifi-scan.json ] || echo '{"networks":[]}' > wifi-scan.json
[ -f host-ip.txt ] || hostname -I | awk '{print $1}' > host-ip.txt
# Edition-Markierung (Default plus) — wird vom Admin-Schalter / Lizenz-Check überschrieben
[ -f edition ] && [ ! -d edition ] || { rm -rf edition 2>/dev/null; echo plus > edition; }
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

# ── 10. Boot-Splash ──────────────────────────────────────────
step "Boot-Splash einrichten"

# Plymouth installieren
sudo apt-get install -y plymouth plymouth-themes > /dev/null

# Splash-Bild: eigenes aus assets/ verwenden, sonst mit ImageMagick generieren
SPLASH_DIR="/usr/share/plymouth/themes/erika"
sudo mkdir -p "$SPLASH_DIR"

if [ -f "$INSTALL_DIR/assets/splash.png" ]; then
    sudo cp "$INSTALL_DIR/assets/splash.png" "$SPLASH_DIR/logo.png"
    info "Eigenes Splash-Bild aus assets/splash.png verwendet"
else
    sudo apt-get install -y imagemagick > /dev/null 2>&1 || true
    if command -v convert &>/dev/null; then
        sudo convert -size 1920x1080 xc:'#0d0d1a' \
            -font DejaVu-Sans-Bold -pointsize 200 \
            -fill '#4fc3f7' -gravity center \
            -annotate 0 'ERIKA' \
            "$SPLASH_DIR/logo.png" 2>/dev/null
        info "Splash-Bild generiert (assets/splash.png im Repo überschreibt es)"
    fi
fi

# Plymouth-Theme anlegen
sudo tee "$SPLASH_DIR/erika.plymouth" > /dev/null << 'EOF'
[Plymouth Theme]
Name=Erika
Description=Erika Robot Core
ModuleName=script

[script]
ImageDir=/usr/share/plymouth/themes/erika
ScriptFile=/usr/share/plymouth/themes/erika/erika.script
EOF

sudo tee "$SPLASH_DIR/erika.script" > /dev/null << 'EOF'
screen_width  = Window.GetWidth();
screen_height = Window.GetHeight();

bg = Rectangle();
bg.SetColor(0.05, 0.05, 0.1, 1);
bg.SetX(0); bg.SetY(0);
bg.SetWidth(screen_width); bg.SetHeight(screen_height);

logo = Image("logo.png");
s    = Sprite(logo);
s.SetX(Math.Int(screen_width  / 2 - logo.GetWidth()  / 2));
s.SetY(Math.Int(screen_height / 2 - logo.GetHeight() / 2));
EOF

sudo plymouth-set-default-theme -R erika > /dev/null 2>&1

# Hyper-V: Grafiktreiber früh ins Initramfs einbinden damit Plymouth den
# Framebuffer findet — ohne das bleibt der Splash-Screen schwarz
if grep -qi "microsoft\|hyper-v" /sys/class/dmi/id/sys_vendor 2>/dev/null || \
   grep -qi "microsoft\|hypervisor" /proc/cpuinfo 2>/dev/null; then
    info "Hyper-V erkannt — hyperv_drm ins Initramfs einbinden"
    grep -q "hyperv_drm" /etc/initramfs-tools/modules 2>/dev/null || \
        echo "hyperv_drm" | sudo tee -a /etc/initramfs-tools/modules > /dev/null
fi

sudo update-initramfs -u > /dev/null 2>&1
success "Plymouth Splash eingerichtet"

# Boot-Parameter: quiet splash (Pi und x86)
if [ -f /boot/firmware/cmdline.txt ]; then
    if ! grep -q "quiet" /boot/firmware/cmdline.txt; then
        sudo sed -i 's/$/ quiet splash plymouth.ignore-serial-consoles/' /boot/firmware/cmdline.txt
    fi
elif [ -f /boot/cmdline.txt ]; then
    if ! grep -q "quiet" /boot/cmdline.txt; then
        sudo sed -i 's/$/ quiet splash plymouth.ignore-serial-consoles/' /boot/cmdline.txt
    fi
elif [ -f /etc/default/grub ]; then
    sudo sed -i 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=0/'                   /etc/default/grub
    sudo sed -i 's/^GRUB_TIMEOUT_STYLE=.*/GRUB_TIMEOUT_STYLE=hidden/'  /etc/default/grub
    # quiet und splash unabhängig voneinander eintragen falls fehlend
    sudo sed -i '/^GRUB_CMDLINE_LINUX_DEFAULT=/ { /quiet/! s/"$/ quiet"/ }' /etc/default/grub
    sudo sed -i '/^GRUB_CMDLINE_LINUX_DEFAULT=/ { /splash/! s/"$/ splash"/ }' /etc/default/grub
    sudo update-grub > /dev/null 2>&1
fi
success "Boot-Parameter gesetzt (quiet splash, kein GRUB-Menü)"

# ── 11. Kiosk-Display (Chromium) ─────────────────────────────
step "Kiosk-Display einrichten"

# Kein Display-Manager — TTY1-Autologin via systemd + startx
# Zuverlässiger als LightDM/gdm3 auf Debian 12/13 für Kiosk-Setups
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf > /dev/null << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin ${USER_NAME} --noclear %I \$TERM
EOF
sudo systemctl daemon-reload
sudo systemctl disable lightdm > /dev/null 2>&1 || true
sudo systemctl disable gdm3   > /dev/null 2>&1 || true
sudo systemctl disable nodm   > /dev/null 2>&1 || true

# startx beim tty1-Login automatisch ausführen
BASH_PROFILE="$HOME/.bash_profile"
if ! grep -q "startx.*kiosk-session" "$BASH_PROFILE" 2>/dev/null; then
    cat >> "$BASH_PROFILE" << 'BASHEOF'

if [[ -z "$DISPLAY" ]] && [[ "$(tty)" == "/dev/tty1" ]]; then
    exec startx ~/robot-core/kiosk-session.sh
fi
BASHEOF
fi

# xinit installieren falls fehlend
sudo apt-get install -y xinit > /dev/null 2>&1 || true

# Chromium installieren falls fehlend
if ! command -v chromium-browser &>/dev/null && ! command -v chromium &>/dev/null; then
    info "Installiere Chromium..."
    sudo apt-get install -y chromium-browser > /dev/null 2>&1 || \
    sudo apt-get install -y chromium > /dev/null 2>&1 || true
fi

# Minimaler WM + Cursor-Hider + Bild-Anzeige + curl für Health-Check
sudo apt-get install -y openbox unclutter feh x11-xserver-utils curl > /dev/null 2>&1 || true

# libinput-gestures: Wisch-Gesten für Touchscreen (3-Finger-Wisch → Erika)
# touchegg ist in Debian 12/13 nicht mehr verfügbar
sudo apt-get install -y libinput-tools python3-libevdev wmctrl xdotool git > /dev/null 2>&1 || true
sudo gpasswd -a "$USER_NAME" input > /dev/null 2>&1 || true
if ! command -v libinput-gestures &>/dev/null; then
    info "Installiere libinput-gestures..."
    git clone --quiet https://github.com/bulletmark/libinput-gestures.git /tmp/lig 2>/dev/null
    if [ -d /tmp/lig ]; then
        cd /tmp/lig && sudo make install > /dev/null 2>&1
        cd "$INSTALL_DIR"
        rm -rf /tmp/lig
    fi
fi
if command -v libinput-gestures &>/dev/null; then
    mkdir -p "$HOME/.config/libinput-gestures"
    cat > "$HOME/.config/libinput-gestures.conf" << 'LIGCONF'
# 3-Finger-Wisch rechts: Chromium killen → Loop startet Erika-URL neu
gesture swipe right 3 sh -c "pkill -f 'chromium --kiosk' || pkill chromium"
# 3-Finger-Wisch links: Browser zurück
gesture swipe left 3 xdotool key alt+Left
LIGCONF
    libinput-gestures-setup install > /dev/null 2>&1 || true
    libinput-gestures-setup start  > /dev/null 2>&1 || true
    success "libinput-gestures konfiguriert (3-Finger-Wisch rechts → Erika)"
else
    warn "libinput-gestures nicht installierbar — Wisch-Gesten nicht verfügbar (F2 als Alternative)"
fi

# Chromium Policy: Kamera/Mikrofon freigeben, Übersetzungs-Popup deaktivieren
sudo mkdir -p /etc/chromium/policies/managed
sudo tee /etc/chromium/policies/managed/erika.json > /dev/null << 'POLICY'
{
  "VideoCaptureAllowedUrls": ["https://localhost:8000/*"],
  "AudioCaptureAllowedUrls": ["https://localhost:8000/*"],
  "TranslateEnabled": false
}
POLICY

# Openbox-Konfiguration: F2 / Super+H bringt Chromium zurück zu Erika
# (pkill chromium → Loop in kiosk-session.sh startet es neu)
mkdir -p "$HOME/.config/openbox"
cat > "$HOME/.config/openbox/erika-rc.xml" << 'OBCONF'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_config xmlns="http://openbox.org/3.4/rc"
                xmlns:xi="http://www.w3.org/2001/XInclude">
  <keyboard>
    <!-- Super+H (Windows-Taste+H): Chromium neu starten → landet auf Erika -->
    <!-- Alt+Home funktioniert direkt in Chromium (navigiert zur Homepage)  -->
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
OBCONF

# Kiosk-Session-Script ausführbar machen
chmod +x "$INSTALL_DIR/kiosk-session.sh"

# Alten LXDE-Autostart entfernen (nicht mehr nötig)
rm -f "$HOME/.config/autostart/erika-kiosk.desktop"

success "Kiosk eingerichtet (TTY1-Autologin + openbox + Chromium)"

# ── Fertig ────────────────────────────────────────────────────
IP=$(hostname -I | awk '{print $1}')
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e ""
echo -e "  ${BOLD}${GREEN}✓  Erika wurde erfolgreich installiert!${NC}"
echo -e ""
echo -e "  Öffne jetzt das ${BOLD}Admin-Panel${NC} im Browser, um die Einrichtung"
echo -e "  abzuschließen. Dort siehst du direkt was noch fehlt:"
echo -e ""
echo -e "  ${BOLD}${CYAN}  https://${IP}:8000/local-admin${NC}"
echo -e ""
if [ "$_HA_SUPERVISED" = true ]; then
echo -e "  ${BOLD}${CYAN}  http://${IP}:8123${NC}  ← Home Assistant (noch nicht fertig)"
echo -e ""
fi
echo -e "  ${BOLD}Hinweis zum SSL-Zertifikat:${NC} Der Browser zeigt eine Warnung —"
echo -e "  das ist normal (selbstsigniert). Einfach auf 'Weiter' klicken."
echo -e ""
if [ "$_HA_SUPERVISED" = true ]; then
echo -e "  ${YELLOW}──  Home Assistant einrichten  ──────────────────────────────────${NC}"
echo -e "  1. ${CYAN}http://${IP}:8123${NC} öffnen → Konto anlegen"
echo -e "  2. Profil → Sicherheit → Langlebiger Token erstellen"
echo -e "  3. Token im Admin-Panel unter ${BOLD}System → Home Assistant${NC} eintragen"
echo -e "  4. ${BOLD}sudo reboot${NC}  (AppArmor dauerhaft aktivieren)"
echo -e ""
fi
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
if ! groups "$USER_NAME" | grep -q docker; then
    warn "Neu einloggen damit Docker ohne sudo genutzt werden kann:  su - $USER_NAME"
fi
