#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

docker compose pull excalidraw
docker compose up -d --force-recreate --wait --wait-timeout 120
docker compose ps
