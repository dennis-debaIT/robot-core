#!/bin/bash
LOG=/var/lib/docker/volumes/robot-core_robot_core_data/_data/update.log
cd ~/robot-core

git -c safe.directory=. fetch origin main

LOCAL=REMOTE=
if [ "" = "" ]; then
  echo "[update] Bereits aktuell (\)" | tee -a   exit 0
fi

echo "[update] Update: \ -> " | tee -a git pull --ff-only origin main 2>&1 | tee -a 
GIT_HASH=echo "[update] Build startet..." | tee -a docker compose build --build-arg GIT_HASH=\ robot-core 2>&1 | tail -3 | tee -a docker compose up -d robot-core 2>&1 | tail -3 | tee -a echo "[update] Abgeschlossen: /15/2026 19:05:10" | tee -a 