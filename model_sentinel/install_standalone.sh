#!/bin/bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./install_standalone.sh [target-path]
       ./install_standalone.sh --check [target-path]

Builds a single-file standalone Model Sentinel zipapp and installs it to the
target path. Default target:

  ~/Library/Scripts/model-sentinel

Building requires uv, which runs build_standalone.py on an interpreter it
selects from that script's header (never downloading one). --check needs
no uv: it only compares the installed target with the source.

The installer also seeds runtime-home config files if they do not already
exist:

  ~/.model_sentinel/providers.env
  ~/.model_sentinel/settings.env
  ~/.model_sentinel/launchd.env

Examples:
  ./install_standalone.sh
  ./install_standalone.sh "$HOME/bin/model-sentinel"
  ./install_standalone.sh --check
  ./install_standalone.sh --check "$HOME/bin/model-sentinel"
EOF
}

ACTION="install"
case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
  --check)
    ACTION="check"
    shift
    ;;
  --*)
    usage >&2
    exit 2
    ;;
esac

if [ "$#" -gt 1 ]; then
  usage >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_HOME="${MODEL_SENTINEL_HOME:-$HOME/.model_sentinel}"
TARGET_PATH="${1:-$HOME/Library/Scripts/model-sentinel}"
BACKUP_ROOT="${MODEL_SENTINEL_BACKUP_ROOT:-$HOME/.utilities-deploy-backups/model-sentinel}"

if [ -d "$TARGET_PATH" ]; then
  TARGET_PATH="$TARGET_PATH/model-sentinel"
fi

TARGET_DIR="$(dirname "$TARGET_PATH")"
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/model-sentinel-zipapp.XXXXXX")"
TMP_TARGET=""

cleanup() {
  if [ -n "$TMP_TARGET" ]; then
    rm -f "$TMP_TARGET"
  fi
  rm -rf "$STAGING_DIR"
}

trap cleanup EXIT

stage_zipapp_source() {
  mkdir -p "$STAGING_DIR/model_sentinel"

  cp "$SCRIPT_DIR/__main__.py" "$STAGING_DIR/__main__.py"
  cp "$SCRIPT_DIR/model_sentinel/"*.py "$STAGING_DIR/model_sentinel/"
  cp -R "$SCRIPT_DIR/model_sentinel/browse" "$STAGING_DIR/model_sentinel/browse"
  find "$STAGING_DIR" -type d -name '__pycache__' -prune -exec rm -rf {} +
  find "$STAGING_DIR" -type f -name '*.pyc' -delete
}

stage_zipapp_source

SOURCE_HASH="$(
  cd "$STAGING_DIR"
  find . -type f \
    ! -path './model_sentinel/_packaged_build.py' \
    -exec shasum -a 256 {} \; \
    | LC_ALL=C sort \
    | shasum -a 256 \
    | awk '{print $1}'
)"

if ! printf '%s\n' "$SOURCE_HASH" | grep -Eq '^[0-9a-f]{64}$'; then
  echo "Failed to calculate a valid standalone source SHA-256." >&2
  exit 1
fi

BUILD_REVISION="unknown"
if revision="$(git -C "$SCRIPT_DIR" rev-parse --short=12 HEAD 2>/dev/null)"; then
  BUILD_REVISION="$revision"
  if [ -n "$(git -C "$SCRIPT_DIR" status --porcelain -- . 2>/dev/null)" ]; then
    BUILD_REVISION="${BUILD_REVISION}+modified"
  fi
fi

if ! printf '%s\n' "$BUILD_REVISION" | grep -Eq '^([0-9a-f]{12}(\+modified)?|unknown)$'; then
  echo "Failed to resolve safe standalone Git revision metadata." >&2
  exit 1
fi

BUILD_TIME_UTC="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
if ! printf '%s\n' "$BUILD_TIME_UTC" | grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'; then
  echo "Failed to resolve safe standalone build timestamp metadata." >&2
  exit 1
fi

cat > "$STAGING_DIR/model_sentinel/_packaged_build.py" <<EOF
BUILD_KIND = "standalone"
BUILD_REVISION = "$BUILD_REVISION"
BUILD_SOURCE_HASH = "$SOURCE_HASH"
BUILD_TIME_UTC = "$BUILD_TIME_UTC"
EOF

target_version() {
  "$1" --version 2>&1
}

version_has_expected_hash() {
  printf '%s\n' "$1" \
    | tr ' ' '\n' \
    | grep -Fxq "source_sha256=$SOURCE_HASH"
}

if [ "$ACTION" = "check" ]; then
  if [ ! -f "$TARGET_PATH" ] || [ ! -x "$TARGET_PATH" ]; then
    echo "stale: standalone target is missing or not executable: $TARGET_PATH" >&2
    exit 1
  fi

  if ! VERSION_OUTPUT="$(target_version "$TARGET_PATH")"; then
    echo "stale: standalone target could not report build identity: $TARGET_PATH" >&2
    if [ -n "$VERSION_OUTPUT" ]; then
      printf '%s\n' "$VERSION_OUTPUT" >&2
    fi
    exit 1
  fi

  if version_has_expected_hash "$VERSION_OUTPUT"; then
    echo "current: standalone target matches source_sha256=$SOURCE_HASH"
    exit 0
  fi

  echo "stale: standalone target does not match current source." >&2
  echo "Expected source_sha256=$SOURCE_HASH" >&2
  printf '%s\n' "$VERSION_OUTPUT" >&2
  exit 1
fi

# uv selects and owns the build interpreter (build_standalone.py's PEP 723
# header) and never downloads one; the build never runs on whatever python3
# is first on PATH.
if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to build the standalone: https://docs.astral.sh/uv/ (brew install uv)." >&2
  exit 1
fi

mkdir -p "$RUNTIME_HOME" "$TARGET_DIR"
TMP_TARGET="$(mktemp "$TARGET_DIR/model-sentinel.XXXXXX")"

if ! uv run --no-python-downloads --script "$SCRIPT_DIR/build_standalone.py" "$STAGING_DIR" "$TMP_TARGET"; then
  echo "Standalone build failed; the existing target was not changed." >&2
  exit 1
fi
chmod +x "$TMP_TARGET"

if ! VERSION_OUTPUT="$(target_version "$TMP_TARGET")"; then
  echo "Standalone candidate verification failed before replacement." >&2
  if [ -n "$VERSION_OUTPUT" ]; then
    printf '%s\n' "$VERSION_OUTPUT" >&2
  fi
  exit 1
fi

if ! version_has_expected_hash "$VERSION_OUTPUT"; then
  echo "Standalone candidate verification failed: source hash mismatch." >&2
  printf '%s\n' "$VERSION_OUTPUT" >&2
  exit 1
fi

# Refuse linked ancestors, except macOS's standard system aliases.
safe_backup_path() {
  local path="$1"
  while [ "$path" != / ] && [ "${path%/}" != "$path" ]; do path="${path%/}"; done
  case "$path" in /*) ;; *) return 1 ;; esac
  case "/$path/" in */../*|*/./*) return 1 ;; esac
  while [ "$path" != / ]; do
    if [ -L "$path" ]; then
      case "$path" in /tmp|/var) [ "$(uname -s)" = Darwin ] && [ -d "$path" ] || return 1 ;; *) return 1 ;; esac
    elif [ -e "$path" ] && [ ! -d "$path" ]; then
      return 1
    fi
    path="$(dirname "$path")"
  done
}

prune_backups() {
  local path candidate stamp best_stamp best index i mode
  local LC_ALL=C
  local -a candidates stamps
  candidates=() stamps=()
  if ! safe_backup_path "$BACKUP_ROOT" || [ ! -d "$BACKUP_ROOT" ]; then
    echo "Warning: unsafe backup root: $BACKUP_ROOT" >&2; return
  fi
  mode=$(stat -f '%Lp' "$BACKUP_ROOT") || { echo "Warning: cannot stat $BACKUP_ROOT" >&2; return; }
  if [ $((8#$mode & 0300)) -ne 192 ] || [ ! -w "$BACKUP_ROOT" ] || [ ! -x "$BACKUP_ROOT" ]; then
    echo "Warning: backup root is not writable/searchable: $BACKUP_ROOT" >&2; return
  fi
  if [ $((8#$mode & 0400)) -eq 0 ] || [ ! -r "$BACKUP_ROOT" ]; then
    echo "Warning: cannot enumerate backup root: $BACKUP_ROOT" >&2; return
  fi
  for path in "$BACKUP_ROOT"/copy-*; do
    [ -d "$path" ] && [ ! -L "$path" ] || continue
    stamp=$(perl -MTime::HiRes=stat -e '@s = stat($ARGV[0]); @s or exit 1; printf "%020.9f", $s[9]' "$path") || { echo "Warning: cannot stat $path" >&2; continue; }
    candidates+=("$path") stamps+=("$stamp")
  done
  # Select newest twice, using descending name to break equal-mtime ties.
  for i in 1 2; do
    best=-1; best_stamp=""
    for ((index=0; index<${#candidates[@]}; index++)); do
      candidate="${candidates[$index]}"; [ -n "$candidate" ] || continue
      stamp="${stamps[$index]}"
      if [[ "$stamp" > "$best_stamp" ]] || { [ "$stamp" = "$best_stamp" ] && [[ "$candidate" > "${candidates[$best]}" ]]; }; then
        best=$index; best_stamp=$stamp
      fi
    done
    [ "$best" -ge 0 ] && candidates[$best]=""
  done
  for path in "${candidates[@]}"; do
    [ -n "$path" ] || continue
    if ! find -P "$path" -type d -exec chmod u+rwx {} + || ! rm -rf -- "$path"; then
      echo "Warning: could not prune backup: $path" >&2
    fi
  done
}

BACKUP_CREATED=""
if [ -e "$TARGET_PATH" ] || [ -L "$TARGET_PATH" ]; then
  if ! safe_backup_path "$BACKUP_ROOT"; then
    echo "Unsafe backup root: $BACKUP_ROOT" >&2; exit 1
  fi
  if [ -d "$BACKUP_ROOT" ]; then
    root_mode=$(stat -f '%Lp' "$BACKUP_ROOT")
    if [ $((8#$root_mode & 0300)) -ne 192 ] || [ ! -w "$BACKUP_ROOT" ] || [ ! -x "$BACKUP_ROOT" ]; then
      echo "Backup root is not writable/searchable: $BACKUP_ROOT" >&2; exit 1
    fi
  fi
  (umask 077; mkdir -p "$BACKUP_ROOT")
  chmod 700 "$BACKUP_ROOT"
  BACKUP_CREATED=$(mktemp -d "$BACKUP_ROOT/copy-XXXXXX")
  cp "$TARGET_PATH" "$BACKUP_CREATED/model-sentinel"
  chmod 600 "$BACKUP_CREATED/model-sentinel"
fi

mv "$TMP_TARGET" "$TARGET_PATH"
TMP_TARGET=""

copy_if_missing() {
  local source_path="$1"
  local target_path="$2"
  local label="$3"

  if [ -f "$target_path" ]; then
    printf "Keeping existing %s: %s\n" "$label" "$target_path"
    return 0
  fi

  cp "$source_path" "$target_path"
  printf "Created %s: %s\n" "$label" "$target_path"
}

copy_if_missing "$SCRIPT_DIR/providers.env.template" "$RUNTIME_HOME/providers.env" "provider config"
copy_if_missing "$SCRIPT_DIR/settings.env.template" "$RUNTIME_HOME/settings.env" "settings config"
copy_if_missing "$SCRIPT_DIR/launchd.env.template" "$RUNTIME_HOME/launchd.env" "launchd env file"

chmod 600 "$RUNTIME_HOME/launchd.env" || true

if [ -n "$BACKUP_CREATED" ]; then
  prune_backups
fi

cat <<EOF

Standalone install complete.

Installed executable:
  $TARGET_PATH

Installed build:
  $VERSION_OUTPUT

Runtime home:
  $RUNTIME_HOME

Next steps:
  1. Review $RUNTIME_HOME/providers.env
  2. Review $RUNTIME_HOME/settings.env
  3. For file mode, configure the credential settings and manually run:
     "$TARGET_PATH" credentials refresh
     Or after loading your existing secrets shell:
     "$TARGET_PATH" credentials refresh --from-environment
     In environment mode, if credentials come from a sourced shell file, either:
     - source that file before running $TARGET_PATH, or
     - put the bootstrap lines in $RUNTIME_HOME/launchd.env for scheduled runs
  4. Run: "$TARGET_PATH" healthcheck
  5. Run: "$TARGET_PATH" scan --save

File-mode scans read only the private cache, never the refresh mount.
Refresh manually after rotation. The cache is plaintext at rest (0700 parent, 0600 file).
Existing configs/bootstrap files are preserved; review obsolete bootstrap lines manually.

After repository updates, rebuild this point-in-time copy or verify it with:
  "$SCRIPT_DIR/install_standalone.sh" --check "$TARGET_PATH"

If you use terminal-notifier, ensure it is in PATH or set
MODEL_SENTINEL_TERMINAL_NOTIFIER_PATH in $RUNTIME_HOME/settings.env.
EOF
