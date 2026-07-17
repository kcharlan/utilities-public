#!/bin/zsh

set -euo pipefail

docker run --pull=always \
  --restart=unless-stopped \
  -d \
  -p 127.0.0.1:5008:8080 \
  --name mermaid \
  ghcr.io/mermaid-js/mermaid-live-editor
