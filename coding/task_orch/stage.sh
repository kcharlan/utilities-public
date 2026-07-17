#!/usr/bin/env bash
set -euo pipefail

# Claude Code commands — defined here because .zshrc functions aren't
# available in non-interactive script shells.
cc-opus()  { claude --dangerously-skip-permissions --model opus "$@"; }
cc-sonnet(){ claude --dangerously-skip-permissions --model sonnet "$@"; }

# =============================================================================
# Dependency Resolution Launcher
#
# Launches a cc-opus agent to analyze all plans in staging/, resolve
# cross-plan dependencies, and move them to execution/ready/.
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STAGING_DIR="$SCRIPT_DIR/planning/staging"
READY_DIR="$SCRIPT_DIR/execution/ready"
LOG_FILE="$SCRIPT_DIR/execution/resolver.log"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

cd "$REPO_ROOT"

# Check for staged plans
staged_count=$(find "$STAGING_DIR" -name '*.plan.md' 2>/dev/null | wc -l | tr -d ' ')
if [ "$staged_count" -eq 0 ]; then
  log "No plans in staging/. Nothing to resolve."
  exit 0
fi

log "Found $staged_count staged plan(s). Launching dependency resolver..."

resolver_prompt="Read task_orch/execution/RESOLVER.md for your full instructions. Read task_orch/SYSTEM.md for pipeline rules. There are $staged_count plans in task_orch/planning/staging/ to resolve. Begin."

set +e
cc-opus -p "$resolver_prompt" \
  --allowedTools "Edit,Read,Write,Bash,Glob,Grep" \
  2>&1 | tee "$LOG_FILE"
resolver_exit=$?
set -e

# Report results
ready_count=$(find "$READY_DIR" -name '*.plan.md' 2>/dev/null | wc -l | tr -d ' ')
remaining=$(find "$STAGING_DIR" -name '*.plan.md' 2>/dev/null | wc -l | tr -d ' ')

log "=== Resolution complete ==="
log "  Moved to ready:      $ready_count"
log "  Remaining in staging: $remaining (conflicts or errors)"

if [ -f "$SCRIPT_DIR/execution/RESOLUTION.md" ]; then
  log ""
  log "Resolution report: task_orch/execution/RESOLUTION.md"
fi

if [ "$remaining" -gt 0 ]; then
  log ""
  log "!! Plans left in staging/ need human review:"
  for f in "$STAGING_DIR"/*.plan.md; do
    [ -f "$f" ] && log "  - $(basename "$f")"
  done
fi

exit $resolver_exit
