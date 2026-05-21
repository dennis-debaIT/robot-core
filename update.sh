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

# .git-Verzeichnis dem aktuellen User gehören lassen (verhindert Permission-Fehler bei gemischten sudo/User-Runs)
chown -R "$(id -u):$(id -g)" .git 2>/dev/null || true

# Execute-Bit auf alle Scripts setzen (git reset kann es entfernen)
chmod +x "$INSTALL_DIR/update.sh" \
         "$INSTALL_DIR/reboot-watcher.sh" \
         "$INSTALL_DIR/setup-watcher.sh" 2>/dev/null || true

# Flag-Dateien sicherstellen — Verzeichnisse (fälschlich von Docker angelegt) entfernen
for _f in update.flag update.log reboot.flag timezone.flag hostname.flag wlan.flag ha-install.flag components.flag host-ip.txt wifi-scan.json printer-start.flag; do
    [ -d "$_f" ] && { rm -rf "$_f" 2>/dev/null || sudo rm -rf "$_f" 2>/dev/null || true; }
done
touch update.flag update.log reboot.flag timezone.flag hostname.flag wlan.flag ha-install.flag components.flag printer-start.flag
[ -s wifi-scan.json ]  || echo '{"networks":[]}' > wifi-scan.json
hostname -I | awk '{print $1}' > host-ip.txt 2>/dev/null || true
mkdir -p ha_config

export GIT_HASH=$(git -c safe.directory=. rev-parse HEAD)
echo "[update] Build startet (GIT_HASH=$GIT_HASH)..." | tee -a "$LOG"
docker compose up -d --build robot-core 2>&1 | tail -4 | tee -a "$LOG"

# Watcher neu starten falls nicht aktiv
chmod +x "$INSTALL_DIR/reboot-watcher.sh" "$INSTALL_DIR/setup-watcher.sh" 2>/dev/null || true
pgrep -f reboot-watcher.sh  > /dev/null || nohup bash "$INSTALL_DIR/reboot-watcher.sh"  >> "$INSTALL_DIR/reboot.log"  2>&1 &
pgrep -f setup-watcher.sh   > /dev/null || nohup bash "$INSTALL_DIR/setup-watcher.sh"   >> "$INSTALL_DIR/setup-watcher.log" 2>&1 &

# Nur verwaiste Images entfernen — Build-Cache NICHT löschen (würde nächsten Build verlangsamen)
docker image prune -f >> "$LOG" 2>&1 || true

# Monatlichen Cron-Job für Build-Cache-Bereinigung einrichten (einmalig, idempotent)
CRON_JOB="0 3 1 * * docker builder prune --keep-storage=2GB -f >> $INSTALL_DIR/update.log 2>&1"
if ! crontab -l 2>/dev/null | grep -qF "docker builder prune"; then
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    echo "[update] Monatlicher Docker-Cache-Cron eingerichtet" | tee -a "$LOG"
fi

echo "[update] Abgeschlossen: $(date)" | tee -a "$LOG"
