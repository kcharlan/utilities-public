#!/bin/bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./install_standalone.sh [target-path]

Builds a single-file standalone Model Sentinel zipapp and installs it to the
target path. Default target:

  ~/Library/Scripts/model-sentinel

The installer also seeds runtime-home config files if they do not already
exist:

  ~/.model_sentinel/providers.env
  ~/.model_sentinel/settings.env
  ~/.model_sentinel/launchd.env

Examples:
  ./install_standalone.sh
  ./install_standalone.sh "$HOME/bin/model-sentinel"
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_HOME="${MODEL_SENTINEL_HOME:-$HOME/.model_sentinel}"
TARGET_PATH="${1:-$HOME/Library/Scripts/model-sentinel}"

if [ -d "$TARGET_PATH" ]; then
  TARGET_PATH="$TARGET_PATH/model-sentinel"
fi

TARGET_DIR="$(dirname "$TARGET_PATH")"

mkdir -p "$RUNTIME_HOME" "$TARGET_DIR"

TMP_TARGET="$(mktemp "$TARGET_DIR/model-sentinel.XXXXXX")"
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/model-sentinel-zipapp.XXXXXX")"

cleanup() {
  rm -f "$TMP_TARGET"
  rm -rf "$STAGING_DIR"
}

trap cleanup EXIT

stage_zipapp_source() {
  mkdir -p "$STAGING_DIR/model_sentinel"

  cp "$SCRIPT_DIR/__main__.py" "$STAGING_DIR/__main__.py"
  cp "$SCRIPT_DIR/model_sentinel/"*.py "$STAGING_DIR/model_sentinel/"
}

stage_zipapp_source

python3 -m zipapp "$STAGING_DIR" -o "$TMP_TARGET" -p "/usr/bin/env python3"
chmod +x "$TMP_TARGET"
mv "$TMP_TARGET" "$TARGET_PATH"
trap - EXIT

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

cat <<EOF

Standalone install complete.

Installed executable:
  $TARGET_PATH

Runtime home:
  $RUNTIME_HOME

Next steps:
  1. Review $RUNTIME_HOME/providers.env
  2. Review $RUNTIME_HOME/settings.env
  3. If your credentials come from a sourced shell file, either:
     - source that file before running $TARGET_PATH, or
     - put the bootstrap lines in $RUNTIME_HOME/launchd.env for scheduled runs
  4. Run: "$TARGET_PATH" healthcheck
  5. Run: "$TARGET_PATH" scan --save

If you use terminal-notifier, ensure it is in PATH or set
MODEL_SENTINEL_TERMINAL_NOTIFIER_PATH in $RUNTIME_HOME/settings.env.
EOF
