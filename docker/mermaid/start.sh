#!/bin/zsh
docker run --pull=always \
  --restart=unless-stopped \
  -d \
  -p 5008:8080 \
  --name mermaid \
  ghcr.io/mermaid-js/mermaid-live-editor