#!/bin/zsh

set -euo pipefail
setopt null_glob

typeset -i AGGRESSIVE=0
typeset -i WITH_VOLUMES=0
typeset -i WITH_DESKTOP_RECLAIM=0
typeset -i DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: ./docker-disk-compact.zsh [options]

Reclaims Docker Desktop disk space on macOS by pruning unused Docker data and
reporting the real on-disk size of Docker.raw before and after.

Options:
  --aggressive            Also remove unused images with docker image prune -a
  --with-volumes          Also remove unused volumes with docker volume prune
  --with-desktop-reclaim  Run docker/desktop-reclaim-space as a best-effort step
  --dry-run               Print commands without executing them
  --help                  Show this help text

Notes:
  - The script uses du/stat, not ls, because Docker.raw is a sparse file.
  - Safe default: build cache, stopped containers, dangling images, and
    unused networks are pruned. Volumes are kept unless you opt in.
EOF
}

log() {
  print -- "$*"
}

warn() {
  print -- "warning: $*" >&2
}

die() {
  print -- "error: $*" >&2
  exit 1
}

run() {
  log "+ $*"
  if (( ! DRY_RUN )); then
    "$@"
  fi
}

human_bytes() {
  local bytes="${1:-0}"
  awk -v bytes="$bytes" '
    BEGIN {
      split("B KiB MiB GiB TiB PiB", unit, " ")
      i = 1
      value = bytes + 0
      while (value >= 1024 && i < 6) {
        value /= 1024
        i++
      }
      printf "%.2f %s", value, unit[i]
    }
  '
}

find_raw_path() {
  local candidate
  local -a candidates

  candidates=(
    "$HOME/Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw"
    "$HOME/Library/Group Containers/group.com.docker/DockerDesktop/vms/0/data/Docker.raw"
  )

  for candidate in "${candidates[@]}"; do
    [[ -f "$candidate" ]] && {
      print -- "$candidate"
      return 0
    }
  done

  for candidate in \
    "$HOME"/Library/Containers/com.docker.docker/Data/vms/*/data/Docker.raw \
    "$HOME"/Library/Group\ Containers/group.com.docker/DockerDesktop/vms/*/data/Docker.raw; do
    [[ -f "$candidate" ]] && {
      print -- "$candidate"
      return 0
    }
  done

  return 1
}

physical_bytes() {
  local raw_path="$1"
  local kib
  kib="$(du -sk "$raw_path" | awk '{print $1}')"
  awk -v kib="$kib" 'BEGIN { printf "%.0f", kib * 1024 }'
}

logical_bytes() {
  local raw_path="$1"
  stat -f '%z' "$raw_path"
}

show_sizes() {
  local raw_path="$1"
  local physical logical

  physical="$(physical_bytes "$raw_path")"
  logical="$(logical_bytes "$raw_path")"

  log "Docker.raw: $raw_path"
  log "Physical on disk: $(human_bytes "$physical")"
  log "Logical max size: $(human_bytes "$logical")"
}

while (( $# > 0 )); do
  case "$1" in
    --aggressive)
      AGGRESSIVE=1
      ;;
    --with-volumes)
      WITH_VOLUMES=1
      ;;
    --with-desktop-reclaim)
      WITH_DESKTOP_RECLAIM=1
      ;;
    --dry-run)
      DRY_RUN=1
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      usage >&2
      die "unknown option: $1"
      ;;
  esac
  shift
done

command -v docker >/dev/null 2>&1 || die "docker CLI not found in PATH"
docker info >/dev/null 2>&1 || die "Docker Desktop does not appear to be running"

RAW_PATH="$(find_raw_path)" || die "could not locate Docker.raw"

BEFORE_PHYSICAL="$(physical_bytes "$RAW_PATH")"

log "Before cleanup:"
show_sizes "$RAW_PATH"
log ""
log "Docker summary before cleanup:"
if (( DRY_RUN )); then
  log "+ docker system df"
else
  docker system df
fi
log ""

run docker builder prune -a -f
run docker system prune -f

if (( AGGRESSIVE )); then
  run docker image prune -a -f
fi

if (( WITH_VOLUMES )); then
  run docker volume prune -f
fi

if (( WITH_DESKTOP_RECLAIM )); then
  if (( DRY_RUN )); then
    log "+ docker run --rm --platform linux/amd64 --privileged --pid=host docker/desktop-reclaim-space"
    log "+ docker image rm docker/desktop-reclaim-space"
  else
    if docker run --rm --platform linux/amd64 --privileged --pid=host docker/desktop-reclaim-space; then
      docker image rm docker/desktop-reclaim-space >/dev/null 2>&1 || true
    else
      warn "desktop reclaim helper failed; continuing"
    fi
  fi
fi

AFTER_PHYSICAL="$(physical_bytes "$RAW_PATH")"
RECLAIMED_BYTES="$(( BEFORE_PHYSICAL - AFTER_PHYSICAL ))"
if (( RECLAIMED_BYTES < 0 )); then
  RECLAIMED_BYTES=0
fi

log ""
log "After cleanup:"
show_sizes "$RAW_PATH"
log "Reclaimed on disk: $(human_bytes "$RECLAIMED_BYTES")"
log ""
log "Docker summary after cleanup:"
if (( DRY_RUN )); then
  log "+ docker system df"
else
  docker system df
fi
log ""
log "Reminder: ls -lh shows Docker.raw's logical size, not the space it is actually consuming."
