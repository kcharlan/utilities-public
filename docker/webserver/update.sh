#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
STACK_DIR="${PROPAGATE_STACK_ROOT:-$SCRIPT_DIR}"
STACK_DIR="${STACK_DIR:A}"
cd "$STACK_DIR"
compose=(docker compose)
if [[ -n "${PROPAGATE_STACK_ROOT:-}" ]]; then
  compose+=(-p webserver --project-directory "$SCRIPT_DIR" --env-file "$STACK_DIR/.env" -f "$SCRIPT_DIR/docker-compose.yml")
fi

# Moving base-image tags are intentional. Application dependency graphs come
# from checked-in Python and npm locks; refresh/audit those separately.
"${compose[@]}" pull web
"${compose[@]}" build --pull --no-cache index app_py app_node
"${compose[@]}" up -d --force-recreate --remove-orphans --wait --wait-timeout 120

curl -fsS http://127.0.0.1:7711/api/py/hello >/dev/null
curl -fsS http://127.0.0.1:7711/api/node/hello >/dev/null
curl -fsS http://127.0.0.1:7711/configure/api/endpoints >/dev/null

"${compose[@]}" ps
