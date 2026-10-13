#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_HOME="${MODEL_SENTINEL_HOME:-$HOME/.model_sentinel}"

PROVIDERS_TEMPLATE="$SCRIPT_DIR/providers.env.template"
SETTINGS_TEMPLATE="$SCRIPT_DIR/settings.env.template"
PROVIDERS_TARGET="$RUNTIME_HOME/providers.env"
SETTINGS_TARGET="$RUNTIME_HOME/settings.env"

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

copy_if_missing "$PROVIDERS_TEMPLATE" "$PROVIDERS_TARGET" "provider config"
copy_if_missing "$SETTINGS_TEMPLATE" "$SETTINGS_TARGET" "settings config"

cat <<EOF

Setup complete.

Review and edit these files before running scans:
  $PROVIDERS_TARGET
  $SETTINGS_TARGET

Remaining setup steps:
  1. Review the enabled providers and credential env var names in providers.env.
  2. Review runtime settings in settings.env, especially log rotation, notifications, and report output.
  3. Use environment credentials, or configure file mode and explicitly refresh its private cache:
     ./model-sentinel credentials refresh
     Alternatively, after loading your existing secrets shell: ./model-sentinel credentials refresh --from-environment
  4. Run ./model-sentinel healthcheck
  5. Create the first saved baseline with ./model-sentinel scan --save

Optional automation setup:
  - Run ./setup_launchd.sh to seed launchd support files into $RUNTIME_HOME

File-mode scans read only the cache; refresh manually after rotation.
Existing config files are preserved; review settings and bootstrap lines yourself.
The tool halts if selected providers lack valid credentials from the configured source.
EOF
