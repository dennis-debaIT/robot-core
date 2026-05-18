#!/bin/bash
set -e

# ── Erika Display Kiosk Installations-Script ───────────────
# Für frisches Ubuntu 22.04 / 24.04 LTS
#
# Schnellstart:
#   curl -fsSL https://raw.githubusercontent.com/dennis-debaIT/robot-core/main/install-display.sh | sudo bash
#
# Mit eigener Erika-IP:
#   sudo ERIKA_URL="https://192.168.1.10:8000/display" bash install-display.sh
# ──────────────────────────────────────────────────────────

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
echo -e "${NC}  Display Kiosk Installations-Script"
echo ""

# Root-Check
[ "$EUID" -eq 0 ] || error "Bitte mit sudo ausführen: sudo bash install-display.sh"

# URL ermitteln: Env-Variable > erika.local (mDNS) > manuelle Eingabe
if [ -z "$ERIKA_URL" ]; then
    # Versuche erika.local automatisch zu erreichen
    DEFAULT_URL=""
    if curl -sk --max-time 3 "https://erika.local:8000/health" &>/dev/null; then
        DEFAULT_URL="https://erika.local:8000/display"
        info "Erika gefunden unter erika.local"
    fi

    if [ -n "$DEFAULT_URL" ]; then
        echo -n "  Erika-Adresse [${DEFAULT_URL}]: "
    else
        echo -n "  Erika-Adresse (z.B. https://192.168.1.10:8000/display): "
    fi
    read -r ERIKA_URL
    ERIKA_URL="${ERIKA_URL:-$DEFAULT_URL}"
    [ -n "$ERIKA_URL" ] || error "Keine Erika-Adresse angegeben."
fi

KIOSK_USER="erika-display"
KIOSK_HOME="/home/$KIOSK_USER"

echo ""
echo -e "  Ziel: ${CYAN}${ERIKA_URL}${NC}"
echo ""

# ── 1. System-Pakete ──────────────────────────────────────
step "System-Pakete installieren"
apt-get update -qq
apt-get install -y --no-install-recommends \
    curl wget gnupg2 ca-certificates \
    xorg x11-xserver-utils \
    openbox \
    lightdm \
    plymouth plymouth-themes \
    unclutter \
    > /dev/null
success "Basis-Pakete installiert"

# ── 2. Google Chrome ──────────────────────────────────────
step "Browser installieren"
CHROME_BIN=""

# 2a. Google Chrome (bevorzugt — echter deb, kein snap)
if ! command -v google-chrome-stable &>/dev/null && ! command -v google-chrome &>/dev/null; then
    info "Lade Google Chrome herunter…"
    if wget -q --show-progress -O /tmp/chrome.deb \
        "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb"; then
        apt-get install -y /tmp/chrome.deb > /dev/null 2>&1 || apt-get install -f -y > /dev/null
        rm -f /tmp/chrome.deb
        success "Google Chrome installiert"
    else
        warn "Chrome-Download fehlgeschlagen — versuche Chromium…"
    fi
fi

# 2b. Chromium als Fallback
if ! command -v google-chrome-stable &>/dev/null && ! command -v google-chrome &>/dev/null; then
    apt-get install -y --no-install-recommends chromium-browser 2>/dev/null \
        || snap install chromium 2>/dev/null \
        || error "Kein Browser installierbar. Netzwerk prüfen."
    success "Chromium installiert"
fi

# Browser-Binary ermitteln
CHROME_BIN="$(command -v google-chrome-stable 2>/dev/null \
           || command -v google-chrome 2>/dev/null \
           || command -v chromium-browser 2>/dev/null \
           || command -v chromium 2>/dev/null)"
[ -n "$CHROME_BIN" ] || error "Browser-Binary nicht gefunden."
success "Browser: $CHROME_BIN"

# ── 3. Kiosk-Benutzer ────────────────────────────────────
step "Kiosk-Benutzer einrichten"
if ! id "$KIOSK_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$KIOSK_USER"
    success "Benutzer '$KIOSK_USER' angelegt"
else
    success "Benutzer '$KIOSK_USER' bereits vorhanden"
fi

# ── 4. LightDM Auto-Login ─────────────────────────────────
step "Auto-Login konfigurieren"
mkdir -p /etc/lightdm
cat > /etc/lightdm/lightdm.conf << EOF
[Seat:*]
autologin-user=$KIOSK_USER
autologin-user-timeout=0
user-session=openbox
xserver-command=X -s 0 -dpms
EOF

# Openbox als X-Session registrieren
mkdir -p /usr/share/xsessions
cat > /usr/share/xsessions/openbox.desktop << 'EOF'
[Desktop Entry]
Name=Openbox
Comment=Openbox Kiosk Session
Exec=openbox-session
Type=Application
EOF
success "LightDM Auto-Login → $KIOSK_USER"

# ── 5. Openbox-Konfiguration ──────────────────────────────
step "Openbox einrichten"
mkdir -p "$KIOSK_HOME/.config/openbox"

# Kein Fensterrahmen, alle Apps maximiert
cat > "$KIOSK_HOME/.config/openbox/rc.xml" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_config xmlns="http://openbox.org/3.4/rc">
  <resistance><strength>10</strength><screen_edge_strength>20</screen_edge_strength></resistance>
  <focus><focusNew>yes</focusNew><followMouse>no</followMouse></focus>
  <placement><policy>Smart</policy></placement>
  <theme>
    <name>Bear2</name>
    <titleLayout>NLIMC</titleLayout>
    <keepBorder>yes</keepBorder>
    <animateIconify>yes</animateIconify>
  </theme>
  <desktops><number>1</number><firstdesk>1</firstdesk></desktops>
  <keyboard>
    <chainQuitKey>C-g</chainQuitKey>
    <keybind key="A-F4"><action name="Close"/></keybind>
  </keyboard>
  <applications>
    <application class="*">
      <decor>no</decor>
      <shade>no</shade>
      <maximized>yes</maximized>
      <fullscreen>no</fullscreen>
    </application>
  </applications>
</openbox_config>
EOF

success "Openbox konfiguriert"

# ── 6. Kiosk-Start-Script ─────────────────────────────────
step "Kiosk-Start-Script erstellen"
cat > "$KIOSK_HOME/start-kiosk.sh" << SCRIPT
#!/bin/bash

# Warte bis Erika erreichbar ist (max. 120s)
echo "Warte auf Erika…"
for i in \$(seq 1 60); do
    curl -sk --max-time 3 "${ERIKA_URL}" &>/dev/null && break
    sleep 2
done

# Bildschirm-Einstellungen
xset s off
xset s noblank
xset -dpms

# Maus-Cursor verstecken
unclutter -idle 0.1 -root &

# Kiosk-Schleife: Chrome bei Absturz automatisch neu starten
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
        --disable-background-networking \\
        --metrics-recording-only \\
        --disable-extensions \\
        --disk-cache-dir=/tmp/chrome-cache \\
        --user-data-dir=/tmp/chrome-user \\
        "${ERIKA_URL}" 2>/dev/null
    echo "Chrome beendet – starte neu in 3s…"
    sleep 3
done
SCRIPT
chmod +x "$KIOSK_HOME/start-kiosk.sh"

# Autostart über Openbox
cat > "$KIOSK_HOME/.config/openbox/autostart" << EOF
$KIOSK_HOME/start-kiosk.sh &
EOF

chown -R "$KIOSK_USER:$KIOSK_USER" "$KIOSK_HOME"
success "Kiosk-Script → $KIOSK_HOME/start-kiosk.sh"

# ── 7. Bildschirm-Timeout deaktivieren ───────────────────
step "Bildschirm-Timeout deaktivieren"

# Xorg: kein Blanking
mkdir -p /etc/X11/xorg.conf.d
cat > /etc/X11/xorg.conf.d/10-no-blanking.conf << 'EOF'
Section "ServerFlags"
    Option "BlankTime"    "0"
    Option "StandbyTime"  "0"
    Option "SuspendTime"  "0"
    Option "OffTime"      "0"
    Option "NoPM"         "true"
EndSection
EOF

# Systemd: kein Sleep / Suspend
mkdir -p /etc/systemd/logind.conf.d
cat > /etc/systemd/logind.conf.d/kiosk.conf << 'EOF'
[Login]
IdleAction=ignore
IdleActionSec=0
HandleLidSwitch=ignore
HandleSuspendKey=ignore
HandleHibernateKey=ignore
HandlePowerKey=poweroff
EOF
success "Bildschirm-Timeout deaktiviert"

# ── 8. Plymouth Boot-Screen ───────────────────────────────
step "Erika Boot-Screen installieren"
THEME_DIR="/usr/share/plymouth/themes/erika"
mkdir -p "$THEME_DIR"

cat > "$THEME_DIR/erika.plymouth" << 'EOF'
[Plymouth Theme]
Name=Erika
Description=Erika Display Boot Screen
ModuleName=script

[script]
ImageDir=/usr/share/plymouth/themes/erika
ScriptFile=/usr/share/plymouth/themes/erika/erika.script
EOF

cat > "$THEME_DIR/erika.script" << 'EOF'
# Dunkler Hintergrund (Erika-Farbschema)
Window.SetBackgroundTopColor(0.02, 0.02, 0.07);
Window.SetBackgroundBottomColor(0.03, 0.03, 0.15);

sw = Window.GetWidth();
sh = Window.GetHeight();

# Titel "ERIKA"
title_img = Image.Text("ERIKA", 1.0, 1.0, 1.0, 1.0, "Sans Bold 54");
title_spr = Sprite(title_img);
title_spr.SetX(sw / 2 - title_img.GetWidth() / 2);
title_spr.SetY(sh / 2 - title_img.GetHeight() / 2 - 50);

# Untertitel
sub_img = Image.Text("Display wird gestartet …", 0.4, 0.7, 1.0, 1.0, "Sans 17");
sub_spr = Sprite(sub_img);
sub_spr.SetX(sw / 2 - sub_img.GetWidth() / 2);
sub_spr.SetY(sh / 2 + 20);

# Fortschrittsbalken
bar_w = 320;  bar_h = 5;
bar_x = sw / 2 - bar_w / 2;
bar_y = sh / 2 + 72;

bg_img = Image(bar_w, bar_h);
bg_img.Fill(0.08, 0.08, 0.20, 1.0);
bg_spr = Sprite(bg_img);
bg_spr.SetX(bar_x);
bg_spr.SetY(bar_y);

fun boot_progress_cb(duration, progress) {
    w = Math.Int(bar_w * progress);
    if (w < 3) { w = 3; }
    bar_img = Image(w, bar_h);
    bar_img.Fill(0.0, 0.78, 1.0, 1.0);
    bar_spr = Sprite(bar_img);
    bar_spr.SetX(bar_x);
    bar_spr.SetY(bar_y);
}

Plymouth.SetBootProgressFunction(boot_progress_cb);
EOF

# Plymouth-Theme aktivieren
if plymouth-set-default-theme erika 2>/dev/null; then
    info "Aktualisiere initramfs…"
    update-initramfs -u -k all > /dev/null 2>&1 || true
    success "Boot-Screen 'Erika' aktiviert"
else
    warn "Plymouth-Theme konnte nicht gesetzt werden — übersprungen"
fi

# ── 9. Dienste aktivieren ─────────────────────────────────
step "Systemdienste konfigurieren"
systemctl enable lightdm > /dev/null 2>&1 || true
systemctl set-default graphical.target
hostnamectl set-hostname erika-display 2>/dev/null || true
success "LightDM aktiviert (graphical.target)"

# ── Fertig ────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  Erika Display ist einsatzbereit! 🖥️${NC}"
echo ""
echo -e "  Kiosk-URL:  ${CYAN}${ERIKA_URL}${NC}"
echo -e "  Benutzer:   ${CYAN}${KIOSK_USER}${NC}"
echo -e "  Browser:    ${CYAN}${CHROME_BIN}${NC}"
echo ""
echo -e "  ${YELLOW}Jetzt neu starten:${NC}"
echo -e "  ${BOLD}sudo reboot${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
