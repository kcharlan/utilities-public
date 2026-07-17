#!/usr/bin/env bash
set -euo pipefail

# Trace log — captures set -x output for post-crash forensics.
# stderr goes to file; the log() function writes to both stdout and session log.
TRACE_LOG="$(cd "$(dirname "$0")" && pwd)/execution/trace.log"
: > "$TRACE_LOG"
exec 2>>"$TRACE_LOG"
set -x

# Claude Code commands — defined here because .zshrc functions aren't
# available in non-interactive script shells.
cc-opus()  { claude --dangerously-skip-permissions --model opus "$@"; }
cc-sonnet(){ claude --dangerously-skip-permissions --model sonnet "$@"; }
cc-fixer() { claude --dangerously-skip-permissions --model "$FIXER_MODEL" "$@"; }

# =============================================================================
# Agent Pipeline Orchestrator — Constraint-Aware Plan Dispatch
#
# Reads RESOLUTION.md to extract per-plan constraints (DEPENDS_ON,
# ANTI_AFFINITY). Dispatches individual plans to worker slots, each in its
# own git worktree. Enforces:
#   - Hard dependencies: plan waits until all DEPENDS_ON plans are done
#   - Anti-affinity: plan waits until no ANTI_AFFINITY plan is running
#
# Moves plans through: ready/ → workers/<slot>/ → done/ | blocked/
# Merges worktree branches after each plan completes.
# Runs full test suite every FULL_TEST_INTERVAL completed plans.
# Halts on full test suite failure.
#
# Compatible with bash 3.2+ (macOS system shell).
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

READY_DIR="$SCRIPT_DIR/execution/ready"
WORKERS_DIR="$SCRIPT_DIR/execution/workers"
DONE_DIR="$SCRIPT_DIR/execution/done"
BLOCKED_DIR="$SCRIPT_DIR/execution/blocked"
WORKTREES_DIR="$REPO_ROOT/.worktrees"
RESOLUTION_FILE="$SCRIPT_DIR/execution/RESOLUTION.md"

MAX_WORKERS="${MAX_WORKERS:-2}"
FULL_TEST_INTERVAL="${FULL_TEST_INTERVAL:-4}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"
FIXER_MODEL="${FIXER_MODEL:-opus}"
MAX_FIX_ATTEMPTS="${MAX_FIX_ATTEMPTS:-2}"

completed_since_full_test=0
total_completed=0
total_blocked=0
total_fix_attempts=0
total_fix_successes=0

# Session log — persistent, predictable location for monitoring
SESSION_LOG="$SCRIPT_DIR/execution/session.log"
: > "$SESSION_LOG"  # truncate at start of each session

log() {
  local msg="[$(date '+%H:%M:%S')] $*"
  echo "$msg"
  echo "$msg" >> "$SESSION_LOG"
}

# Current orchestrator phase — shown in dashboard
ORCH_PHASE="starting"

# ---------------------------------------------------------------------------
# Temp dir for per-plan constraint metadata (bash 3.2 has no associative arrays)
# PLAN_META_DIR/<plan_id>/depends_on    → space-separated plan IDs or "none"
# PLAN_META_DIR/<plan_id>/anti_affinity → space-separated plan IDs or "none"
# PLAN_META_DIR/<plan_id>/exec_order    → integer
# ---------------------------------------------------------------------------

PLAN_META_DIR=$(mktemp -d)
trap 'rm -rf "$PLAN_META_DIR"' EXIT

# Crash diagnostics — log the line number if set -e kills the script
trap 'log "!! FATAL: orchestrate.sh crashed at line $LINENO (exit code $?)"; log "!! Trace log: $TRACE_LOG (last 20 lines follow)"; tail -20 "$TRACE_LOG" >> "$SESSION_LOG" 2>/dev/null' ERR

# Helpers for plan constraint metadata
get_plan_depends()       { cat "$PLAN_META_DIR/$1/depends_on" 2>/dev/null || echo "none"; }
get_plan_anti_affinity() { cat "$PLAN_META_DIR/$1/anti_affinity" 2>/dev/null || echo "none"; }
all_plan_ids()           { ls "$PLAN_META_DIR" 2>/dev/null | sort; }
plan_count()             { ls "$PLAN_META_DIR" 2>/dev/null | wc -l | tr -d ' '; }

# Per-worker state (indexed arrays — numeric keys work in bash 3.2)
WORKER_PIDS=()
WORKER_PLANS=()
for ((i=0; i<MAX_WORKERS; i++)); do
  WORKER_PIDS[$i]=""
  WORKER_PLANS[$i]=""
done

# ---------------------------------------------------------------------------
# Branch safety guard
# ---------------------------------------------------------------------------

cd "$REPO_ROOT"

current_branch=$(git rev-parse --abbrev-ref HEAD)
if [ "$current_branch" = "main" ]; then
  log "!! REFUSING TO RUN: current branch is 'main'."
  log "!! Switch to a feature/development branch first."
  exit 1
fi
log "Operating on branch: $current_branch"

# ---------------------------------------------------------------------------
# Crash recovery
# ---------------------------------------------------------------------------

recover_from_crash() {
  log "Checking for leftover state from prior run..."

  mkdir -p "$READY_DIR"

  # Move any plans in workers/ back to ready/ BEFORE touching worktrees.
  # Discard any partial work — plans will be re-executed from scratch.
  if [ -d "$WORKERS_DIR" ]; then
    for slot_dir in "$WORKERS_DIR"/*/; do
      [ -d "$slot_dir" ] || continue
      for plan in "$slot_dir"*.plan.md; do
        [ -f "$plan" ] || continue
        log "  Returning $(basename "$plan") to ready/"
        mv "$plan" "$READY_DIR/"
      done
      # Clean up status and log files from prior run
      rm -f "$slot_dir"*.status "$slot_dir"*.log 2>/dev/null || true
    done
  fi

  # Clean up leftover worktrees and their branches
  if [ -d "$WORKTREES_DIR" ]; then
    for wt in "$WORKTREES_DIR"/worker_*; do
      [ -d "$wt" ] || continue
      local wt_name
      wt_name=$(basename "$wt")
      # Extract the branch name from git worktree list
      local wt_branch
      wt_branch=$(git worktree list --porcelain | grep -A2 "$wt" | grep 'branch' | sed 's|.*refs/heads/||' || true)
      log "  Removing leftover worktree: $wt_name (branch: ${wt_branch:-unknown})"
      git worktree remove --force "$wt" 2>/dev/null || rm -rf "$wt"
      if [ -n "$wt_branch" ]; then
        git branch -D "$wt_branch" 2>/dev/null || true
      fi
    done
  fi

  # Warn about uncommitted changes but do NOT stash — stashing disrupts other
  # processes and can revert edits to this script itself mid-execution.
  if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    log "  WARNING: Uncommitted changes detected in working tree (not touching them)"
  fi

  # Clean up fixer logs from prior run
  rm -f "$SCRIPT_DIR/execution/"*_fix_attempt_*.log 2>/dev/null || true
  rm -f "$SCRIPT_DIR/execution/"*test_fix*.log 2>/dev/null || true

  log "Recovery complete."
}

recover_from_crash

# ---------------------------------------------------------------------------
# RESOLUTION.md constraint parser
# ---------------------------------------------------------------------------

parse_constraints() {
  if [ ! -f "$RESOLUTION_FILE" ]; then
    log "!! No RESOLUTION.md found. Run the resolver first."
    exit 1
  fi

  local in_constraints=false
  local header_seen=false
  while IFS= read -r line; do
    case "$line" in
      "## Constraints"*)
        in_constraints=true
        continue
        ;;
      "##"*)
        $in_constraints && break  # entered next section
        ;;
    esac

    if $in_constraints; then
      # Skip table header and separator rows
      case "$line" in
        "| Plan"*) header_seen=true; continue ;;
        "|---"*|"| ---"*) continue ;;
      esac

      # Parse data rows: | plan_id | depends_on | anti_affinity | exec_order |
      if $header_seen; then
        # Strip leading/trailing pipes and whitespace, split on |
        local stripped
        stripped=$(echo "$line" | sed 's/^[[:space:]]*|//;s/|[[:space:]]*$//')
        [ -z "$stripped" ] && continue

        local plan_id depends_on anti_affinity exec_order
        plan_id=$(echo "$stripped" | awk -F'|' '{gsub(/^[[:space:]]+|[[:space:]]+$/,"",$1); print $1}')
        depends_on=$(echo "$stripped" | awk -F'|' '{gsub(/^[[:space:]]+|[[:space:]]+$/,"",$2); print $2}')
        anti_affinity=$(echo "$stripped" | awk -F'|' '{gsub(/^[[:space:]]+|[[:space:]]+$/,"",$3); print $3}')
        exec_order=$(echo "$stripped" | awk -F'|' '{gsub(/^[[:space:]]+|[[:space:]]+$/,"",$4); print $4}')

        [ -z "$plan_id" ] && continue

        # Normalize comma-separated lists to space-separated
        depends_on=$(echo "$depends_on" | tr ',' ' ' | tr -s ' ' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        anti_affinity=$(echo "$anti_affinity" | tr ',' ' ' | tr -s ' ' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        [ -z "$depends_on" ] && depends_on="none"
        [ -z "$anti_affinity" ] && anti_affinity="none"
        [ -z "$exec_order" ] && exec_order="1"

        mkdir -p "$PLAN_META_DIR/$plan_id"
        echo "$depends_on" > "$PLAN_META_DIR/$plan_id/depends_on"
        echo "$anti_affinity" > "$PLAN_META_DIR/$plan_id/anti_affinity"
        echo "$exec_order" > "$PLAN_META_DIR/$plan_id/exec_order"
      fi
    fi
  done < "$RESOLUTION_FILE"

  if [ "$(plan_count)" -eq 0 ]; then
    log "!! No constraints found in RESOLUTION.md. Check resolver output."
    exit 1
  fi

  log "Parsed $(plan_count) plan(s) from RESOLUTION.md"
  for pid in $(all_plan_ids); do
    log "  Plan $pid: deps=$(get_plan_depends "$pid") anti=$(get_plan_anti_affinity "$pid") order=$(cat "$PLAN_META_DIR/$pid/exec_order")"
  done
}

parse_constraints

# ---------------------------------------------------------------------------
# Plan eligibility checks
# ---------------------------------------------------------------------------

# Returns 0 if plan is in done/
plan_is_done() {
  local plan_id="$1"
  ls "$DONE_DIR"/${plan_id}_*.plan.md >/dev/null 2>&1
}

# Returns 0 if plan file exists in ready/
plan_is_ready() {
  local plan_id="$1"
  ls "$READY_DIR"/${plan_id}_*.plan.md >/dev/null 2>&1
}

# Returns 0 if plan is in blocked/
plan_is_blocked() {
  local plan_id="$1"
  ls "$BLOCKED_DIR"/${plan_id}_*.plan.md >/dev/null 2>&1
}

# Returns 0 if plan is currently running in a worker slot
plan_is_running() {
  local plan_id="$1"
  for ((i=0; i<MAX_WORKERS; i++)); do
    [ "${WORKER_PLANS[$i]}" = "$plan_id" ] && return 0
  done
  return 1
}

# Returns 0 if plan is eligible for dispatch:
#   - In ready/ (not already done, blocked, or running)
#   - All DEPENDS_ON plans are done
#   - No ANTI_AFFINITY plans are currently running
plan_is_eligible() {
  local plan_id="$1"

  # Must be in ready/
  plan_is_ready "$plan_id" || return 1

  # Must not already be running
  plan_is_running "$plan_id" && return 1

  # All hard dependencies must be done
  local deps
  deps=$(get_plan_depends "$plan_id")
  if [ "$deps" != "none" ]; then
    for dep in $deps; do
      plan_is_done "$dep" || return 1
    done
  fi

  # No anti-affinity plan currently running
  local aa
  aa=$(get_plan_anti_affinity "$plan_id")
  if [ "$aa" != "none" ]; then
    for aa_plan in $aa; do
      plan_is_running "$aa_plan" && return 1
    done
  fi

  return 0
}

# Find the next eligible plan (lowest EXEC_ORDER, then lowest plan ID)
find_eligible_plan() {
  local best_id=""
  local best_order=9999
  for pid in $(all_plan_ids); do
    plan_is_eligible "$pid" || continue
    local order
    order=$(cat "$PLAN_META_DIR/$pid/exec_order" 2>/dev/null || echo "9999")
    if [ "$order" -lt "$best_order" ] || \
       { [ "$order" -eq "$best_order" ] && [ -z "$best_id" -o "$pid" \< "$best_id" ]; }; then
      best_id="$pid"
      best_order="$order"
    fi
  done
  [ -n "$best_id" ] && echo "$best_id"
  return 0
}

# Count plans still pending (not done and not blocked)
count_pending() {
  local count=0
  for pid in $(all_plan_ids); do
    if ! plan_is_done "$pid" && ! plan_is_blocked "$pid"; then
      ((count++)) || true
    fi
  done
  echo "$count"
}

# Check initial state
pending_count=0
for pid in $(all_plan_ids); do
  if plan_is_done "$pid"; then
    log "Plan $pid already complete -- skipping"
  else
    ((pending_count++)) || true
  fi
done

if [ "$pending_count" -eq 0 ]; then
  log "All plans already complete. Nothing to do."
  exit 0
fi

log "$pending_count plan(s) pending"

# ---------------------------------------------------------------------------
# Worker and worktree management
# ---------------------------------------------------------------------------

mkdir -p "$WORKERS_DIR" "$WORKTREES_DIR" "$BLOCKED_DIR"

# Create worker slot directories
for ((i=0; i<MAX_WORKERS; i++)); do
  mkdir -p "$WORKERS_DIR/$i"
done

find_idle_slot() {
  for ((i=0; i<MAX_WORKERS; i++)); do
    if [ -z "${WORKER_PIDS[$i]}" ]; then
      echo "$i"
      return 0
    fi
  done
  return 1
}

dispatch_plan() {
  local slot="$1"
  local plan_id="$2"
  local worktree_path="$WORKTREES_DIR/worker_${slot}"
  local branch_name="worker-${slot}-${plan_id}"

  log "Dispatching plan $plan_id to worker slot $slot"

  # Find the plan file in ready/
  local plan_file
  plan_file=$(ls "$READY_DIR"/${plan_id}_*.plan.md 2>/dev/null | head -1)
  if [ -z "$plan_file" ]; then
    log "!! Plan file for $plan_id not found in ready/"
    return 1
  fi
  local plan_basename
  plan_basename=$(basename "$plan_file")

  # Create worktree with a new branch from HEAD
  if ! git worktree add "$worktree_path" -b "$branch_name" HEAD 2>&1; then
    log "!! Failed to create worktree for plan $plan_id (branch: $branch_name)"
    return 1
  fi

  # Copy plan file to worker slot and into the worktree
  mkdir -p "$worktree_path/task_orch/execution/workers/$slot"
  cp "$plan_file" "$worktree_path/task_orch/execution/workers/$slot/"
  mv "$plan_file" "$WORKERS_DIR/$slot/"

  # Derive log filename from plan basename (e.g., 029_failed_badge.plan.md → 029_failed_badge.log)
  local log_name="${plan_basename%.plan.md}.log"

  # Build worker prompt
  local worker_prompt="You are a Worker agent running in worker slot $slot. \
Read task_orch/SYSTEM.md first, then read task_orch/execution/WORKER.md for your full \
instructions. Your plan is in task_orch/execution/workers/$slot/. Plan: $plan_basename. Begin."

  # Launch worker in the worktree (background)
  (
    cd "$worktree_path"
    cc-sonnet -p "$worker_prompt" \
      --allowedTools "Edit,Read,Write,Bash,Glob,Grep" \
      2>&1 | tee "$WORKERS_DIR/$slot/$log_name"
  ) &
  local pid=$!

  WORKER_PIDS[$slot]=$pid
  WORKER_PLANS[$slot]=$plan_id
  log "Worker slot $slot started (PID $pid) for plan $plan_id"
}

move_plan_to_blocked() {
  local slot="$1"
  local reason="$2"
  for f in "$WORKERS_DIR/$slot/"*.plan.md "$WORKERS_DIR/$slot/"*.status; do
    [ -f "$f" ] && mv "$f" "$BLOCKED_DIR/"
  done
  mv "$WORKERS_DIR/$slot/"*.log "$BLOCKED_DIR/" 2>/dev/null || true
  ((total_blocked++)) || true
  log "  Moved plan ${WORKER_PLANS[$slot]} to blocked/ (reason: $reason)"
}

# ---------------------------------------------------------------------------
# Auto-fix functions
# ---------------------------------------------------------------------------

build_error_context() {
  local output_file="$1"
  local context_type="$2"  # "worker" or "full_test"

  if [ "$context_type" = "worker" ]; then
    local slot="$3"
    local plan_id="$4"
    {
      echo "=== FAILURE CONTEXT: Worker Plan Failure ==="
      echo ""
      echo "--- Status Files ---"
      for sf in "$WORKERS_DIR/$slot/"*.status; do
        [ -f "$sf" ] || continue
        echo "## $(basename "$sf")"
        cat "$sf"
        echo ""
      done
      echo "--- Worker Log (last 200 lines) ---"
      local worker_log
      worker_log=$(ls "$WORKERS_DIR/$slot/"${plan_id}_*.log 2>/dev/null | head -1 || true)
      tail -200 "${worker_log:-/dev/null}" 2>/dev/null || echo "(no log found)"
      echo ""
      echo "--- Plan Files ---"
      for pf in "$WORKERS_DIR/$slot/"*.plan.md; do
        [ -f "$pf" ] || continue
        echo "## $(basename "$pf")"
        cat "$pf"
        echo ""
      done
    } > "$output_file"
  elif [ "$context_type" = "full_test" ]; then
    local test_log="$3"
    {
      echo "=== FAILURE CONTEXT: Full Test Suite Failure ==="
      echo ""
      echo "--- Test Output (last 300 lines) ---"
      tail -300 "$test_log" 2>/dev/null || echo "(no test log found)"
    } > "$output_file"
  fi
}

run_fixer_agent() {
  local context_type="$1"       # "worker" or "full_test"
  local working_dir="$2"
  local error_context_file="$3"
  local attempt_num="$4"
  local log_file="$5"

  local error_context
  error_context=$(cat "$error_context_file")

  local bse_data_dir="${BSE_DATA_DIR:-$HOME/Downloads/BSE2}"

  if [ "$context_type" = "worker" ]; then
    local fixer_prompt="You are a Fixer agent (attempt $attempt_num). A worker agent \
tried to implement a plan and failed. Your job: diagnose the failure, fix the code, \
verify tests pass, and commit.

RULES:
1. Read CLAUDE.md at the repo root for project conventions.
2. Read docs/LESSONS_LEARNED.md for patterns to follow and avoid.
3. Fix the ACTUAL problem. Do not patch tests to pass unless the tests themselves \
are genuinely wrong.
4. The fix may be in ANY file — not just the files the worker touched. Follow the \
error to its root cause.
5. After fixing, run targeted tests: .venv/bin/pytest tests/ -v --tb=short
6. If tests pass, commit your fix: git commit -m \"fix: <concise description>\"
7. If you cannot fix the problem, exit 1.
8. Use .venv/bin/pytest — never system pytest.

ERROR CONTEXT:
$error_context

PROCEDURE:
1. Read the error context above carefully.
2. Identify root cause — code bug, test bug, missing dep, merge issue?
3. Read the relevant source files.
4. Implement the fix.
5. Run targeted tests to verify.
6. If pass, commit and exit 0. If fail, try one more approach.
7. If still failing, exit 1.
Begin."
  else
    local fixer_prompt="You are a Fixer agent (attempt $attempt_num). The full test \
suite failed after merging completed pipeline work. Your job: diagnose ALL failures, \
fix the code, verify the full suite passes, and commit.

RULES:
1. Read CLAUDE.md at the repo root for project conventions.
2. Read docs/LESSONS_LEARNED.md for patterns to follow and avoid.
3. Fix the ACTUAL problem. Do not patch tests unless the tests are genuinely wrong.
4. Failures may be in ANY module — backend, frontend, deploy tools, e2e. Fix them all.
5. After fixing, run the full test suite:
   BSE_DATA_DIR=$bse_data_dir BSE_ENABLE_DEV_ENDPOINTS=1 ./scripts/test_all.sh
6. If the suite passes, commit: git commit -m \"fix: <concise description>\"
7. If you cannot fix the problem, exit 1.
8. Use .venv/bin/pytest — never system pytest.

TEST FAILURE DETAILS:
$error_context

PROCEDURE:
1. Read the test failure output above carefully.
2. Identify which suites failed and what the errors are.
3. For each failure, trace to the root cause in the source code.
4. Implement fixes — you may need to fix multiple issues across modules.
5. Run targeted tests first, then the full suite.
6. Commit all fixes and exit 0.
7. If you cannot resolve all failures, exit 1.
Begin."
  fi

  # Launch fixer (foreground — blocks until done)
  log "    Launching fixer ($FIXER_MODEL, attempt $attempt_num)..."
  (
    cd "$working_dir"
    cc-fixer -p "$fixer_prompt" \
      --allowedTools "Edit,Read,Write,Bash,Glob,Grep" \
      2>&1 | tee "$log_file"
  )
  local fixer_exit=$?

  # Independent verification — don't trust the fixer's self-report
  log "    Fixer exited ($fixer_exit). Running independent verification..."

  # Save verification output for context enrichment (used if this attempt fails)
  LAST_VERIFICATION_LOG=$(mktemp)

  if [ "$context_type" = "worker" ]; then
    # Run targeted tests in the worktree (retry once for transient failures)
    local attempt
    for attempt in 1 2; do
      if (cd "$working_dir" && .venv/bin/pytest tests/ -v --tb=short 2>&1 | tee "$LAST_VERIFICATION_LOG" | tail -5); then
        log "    Verification: targeted tests PASSED"
        rm -f "$LAST_VERIFICATION_LOG"
        return 0
      fi
      if [ "$attempt" -eq 1 ]; then
        log "    Verification: targeted tests FAILED (retry 1/1)..."
        sleep 3
      fi
    done
    log "    Verification: targeted tests FAILED"
    return 1
  else
    # Run full test suite on main repo
    if run_full_test_suite; then
      log "    Verification: full test suite PASSED"
      rm -f "$LAST_VERIFICATION_LOG"
      return 0
    else
      log "    Verification: full test suite FAILED"
      return 1
    fi
  fi
}

attempt_fix_with_retry() {
  local context_type="$1"       # "worker" or "full_test"
  local working_dir="$2"
  local error_context_file="$3"
  local log_prefix="$4"

  for attempt in $(seq 1 "$MAX_FIX_ATTEMPTS"); do
    log "  Auto-fix attempt $attempt/$MAX_FIX_ATTEMPTS ($context_type)..."
    local fix_log="${log_prefix}_fix_attempt_${attempt}.log"

    ((total_fix_attempts++)) || true

    if run_fixer_agent "$context_type" "$working_dir" "$error_context_file" \
                       "$attempt" "$fix_log"; then
      log "  Auto-fix attempt $attempt SUCCEEDED"
      ((total_fix_successes++)) || true
      return 0
    fi

    log "  Auto-fix attempt $attempt FAILED"

    # Enrich context for next attempt — include only the verification failures,
    # NOT the fixer's log (which contains self-reported "all tests pass" claims
    # that mislead the next fixer into thinking the problem is already solved).
    if [ "$attempt" -lt "$MAX_FIX_ATTEMPTS" ]; then
      log "  Enriching context for fresh attempt..."
      {
        cat "$error_context_file"
        echo ""
        echo "=== PREVIOUS FIX ATTEMPT ($attempt) FAILED ==="
        echo "The previous fixer committed changes but independent verification still fails."
        echo ""
        echo "--- Independent verification output (actual test failures) ---"
        if [ -f "$LAST_VERIFICATION_LOG" ]; then
          tail -100 "$LAST_VERIFICATION_LOG"
        else
          echo "(verification log not available)"
        fi
        echo ""
        echo "--- Git diff of what the previous fixer changed ---"
        (cd "$working_dir" && git diff HEAD~1 --stat 2>/dev/null) || echo "(no diff available)"
        echo "=== END PREVIOUS ATTEMPT ==="
        echo ""
        echo "Try a DIFFERENT approach. The previous fixer's changes are already committed."
        echo "Focus on the ACTUAL test failures shown above."
      } > "${error_context_file}.enriched"
      mv "${error_context_file}.enriched" "$error_context_file"
    fi
  done

  return 1  # All attempts exhausted
}

handle_worker_completion() {
  local slot="$1"
  local plan_id="${WORKER_PLANS[$slot]}"
  local worktree_path="$WORKTREES_DIR/worker_${slot}"
  local branch_name="worker-${slot}-${plan_id}"

  log "Worker slot $slot finished. Processing plan $plan_id..."

  # Copy status file from worktree back to workers/ slot
  local wt_status
  wt_status=$(ls "$worktree_path/task_orch/execution/workers/$slot/"${plan_id}_*.status 2>/dev/null | head -1 || true)
  if [ -n "$wt_status" ] && [ -f "$wt_status" ]; then
    cp "$wt_status" "$WORKERS_DIR/$slot/"
  fi

  # Check if plan completed successfully
  local status_file
  status_file=$(ls "$WORKERS_DIR/$slot/"${plan_id}_*.status 2>/dev/null | head -1 || true)
  local plan_done=false
  if [ -n "$status_file" ] && grep -qi '^STATUS:[[:space:]]*done\|^DONE$' "$status_file" 2>/dev/null; then
    plan_done=true
  fi

  if $plan_done; then
    log "Plan $plan_id succeeded. Merging branch $branch_name..."
    if git merge --squash "$branch_name" && \
       git commit -m "feat(pipeline): plan $plan_id"; then
      log "Squash merge succeeded for plan $plan_id"
      for f in "$WORKERS_DIR/$slot/"*.plan.md "$WORKERS_DIR/$slot/"*.status; do
        [ -f "$f" ] && mv "$f" "$DONE_DIR/"
      done
      mv "$WORKERS_DIR/$slot/"*.log "$DONE_DIR/" 2>/dev/null || true
      ((total_completed++)) || true
      ((completed_since_full_test++)) || true

      # Check for FULL_TEST_AFTER: yes
      local done_plan
      done_plan=$(ls "$DONE_DIR"/${plan_id}_*.plan.md 2>/dev/null | head -1 || true)
      if [ -n "$done_plan" ] && grep -q '^FULL_TEST_AFTER: yes' "$done_plan"; then
        log "Plan $plan_id has FULL_TEST_AFTER: yes -- will trigger full test"
        completed_since_full_test=$FULL_TEST_INTERVAL  # force trigger
      fi

      # Update release notes with newly completed plan
      "$SCRIPT_DIR/generate_release_notes.sh" >/dev/null 2>&1 || true
      log "Release notes updated"
    else
      log "!! Merge conflict for plan $plan_id. Aborting merge."
      git merge --abort 2>/dev/null || true
      move_plan_to_blocked "$slot" "merge conflict"
    fi
  else
    log "!! Plan $plan_id failed -- attempting auto-fix..."

    # Build error context from status files, worker log, and plan files
    local error_ctx
    error_ctx=$(mktemp)
    build_error_context "$error_ctx" "worker" "$slot" "$plan_id"

    local fix_log_prefix="$WORKERS_DIR/$slot/${plan_id}"

    if attempt_fix_with_retry "worker" "$worktree_path" "$error_ctx" "$fix_log_prefix"; then
      log "Auto-fix succeeded for plan $plan_id. Re-evaluating..."

      # Re-copy status file from worktree (fixer may have updated it)
      wt_status=$(ls "$worktree_path/task_orch/execution/workers/$slot/"${plan_id}_*.status 2>/dev/null | head -1 || true)
      if [ -n "$wt_status" ] && [ -f "$wt_status" ]; then
        cp "$wt_status" "$WORKERS_DIR/$slot/"
      fi

      # Ensure status reflects success (fixer may not have updated it)
      local sf
      for sf in "$WORKERS_DIR/$slot/"*.status; do
        [ -f "$sf" ] || continue
        if ! grep -qi '^STATUS:[[:space:]]*done' "$sf"; then
          {
            echo "STATUS: done"
            echo "COMMITS: (auto-fixed)"
            echo "TESTS_RAN: targeted"
            echo "TEST_RESULT: pass"
            echo "NOTES: Auto-fixed by fixer agent ($FIXER_MODEL)"
          } > "$sf"
        fi
      done

      # Set flag so the merge/cleanup logic runs
      plan_done=true
    else
      log "!! Auto-fix FAILED for plan $plan_id after $MAX_FIX_ATTEMPTS attempts"
      move_plan_to_blocked "$slot" "plan $plan_id failed (auto-fix exhausted)"
      # Preserve fixer logs in blocked/
      for flog in "$WORKERS_DIR/$slot/"*_fix_attempt_*.log; do
        [ -f "$flog" ] && mv "$flog" "$BLOCKED_DIR/"
      done
    fi

    rm -f "$error_ctx"
  fi

  # Clean up worktree and branch — only on success.
  # On failure, preserve the worktree so work can be recovered.
  if $plan_done; then
    git worktree remove --force "$worktree_path" 2>/dev/null || rm -rf "$worktree_path"
    git branch -D "$branch_name" 2>/dev/null || true
  else
    log "  Preserving worktree at $worktree_path (branch: $branch_name) for recovery"
  fi

  # Clear slot state
  WORKER_PIDS[$slot]=""
  WORKER_PLANS[$slot]=""
}

# ---------------------------------------------------------------------------
# Full test suite
# ---------------------------------------------------------------------------

run_full_test_suite() {
  log "Running full test suite (including E2E)..."
  local bse_data_dir="${BSE_DATA_DIR:-$HOME/Downloads/BSE2}"
  if BSE_DATA_DIR="$bse_data_dir" BSE_ENABLE_DEV_ENDPOINTS=1 "$REPO_ROOT/scripts/test_all.sh"; then
    log "Full test suite PASSED"
    completed_since_full_test=0
    return 0
  else
    log "!! Full test suite FAILED"
    return 1
  fi
}

FULL_TEST_LOG="$SCRIPT_DIR/execution/full_test_latest.log"

run_full_test_suite_captured() {
  local output_file="$1"
  log "Running full test suite (including E2E)..."
  log "  Test output: $FULL_TEST_LOG"
  local bse_data_dir="${BSE_DATA_DIR:-$HOME/Downloads/BSE2}"
  if BSE_DATA_DIR="$bse_data_dir" BSE_ENABLE_DEV_ENDPOINTS=1 \
     "$REPO_ROOT/scripts/test_all.sh" 2>&1 | tee "$output_file" "$FULL_TEST_LOG"; then
    log "Full test suite PASSED"
    completed_since_full_test=0
    return 0
  else
    log "!! Full test suite FAILED (output captured to $output_file)"
    return 1
  fi
}

run_full_test_suite_with_pause() {
  ORCH_PHASE="waiting for workers before full test"
  generate_dashboard
  log "=== Full test suite triggered ==="
  log "Waiting for active workers to finish before running tests..."

  while true; do
    any_active=false
    for ((i=0; i<MAX_WORKERS; i++)); do
      pid="${WORKER_PIDS[$i]}"
      [ -z "$pid" ] && continue
      if kill -0 "$pid" 2>/dev/null; then
        any_active=true
      else
        wait "$pid" 2>/dev/null || true
        handle_worker_completion "$i"
      fi
    done
    $any_active || break
    sleep "$POLL_INTERVAL"
  done

  ORCH_PHASE="running full test suite (interval)"
  generate_dashboard
  log "All workers idle. Running full test suite..."
  local test_output_log
  test_output_log=$(mktemp)

  if run_full_test_suite_captured "$test_output_log"; then
    rm -f "$test_output_log"
    return 0
  fi

  ORCH_PHASE="auto-fixing test failures (interval)"
  generate_dashboard
  log "!! Full test suite failed — attempting auto-fix..."
  local error_ctx
  error_ctx=$(mktemp)
  build_error_context "$error_ctx" "full_test" "$test_output_log"

  local fix_log_prefix="$SCRIPT_DIR/execution/full_test_fix"

  if attempt_fix_with_retry "full_test" "$REPO_ROOT" "$error_ctx" "$fix_log_prefix"; then
    log "Auto-fix succeeded. Full test suite now passing."
    rm -f "$error_ctx" "$test_output_log"
    return 0
  fi

  log "!! Auto-fix FAILED after $MAX_FIX_ATTEMPTS attempts. HALTING."
  rm -f "$error_ctx" "$test_output_log"
  generate_dashboard
  exit 1
}

# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

generate_dashboard() {
  local ready_count blocked_count done_count
  ready_count=$(find "$READY_DIR" -name '*.plan.md' 2>/dev/null | wc -l | tr -d ' ')
  blocked_count=$(find "$BLOCKED_DIR" -name '*.plan.md' 2>/dev/null | wc -l | tr -d ' ')
  done_count=$(find "$DONE_DIR" -name '*.plan.md' 2>/dev/null | wc -l | tr -d ' ')

  {
    echo "# Pipeline Dashboard"
    echo "> Auto-generated by orchestrate.sh — do not edit"
    echo ""
    echo "| Queue | Count |"
    echo "|-------|-------|"
    echo "| Ready | $ready_count |"
    echo "| Done | $done_count |"
    echo "| Blocked | $blocked_count |"
    echo ""
    echo "## Active Workers"
    for ((i=0; i<MAX_WORKERS; i++)); do
      local wpid="${WORKER_PLANS[$i]}"
      local wnum="${WORKER_PIDS[$i]}"
      if [ -n "$wpid" ]; then
        echo "| Slot $i | Plan $wpid | PID $wnum |"
      else
        echo "| Slot $i | idle | — |"
      fi
    done
    echo ""
    echo "## Current Phase"
    echo "**$ORCH_PHASE**"
    echo ""
    echo "## Session stats"
    echo "- Completed this session: $total_completed"
    echo "- Blocked this session: $total_blocked"
    echo "- Plans since last full test: $completed_since_full_test / $FULL_TEST_INTERVAL"
    echo "- Auto-fix attempts: $total_fix_attempts ($total_fix_successes succeeded)"
    echo "- Fixer model: $FIXER_MODEL"
    echo ""
    echo "## Plan Constraints"
    echo "| Plan | Status | DEPENDS_ON | ANTI_AFFINITY |"
    echo "|------|--------|------------|---------------|"
    for pid in $(all_plan_ids); do
      local deps aa status_str
      deps=$(get_plan_depends "$pid")
      aa=$(get_plan_anti_affinity "$pid")
      if plan_is_done "$pid"; then
        status_str="done"
      elif plan_is_running "$pid"; then
        status_str="running"
      elif plan_is_blocked "$pid"; then
        status_str="blocked"
      elif plan_is_eligible "$pid"; then
        status_str="eligible"
      else
        status_str="waiting"
      fi
      echo "| $pid | $status_str | $deps | $aa |"
    done
    echo ""
    echo "## Blocked items"
    if [ "$blocked_count" -gt 0 ]; then
      for f in "$BLOCKED_DIR"/*.plan.md; do
        [ -f "$f" ] || continue
        echo "- $(basename "$f")"
        sf="${f%.plan.md}.status"
        if [ -f "$sf" ]; then
          grep '^BLOCKED_REASON:' "$sf" | sed 's/^/  /' || true
        fi
      done
    else
      echo "_none_"
    fi
    echo ""
    echo "## Monitoring"
    echo '```bash'
    echo "# Session log (all orchestrator output):"
    echo "tail -f $SESSION_LOG"
    echo ""
    echo "# Active worker logs:"
    for ((j=0; j<MAX_WORKERS; j++)); do
      local wpid="${WORKER_PLANS[$j]}"
      if [ -n "$wpid" ]; then
        echo "tail -f $WORKERS_DIR/$j/${wpid}_*.log"
      fi
    done
    echo ""
    echo "# Full test suite output (during test runs):"
    echo "tail -f $FULL_TEST_LOG"
    echo ""
    echo "# Worker progress (grep for markers):"
    for ((j=0; j<MAX_WORKERS; j++)); do
      local wpid="${WORKER_PLANS[$j]}"
      if [ -n "$wpid" ]; then
        echo "grep '##PROGRESS##' $WORKERS_DIR/$j/${wpid}_*.log"
      fi
    done
    echo '```'
    echo ""
    echo "_Updated: $(date '+%Y-%m-%d %H:%M:%S')_"
  } > "$SCRIPT_DIR/DASHBOARD.md"
}

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

ORCH_PHASE="dispatching plans"
log "=== Orchestrator started ==="
log "Workers: $MAX_WORKERS | Full test interval: $FULL_TEST_INTERVAL | Poll: ${POLL_INTERVAL}s | Fixer: $FIXER_MODEL (max $MAX_FIX_ATTEMPTS attempts)"

while true; do
  generate_dashboard

  # Check for completed workers
  for ((i=0; i<MAX_WORKERS; i++)); do
    loop_pid="${WORKER_PIDS[$i]}"
    [ -z "$loop_pid" ] && continue
    if ! kill -0 "$loop_pid" 2>/dev/null; then
      wait "$loop_pid" 2>/dev/null || true
      handle_worker_completion "$i"
    fi
  done

  # Check if full test suite is due
  if [ "$completed_since_full_test" -ge "$FULL_TEST_INTERVAL" ]; then
    run_full_test_suite_with_pause
  fi

  # Try to dispatch eligible plans to idle workers
  while true; do
    slot=$(find_idle_slot) || break
    eligible=$(find_eligible_plan)
    [ -z "$eligible" ] && break
    dispatch_plan "$slot" "$eligible" || {
      log "!! Failed to dispatch plan $eligible to slot $slot"
      break
    }
  done

  # Check exit conditions: any workers active? any plans still pending?
  any_workers_active=false
  for ((i=0; i<MAX_WORKERS; i++)); do
    [ -n "${WORKER_PIDS[$i]}" ] && any_workers_active=true
  done

  any_pending=false
  for pid in $(all_plan_ids); do
    if ! plan_is_done "$pid" && ! plan_is_blocked "$pid"; then
      any_pending=true
      break
    fi
  done

  if ! $any_workers_active && ! $any_pending; then
    log "=== All plans processed ==="
    log "Completed: $total_completed | Blocked: $total_blocked"

    if [ "$completed_since_full_test" -gt 0 ]; then
      ORCH_PHASE="running final test suite"
      generate_dashboard
      log "Running final full test suite..."
      final_test_log=$(mktemp)
      if ! run_full_test_suite_captured "$final_test_log"; then
        ORCH_PHASE="auto-fixing final test failures"
        generate_dashboard
        log "!! Final full test suite failed — attempting auto-fix..."
        error_ctx=$(mktemp)
        build_error_context "$error_ctx" "full_test" "$final_test_log"
        fix_log_prefix="$SCRIPT_DIR/execution/final_test_fix"
        if ! attempt_fix_with_retry "full_test" "$REPO_ROOT" "$error_ctx" "$fix_log_prefix"; then
          log "!! Auto-fix FAILED. HALTING."
          rm -f "$error_ctx" "$final_test_log"
          generate_dashboard
          exit 1
        fi
        log "Auto-fix succeeded. Final test suite now passing."
        rm -f "$error_ctx"
      fi
      rm -f "$final_test_log"
    fi

    log "Generating final release notes..."
    RELEASE_NOTES="$SCRIPT_DIR/RELEASE_NOTES.md"
    "$SCRIPT_DIR/generate_release_notes.sh" || true
    generate_dashboard
    log "Release notes written to $RELEASE_NOTES"
    printf "\nHit enter when ready to review release notes: "
    read -r _ && open "$RELEASE_NOTES"
    exit 0
  fi

  # If no workers active and nothing eligible but plans still pending,
  # we're deadlocked — remaining plans depend on blocked plans
  if ! $any_workers_active && $any_pending; then
    eligible_check=$(find_eligible_plan)
    if [ -z "$eligible_check" ]; then
      log "!! No eligible plans and no active workers. Possible deadlock."
      log "   Remaining plans may depend on blocked plans. Check blocked/ directory."
      generate_dashboard
      exit 1
    fi
  fi

  sleep "$POLL_INTERVAL"
done
