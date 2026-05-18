#!/bin/bash
set -e

# ── Erika Display Kiosk Installations-Script ───────────────
# Für frisches Ubuntu 22.04 / 24.04 LTS (Server oder Desktop)
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

[ "$EUID" -eq 0 ] || error "Bitte mit sudo ausführen: sudo bash install-display.sh"

# ── URL ermitteln ─────────────────────────────────────────
if [ -z "$ERIKA_URL" ]; then
    info "Suche Erika im Netzwerk via erika.local…"
    if curl -sk --max-time 5 "https://erika.local:8000/health" &>/dev/null; then
        ERIKA_URL="https://erika.local:8000/display"
        success "Erika gefunden → ${ERIKA_URL}"
    else
        warn "erika.local nicht erreichbar — bitte IP eingeben."
        echo -n "  Erika-Adresse (z.B. https://192.168.1.10:8000/display): "
        read -r ERIKA_URL
        [ -n "$ERIKA_URL" ] || error "Keine Erika-Adresse angegeben."
    fi
fi

KIOSK_USER="erika-display"
KIOSK_HOME="/home/$KIOSK_USER"

echo ""
echo -e "  Ziel: ${CYAN}${ERIKA_URL}${NC}"
echo ""

# ── 1. Pakete ─────────────────────────────────────────────
step "System-Pakete installieren"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    curl wget gnupg2 ca-certificates \
    xserver-xorg xinit x11-xserver-utils \
    xserver-xorg-video-all xserver-xorg-input-all \
    openbox \
    avahi-daemon libnss-mdns \
    unclutter \
    fonts-noto-color-emoji fonts-noto-core fonts-liberation \
    > /dev/null
success "Basis-Pakete installiert (inkl. Emoji-Schriftarten)"

# ── 2. VM-Treiber erkennen und installieren ───────────────
step "VM-Grafiktreiber ermitteln"
VIRT="$(systemd-detect-virt 2>/dev/null || echo none)"
info "Virtualisierung: $VIRT"
case "$VIRT" in
    oracle)
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            virtualbox-guest-x11 virtualbox-guest-utils > /dev/null 2>&1 \
            && success "VirtualBox-Gast-Treiber installiert" \
            || warn "VirtualBox-Treiber nicht verfügbar – modesetting wird genutzt"
        ;;
    vmware)
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            open-vm-tools-desktop > /dev/null 2>&1 \
            && success "VMware-Gast-Treiber installiert" \
            || warn "VMware-Treiber nicht verfügbar – modesetting wird genutzt"
        ;;
    kvm|qemu)
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            spice-vdagent > /dev/null 2>&1 \
            && success "QEMU/KVM SPICE-Agent installiert" \
            || warn "SPICE-Agent nicht verfügbar – modesetting wird genutzt"
        ;;
    microsoft)
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            hyperv-daemons > /dev/null 2>&1 \
            && success "Hyper-V-Treiber installiert" \
            || warn "Hyper-V-Treiber nicht verfügbar – modesetting wird genutzt"
        ;;
    *)
        success "Kein spezifischer VM-Treiber nötig (oder Bare-Metal)"
        ;;
esac

# Generische Xorg-Konfiguration mit modesetting als Fallback
mkdir -p /etc/X11/xorg.conf.d
cat > /etc/X11/xorg.conf.d/10-display.conf << 'EOF'
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
success "Xorg-Konfiguration gesetzt"

# ── 3. Google Chrome ──────────────────────────────────────
step "Browser installieren"
CHROME_BIN=""

if ! command -v google-chrome-stable &>/dev/null && ! command -v google-chrome &>/dev/null; then
    info "Lade Google Chrome…"
    if wget -q -O /tmp/chrome.deb \
        "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb"; then
        DEBIAN_FRONTEND=noninteractive apt-get install -y /tmp/chrome.deb > /dev/null 2>&1 \
            || apt-get install -f -y > /dev/null
        rm -f /tmp/chrome.deb
        success "Google Chrome installiert"
    else
        warn "Chrome-Download fehlgeschlagen – installiere Chromium"
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            chromium-browser > /dev/null 2>&1 \
            || snap install chromium 2>/dev/null \
            || error "Kein Browser installierbar."
        success "Chromium installiert"
    fi
fi

CHROME_BIN="$(command -v google-chrome-stable 2>/dev/null \
           || command -v google-chrome 2>/dev/null \
           || command -v chromium-browser 2>/dev/null \
           || command -v chromium 2>/dev/null)"
[ -n "$CHROME_BIN" ] || error "Browser-Binary nicht gefunden."
success "Browser: $CHROME_BIN"

# ── 4. Kiosk-Benutzer ────────────────────────────────────
step "Kiosk-Benutzer einrichten"
if ! id "$KIOSK_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$KIOSK_USER"
    success "Benutzer '$KIOSK_USER' angelegt"
else
    success "Benutzer '$KIOSK_USER' bereits vorhanden"
fi

# ── 5. Openbox-Konfiguration ──────────────────────────────
step "Kiosk konfigurieren"
mkdir -p "$KIOSK_HOME/.config/openbox"

# Kein Fensterrahmen, maximiert
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

# Kiosk-Start-Script
cat > "$KIOSK_HOME/start-kiosk.sh" << SCRIPT
#!/bin/bash

# Bildschirm: nie aus
xset s off
xset s noblank
xset -dpms

# Maus-Cursor ausblenden
unclutter -idle 0.1 -root &

# Warte bis Erika erreichbar (max. 2 Minuten)
for i in \$(seq 1 60); do
    curl -sk --max-time 3 "${ERIKA_URL}" &>/dev/null && break
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
        "${ERIKA_URL}" 2>/dev/null
    sleep 3
done
SCRIPT
chmod +x "$KIOSK_HOME/start-kiosk.sh"

# Openbox startet das Kiosk-Script (mit Auflösungs-Erzwingung via xrandr)
cat > "$KIOSK_HOME/.config/openbox/autostart" << EOF
# Auflösung auf 1280x800 setzen (funktioniert in VMs zuverlässiger als Xorg-Config)
OUTPUT=\$(xrandr 2>/dev/null | grep " connected" | head -1 | awk '{print \$1}')
if [ -n "\$OUTPUT" ]; then
    xrandr --output "\$OUTPUT" --mode 1280x800 2>/dev/null \\
    || xrandr --output "\$OUTPUT" --preferred 2>/dev/null \\
    || true
fi

$KIOSK_HOME/start-kiosk.sh &
EOF

# xinitrc: Openbox starten
cat > "$KIOSK_HOME/.xinitrc" << 'EOF'
exec openbox-session
EOF

# .bash_profile: startx automatisch auf TTY1
cat > "$KIOSK_HOME/.bash_profile" << 'EOF'
[[ -z $DISPLAY && $(tty) == /dev/tty1 ]] && exec startx -- -nocursor 2>/dev/null
EOF

chown -R "$KIOSK_USER:$KIOSK_USER" "$KIOSK_HOME"
success "Kiosk konfiguriert"

# ── 6. TTY1 Auto-Login (kein LightDM nötig) ──────────────
step "Auto-Login auf TTY1 einrichten"
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin ${KIOSK_USER} --noclear %I \$TERM
Type=simple
EOF
systemctl daemon-reload
systemctl enable getty@tty1
success "Auto-Login → $KIOSK_USER auf TTY1"

# LightDM deaktivieren falls vorhanden
systemctl disable lightdm 2>/dev/null || true
systemctl set-default multi-user.target

# ── 7. Energiesparmodus deaktivieren ─────────────────────
step "Bildschirm-Timeout deaktivieren"
mkdir -p /etc/systemd/logind.conf.d
cat > /etc/systemd/logind.conf.d/kiosk.conf << 'EOF'
[Login]
IdleAction=ignore
HandleLidSwitch=ignore
HandleSuspendKey=ignore
HandleHibernateKey=ignore
EOF
success "Bildschirm-Timeout deaktiviert"

# ── 8. Plymouth Boot-Screen ───────────────────────────────
step "Erika Boot-Screen installieren"
if DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    plymouth plymouth-themes > /dev/null 2>&1; then

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
Window.SetBackgroundTopColor(0.02, 0.02, 0.07);
Window.SetBackgroundBottomColor(0.03, 0.03, 0.15);

sw = Window.GetWidth();
sh = Window.GetHeight();

title_img = Image.Text("ERIKA", 1.0, 1.0, 1.0, 1.0, "Sans Bold 54");
title_spr = Sprite(title_img);
title_spr.SetX(sw / 2 - title_img.GetWidth() / 2);
title_spr.SetY(sh / 2 - title_img.GetHeight() / 2 - 50);

sub_img = Image.Text("Display wird gestartet …", 0.4, 0.7, 1.0, 1.0, "Sans 17");
sub_spr = Sprite(sub_img);
sub_spr.SetX(sw / 2 - sub_img.GetWidth() / 2);
sub_spr.SetY(sh / 2 + 20);

bar_w = 320; bar_h = 5;
bar_x = sw / 2 - bar_w / 2;
bar_y = sh / 2 + 72;

bg_img = Image(bar_w, bar_h);
bg_img.Fill(0.08, 0.08, 0.20, 1.0);
bg_spr = Sprite(bg_img); bg_spr.SetX(bar_x); bg_spr.SetY(bar_y);

fun boot_progress_cb(duration, progress) {
    w = Math.Int(bar_w * progress);
    if (w < 3) { w = 3; }
    bar_img = Image(w, bar_h);
    bar_img.Fill(0.0, 0.78, 1.0, 1.0);
    bar_spr = Sprite(bar_img); bar_spr.SetX(bar_x); bar_spr.SetY(bar_y);
}
Plymouth.SetBootProgressFunction(boot_progress_cb);
EOF

    # Theme direkt in Plymouth-Konfiguration erzwingen
    mkdir -p /etc/plymouth
    cat > /etc/plymouth/plymouthd.conf << 'EOF'
[Daemon]
Theme=erika
ShowDelay=0
EOF

    # update-alternatives mit hoher Priorität (überschreibt ubuntu-logo etc.)
    update-alternatives --install \
        /usr/share/plymouth/themes/default.plymouth \
        default.plymouth \
        "$THEME_DIR/erika.plymouth" 200 2>/dev/null || true
    update-alternatives --set \
        default.plymouth \
        "$THEME_DIR/erika.plymouth" 2>/dev/null || true

    plymouth-set-default-theme erika 2>/dev/null || true

    # GRUB: quiet splash + loglevel=3 (unterdrückt Boot-Warnungen wie copymods)
    if [ -f /etc/default/grub ]; then
        sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="quiet splash loglevel=3"/' /etc/default/grub
        grep -q "GRUB_CMDLINE_LINUX_DEFAULT" /etc/default/grub \
            || echo 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash loglevel=3"' >> /etc/default/grub
        update-grub > /dev/null 2>&1 || true
    fi

    # Veraltetes copymods dracut-Modul deaktivieren (verhindert Boot-Warnung)
    rm -f /usr/share/initramfs-tools/hooks/copymods 2>/dev/null || true
    if [ -d /usr/lib/dracut/modules.d/50copymods ]; then
        mkdir -p /etc/dracut.conf.d
        echo 'omit_dracutmodules+=" copymods"' > /etc/dracut.conf.d/no-copymods.conf
        dracut --force > /dev/null 2>&1 || true
    fi

    update-initramfs -u -k all > /dev/null 2>&1 || true
    success "Boot-Screen 'Erika' aktiviert"
else
    warn "Plymouth nicht verfügbar — kein benutzerdefinierter Boot-Screen"
fi

# ── Avahi mDNS ────────────────────────────────────────────
systemctl enable --now avahi-daemon > /dev/null 2>&1 || true

# ── Fertig ────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  Erika Display ist einsatzbereit!${NC}"
echo ""
echo -e "  Kiosk-URL:  ${CYAN}${ERIKA_URL}${NC}"
echo -e "  Benutzer:   ${CYAN}${KIOSK_USER}${NC}"
echo -e "  Browser:    ${CYAN}${CHROME_BIN}${NC}"
echo -e "  VM-Typ:     ${CYAN}${VIRT}${NC}"
echo ""
echo -e "  ${YELLOW}Jetzt neu starten:${NC}  ${BOLD}sudo reboot${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
