#!/bin/bash

set -euo pipefail

ACTION="${1:-install}"
RUNTIME_HOME="${MODEL_SENTINEL_HOME:-$HOME/.model_sentinel}"
PROJECT_DIR="__MODEL_SENTINEL_PROJECT_DIR__"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
LAUNCHD_ENV_FILE="$RUNTIME_HOME/launchd.env"
RUNNER_SCRIPT="$RUNTIME_HOME/run_model_sentinel_launchd.sh"
RUNTIME_PLIST="$RUNTIME_HOME/local.model_sentinel.scan.plist"
INSTALLED_PLIST="$LAUNCH_AGENTS_DIR/local.model_sentinel.scan.plist"
JOB_LABEL="local.model_sentinel.scan"

# Editable schedule. Re-run this script after changes.
START_HOUR=9
START_MINUTE=5

# Editable command. Re-run this script after changes.
MODEL_SENTINEL_ARGS=(
  scan
  --save
)

# launchd stdout/stderr capture.
STDOUT_LOG="$RUNTIME_HOME/logs/launchd.stdout.log"
STDERR_LOG="$RUNTIME_HOME/logs/launchd.stderr.log"

usage() {
  cat <<EOF
Usage: $(basename "$0") [install|reload|uninstall|status|print|help]

Actions:
  install    Generate the launchd runner/plist and load the user LaunchAgent.
  reload     Alias for install.
  uninstall  Unload and remove the LaunchAgent plist from ~/Library/LaunchAgents.
  status     Show current config paths and launchctl status if installed.
  print      Print the generated plist path.
  help       Show this help text.

Edit this file in $RUNTIME_HOME and re-run it whenever you want to change:
  - JOB_LABEL
  - START_HOUR / START_MINUTE
  - MODEL_SENTINEL_ARGS
  - stdout/stderr log paths

Secrets/bootstrap lines belong in:
  $LAUNCHD_ENV_FILE
EOF
}

ensure_dirs() {
  mkdir -p "$RUNTIME_HOME" "$RUNTIME_HOME/logs" "$LAUNCH_AGENTS_DIR"
}

render_runner() {
  cat > "$RUNNER_SCRIPT" <<EOF
#!/bin/bash
set -euo pipefail

RUNTIME_HOME="${RUNTIME_HOME}"
PROJECT_DIR="${PROJECT_DIR}"
LAUNCHD_ENV_FILE="${LAUNCHD_ENV_FILE}"

if [ ! -f "\$LAUNCHD_ENV_FILE" ]; then
  echo "Missing launchd env file: \$LAUNCHD_ENV_FILE" >&2
  exit 2
fi

export MODEL_SENTINEL_HOME="\$RUNTIME_HOME"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:\${PATH:-}"
source "\$LAUNCHD_ENV_FILE"

cd "\$PROJECT_DIR"
exec "\$PROJECT_DIR/model-sentinel" $(printf '%q ' "${MODEL_SENTINEL_ARGS[@]}")
EOF
  chmod +x "$RUNNER_SCRIPT"
}

render_plist() {
  cat > "$RUNTIME_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${JOB_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${RUNNER_SCRIPT}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${PROJECT_DIR}</string>
  <key>RunAtLoad</key>
  <false/>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>${START_HOUR}</integer>
    <key>Minute</key>
    <integer>${START_MINUTE}</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${STDOUT_LOG}</string>
  <key>StandardErrorPath</key>
  <string>${STDERR_LOG}</string>
</dict>
</plist>
EOF
  plutil -lint "$RUNTIME_PLIST" >/dev/null
}

install_job() {
  ensure_dirs
  render_runner
  render_plist
  cp "$RUNTIME_PLIST" "$INSTALLED_PLIST"
  launchctl bootout "gui/$(id -u)" "$INSTALLED_PLIST" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$(id -u)" "$INSTALLED_PLIST"
  launchctl enable "gui/$(id -u)/${JOB_LABEL}" >/dev/null 2>&1 || true
  cat <<EOF
Installed launchd job.

Label: $JOB_LABEL
LaunchAgent plist: $INSTALLED_PLIST
Runner script: $RUNNER_SCRIPT
launchd env file: $LAUNCHD_ENV_FILE

Next steps:
  1. Review $LAUNCHD_ENV_FILE and add your secrets bootstrap or exports.
  2. Run: launchctl kickstart -k gui/$(id -u)/$JOB_LABEL
  3. Check: $STDOUT_LOG
  4. Check: $STDERR_LOG
EOF
}

uninstall_job() {
  launchctl bootout "gui/$(id -u)" "$INSTALLED_PLIST" >/dev/null 2>&1 || true
  rm -f "$INSTALLED_PLIST"
  cat <<EOF
Removed launchd job:
  $JOB_LABEL

Kept runtime files:
  $RUNTIME_PLIST
  $RUNNER_SCRIPT
  $LAUNCHD_ENV_FILE
EOF
}

status_job() {
  cat <<EOF
Job label: $JOB_LABEL
Runtime home: $RUNTIME_HOME
Project dir: $PROJECT_DIR
LaunchAgent plist: $INSTALLED_PLIST
Runner script: $RUNNER_SCRIPT
launchd env file: $LAUNCHD_ENV_FILE
Stdout log: $STDOUT_LOG
Stderr log: $STDERR_LOG
Scheduled time: $(printf '%02d:%02d' "$START_HOUR" "$START_MINUTE")
EOF
  if [ -f "$INSTALLED_PLIST" ]; then
    echo
    launchctl print "gui/$(id -u)/$JOB_LABEL" 2>/dev/null || true
  else
    echo
    echo "LaunchAgent plist is not installed."
  fi
}

case "$ACTION" in
  install|reload)
    install_job
    ;;
  uninstall)
    uninstall_job
    ;;
  status)
    status_job
    ;;
  print)
    echo "$INSTALLED_PLIST"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
