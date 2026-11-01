#!/bin/zsh
set -euo pipefail

DATA_DIR="$(cd "$(dirname "$0")" && pwd -P)"
dir="$DATA_DIR"
while true; do
  if [[ -e "$dir/.git" || -L "$dir/.git" ]]; then
    print -u2 'Refusing to store Actual data inside a Git worktree; use a private operational copy.'
    exit 1
  fi
  [[ "$dir" == / ]] && break
  dir="${dir:h}"
done

docker run --pull=always \
  --restart=unless-stopped \
  --health-cmd="node /app/scripts/health-check.js" \
  --health-interval=30s \
  --health-timeout=5s \
  --health-retries=3 \
  --health-start-period=10s \
  -d \
  -p 127.0.0.1:5006:5006 \
  -v "${DATA_DIR}:/data" \
  --name actual \
  actualbudget/actual-server:latest
