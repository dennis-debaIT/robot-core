#!/bin/bash
set -e
# Fehler in einer Pipe (z.B. "docker compose ... | tail -4") sollen das Skript
# stoppen wenn der ERSTE Befehl scheitert, nicht nur wenn tail scheitert.
set -o pipefail

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
# SSH-Fetch (falls Key vorhanden), Fallback auf HTTPS (Public Repo, kein Token nötig).
# timeout schützt vor unbegrenztem Haengen bei Netzwerkproblemen (z.B. TLS-Handshake-
# Timeout beim GitHub-Zugriff) — ohne das konnte ein einzelner haengender Lauf die
# Admin-Oberflaeche weit ueber ihr 5-Minuten-Warten hinaus blockieren, ohne jede
# Fehlermeldung im Log.
if timeout 60 git -c safe.directory=. fetch git@github.com:dennis-debaIT/robot-core.git main:refs/remotes/origin/main 2>&1; then
    echo "[update] Fetch via SSH"
else
    echo "[update] SSH nicht verfügbar, versuche HTTPS..."
    if ! GIT_TERMINAL_PROMPT=0 timeout 60 git -c safe.directory=. -c credential.helper= \
        fetch https://github.com/dennis-debaIT/robot-core.git main:refs/remotes/origin/main 2>&1; then
        echo "[update] FEHLER: git fetch (HTTPS) fehlgeschlagen oder Timeout nach 60s — Update abgebrochen: $(date)"
        exit 1
    fi
fi
git -c safe.directory=. reset --hard origin/main 2>&1

# .git-Verzeichnis dem aktuellen User gehören lassen (verhindert Permission-Fehler bei gemischten sudo/User-Runs)
chown -R "$(id -u):$(id -g)" .git 2>/dev/null || true

# Execute-Bit auf alle Scripts setzen (git reset kann es entfernen)
chmod +x "$INSTALL_DIR/update.sh" \
         "$INSTALL_DIR/reboot-watcher.sh" \
         "$INSTALL_DIR/setup-watcher.sh" 2>/dev/null || true

# Flag-Dateien sicherstellen — Verzeichnisse (fälschlich von Docker angelegt) entfernen
for _f in update.flag update.log reboot.flag timezone.flag hostname.flag wlan.flag ha-install.flag components.flag host-ip.txt wifi-scan.json printer-start.flag tts-model.flag; do
    [ -d "$_f" ] && { rm -rf "$_f" 2>/dev/null || sudo rm -rf "$_f" 2>/dev/null || true; }
done
touch update.flag update.log reboot.flag timezone.flag hostname.flag wlan.flag ha-install.flag components.flag printer-start.flag tts-model.flag
[ -s wifi-scan.json ]  || echo '{"networks":[]}' > wifi-scan.json
# edition als Datei sicherstellen (Default community) — Docker mountet sie sonst als Verzeichnis.
# Bestehenden Wert (z.B. von der Admin-Auswahl/Lizenz) NICHT überschreiben.
[ -f edition ] && [ ! -d edition ] || { rm -rf edition 2>/dev/null; echo community > edition; }
hostname -I | awk '{print $1}' > host-ip.txt 2>/dev/null || true
mkdir -p ha_config

# Backup-Restore: restore.env → .env übernehmen falls vorhanden
if [ -f "${INSTALL_DIR}/restore.env" ] && [ -s "${INSTALL_DIR}/restore.env" ]; then
    cp "${INSTALL_DIR}/restore.env" "${INSTALL_DIR}/.env"
    rm -f "${INSTALL_DIR}/restore.env"
    echo "[update] .env aus Backup-Restore übernommen"
fi

# Firebase-Credentials automatisch in .env eintragen (einmalig, kein Überschreiben)
_FCM_B64="ewogICJ0eXBlIjogInNlcnZpY2VfYWNjb3VudCIsCiAgInByb2plY3RfaWQiOiAiZXJpa2EtOTJkNGUiLAogICJwcml2YXRlX2tleV9pZCI6ICI3YzgwMTEwODNhNzRjZmY1NzQ1YTc2ZmJhN2U5Y2VkZTVlNzVkOGFjIiwKICAicHJpdmF0ZV9rZXkiOiAiLS0tLS1CRUdJTiBQUklWQVRFIEtFWS0tLS0tXG5NSUlFdndJQkFEQU5CZ2txaGtpRzl3MEJBUUVGQUFTQ0JLa3dnZ1NsQWdFQUFvSUJBUURUZG54TmROUEFRS2ZTXG5vRGRyM2NLRGlsMzBtZGIxTDUwSm5hUkV3R0xFQjhrSCt3OTkvN2dSTHh5a29ZOVorWWpXVnZSKzlHNVVhdUY5XG5vRDhqQWtRWFBBeDhOSDJhNXo0cURNSDVVaEtIZjZtdmZmdmJDR0xxQWRoZWlLK2FDbFpjRzFWS2RTYXlhRDh1XG5pT1IrTkN2YTEyVmQ1K2lVeUZtWXNXd1RYRmVucFJYRmZGcHlXWXZMay84K3I3NTV5M2IrQVlJZjNyNUM5aTdhXG5mcVNnTUozbFZaLzNOenJGOHJQZFExWXRRSndTbHpBUjNsNjBzUWk0cCtLN3YwOCs1SmVUL3BLeFUrZG4rRXlOXG5xRDJFeXlLLzdGSTlMWU9FaXV1N2t6cEJKa2NabXVLWUJZbEVteVVBTmZBc0NMUlFKbGMrZ3RIdTNMMEhRZld5XG5YMG5iV04vWkFnTUJBQUVDZ2dFQUI2UkcxbG04SHBJaVBuSDhicnZOMVY1cnRNb3J3czB5Qkp0R0hoZEJ1blI1XG5rYWlZcFE5WHJJU2lWQVM1U2N3WVkzNklTVitMUTlFS1RiV1JIVEp1R1grRVhWSUc4L3ZGVUZSZVhNOHRkNU5uXG56aEs1eGtRNi9DL2k0aVVEQzRoY3hKUUJuMkRmd1hTK1M4VTEvMUE0QVg3bE1vdmpQaC9iWDdHUnNVVnJXWUNFXG5tQ0l2MUpwdkVZakpYL2NVaTlyZkVrWXdFSUxUaFRjVEpZZk0zUTBDZFVFU2MraEJJRHcwbGZvNGlNV0dIRkFWXG5uMldVcGRKQW5qMlR4OUVDdloxQ3ZtMVYrR25BRWRmbVRNYWhNRVVVRndhQU9UTFVaT291U3B2N0hIR1lvR1kxXG5JSGREaVhvYkNhRURObGx5b2Q5UHRzbGR6a1J1WENYdkxabWN0L21BdlFLQmdRRHV6NmpTYVZOb1FFekV6SitJXG52RmNSdTFIZWRCbkhzMFM2NFpISWRIVUtqWHE5OFo5YkJjL2dKRGZxMU9rK2psbUtJVTRmRWJIazcxQ2QzYkpvXG50NFo1T1FxVjdLNkRkTGd0NkxHT216TlBIU2huY1NqaWZWYWRkVUx3dkhRWHVTTHprS2cvSlZsajl0L05uRTJJXG5EWU1tVE44UU1WbDR6c2k4OUN3UmVzRlhOd0tCZ1FEaXJ1ZXROTE55ZmNoRDF5Y3RyUlptRXM4WUF2Q3FVTGdCXG44T1ZsSS8veGYrWnh5YUlqcHVvaU51dng2K3IxK3pHb0tGcDhUakRIYS8va1F3Z2V4eEg3Z3RTclpyNVgvdTJGXG5jSlVMRGZTYWcvZVBCY1VkU21BOXdsYTdIVFh4VlA0WG1WSFUxVkxyMVh1RUtvNlJpM1pPSjRpR2drbk5KZEJQXG5LeVQwRzNYcGJ3S0JnUUMxUGJDNGorc1hNY1dSam1KOVdjTVMyQUZZUFBEYjJMZ094T2JwSlVrMml3MWVYcVE4XG5abnJQZDIxZ3NkbWErbG9HTlNTZSs4VHhKSmNnV0lMd2FtaUtVN291OG9PM2pMdkRTOWlGakZBeWVNU1RUUlJrXG5ZQTkrVE9KUzVoT05kWnFMRTN3OUFGR0pSbkd3RURIZlViSDVQVm9GWmc2cld2U0tReDIyM2wwaG5RS0JnUUNkXG5BOC9nRHJnWm52eWYyU0QvSjN4eldhWHZHT0pBNXNaK09iRjduRE1Gd2JVS3JrTEw5U3NLWmdhS3ZRSTBQam1JXG5JK09CWk51dTFxVWFKRUEwcVdsUVVMQWt4WGNsRnFUSm9GRHNwazcrMUZnZXpqMVo2NUc4VmFlajFqanVJQlFjXG5ub3VySTlSYkhMV0F0OFduRlBYdWJyM0hoZW0rMnVsdVhSRXNzUFM4cXdLQmdRRGpDTGFOeklLOXJqMjMxK3ZPXG5NbWx0QjU0Sm5YY1FZT1ZpbW0rMm1oTktsODZHdnZxZ1dXS3ZnbFFNZ1d1WGJVZk5FTFpZNTNQR1Zob0wxSnhYXG5vdDBkZXBpSEVXNmdmeG5MTXhZdkJxRXBoclUzMnlHNmdmeVJZamhvdWlNM0xFWnQ4ZzR3cVdCeVVETEY2V2hXXG5ZTDBSRE9INzlDYStQVmN2OFZtV2ViOWcxQT09XG4tLS0tLUVORCBQUklWQVRFIEtFWS0tLS0tXG4iLAogICJjbGllbnRfZW1haWwiOiAiZmlyZWJhc2UtYWRtaW5zZGstZmJzdmNAZXJpa2EtOTJkNGUuaWFtLmdzZXJ2aWNlYWNjb3VudC5jb20iLAogICJjbGllbnRfaWQiOiAiMTA3NTUzOTUxNDEyNjc4NDEyNTUxIiwKICAiYXV0aF91cmkiOiAiaHR0cHM6Ly9hY2NvdW50cy5nb29nbGUuY29tL28vb2F1dGgyL2F1dGgiLAogICJ0b2tlbl91cmkiOiAiaHR0cHM6Ly9vYXV0aDIuZ29vZ2xlYXBpcy5jb20vdG9rZW4iLAogICJhdXRoX3Byb3ZpZGVyX3g1MDlfY2VydF91cmwiOiAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vb2F1dGgyL3YxL2NlcnRzIiwKICAiY2xpZW50X3g1MDlfY2VydF91cmwiOiAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vcm9ib3QvdjEvbWV0YWRhdGEveDUwOS9maXJlYmFzZS1hZG1pbnNkay1mYnN2YyU0MGVyaWthLTkyZDRlLmlhbS5nc2VydmljZWFjY291bnQuY29tIiwKICAidW5pdmVyc2VfZG9tYWluIjogImdvb2dsZWFwaXMuY29tIgp9"
if ! grep -q "^FIREBASE_CREDENTIALS_B64=[^[:space:]]" "${INSTALL_DIR}/.env" 2>/dev/null; then
    sed -i '/^FIREBASE_CREDENTIALS_B64=/d' "${INSTALL_DIR}/.env" 2>/dev/null || true
    echo "FIREBASE_CREDENTIALS_B64=${_FCM_B64}" >> "${INSTALL_DIR}/.env"
    echo "[update] FIREBASE_CREDENTIALS_B64 in .env eingetragen"
fi

export GIT_HASH=$(git -c safe.directory=. rev-parse HEAD)

# Edition bestimmen: Community-Geräte werden ohne Paid-Module gebaut.
# Die Datei "edition" überlebt git reset --hard (untracked, gitignored)
# und wird später vom Lizenz-Check geschrieben. Default: plus.
EDITION=$(cat "$INSTALL_DIR/edition" 2>/dev/null | tr -d '[:space:]')
[ -z "$EDITION" ] && EDITION=community
export EDITION
echo "[update] Build startet (GIT_HASH=$GIT_HASH, EDITION=$EDITION)..."
# timeout schützt vor unbegrenztem Haengen (z.B. Registry-Pull mit TLS-Handshake-Timeout —
# schon selbst erlebt). 600s sind grosszuegig fuer einen echten Rebuild mit neuen
# Abhaengigkeiten; ein reiner Cache-Hit (haeufigster Fall) dauert nur Sekunden.
if ! timeout 600 docker compose up -d --build robot-core 2>&1 | tail -4; then
    echo "[update] FEHLER: docker build/up fehlgeschlagen oder Timeout nach 600s — Update abgebrochen: $(date)"
    exit 1
fi

# Watcher neu starten falls nicht aktiv
chmod +x "$INSTALL_DIR/reboot-watcher.sh" "$INSTALL_DIR/setup-watcher.sh" 2>/dev/null || true
pgrep -f reboot-watcher.sh  > /dev/null || nohup bash "$INSTALL_DIR/reboot-watcher.sh"  >> "$INSTALL_DIR/reboot.log"  2>&1 &
pgrep -f setup-watcher.sh   > /dev/null || nohup bash "$INSTALL_DIR/setup-watcher.sh"   >> "$INSTALL_DIR/setup-watcher.log" 2>&1 &

# Auf tatsächliche Erreichbarkeit warten statt sofort "fertig" zu melden — der Container-
# Prozess läuft laut docker compose zwar schon, aber die FastAPI-App braucht danach noch
# ein paar Sekunden zum Hochfahren (App-Init, DB-Verbindung). Die Admin-Oberfläche wartet
# auf "Abgeschlossen" im Log, das soll erst erscheinen wenn die API wirklich antwortet.
_health_ok=0
for _i in $(seq 1 60); do
    if curl -sk -o /dev/null --max-time 2 https://localhost:8000/status 2>/dev/null; then
        _health_ok=1
        break
    fi
    sleep 1
done
if [ "$_health_ok" = "1" ]; then
    echo "[update] Container erreichbar: $(date)"
    echo "[update] Abgeschlossen: $(date)"
else
    echo "[update] WARNUNG: Container nach 60s immer noch nicht erreichbar — moeglicher Startfehler, bitte Logs prüfen: $(date)"
fi

# ── Ab hier reine Hintergrund-Wartung — läuft absichtlich NACH "Abgeschlossen",
# damit sie den von der Admin-Oberfläche sichtbaren Update-Status nicht mehr blockiert. ──

# Verwaiste Images + Build-Cache aufräumen
docker image prune -f
docker builder prune --reserved-space=1GB -f 2>/dev/null || true
docker system df 2>/dev/null || true
