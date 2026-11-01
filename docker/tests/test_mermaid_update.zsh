#!/bin/zsh
set -euo pipefail
root="${0:A:h:h}"
d=$(mktemp -d "${TMPDIR:-/tmp}/mermaid-test-XXXXXX")
trap 'rm -r -- "${d:?}"' EXIT
mkdir -p "$d/bin"
cat > "$d/bin/docker" <<'STUB'
#!/bin/zsh
print -r -- "$*" >> "$CALL_LOG"
[[ "${FAIL_PULL:-0}" == 1 && "$1" == pull ]] && exit 1
[[ "$1" == create ]] && { [[ "${FAIL_CREATE:-0}" == 1 ]] && exit 1; print synthetic-container-id; exit 0; }
[[ "${FAIL_RUN:-0}" == 1 && "$1" == start && "$2" == synthetic-container-id ]] && exit 1
exit 0
STUB
chmod +x "$d/bin/docker"
export PATH="$d/bin:$PATH" CALL_LOG="$d/calls"
: > "$CALL_LOG"
if FAIL_PULL=1 "$root/mermaid/update.sh" > "$d/out" 2>&1; then print -u2 'pull failure accepted'; exit 1; fi
! grep -E '^(stop|rm|rename|run|create|start) ' "$CALL_LOG" >/dev/null
: > "$CALL_LOG"
if FAIL_RUN=1 "$root/mermaid/update.sh" > "$d/out" 2>&1; then print -u2 'run failure accepted'; exit 1; fi
grep -E '^rename mermaid-rollback-[0-9]+ mermaid$' "$CALL_LOG" >/dev/null
grep -Fx 'start mermaid' "$CALL_LOG" >/dev/null
: > "$CALL_LOG"
if FAIL_CREATE=1 "$root/mermaid/update.sh" > "$d/out" 2>&1; then print -u2 'create failure accepted'; exit 1; fi
grep -E '^rename mermaid-rollback-[0-9]+ mermaid$' "$CALL_LOG" >/dev/null
! grep -E '^rm -f ' "$CALL_LOG" >/dev/null || { print -u2 'create failure removed an unowned container'; exit 1; }
: > "$CALL_LOG"
"$root/mermaid/update.sh" > "$d/out" 2>&1
grep -Fx 'rename synthetic-container-id mermaid' "$CALL_LOG" >/dev/null
grep -E '^rm mermaid-rollback-[0-9]+$' "$CALL_LOG" >/dev/null
print 'All mermaid update tests passed.'
