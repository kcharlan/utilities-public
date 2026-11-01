#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
source_file="${ORCHESTRATOR_SOURCE:-$root/task_orch/orchestrate.sh}"
d=$(mktemp -d "${TMPDIR:-/tmp}/audit-XXXXXX")
trap 'rm -r -- "${d:?}"' EXIT
mkdir -p "$d/workers/1" "$d/blocked" "$d/worktrees/worker_1"
printf 'STATUS: done\n' > "$d/workers/1/123_test.status"
printf 'plan\n' > "$d/workers/1/123_test.plan.md"
awk '/^move_plan_to_blocked\(\)/,/^}/; /^handle_worker_completion\(\)/,/^}/' "$source_file" > "$d/functions"
WORKERS_DIR="$d/workers" BLOCKED_DIR="$d/blocked" WORKTREES_DIR="$d/worktrees"
SCRIPT_DIR="$d" total_blocked=0
: > "$d/git_calls"
WORKER_PLANS=(unused 123) WORKER_PIDS=(unused 42)
log() { :; }
git() { printf '%s\n' "$*" >> "$d/git_calls"; if [ "$1" = merge ] && [ "${case_mode:-conflict}" = conflict ]; then return 1; fi; }
source "$d/functions"
handle_worker_completion 1
test -d "$d/worktrees/worker_1"
test -f "$d/blocked/123_test.plan.md"
if grep -q 'worktree remove\|branch -D' "$d/git_calls"; then
  echo 'blocked work was removed' >&2; exit 1
fi
echo 'blocked work preserved'
mkdir -p "$d/done"
mkdir -p "$d/worktrees/worker_1/task_orch/execution/workers/1"
printf 'STATUS: failed\n' > "$d/worktrees/worker_1/task_orch/execution/workers/1/123_test.status"
mv "$d/blocked/123_test.plan.md" "$d/workers/1/"
printf 'STATUS: failed\n' > "$d/workers/1/123_test.status"
WORKER_PLANS[1]=123 WORKER_PIDS[1]=42
DONE_DIR="$d/done" FULL_TEST_INTERVAL=4 completed_since_full_test=0 total_completed=0 FIXER_MODEL=stub MAX_FIX_ATTEMPTS=2
case_mode=repaired
build_error_context() { :; }
attempt_count=0
attempt_fix_with_retry() { ((attempt_count+=1)); [ "$attempt_count" -eq 1 ]; }
: > "$d/git_calls"
handle_worker_completion 1
grep -q '^merge --squash worker-1-123$' "$d/git_calls"
test -f "$d/done/123_test.plan.md"
echo 'repaired work merged'
