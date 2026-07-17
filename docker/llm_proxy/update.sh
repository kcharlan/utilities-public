#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Refresh the moving Python base and all allowed dependency ranges.
docker compose build --pull --no-cache
docker compose up -d --force-recreate --wait --wait-timeout 120
curl -fsS http://127.0.0.1:4141/health >/dev/null
docker compose ps
