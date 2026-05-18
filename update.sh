#!/bin/bash
set -e

# HOME und PATH sicherstellen (cron liefert oft minimales Environment)
export HOME=${HOME:-$(getent passwd "$(id -u)" | cut -d: -f6)}
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

INSTALL_DIR="$HOME/robot-core"
LOG="$INSTALL_DIR/update.log"
cd "$INSTALL_DIR"

# Crontab selbst reparieren falls HOME/PATH fehlen (Einmal-Fix fuer Bestandsinstallationen)
if ! crontab -l 2>/dev/null | grep -q "^HOME="; then
    CRON_DAILY="0 3 * * * $INSTALL_DIR/update.sh >> $INSTALL_DIR/update.log 2>&1"
    CRON_FLAG="* * * * * grep -q requested_at $INSTALL_DIR/update.flag 2>/dev/null && echo '{}' > $INSTALL_DIR/update.flag && $INSTALL_DIR/update.sh >> $INSTALL_DIR/update.log 2>&1 || true"
    (crontab -l 2>/dev/null | grep -v "robot-core/update" | grep -v "^HOME=" | grep -v "^PATH="; \
     echo "HOME=$HOME"; \
     echo "PATH=$PATH"; \
     echo "$CRON_DAILY"; \
     echo "$CRON_FLAG") | crontab -
    echo "[update] Crontab repariert (HOME/PATH ergaenzt)" | tee -a "$LOG"
fi

echo "[update] Starte Update: $(date)" | tee -a "$LOG"
git -c safe.directory=. fetch git@github.com:dennis-debaIT/robot-core.git main:refs/remotes/origin/main 2>&1 | tee -a "$LOG"
git -c safe.directory=. reset --hard origin/main 2>&1 | tee -a "$LOG"

export GIT_HASH=$(git -c safe.directory=. rev-parse HEAD)
echo "[update] Build startet (GIT_HASH=$GIT_HASH)..." | tee -a "$LOG"
docker compose up -d --build robot-core 2>&1 | tail -4 | tee -a "$LOG"
echo "[update] Abgeschlossen: $(date)" | tee -a "$LOG"
