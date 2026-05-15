#!/bin/bash
set -e
cd ~/robot-core

git fetch origin main

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
  echo "[update] Bereits aktuell ($LOCAL)"
  exit 0
fi

echo "[update] Neues Update: $LOCAL -> $REMOTE"
git pull --ff-only origin main

GIT_HASH=$(git rev-parse HEAD)
docker compose build --build-arg GIT_HASH=$GIT_HASH robot-core
docker compose up -d robot-core
echo "[update] Abgeschlossen: $(date)"
