#!/bin/zsh
set -euo pipefail
root="${0:A:h:h}"
d=$(mktemp -d "${TMPDIR:-/tmp}/docker-bundle-test-XXXXXX")
trap 'rm -r -- "${d:?}"' EXIT
mkdir -p "$d/bin" "$d/bundle" "$d/deploy" "$d/config/llm_collector" "$d/state"
for stack in webserver excalidraw llm_proxy n8n-poc; do
  mkdir -p "$d/bundle/$stack"
  cp "$root/$stack/update.sh" "$d/bundle/$stack/"
done
cp "$root/n8n-poc/up.sh" "$d/bundle/n8n-poc/"
mkdir -p "$d/bundle/llm_collector/llm_collector_container"
cp "$root/llm_collector/local_config.sh" "$d/bundle/llm_collector/"
cp "$root/llm_collector/llm_collector_container/update.sh" "$d/bundle/llm_collector/llm_collector_container/"
mkdir -p "$d/deploy/"{webserver,excalidraw,llm_proxy,llm_collector/llm_collector_container,n8n-poc}
print -l '#!/bin/zsh' 'print untrusted-helper >> "$CALL_LOG"' > "$d/deploy/n8n-poc/up.sh"
chmod 755 "$d/deploy/n8n-poc/up.sh"
print 'print untrusted-helper >> "$CALL_LOG"' > "$d/deploy/llm_collector/local_config.sh"
print 'WEBROOT_PATH=/synthetic/webroot' > "$d/deploy/webserver/.env"
print 'N8N_ENCRYPTION_KEY=synthetic-safe-key' > "$d/deploy/n8n-poc/.env"
print "API_KEY=synthetic-key\nLLM_COLLECTOR_DATA_DIR=$d/state" > "$d/config/llm_collector/secret.env"
cat > "$d/bin/docker" <<'STUB'
#!/bin/zsh
print -r -- "$PWD :: $* :: output=${PROPAGATE_PROXY_OUTPUT_DIR:-unset}" >> "$CALL_LOG"
if [[ " $* " == *' config --format json '* ]]; then print -r -- '{"services":{"n8n":{"environment":{"N8N_ENCRYPTION_KEY":"synthetic-key"}}}}'; fi
STUB
cat > "$d/bin/curl" <<'STUB'
#!/bin/zsh
exit 0
STUB
chmod 755 "$d/bin/"{docker,curl}
export PATH="$d/bin:$PATH" CALL_LOG="$d/calls" XDG_CONFIG_HOME="$d/config"
for stack in webserver excalidraw llm_proxy n8n-poc; do
  : > "$CALL_LOG"
  PROPAGATE_STACK_ROOT="$d/deploy/$stack" "$d/bundle/$stack/update.sh" > "$d/out" 2>&1
  grep -F -- "--project-directory ${d:A}/bundle/$stack" "$CALL_LOG" >/dev/null || { print -u2 "missing trusted context: $stack"; exit 1; }
  grep -F -- "${d:A}/deploy/$stack ::" "$CALL_LOG" >/dev/null || { print -u2 "wrong working directory: $stack"; exit 1; }
  if [[ "$stack" == webserver ]]; then
    grep -F -- "--env-file ${d:A}/deploy/webserver/.env" "$CALL_LOG" >/dev/null
  elif [[ "$stack" == llm_proxy ]]; then
    grep -F -- "-f ${d:A}/bundle/llm_proxy/compose.propagate.yml" "$CALL_LOG" >/dev/null
    grep -F -- "output=${d:A}/deploy/llm_proxy/output" "$CALL_LOG" >/dev/null
  fi
done
! grep -Fxq 'untrusted-helper' "$CALL_LOG" || { print -u2 'executed deployed n8n helper'; exit 1; }
grep -F -- "--env-file ${d:A}/deploy/n8n-poc/.env" "$CALL_LOG" >/dev/null
: > "$CALL_LOG"
PROPAGATE_STACK_ROOT="$d/deploy/llm_collector/llm_collector_container" "$d/bundle/llm_collector/llm_collector_container/update.sh" > "$d/out" 2>&1
grep -F -- "--project-directory ${d:A}/bundle/llm_collector/llm_collector_container" "$CALL_LOG" >/dev/null
! grep -Fxq 'untrusted-helper' "$CALL_LOG" || { print -u2 'executed deployed collector helper'; exit 1; }
print 'All trusted updater tests passed.'
