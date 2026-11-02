#!/bin/zsh

set -euo pipefail

docker pull ghcr.io/mermaid-js/mermaid-live-editor
old="mermaid-rollback-$$"
docker stop mermaid
docker rename mermaid "$old" || { docker start mermaid; exit 1; }
candidate=""
if candidate="$(docker create --pull=never --restart=unless-stopped -p 127.0.0.1:5008:8080 \
  --name "mermaid-candidate-$$" ghcr.io/mermaid-js/mermaid-live-editor)" &&
  docker start "$candidate" && docker rename "$candidate" mermaid; then
  docker rm "$old"
else
  [[ -z "$candidate" ]] || docker rm -f "$candidate" || true
  docker rename "$old" mermaid && docker start mermaid || print -u2 "Rollback failed; recover container $old manually."
  exit 1
fi
