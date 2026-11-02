#!/bin/zsh
set -euo pipefail
root="${0:A:h:h}"
d=$(mktemp -d "${TMPDIR:-/tmp}/actual-test-XXXXXX")
trap 'rm -r -- "${d:?}"' EXIT
mkdir -p "$d/bin" "$d/repo/actual" "$d/private/actual"
cp "$root/actual-data/"{start.sh,update.sh} "$d/repo/actual/"
cp "$root/actual-data/"{start.sh,update.sh} "$d/private/actual/"
git -C "$d/repo" init -q
cat > "$d/bin/docker" <<'STUB'
#!/bin/zsh
print -r -- "$*" >> "$CALL_LOG"
[[ "${FAIL_PULL:-0}" == 1 && "$1" == pull ]] && exit 1
[[ "$1" == create ]] && { [[ "${FAIL_CREATE:-0}" == 1 ]] && exit 1; print synthetic-container-id; exit 0; }
[[ "${FAIL_RUN:-0}" == 1 && "$1" == start && "$2" == synthetic-container-id ]] && exit 1
[[ "$1" == inspect ]] && { print "${FAKE_HEALTH:-healthy}"; exit 0; }
exit 0
STUB
chmod +x "$d/bin/docker"
export PATH="$d/bin:$PATH" CALL_LOG="$d/calls"
: > "$CALL_LOG"
if "$d/repo/actual/start.sh" > "$d/out" 2>&1; then print -u2 'start accepted Git checkout'; exit 1; fi
[[ ! -s "$CALL_LOG" ]] || { print -u2 'start invoked Docker in checkout'; exit 1; }
if "$d/repo/actual/update.sh" > "$d/out" 2>&1; then print -u2 'update accepted Git checkout'; exit 1; fi
[[ ! -s "$CALL_LOG" ]] || { print -u2 'update invoked Docker in checkout'; exit 1; }
ln -s "$d/repo/actual" "$d/linked"
if "$d/linked/start.sh" > "$d/out" 2>&1; then print -u2 'start accepted linked Git checkout'; exit 1; fi
"$d/private/actual/start.sh" > "$d/out" 2>&1
grep -F -- "${d:A}/private/actual:/data" "$CALL_LOG" >/dev/null
: > "$CALL_LOG"
if FAIL_PULL=1 "$d/private/actual/update.sh" > "$d/out" 2>&1; then print -u2 'update accepted pull failure'; exit 1; fi
! grep -E '^(stop|rm|rename|run|create|start) ' "$CALL_LOG" >/dev/null || { print -u2 'pull failure changed container'; exit 1; }
: > "$CALL_LOG"
if FAIL_RUN=1 "$d/private/actual/update.sh" > "$d/out" 2>&1; then print -u2 'update accepted run failure'; exit 1; fi
grep -E '^rename actual-rollback-[0-9]+ actual$' "$CALL_LOG" >/dev/null
grep -F 'start actual' "$CALL_LOG" >/dev/null
: > "$CALL_LOG"
if FAKE_HEALTH=unhealthy "$d/private/actual/update.sh" > "$d/out" 2>&1; then print -u2 'unhealthy replacement accepted'; exit 1; fi
grep -E '^rename actual-rollback-[0-9]+ actual$' "$CALL_LOG" >/dev/null
grep -Fx 'start actual' "$CALL_LOG" >/dev/null
: > "$CALL_LOG"
if FAIL_CREATE=1 "$d/private/actual/update.sh" > "$d/out" 2>&1; then print -u2 'update accepted create failure'; exit 1; fi
grep -E '^rename actual-rollback-[0-9]+ actual$' "$CALL_LOG" >/dev/null
grep -Fx 'start actual' "$CALL_LOG" >/dev/null
! grep -E '^rm -f ' "$CALL_LOG" >/dev/null || { print -u2 'create failure removed an unowned container'; exit 1; }
: > "$CALL_LOG"
"$d/private/actual/update.sh" > "$d/out" 2>&1
grep -Fx 'rename synthetic-container-id actual' "$CALL_LOG" >/dev/null
grep -E '^rm actual-rollback-[0-9]+$' "$CALL_LOG" >/dev/null
: > "$CALL_LOG"
mkdir "$d/bundle"
cp "$root/actual-data/update.sh" "$d/bundle/update.sh"
PROPAGATE_STACK_ROOT="$d/private/actual" "$d/bundle/update.sh" > "$d/out" 2>&1
grep -F -- "${d:A}/private/actual:/data" "$CALL_LOG" >/dev/null
print 'All actual start/update tests passed.'
