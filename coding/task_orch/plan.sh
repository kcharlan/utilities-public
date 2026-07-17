#!/usr/bin/env bash
set -euo pipefail

# Claude Code commands — defined here because .zshrc functions aren't
# available in non-interactive script shells.
cc-opus()  { claude --dangerously-skip-permissions --model opus "$@"; }
cc-sonnet(){ claude --dangerously-skip-permissions --model sonnet "$@"; }

# =============================================================================
# Planner Launcher
#
# Launches cc-opus planning agents to process intake items. Each planner runs
# autonomously: claim an intake item, read source code, write a plan to
# ready/ or review/, repeat until intake is empty.
#
# Usage:
#   task_orch/plan.sh              # Launch one planner
#   task_orch/plan.sh 2            # Launch two planners in parallel
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
NUM_PLANNERS="${1:-1}"
LOG_DIR="$SCRIPT_DIR/planning"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

cd "$REPO_ROOT"

# Validate intake has items
intake_count=$(find "$SCRIPT_DIR/planning/intake" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
if [ "$intake_count" -eq 0 ]; then
  log "No intake items found in task_orch/planning/intake/. Nothing to plan."
  exit 0
fi
log "Found $intake_count intake item(s)"

# Check for plan ID collisions with existing done/ plans
collision=false
for intake_file in "$SCRIPT_DIR/planning/intake/"*.md; do
  [ -f "$intake_file" ] || continue
  # Extract the numeric prefix (e.g., "029" from "029_some_name.md")
  prefix=$(basename "$intake_file" | grep -oE '^[0-9]+')
  [ -z "$prefix" ] && continue
  # Check if this prefix (or a split variant like 029-a) already exists in done/
  if ls "$SCRIPT_DIR/execution/done/${prefix}_"*.plan.md >/dev/null 2>&1 || \
     ls "$SCRIPT_DIR/execution/done/${prefix}-"*.plan.md >/dev/null 2>&1; then
    log "!! WARNING: Intake item $(basename "$intake_file") uses prefix $prefix which already exists in done/"
    log "   Existing: $(ls "$SCRIPT_DIR/execution/done/${prefix}"_*.plan.md "$SCRIPT_DIR/execution/done/${prefix}-"*.plan.md 2>/dev/null | xargs -I{} basename {} | tr '\n' ' ')"
    collision=true
  fi
done
if $collision; then
  log "!! Plan ID collision detected. Renumber the intake items to avoid confusion."
  log "!! Aborting. Fix numbering and re-run."
  exit 1
fi

# Planner prompt — tells the agent to read its instructions and begin
planner_prompt_base="Read task_orch/planning/PLANNER.md for your full instructions. Read task_orch/SYSTEM.md for pipeline rules. You are Planner"

pids=()
for i in $(seq 1 "$NUM_PLANNERS"); do
  planner_id=$(echo "$i" | tr '1234' 'ABCD')
  log_file="$LOG_DIR/planner_${planner_id}.log"

  log "Launching Planner $planner_id → $log_file"

  cc-opus -p "${planner_prompt_base} ${planner_id}. Begin." \
    --allowedTools "Edit,Read,Write,Bash,Glob,Grep" \
    > "$log_file" 2>&1 &
  pids+=($!)
done

log "Planner(s) running. PIDs: ${pids[*]}"
log "Logs: $LOG_DIR/planner_*.log"
log "Waiting for all planners to finish..."

# Wait for all planners and report results
all_ok=true
for i in "${!pids[@]}"; do
  pid=${pids[$i]}
  planner_id=$(echo "$((i+1))" | tr '1234' 'ABCD')
  if wait "$pid"; then
    log "Planner $planner_id finished successfully"
  else
    log "!! Planner $planner_id exited with error (check planner_${planner_id}.log)"
    all_ok=false
  fi
done

# git rm intake files that planners processed (moved to claimed/ then deleted).
# Intake is git-tracked; claimed/ is gitignored. Without git rm, rebases and
# merges restore the committed intake files even after the planner moved them.
for intake_file in "$SCRIPT_DIR/planning/intake/"*.md; do
  [ -f "$intake_file" ] || continue
  prefix=$(basename "$intake_file" | grep -oE '^[0-9]+')
  [ -z "$prefix" ] && continue
  # If a plan with this prefix now exists in staging/ or review/, the intake
  # item was processed — remove it from git so it doesn't resurrect on rebase.
  if ls "$SCRIPT_DIR/planning/staging/${prefix}"_*.plan.md >/dev/null 2>&1 || \
     ls "$SCRIPT_DIR/planning/staging/${prefix}-"*.plan.md >/dev/null 2>&1 || \
     ls "$SCRIPT_DIR/planning/review/${prefix}"_*.plan.md >/dev/null 2>&1 || \
     ls "$SCRIPT_DIR/planning/review/${prefix}-"*.plan.md >/dev/null 2>&1; then
    log "Removing processed intake file from git: $(basename "$intake_file")"
    (cd "$REPO_ROOT" && git rm -f "$intake_file") 2>/dev/null || true
  fi
done

# Report what ended up where
staged_count=$(find "$SCRIPT_DIR/planning/staging" -name '*.plan.md' 2>/dev/null | wc -l | tr -d ' ')
review_count=$(find "$SCRIPT_DIR/planning/review" -name '*.plan.md' 2>/dev/null | wc -l | tr -d ' ')
claimed_count=$(find "$SCRIPT_DIR/planning/claimed" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')

log "=== Planning complete ==="
log "  Staged (run task_orch/stage.sh next): $staged_count"
log "  Needs human review:              $review_count"
if [ "$claimed_count" -gt 0 ]; then
  log "  Still in claimed (possible failure): $claimed_count"
  log "  (If these have matching plans in staging/ or review/, the planner"
  log "   forgot to clean up. Safe to delete them from claimed/.)"
fi

if [ "$review_count" -gt 0 ]; then
  log ""
  log "Plans in review/ (need your input before they can execute):"
  for f in "$SCRIPT_DIR/planning/review"/*.plan.md; do
    log "  - $(basename "$f")"
  done
fi

if [ "$all_ok" = true ]; then
  exit 0
else
  exit 1
fi
