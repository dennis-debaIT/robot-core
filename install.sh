#!/bin/bash
set -e

# ── Erika Robot-Core Installations-Script ─────────────────────
# Führe dieses Script auf einem frischen Ubuntu/Debian System aus:
#   curl -fsSL https://raw.githubusercontent.com/dennis-debaIT/robot-core/main/install.sh | bash
# ─────────────────────────────────────────────────────────────

REPO="git@github.com:dennis-debaIT/robot-core.git"
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
echo -e "${NC}  Robot-Core Installations-Script\n"

# ── 1. System-Voraussetzungen ─────────────────────────────────
step "System aktualisieren"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    curl git ca-certificates gnupg lsb-release openssh-client openssl sqlite3 > /dev/null
success "Pakete installiert"

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

# ── 3. SSH-Key für GitHub ─────────────────────────────────────
step "SSH-Key einrichten"
KEY_FILE="$HOME/.ssh/id_ed25519"
if [ ! -f "$KEY_FILE" ]; then
    ssh-keygen -t ed25519 -C "erika-robot-core" -f "$KEY_FILE" -N "" > /dev/null
    success "Neuer SSH-Key erstellt"
fi

echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}Füge diesen SSH-Key bei GitHub hinzu:${NC}"
echo -e "${YELLOW}github.com → Settings → SSH and GPG keys → New SSH key${NC}"
echo ""
cat "$KEY_FILE.pub"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
read -r -p "Drücke ENTER sobald der Key bei GitHub eingetragen ist..."

# Verbindung testen
info "Teste GitHub-Verbindung..."
if ssh -o StrictHostKeyChecking=no -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
    success "GitHub-Verbindung erfolgreich"
else
    warn "Verbindungstest fehlgeschlagen — fahre trotzdem fort"
fi

# ── 4. Repo klonen ────────────────────────────────────────────
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

# ── 6. .env erstellen (minimal) ───────────────────────────────
step ".env Konfiguration"
if [ ! -f .env ]; then
    cat > .env << 'EOF'
# Home Assistant (kann auch im Admin-Panel eingetragen werden)
ROBOT_HA_URL=
ROBOT_HA_TOKEN=

# LLM (optional)
LLM_API_URL=
LLM_PROVIDER=generic
LLM_MODEL=

# TTS
ROBOT_TTS_PROVIDER=disabled
EOF
    success ".env angelegt (HA-Konfiguration im Admin-Panel unter System)"
else
    success ".env bereits vorhanden — unverändert"
fi

# ── 7. Update-Hilfsdateien ────────────────────────────────────
step "Update-System einrichten"
touch update.flag
chmod +x update.sh

# Cron-Jobs einrichten
CRON_DAILY="0 3 * * * $INSTALL_DIR/update.sh >> $INSTALL_DIR/update.log 2>&1"
CRON_FLAG="* * * * * [ -f $INSTALL_DIR/update.flag ] && cat $INSTALL_DIR/update.flag | grep -q requested_at && echo '{}' > $INSTALL_DIR/update.flag && $INSTALL_DIR/update.sh >> $INSTALL_DIR/update.log 2>&1 || true"

(crontab -l 2>/dev/null | grep -v "robot-core/update"; \
 echo "$CRON_DAILY"; \
 echo "$CRON_FLAG") | crontab -
success "Cron-Jobs eingerichtet (täglich 03:00 + Install-Trigger)"

# ── 8. Container bauen und starten ───────────────────────────
step "Container bauen und starten"
info "Dies kann einige Minuten dauern..."
GIT_HASH=$(git rev-parse HEAD)
docker compose build --build-arg GIT_HASH="$GIT_HASH" robot-core
docker compose up -d robot-core
success "Container gestartet"

# ── 9. Autostart sicherstellen ────────────────────────────────
sudo systemctl enable docker > /dev/null 2>&1 || true

# ── Fertig ────────────────────────────────────────────────────
IP=$(hostname -I | awk '{print $1}')
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  Erika ist einsatzbereit! 🤖${NC}"
echo ""
echo -e "  Web-Interface:   ${CYAN}https://${IP}:8000${NC}"
echo -e "  Display-Panel:   ${CYAN}https://${IP}:8000/display${NC}"
echo -e "  Admin-Panel:     ${CYAN}https://${IP}:8000/local-admin${NC}"
echo ""
echo -e "  ${YELLOW}Hinweis:${NC} Browser-Warnung beim SSL-Zertifikat ist normal"
echo -e "           (selbstsigniert). Einfach bestätigen."
echo ""
echo -e "  Home Assistant im Admin-Panel unter System → Home Assistant"
echo -e "  eintragen falls noch nicht in der .env gesetzt."
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
if ! groups "$USER_NAME" | grep -q docker; then
    warn "Bitte neu einloggen damit Docker ohne sudo funktioniert"
fi
