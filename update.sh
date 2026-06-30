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

# Alle Ausgaben direkt in den Log leiten — verhindert Doppelzeilen wenn
# der Cron-Aufruf (>> update.log 2>&1) stdout zusätzlich umleitet.
exec 1>>"$LOG" 2>&1

echo "[update] Starte Update: $(date)"
# SSH-Fetch (falls Key vorhanden), Fallback auf HTTPS (Public Repo, kein Token nötig)
if git -c safe.directory=. fetch git@github.com:dennis-debaIT/robot-core.git main:refs/remotes/origin/main 2>&1; then
    echo "[update] Fetch via SSH"
else
    echo "[update] SSH nicht verfügbar, versuche HTTPS..."
    GIT_TERMINAL_PROMPT=0 git -c safe.directory=. -c credential.helper= \
        fetch https://github.com/dennis-debaIT/robot-core.git main:refs/remotes/origin/main 2>&1
fi
git -c safe.directory=. reset --hard origin/main 2>&1

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
# edition als Datei sicherstellen (Default community) — Docker mountet sie sonst als Verzeichnis.
# Bestehenden Wert (z.B. von der Admin-Auswahl/Lizenz) NICHT überschreiben.
[ -f edition ] && [ ! -d edition ] || { rm -rf edition 2>/dev/null; echo community > edition; }
hostname -I | awk '{print $1}' > host-ip.txt 2>/dev/null || true
mkdir -p ha_config

export GIT_HASH=$(git -c safe.directory=. rev-parse HEAD)

# Edition bestimmen: Community-Geräte werden ohne Paid-Module gebaut.
# Die Datei "edition" überlebt git reset --hard (untracked, gitignored)
# und wird später vom Lizenz-Check geschrieben. Default: plus.
EDITION=$(cat "$INSTALL_DIR/edition" 2>/dev/null | tr -d '[:space:]')
[ -z "$EDITION" ] && EDITION=community
export EDITION
echo "[update] Build startet (GIT_HASH=$GIT_HASH, EDITION=$EDITION)..."
docker compose up -d --build robot-core 2>&1 | tail -4

# Watcher neu starten falls nicht aktiv
chmod +x "$INSTALL_DIR/reboot-watcher.sh" "$INSTALL_DIR/setup-watcher.sh" 2>/dev/null || true
pgrep -f reboot-watcher.sh  > /dev/null || nohup bash "$INSTALL_DIR/reboot-watcher.sh"  >> "$INSTALL_DIR/reboot.log"  2>&1 &
pgrep -f setup-watcher.sh   > /dev/null || nohup bash "$INSTALL_DIR/setup-watcher.sh"   >> "$INSTALL_DIR/setup-watcher.log" 2>&1 &

# Verwaiste Images + Build-Cache aufräumen
docker image prune -f
echo "[update] $(docker system df --format 'Images: {{.ImagesSize}}  Build-Cache: {{.BuildCacheSize}}')"

# Monatlichen Cron-Job für Build-Cache-Bereinigung einrichten (einmalig, idempotent)
CRON_JOB="0 3 1 * * docker builder prune --keep-storage=2GB -f >> $INSTALL_DIR/update.log 2>&1"
if ! crontab -l 2>/dev/null | grep -qF "docker builder prune"; then
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    echo "[update] Monatlicher Docker-Cache-Cron eingerichtet"
fi

echo "[update] Abgeschlossen: $(date)"
