#!/bin/bash

set -euo pipefail

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  cat <<'EOF'
Usage: ./setup_launchd.sh

Seeds launchd support files into ~/.model_sentinel/:
  - launchd.env
  - install_launchd.sh

It does not overwrite existing runtime-home files.
After seeding those files:
  1. Edit ~/.model_sentinel/launchd.env
  2. Edit ~/.model_sentinel/install_launchd.sh if you want a different schedule or command
  3. Run ~/.model_sentinel/install_launchd.sh install
EOF
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_HOME="${MODEL_SENTINEL_HOME:-$HOME/.model_sentinel}"
LAUNCHD_ENV_TEMPLATE="$SCRIPT_DIR/launchd.env.template"
INSTALL_TEMPLATE="$SCRIPT_DIR/install_launchd.template.sh"
LAUNCHD_ENV_TARGET="$RUNTIME_HOME/launchd.env"
INSTALL_TARGET="$RUNTIME_HOME/install_launchd.sh"

mkdir -p "$RUNTIME_HOME"

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

copy_if_missing "$LAUNCHD_ENV_TEMPLATE" "$LAUNCHD_ENV_TARGET" "launchd env file"

if [ -f "$INSTALL_TARGET" ]; then
  printf "Keeping existing launchd installer: %s\n" "$INSTALL_TARGET"
else
  sed "s|__MODEL_SENTINEL_PROJECT_DIR__|$SCRIPT_DIR|g" "$INSTALL_TEMPLATE" > "$INSTALL_TARGET"
  chmod +x "$INSTALL_TARGET"
  printf "Created launchd installer: %s\n" "$INSTALL_TARGET"
fi

chmod 600 "$LAUNCHD_ENV_TARGET" || true

cat <<EOF

launchd setup complete.

Review and edit:
  $LAUNCHD_ENV_TARGET
  $INSTALL_TARGET

Then install or reload the LaunchAgent with:
  $INSTALL_TARGET install

The runtime-home installer is meant to be re-run after edits so you can update
the scheduled time, command arguments, or plist contents without returning to
the repo copy.
EOF
