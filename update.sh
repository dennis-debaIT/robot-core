#!/bin/bash
set -e
LOG=/var/lib/docker/volumes/robot-core_robot_core_data/_data/update.log
cd ~/robot-core

git -c safe.directory=. fetch origin main

LOCAL=$(git -c safe.directory=. rev-parse HEAD)
REMOTE=$(git -c safe.directory=. rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
  echo "[update] Bereits aktuell ($LOCAL)" | tee -a "$LOG"
  exit 0
fi

echo "[update] Update: $LOCAL -> $REMOTE" | tee -a "$LOG"
git -c safe.directory=. pull --ff-only origin main 2>&1 | tee -a "$LOG"

GIT_HASH=$(git -c safe.directory=. rev-parse HEAD)
echo "[update] Build startet..." | tee -a "$LOG"
docker compose build --build-arg GIT_HASH="$GIT_HASH" robot-core 2>&1 | tail -3 | tee -a "$LOG"
docker compose up -d robot-core 2>&1 | tail -3 | tee -a "$LOG"
echo "[update] Abgeschlossen: $(date)" | tee -a "$LOG"
