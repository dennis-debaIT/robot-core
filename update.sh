#!/bin/bash
set -e
LOG=~/robot-core/update.log
cd ~/robot-core

echo "[update] Starte Update: $(date)" | tee -a "$LOG"
git -c safe.directory=. fetch origin main 2>&1 | tee -a "$LOG"
git -c safe.directory=. reset --hard origin/main 2>&1 | tee -a "$LOG"

export GIT_HASH=$(git -c safe.directory=. rev-parse HEAD)
echo "[update] Build startet (GIT_HASH=$GIT_HASH)..." | tee -a "$LOG"
docker compose up -d --build robot-core 2>&1 | tail -4 | tee -a "$LOG"
echo "[update] Abgeschlossen: $(date)" | tee -a "$LOG"
