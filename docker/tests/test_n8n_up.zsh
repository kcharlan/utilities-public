#!/bin/zsh
set -euo pipefail
root="${0:A:h:h}"
d=$(mktemp -d "${TMPDIR:-/tmp}/n8n-test-XXXXXX")
trap 'rm -r -- "${d:?}"' EXIT
mkdir -p "$d/bin" "$d/stack"
cp "$root/n8n-poc/"{up.sh,.env.example} "$d/stack/"
cat > "$d/bin/docker" <<'STUB'
#!/bin/zsh
print -r -- "$*" >> "$CALL_LOG"
if [[ " $* " == *' config --format json '* ]]; then
  print -r -- "{\"services\":{\"n8n\":{\"environment\":{\"N8N_ENCRYPTION_KEY\":\"${FAKE_RESOLVED_KEY:-synthetic-key}\"}}}}"
fi
STUB
chmod +x "$d/bin/docker"
export PATH="$d/bin:$PATH" CALL_LOG="$d/calls"
cp "$d/stack/.env.example" "$d/stack/.env"
: > "$CALL_LOG"
if "$d/stack/up.sh" > "$d/out" 2>&1; then print -u2 'example key accepted'; exit 1; fi
[[ ! -s "$CALL_LOG" ]] || { print -u2 'Docker called for example key'; exit 1; }
sed 's/SYNTHETIC_ONLY_REPLACE_WITH_A_LONG_RANDOM_VALUE/synthetic-test-key/' "$d/stack/.env.example" > "$d/stack/.env"
print '# Old example: SYNTHETIC_ONLY_REPLACE_WITH_A_LONG_RANDOM_VALUE' >> "$d/stack/.env"
"$d/stack/up.sh" > "$d/out" 2>&1
grep -F 'compose up -d --wait' "$CALL_LOG" >/dev/null
: > "$CALL_LOG"
if FAKE_RESOLVED_KEY=SYNTHETIC_ONLY_REPLACE_WITH_A_LONG_RANDOM_VALUE "$d/stack/up.sh" > "$d/out" 2>&1; then print -u2 'resolved example key accepted'; exit 1; fi
! grep -F 'compose pull' "$CALL_LOG" >/dev/null || { print -u2 'pulled with example key'; exit 1; }
: > "$CALL_LOG"
mkdir "$d/bundle"
cp "$root/n8n-poc/up.sh" "$d/bundle/up.sh"
PROPAGATE_STACK_ROOT="$d/stack" "$d/bundle/up.sh" > "$d/out" 2>&1
grep -F -- "--project-directory ${d:A}/bundle" "$CALL_LOG" >/dev/null
grep -F -- "--env-file ${d:A}/stack/.env" "$CALL_LOG" >/dev/null
print 'All n8n up tests passed.'
