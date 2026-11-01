#!/bin/zsh
set -euo pipefail

DATA_DIR="$(cd "${PROPAGATE_STACK_ROOT:-$(dirname "$0")}" && pwd -P)"
dir="$DATA_DIR"
while true; do
  if [[ -e "$dir/.git" || -L "$dir/.git" ]]; then
    print -u2 'Refusing to store Actual data inside a Git worktree; use a private operational copy.'
    exit 1
  fi
  [[ "$dir" == / ]] && break
  dir="${dir:h}"
done

# Keep the previous container until its replacement has started successfully.
docker pull actualbudget/actual-server:latest
old="actual-rollback-$$"
docker stop actual
docker rename actual "$old" || { docker start actual; exit 1; }
wait_for_health() {
  local health attempt
  for attempt in {1..60}; do
    health="$(docker inspect --format '{{.State.Health.Status}}' "$1")" || return 1
    case "$health" in
      healthy) return 0 ;;
      starting) sleep 2 ;;
      *) return 1 ;;
    esac
  done
  return 1
}
candidate=""
if candidate="$(docker create --pull=never \
  --restart=unless-stopped \
  --health-cmd="node /app/scripts/health-check.js" \
  --health-interval=30s \
  --health-timeout=5s \
  --health-retries=3 \
  --health-start-period=10s \
  -p 127.0.0.1:5006:5006 \
  -v "${DATA_DIR}:/data" --name "actual-candidate-$$" actualbudget/actual-server:latest)" &&
  docker start "$candidate" && wait_for_health "$candidate" && docker rename "$candidate" actual; then
  docker rm "$old"
else
  [[ -z "$candidate" ]] || docker rm -f "$candidate" || true
  docker rename "$old" actual && docker start actual || print -u2 "Rollback failed; recover container $old manually."
  exit 1
fi
