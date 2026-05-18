#!/bin/bash
set -e

# ── Erika Komplett-Installation ────────────────────────────
# Robot-Core (Backend) + Display-Kiosk auf einer Maschine
#
#   curl -fsSL https://raw.githubusercontent.com/dennis-debaIT/robot-core/main/install-complete.sh | bash
# ──────────────────────────────────────────────────────────

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

echo -e "${BOLD}"
echo "  ███████╗██████╗ ██╗██╗  ██╗ █████╗ "
echo "  ██╔════╝██╔══██╗██║██║ ██╔╝██╔══██╗"
echo "  █████╗  ██████╔╝██║█████╔╝ ███████║"
echo "  ██╔══╝  ██╔══██╗██║██╔═██╗ ██╔══██║"
echo "  ███████╗██║  ██║██║██║  ██╗██║  ██║"
echo "  ╚══════╝╚═╝  ╚═╝╚═╝╚═╝  ╚═╝╚═╝  ╚═╝"
echo -e "${NC}  Komplett-Installation (Robot-Core + Display-Kiosk)"
echo ""

# ══════════════════════════════════════════════════════════
# TEIL 1: ROBOT-CORE (Backend)
# ══════════════════════════════════════════════════════════

# ── 1. System-Pakete ──────────────────────────────────────
step "System aktualisieren"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    curl git ca-certificates gnupg lsb-release openssh-client openssl sqlite3 \
    avahi-daemon > /dev/null
sudo systemctl enable --now avahi-daemon > /dev/null 2>&1 || true
success "Pakete installiert (erreichbar als erika.local)"

# ── 2. Docker ─────────────────────────────────────────────
step "Docker installieren"
if command -v docker &>/dev/null; then
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

# ── 3. Repository klonen ──────────────────────────────────
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

# ── 4. SSL-Zertifikat ─────────────────────────────────────
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

# ── 5. .env erstellen ─────────────────────────────────────
step ".env Konfiguration"
if [ ! -f .env ]; then
    cat > .env << EOF
# Home Assistant (kann auch im Admin-Panel eingetragen werden)
ROBOT_HA_URL=
ROBOT_HA_TOKEN=

# LLM (optional)
LLM_API_URL=
LLM_PROVIDER=generic
LLM_MODEL=

# TTS
ROBOT_TTS_PROVIDER=disabled

# SSH-Verzeichnis (für git-Fetch im Container)
SSH_DIR=$HOME/.ssh
EOF
    success ".env angelegt"
else
    if ! grep -q "SSH_DIR" .env; then
        echo -e "\nSSH_DIR=$HOME/.ssh" >> .env
    fi
    success ".env bereits vorhanden — unverändert"
fi

# ── 6. Update-System einrichten ───────────────────────────
step "Update-System einrichten"
touch update.flag update.log
chmod +x update.sh

_CRON_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
CRON_DAILY="0 3 * * * $INSTALL_DIR/update.sh >> $INSTALL_DIR/update.log 2>&1"
CRON_FLAG="* * * * * grep -q requested_at $INSTALL_DIR/update.flag 2>/dev/null && echo '{}' > $INSTALL_DIR/update.flag && $INSTALL_DIR/update.sh >> $INSTALL_DIR/update.log 2>&1 || true"
_CRON_TMP=$(mktemp)
(echo "HOME=$HOME"; echo "PATH=$_CRON_PATH"; echo "$CRON_DAILY"; echo "$CRON_FLAG") > "$_CRON_TMP"
crontab - < "$_CRON_TMP"
rm -f "$_CRON_TMP"
success "Cron-Jobs eingerichtet"

# ── 7. Container bauen und starten ────────────────────────
step "Container bauen und starten"
info "Dies kann einige Minuten dauern..."
GIT_HASH=$(git rev-parse HEAD)
docker compose build --build-arg GIT_HASH="$GIT_HASH" robot-core
docker compose up -d robot-core
success "Container gestartet"

sudo systemctl enable docker > /dev/null 2>&1 || true

# ══════════════════════════════════════════════════════════
# TEIL 2: DISPLAY-KIOSK
# ══════════════════════════════════════════════════════════

KIOSK_URL="https://localhost:8000/display"
KIOSK_USER="$USER_NAME"
KIOSK_HOME="$HOME"

step "Display-Kiosk installieren"

# ── 8. X11 + Kiosk-Pakete ────────────────────────────────
info "Installiere X11 und Kiosk-Pakete..."
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    xserver-xorg xinit x11-xserver-utils \
    xserver-xorg-video-all xserver-xorg-input-all \
    openbox \
    unclutter \
    fonts-noto-color-emoji fonts-noto-core fonts-liberation \
    > /dev/null
success "X11-Pakete installiert"

# ── 9. VM-Grafiktreiber ───────────────────────────────────
VIRT="$(systemd-detect-virt 2>/dev/null || echo none)"
case "$VIRT" in
    oracle)
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            virtualbox-guest-x11 virtualbox-guest-utils > /dev/null 2>&1 \
            && success "VirtualBox-Treiber installiert" || true ;;
    vmware)
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            open-vm-tools-desktop > /dev/null 2>&1 \
            && success "VMware-Treiber installiert" || true ;;
    kvm|qemu)
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            spice-vdagent > /dev/null 2>&1 \
            && success "QEMU/KVM-Treiber installiert" || true ;;
    microsoft)
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            hyperv-daemons > /dev/null 2>&1 \
            && success "Hyper-V-Treiber installiert" || true ;;
esac

# Xorg: modesetting + kein Bildschirmschoner
sudo mkdir -p /etc/X11/xorg.conf.d
sudo tee /etc/X11/xorg.conf.d/10-display.conf > /dev/null << 'EOF'
Section "Device"
    Identifier "Default Device"
    Driver     "modesetting"
EndSection
Section "ServerFlags"
    Option "BlankTime"   "0"
    Option "StandbyTime" "0"
    Option "SuspendTime" "0"
    Option "OffTime"     "0"
EndSection
EOF

# ── 10. Google Chrome ─────────────────────────────────────
step "Browser installieren"
CHROME_BIN=""
if ! command -v google-chrome-stable &>/dev/null && ! command -v google-chrome &>/dev/null; then
    info "Lade Google Chrome..."
    if wget -q -O /tmp/chrome.deb \
        "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb"; then
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y /tmp/chrome.deb > /dev/null 2>&1 \
            || sudo apt-get install -f -y > /dev/null
        rm -f /tmp/chrome.deb
        success "Google Chrome installiert"
    else
        warn "Chrome nicht verfügbar — installiere Chromium"
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            chromium-browser > /dev/null 2>&1 || true
    fi
fi
CHROME_BIN="$(command -v google-chrome-stable 2>/dev/null \
           || command -v google-chrome 2>/dev/null \
           || command -v chromium-browser 2>/dev/null \
           || command -v chromium 2>/dev/null)"
[ -n "$CHROME_BIN" ] || error "Kein Browser gefunden."
success "Browser: $CHROME_BIN"

# ── 11. Openbox-Konfiguration ─────────────────────────────
step "Kiosk konfigurieren"
mkdir -p "$KIOSK_HOME/.config/openbox"

sudo tee /etc/X11/xorg.conf.d/20-resolution.conf > /dev/null << 'EOF'
Section "Screen"
    Identifier "Default Screen"
    DefaultDepth 24
    SubSection "Display"
        Depth 24
        Modes "1280x800"
    EndSubSection
EndSection
EOF

cat > "$KIOSK_HOME/.config/openbox/rc.xml" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_config xmlns="http://openbox.org/3.4/rc">
  <applications>
    <application class="*">
      <decor>no</decor>
      <maximized>yes</maximized>
    </application>
  </applications>
</openbox_config>
EOF

# Kiosk Start-Script
cat > "$KIOSK_HOME/start-kiosk.sh" << SCRIPT
#!/bin/bash

# Bildschirm: nie aus
xset s off
xset s noblank
xset -dpms

# Auflösung setzen
OUTPUT=\$(xrandr 2>/dev/null | grep " connected" | head -1 | awk '{print \$1}')
[ -n "\$OUTPUT" ] && xrandr --output "\$OUTPUT" --mode 1280x800 2>/dev/null || true

# Cursor ausblenden
unclutter -idle 0.1 -root &

# Warte bis robot-core bereit ist
for i in \$(seq 1 60); do
    curl -sk --max-time 2 "${KIOSK_URL}" &>/dev/null && break
    sleep 2
done

# Chrome im Kiosk-Modus – Neustart bei Absturz
while true; do
    "${CHROME_BIN}" \\
        --kiosk \\
        --noerrdialogs \\
        --disable-infobars \\
        --disable-session-crashed-bubble \\
        --no-first-run \\
        --no-default-browser-check \\
        --ignore-certificate-errors \\
        --disable-translate \\
        --disable-features=TranslateUI \\
        --disable-sync \\
        --disable-extensions \\
        --disable-background-networking \\
        --metrics-recording-only \\
        --disk-cache-dir=/tmp/chrome-cache \\
        --user-data-dir=/tmp/chrome-user \\
        "${KIOSK_URL}" 2>/dev/null
    sleep 3
done
SCRIPT
chmod +x "$KIOSK_HOME/start-kiosk.sh"

cat > "$KIOSK_HOME/.config/openbox/autostart" << EOF
$KIOSK_HOME/start-kiosk.sh &
EOF

cat > "$KIOSK_HOME/.xinitrc" << 'EOF'
exec openbox-session
EOF

# .bash_profile: startx automatisch auf TTY1
cat > "$KIOSK_HOME/.bash_profile" << 'EOF'
[[ -z $DISPLAY && $(tty) == /dev/tty1 ]] && exec startx -- -nocursor 2>/dev/null
EOF
success "Kiosk konfiguriert → $KIOSK_URL"

# ── 12. TTY1 Auto-Login ───────────────────────────────────
step "Auto-Login einrichten"
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf > /dev/null << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin ${USER_NAME} --noclear %I \$TERM
Type=simple
EOF
sudo systemctl daemon-reload
sudo systemctl enable getty@tty1
sudo systemctl disable lightdm 2>/dev/null || true
sudo mkdir -p /etc/systemd/logind.conf.d
sudo tee /etc/systemd/logind.conf.d/kiosk.conf > /dev/null << 'EOF'
[Login]
IdleAction=ignore
HandleLidSwitch=ignore
HandleSuspendKey=ignore
HandleHibernateKey=ignore
EOF
success "Auto-Login → $USER_NAME auf TTY1"

# ── 13. Plymouth Boot-Screen ──────────────────────────────
step "Erika Boot-Screen installieren"
if sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    plymouth plymouth-themes > /dev/null 2>&1; then

    THEME_DIR="/usr/share/plymouth/themes/erika"
    sudo mkdir -p "$THEME_DIR"

    sudo tee "$THEME_DIR/erika.plymouth" > /dev/null << 'EOF'
[Plymouth Theme]
Name=Erika
Description=Erika Boot Screen
ModuleName=script

[script]
ImageDir=/usr/share/plymouth/themes/erika
ScriptFile=/usr/share/plymouth/themes/erika/erika.script
EOF

    sudo tee "$THEME_DIR/erika.script" > /dev/null << 'EOF'
Window.SetBackgroundTopColor(0.02, 0.02, 0.07);
Window.SetBackgroundBottomColor(0.03, 0.03, 0.15);
sw = Window.GetWidth(); sh = Window.GetHeight();
title_img = Image.Text("ERIKA", 1.0, 1.0, 1.0, 1.0, "Sans Bold 54");
title_spr = Sprite(title_img);
title_spr.SetX(sw / 2 - title_img.GetWidth() / 2);
title_spr.SetY(sh / 2 - title_img.GetHeight() / 2 - 50);
sub_img = Image.Text("Wird gestartet …", 0.4, 0.7, 1.0, 1.0, "Sans 17");
sub_spr = Sprite(sub_img);
sub_spr.SetX(sw / 2 - sub_img.GetWidth() / 2);
sub_spr.SetY(sh / 2 + 20);
bar_w = 320; bar_h = 5; bar_x = sw / 2 - bar_w / 2; bar_y = sh / 2 + 72;
bg_img = Image(bar_w, bar_h); bg_img.Fill(0.08, 0.08, 0.20, 1.0);
bg_spr = Sprite(bg_img); bg_spr.SetX(bar_x); bg_spr.SetY(bar_y);
fun boot_progress_cb(duration, progress) {
    w = Math.Int(bar_w * progress); if (w < 3) { w = 3; }
    bar_img = Image(w, bar_h); bar_img.Fill(0.0, 0.78, 1.0, 1.0);
    bar_spr = Sprite(bar_img); bar_spr.SetX(bar_x); bar_spr.SetY(bar_y);
}
Plymouth.SetBootProgressFunction(boot_progress_cb);
EOF

    # Theme erzwingen
    sudo mkdir -p /etc/plymouth
    sudo tee /etc/plymouth/plymouthd.conf > /dev/null << 'EOF'
[Daemon]
Theme=erika
ShowDelay=0
EOF
    sudo update-alternatives --install \
        /usr/share/plymouth/themes/default.plymouth \
        default.plymouth "$THEME_DIR/erika.plymouth" 200 2>/dev/null || true
    sudo update-alternatives --set \
        default.plymouth "$THEME_DIR/erika.plymouth" 2>/dev/null || true
    sudo plymouth-set-default-theme erika 2>/dev/null || true

    # GRUB: quiet splash loglevel=3
    if [ -f /etc/default/grub ]; then
        sudo sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="quiet splash loglevel=3"/' /etc/default/grub
        grep -q "GRUB_CMDLINE_LINUX_DEFAULT" /etc/default/grub \
            || echo 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash loglevel=3"' | sudo tee -a /etc/default/grub
        grep -q "^GRUB_GFXMODE" /etc/default/grub \
            || echo 'GRUB_GFXMODE=1280x800' | sudo tee -a /etc/default/grub
        grep -q "^GRUB_GFXPAYLOAD" /etc/default/grub \
            || echo 'GRUB_GFXPAYLOAD_LINUX=keep' | sudo tee -a /etc/default/grub
        sudo update-grub > /dev/null 2>&1 || true
    fi

    # copymods-Warnung unterdrücken
    if [ -d /usr/lib/dracut/modules.d/50copymods ]; then
        sudo mkdir -p /etc/dracut.conf.d
        echo 'omit_dracutmodules+=" copymods"' | sudo tee /etc/dracut.conf.d/no-copymods.conf > /dev/null
        sudo dracut --force > /dev/null 2>&1 || true
    fi

    sudo update-initramfs -u -k all > /dev/null 2>&1 || true
    success "Boot-Screen 'Erika' aktiviert"
else
    warn "Plymouth nicht verfügbar — kein Boot-Screen"
fi

# ── Fertig ────────────────────────────────────────────────
IP=$(hostname -I | awk '{print $1}')
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  Erika ist einsatzbereit!${NC}"
echo ""
echo -e "  Web-Interface:   ${CYAN}https://${IP}:8000${NC}"
echo -e "  Admin-Panel:     ${CYAN}https://${IP}:8000/local-admin${NC}"
echo -e "  Display-Kiosk:   ${CYAN}https://localhost:8000/display${NC} (startet automatisch)"
echo -e "  Browser:         ${CYAN}${CHROME_BIN}${NC}"
echo -e "  VM-Typ:          ${CYAN}${VIRT}${NC}"
echo ""
echo -e "  ${YELLOW}Hinweis:${NC} Browser-Warnung beim SSL-Zertifikat ist normal."
echo ""
if ! groups "$USER_NAME" | grep -q docker; then
    warn "Bitte neu einloggen damit Docker ohne sudo funktioniert"
fi
echo -e "  ${YELLOW}Jetzt neu starten:${NC}  ${BOLD}sudo reboot${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
