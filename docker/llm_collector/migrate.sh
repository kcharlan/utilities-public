#!/bin/bash

set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_DEPLOY_DIR="$HOME/docker/llm_collector"
DEFAULT_BACKUP_ROOT="$HOME/docker/llm_collector_migration_backups"
DEPLOY_DIR="$DEFAULT_DEPLOY_DIR"
BACKUP_ROOT="$DEFAULT_BACKUP_ROOT"
DRY_RUN=0
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR=""

usage() {
  cat <<EOF
Usage: ./migrate.sh [--dry-run] [--deploy-dir PATH] [--backup-root PATH]

Safely migrates this source tree to the deployed llm_collector directory.

Steps:
  1. Run source tests in a project virtual environment.
  2. Back up deployed code, external secrets, and external runtime state.
  3. If live counters are non-empty, call reset_collector.sh to snapshot and roll them up.
  4. Copy source with rsync while preserving secrets, state, snapshots, and logs.
  5. Regenerate extension/config.local.js from the external secret env.
  6. Rebuild/restart Docker Compose and validate health/counters.

Options:
  --dry-run           Show intended actions without changing files or containers.
  --deploy-dir PATH   Deployed llm_collector path. Default: $DEFAULT_DEPLOY_DIR
  --backup-root PATH  Directory where timestamped backups are stored.
                      Default: $DEFAULT_BACKUP_ROOT
  --help              Show this help.
EOF
}

log() {
  printf '[llm-migrate] %s\n' "$*"
}

die() {
  printf '[llm-migrate] ERROR: %s\n' "$*" >&2
  exit 1
}

run() {
  if [ "$DRY_RUN" = "1" ]; then
    printf '[llm-migrate] DRY RUN:'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

api_key_hash_from_dir() {
  local config_dir="$1"

  if ! load_config_from_dir "$config_dir" >/dev/null 2>&1; then
    printf 'missing'
    return 0
  fi

  if [ -z "${API_KEY:-}" ]; then
    printf 'missing'
    return 0
  fi

  # Hash only the API key so setup.sh can add newly introduced non-secret
  # defaults without being flagged as a secret rotation.
  printf '%s' "$API_KEY" | shasum -a 256 | awk '{print $1}'
}

load_config_from_dir() {
  local config_dir="$1"

  if [ ! -f "$config_dir/local_config.sh" ]; then
    return 1
  fi

  # shellcheck disable=SC1090
  . "$config_dir/local_config.sh"
  load_llm_collector_env
}

source_test() {
  log "Running source tests in a project virtual environment."

  if [ "$DRY_RUN" = "1" ]; then
    log "DRY RUN: would create/use $SOURCE_DIR/.venv and run pytest."
    return 0
  fi

  if [ ! -x "$SOURCE_DIR/.venv/bin/python" ]; then
    python3 -m venv "$SOURCE_DIR/.venv"
  fi

  "$SOURCE_DIR/.venv/bin/python" -m pip install --upgrade pip
  "$SOURCE_DIR/.venv/bin/python" -m pip install -r "$SOURCE_DIR/collector/requirements.txt" pytest
  "$SOURCE_DIR/.venv/bin/python" -m pytest "$SOURCE_DIR/collector" "$SOURCE_DIR/snapshots"
}

backup_path() {
  local src="$1"
  local dst="$2"

  if [ -e "$src" ]; then
    run mkdir -p "$(dirname "$dst")"
    run rsync -a \
      --exclude gunicorn.ctl \
      --exclude __pycache__/ \
      --exclude .pytest_cache/ \
      --exclude '*.pyc' \
      "$src" "$dst"
  else
    log "Backup source not present, skipping: $src"
  fi
}

make_backups() {
  BACKUP_DIR="$BACKUP_ROOT/$TIMESTAMP"
  log "Backing up deployed files and external runtime data to $BACKUP_DIR."

  run mkdir -p "$BACKUP_DIR"
  backup_path "$DEPLOY_DIR/" "$BACKUP_DIR/deploy/"

  local secret_env="${LLM_COLLECTOR_SECRET_ENV:-${XDG_CONFIG_HOME:-$HOME/.config}/llm_collector/secret.env}"
  local data_dir="${LLM_COLLECTOR_DATA_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/llm_collector}"
  if load_config_from_dir "$DEPLOY_DIR" >/dev/null 2>&1 || load_config_from_dir "$SOURCE_DIR" >/dev/null 2>&1; then
    secret_env="$LLM_COLLECTOR_SECRET_ENV"
    data_dir="$LLM_COLLECTOR_DATA_DIR"
  fi
  backup_path "$secret_env" "$BACKUP_DIR/config/secret.env"
  backup_path "$data_dir/" "$BACKUP_DIR/state/"
}

curl_with_api_key() {
  curl -fsS -H "X-API-KEY: $API_KEY" "$@"
}

is_empty_counters_response() {
  local response="$1"
  local compact
  compact="$(printf '%s' "$response" | tr -d '[:space:]')"
  [ "$compact" = '{"counters":{}}' ]
}

reset_current_counters_if_needed() {
  log "Checking live counters before copy."

  if ! load_config_from_dir "$DEPLOY_DIR" >/dev/null 2>&1; then
    log "Existing deployed config could not be loaded; skipping pre-copy reset."
    return 0
  fi

  if [ -z "${API_KEY:-}" ] || [ -z "${COLLECTOR_URL:-}" ]; then
    log "Existing API key or collector URL is missing; skipping pre-copy reset."
    return 0
  fi

  if [ "$DRY_RUN" = "1" ]; then
    log "DRY RUN: would call $COLLECTOR_URL/counters and run reset_collector.sh only if counters are non-empty."
    return 0
  fi

  local counters
  if ! counters="$(curl_with_api_key "$COLLECTOR_URL/counters")"; then
    die "Could not read live counters from $COLLECTOR_URL/counters."
  fi

  if is_empty_counters_response "$counters"; then
    log "Live counters are empty; no pre-copy reset needed."
    return 0
  fi

  log "Live counters are non-empty; running deployed reset_collector.sh to snapshot and roll up current state."
  run "$DEPLOY_DIR/reset_collector.sh"

  counters="$(curl_with_api_key "$COLLECTOR_URL/counters")"
  is_empty_counters_response "$counters" || die "Counters are still non-empty after reset."
}

copy_source() {
  log "Copying source to deployed tree while preserving local secrets and runtime data."

  local rsync_args=(
    -av --delete
    --exclude .DS_Store
    --exclude MY_API_KEY.txt
    --exclude collector.log
    --exclude 'reset_launchd.log*'
    --exclude reset_launchd.err
    --exclude state.json
    --exclude snapshots/snapshots.csv
    --exclude 'snapshots/snapshot_*'
    --exclude extension/config.local.js
    --exclude gunicorn.ctl
    --exclude .venv/
    --exclude __pycache__/
    --exclude .pytest_cache/
    --exclude '*.pyc'
    "$SOURCE_DIR/"
    "$DEPLOY_DIR/"
  )

  run mkdir -p "$DEPLOY_DIR"
  if [ "$DRY_RUN" = "1" ]; then
    rsync -avn --delete \
      --exclude .DS_Store \
      --exclude MY_API_KEY.txt \
      --exclude collector.log \
      --exclude 'reset_launchd.log*' \
      --exclude reset_launchd.err \
      --exclude state.json \
      --exclude snapshots/snapshots.csv \
      --exclude 'snapshots/snapshot_*' \
      --exclude extension/config.local.js \
      --exclude gunicorn.ctl \
      --exclude .venv/ \
      --exclude __pycache__/ \
      --exclude .pytest_cache/ \
      --exclude '*.pyc' \
      "$SOURCE_DIR/" \
      "$DEPLOY_DIR/"
  else
    rsync "${rsync_args[@]}"
  fi
}

refresh_deployed_config() {
  log "Regenerating deployed extension config from external secret env."

  if [ "$DRY_RUN" = "1" ]; then
    log "DRY RUN: would run $DEPLOY_DIR/setup.sh --non-interactive."
    return 0
  fi

  (cd "$DEPLOY_DIR" && ./setup.sh --non-interactive)
}

restart_container() {
  log "Rebuilding and restarting Docker container."

  if [ "$DRY_RUN" = "1" ]; then
    log "DRY RUN: would run $DEPLOY_DIR/llm_collector_container/up.sh."
    return 0
  fi

  (cd "$DEPLOY_DIR/llm_collector_container" && ./up.sh)
}

validate_deployment() {
  log "Validating deployed collector."

  if ! load_config_from_dir "$DEPLOY_DIR" >/dev/null 2>&1; then
    die "Could not load deployed local_config.sh after migration."
  fi

  if [ "$DRY_RUN" = "1" ]; then
    log "DRY RUN: would validate Docker health, /health, /counters, mounts, and secret hash."
    return 0
  fi

  local health_status
  local attempt
  for attempt in $(seq 1 30); do
    health_status="$(docker inspect llm-collector --format '{{.State.Health.Status}}' 2>/dev/null || true)"
    if [ "$health_status" = "healthy" ]; then
      break
    fi
    log "Container health is '$health_status'; waiting for healthy ($attempt/30)."
    sleep 2
  done

  [ "$health_status" = "healthy" ] || die "Container health is '$health_status', expected healthy."

  curl -fsS "$COLLECTOR_URL/health" >/dev/null
  curl_with_api_key "$COLLECTOR_URL/counters" >/dev/null

  docker inspect llm-collector --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'

  [ -f "$LLM_COLLECTOR_SECRET_ENV" ] || die "Secret env missing after migration: $LLM_COLLECTOR_SECRET_ENV"
  [ -d "$LLM_COLLECTOR_DATA_DIR" ] || die "Data dir missing after migration: $LLM_COLLECTOR_DATA_DIR"
  [ -f "$DEPLOY_DIR/extension/config.local.js" ] || die "Extension config was not generated."
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --dry-run)
        DRY_RUN=1
        ;;
      --deploy-dir)
        shift
        [ "$#" -gt 0 ] || die "--deploy-dir requires a path"
        DEPLOY_DIR="$1"
        ;;
      --backup-root)
        shift
        [ "$#" -gt 0 ] || die "--backup-root requires a path"
        BACKUP_ROOT="$1"
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        usage >&2
        die "Unknown option: $1"
        ;;
    esac
    shift
  done

  DEPLOY_DIR="${DEPLOY_DIR%/}"
  BACKUP_ROOT="${BACKUP_ROOT%/}"
}

main() {
  parse_args "$@"

  require_cmd rsync
  require_cmd curl
  require_cmd docker
  require_cmd shasum
  require_cmd awk

  [ -f "$SOURCE_DIR/collector/collector.py" ] || die "Source dir does not look like llm_collector: $SOURCE_DIR"

  local before_api_key_hash
  local after_api_key_hash
  before_api_key_hash="$(api_key_hash_from_dir "$DEPLOY_DIR")"

  source_test
  make_backups
  reset_current_counters_if_needed
  copy_source
  refresh_deployed_config
  restart_container
  validate_deployment

  after_api_key_hash="$(api_key_hash_from_dir "$DEPLOY_DIR")"
  if [ "$DRY_RUN" != "1" ] && [ "$before_api_key_hash" != "missing" ] && [ "$before_api_key_hash" != "$after_api_key_hash" ]; then  # pragma: allowlist secret
    die "API key changed during migration. Backup is at $BACKUP_DIR."
  fi

  log "Migration complete."
  if [ -n "$BACKUP_DIR" ]; then
    log "Backup directory: $BACKUP_DIR"
  fi
  log "Manual step required: reload the unpacked browser extension so it picks up the updated extension/config.local.js."
}

main "$@"
