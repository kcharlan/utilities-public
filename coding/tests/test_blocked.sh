#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
source_file="${ORCHESTRATOR_SOURCE:-$root/task_orch/orchestrate.sh}"
d=$(mktemp -d "${TMPDIR:-/tmp}/audit-XXXXXX")
trap 'rm -r -- "${d:?}"' EXIT
export HOME="$d/home" GIT_CONFIG_NOSYSTEM=1
mkdir -p "$HOME"
awk '/^move_plan_to_blocked\(\)/,/^}/; /^handle_worker_completion\(\)/,/^}/' "$source_file" > "$d/functions"
source "$d/functions"
log() { :; }
build_error_context() { :; }
attempt_fix_with_retry() { ((attempt_count+=1)); [ "$attempt_count" -eq 1 ]; }

# Delegate to real Git, except intercept legacy destructive cleanup so the
# baseline can demonstrate the attempted loss without performing it.
git() {
  if [ "$1" = worktree ] && [ "$2" = remove ] && [ "${3:-}" = --force ]; then
    printf 'forced removal\n' >> "$case_dir/unsafe"
    return 0
  fi
  if [ "$1" = branch ] && [ "${2:-}" = -D ]; then
    printf 'forced branch deletion\n' >> "$case_dir/unsafe"
    return 0
  fi
  if [ "$1" = worktree ] && [ "$2" = remove ]; then
    test "$(command git show HEAD:repaired)" = 'merged repair' || {
      echo 'cleanup preceded repaired merge' >&2; return 1;
    }
    : > "$case_dir/merged_before_cleanup"
  fi
  command git "$@"
}

setup_case() {
  case_dir="$d/$1"
  mkdir -p "$case_dir/repo" "$case_dir/queue/workers/1" "$case_dir/queue/blocked" "$case_dir/queue/done"
  cd "$case_dir/repo"
  command git init -q
  command git config user.email synthetic@example.invalid
  command git config user.name Synthetic
  mkdir -p task_orch/execution/workers/1
  printf 'base\n' > conflict
  printf 'STATUS: failed\n' > task_orch/execution/workers/1/123_test.status
  command git add conflict task_orch
  command git commit -qm initial
  WORKERS_DIR="$case_dir/queue/workers" BLOCKED_DIR="$case_dir/queue/blocked"
  DONE_DIR="$case_dir/queue/done" WORKTREES_DIR="$case_dir/worktrees" SCRIPT_DIR="$case_dir"
  mkdir -p "$WORKTREES_DIR"
  command git worktree add -qb worker-1-123 "$WORKTREES_DIR/worker_1"
  printf 'plan\n' > "$WORKERS_DIR/1/123_test.plan.md"
  WORKER_PLANS=(unused 123) WORKER_PIDS=(unused 42)
  total_blocked=0 total_completed=0 completed_since_full_test=0 FULL_TEST_INTERVAL=4
  FIXER_MODEL=stub MAX_FIX_ATTEMPTS=2
  attempt_count=0
  : > "$case_dir/unsafe"
}

setup_case conflict
printf 'worker\n' > "$WORKTREES_DIR/worker_1/conflict"
command git -C "$WORKTREES_DIR/worker_1" add conflict
command git -C "$WORKTREES_DIR/worker_1" commit -qm worker
worker_commit=$(command git -C "$WORKTREES_DIR/worker_1" rev-parse HEAD)
printf 'main\n' > conflict
command git add conflict
command git commit -qm main
printf 'STATUS: done\n' > "$WORKTREES_DIR/worker_1/task_orch/execution/workers/1/123_test.status"
printf 'preserve me\n' > "$WORKTREES_DIR/worker_1/untracked"
handle_worker_completion 1
test ! -s "$case_dir/unsafe" || { echo 'blocked work was removed' >&2; exit 1; }
test -f "$BLOCKED_DIR/123_test.plan.md"
test "$(command git rev-parse worker-1-123)" = "$worker_commit"
test "$(command git -C "$WORKTREES_DIR/worker_1" rev-parse HEAD)" = "$worker_commit"
test "$(cat "$WORKTREES_DIR/worker_1/conflict")" = worker
test "$(cat "$WORKTREES_DIR/worker_1/untracked")" = 'preserve me'
test -n "$(command git ls-files -u)"
echo 'real merge conflict preserved worktree, branch, and unresolved index'

setup_case repaired
printf 'merged repair\n' > "$WORKTREES_DIR/worker_1/repaired"
command git -C "$WORKTREES_DIR/worker_1" add repaired
command git -C "$WORKTREES_DIR/worker_1" commit -qm repair
handle_worker_completion 1
test -f "$case_dir/merged_before_cleanup"
test "$(command git show HEAD:repaired)" = 'merged repair'
test -f "$DONE_DIR/123_test.plan.md"
test ! -e "$WORKTREES_DIR/worker_1"
test ! -s "$case_dir/unsafe"
echo 'real repaired branch merged before cleanup'
