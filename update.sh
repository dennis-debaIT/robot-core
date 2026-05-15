#!/bin/bash
set -e
LOG=~/robot-core/update.log
cd ~/robot-core

echo "[update] Starte Update: $(date)" | tee -a "$LOG"

git -c safe.directory=. pull --ff-only origin main 2>&1 | tee -a "$LOG"

export GIT_HASH
GIT_HASH=$(git -c safe.directory=. rev-parse HEAD)
echo "[update] Build startet (GIT_HASH=$GIT_HASH)..." | tee -a "$LOG"
docker compose build --build-arg GIT_HASH="$GIT_HASH" robot-core 2>&1 | tail -3 | tee -a "$LOG"
docker compose up -d robot-core 2>&1 | tail -3 | tee -a "$LOG"
echo "[update] Abgeschlossen: $(date)" | tee -a "$LOG"
