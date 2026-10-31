#!/bin/zsh

set -euo pipefail

cd "${0:A:h}"
./up.sh
docker compose ps
