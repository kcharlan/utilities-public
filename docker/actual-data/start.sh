#!/bin/zsh

DATA_DIR="$(cd "$(dirname "$0")" && pwd)"

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
