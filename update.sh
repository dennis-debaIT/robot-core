#!/bin/bash
set -e

# HOME und PATH sicherstellen (cron liefert oft minimales Environment)
export HOME=${HOME:-$(getent passwd "$(id -u)" | cut -d: -f6)}
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

INSTALL_DIR="$HOME/robot-core"
LOG="$INSTALL_DIR/update.log"
cd "$INSTALL_DIR"

# Lock-Datei: verhindert parallele Runs (z.B. durch Cron + manuellem Aufruf)
LOCKFILE="/tmp/robot-core-update.lock"
if ! mkdir "$LOCKFILE" 2>/dev/null; then
    echo "[update] Bereits aktiv, ueberspringe: $(date)" >> "$LOG"
    exit 0
fi
trap "rmdir '$LOCKFILE' 2>/dev/null || true" EXIT

echo "[update] Starte Update: $(date)" | tee -a "$LOG"
# SSH-Fetch (falls Key vorhanden), Fallback auf HTTPS (Public Repo, kein Token nötig)
if git -c safe.directory=. fetch git@github.com:dennis-debaIT/robot-core.git main:refs/remotes/origin/main 2>>"$LOG"; then
    echo "[update] Fetch via SSH" | tee -a "$LOG"
else
    echo "[update] SSH nicht verfügbar, versuche HTTPS..." | tee -a "$LOG"
    GIT_TERMINAL_PROMPT=0 git -c safe.directory=. -c credential.helper= \
        fetch https://github.com/dennis-debaIT/robot-core.git main:refs/remotes/origin/main 2>&1 | tee -a "$LOG"
fi
git -c safe.directory=. reset --hard origin/main 2>&1 | tee -a "$LOG"

# Flag-Dateien sicherstellen (werden durch git reset ggf. gelöscht, da in .gitignore)
touch update.flag reboot.flag timezone.flag hostname.flag wlan.flag ha-install.flag components.flag
[ -f wifi-scan.json ] || echo '{"networks":[]}' > wifi-scan.json
mkdir -p ha_config

export GIT_HASH=$(git -c safe.directory=. rev-parse HEAD)
echo "[update] Build startet (GIT_HASH=$GIT_HASH)..." | tee -a "$LOG"
docker compose up -d --build robot-core 2>&1 | tail -4 | tee -a "$LOG"
echo "[update] Abgeschlossen: $(date)" | tee -a "$LOG"
