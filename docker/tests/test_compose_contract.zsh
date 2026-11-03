#!/bin/zsh
set -euo pipefail
root="${0:A:h:h}"
d=$(mktemp -d "${TMPDIR:-/tmp}/compose-contract-XXXXXX")
trap 'rm -r -- "${d:?}"' EXIT
d="${d:A}"
loopback_only() {
  jq -e '[.services[] | (.ports // [])[]] | length > 0 and all(.host_ip == "127.0.0.1")' "$1" >/dev/null
}
# Exit, not return: zsh 5.9 skips the EXIT trap when a function returns
# nonzero at top level, which would leave $d behind.
assert_loopback() {
  loopback_only "$2" || { print -u2 -- "$1 publishes no ports or a non-loopback port"; exit 1; }
}
mkdir -p "$d/home" "$d/bundle/"{webserver,excalidraw,llm_proxy,n8n-poc,llm_collector/llm_collector_container} "$d/deploy/"{webserver,llm_proxy/output,n8n-poc} "$d/data" "$d/webroot"
# Cleanup regression hook: fail one assertion and stop, as a failing check would.
if [[ -n "${COMPOSE_CONTRACT_INJECT_FAILURE:-}" ]]; then
  print -r -- '{"services":{}}' > "$d/no-ports.json"
  assert_loopback synthetic-injected "$d/no-ports.json"
  print -u2 'Injected failure unexpectedly passed'
  exit 0
fi
for stack in webserver excalidraw llm_proxy n8n-poc; do
  cp "$root/$stack/docker-compose.yml" "$d/bundle/$stack/"
done
cp "$root/llm_proxy/compose.propagate.yml" "$d/bundle/llm_proxy/"
cp "$root/llm_collector/llm_collector_container/docker-compose.yml" "$d/bundle/llm_collector/llm_collector_container/"
print -r -- "WEBROOT_PATH=$d/webroot" > "$d/deploy/webserver/.env"
print -l 'N8N_ENCRYPTION_KEY=synthetic-test-key' "N8N_DATA_DIR=$d/data" > "$d/deploy/n8n-poc/.env"
export HOME="$d/home"
docker-compose -p webserver --project-directory "$d/bundle/webserver" --env-file "$d/deploy/webserver/.env" -f "$d/bundle/webserver/docker-compose.yml" config --format json > "$d/web.json"
assert_loopback webserver "$d/web.json"
jq -e --arg code "$d/bundle/webserver" --arg webroot "$d/webroot" '.services.app_py.build.context == ($code + "/app_py") and .services.app_node.build.context == $code and ([.services.app_py.volumes[] | select(.target == "/app" and .read_only == true) | .source] == [($code + "/app_py")]) and ([.services.web.volumes[] | select(.target == "/etc/nginx/conf.d/default.conf" and .read_only == true) | .source] == [($code + "/nginx/default.conf")]) and ([.services.web.volumes[] | select(.target == "/usr/share/nginx/html") | .source] == [$webroot])' "$d/web.json" >/dev/null
PROPAGATE_PROXY_OUTPUT_DIR="$d/deploy/llm_proxy/output" docker-compose -p llm_proxy --project-directory "$d/bundle/llm_proxy" -f "$d/bundle/llm_proxy/docker-compose.yml" -f "$d/bundle/llm_proxy/compose.propagate.yml" config --format json > "$d/proxy.json"
assert_loopback llm_proxy "$d/proxy.json"
jq -e --arg code "$d/bundle/llm_proxy" --arg output "$d/deploy/llm_proxy/output" '.services["llm-proxy"].build.context == $code and ([.services["llm-proxy"].volumes[] | select(.target == "/output") | .source] == [$output])' "$d/proxy.json" >/dev/null
API_KEY=synthetic-key LLM_COLLECTOR_DATA_DIR="$d/data" docker-compose -p llm_collector_container --project-directory "$d/bundle/llm_collector/llm_collector_container" -f "$d/bundle/llm_collector/llm_collector_container/docker-compose.yml" config --format json > "$d/collector.json"
assert_loopback llm_collector "$d/collector.json"
jq -e --arg code "$d/bundle/llm_collector" --arg data "$d/data" '.services["llm-collector"].build.context == $code and ([.services["llm-collector"].volumes[] | select(.target == "/var/lib/llm_collector") | .source] == [$data])' "$d/collector.json" >/dev/null
docker-compose -p n8n-poc --project-directory "$d/bundle/n8n-poc" --env-file "$d/deploy/n8n-poc/.env" -f "$d/bundle/n8n-poc/docker-compose.yml" config --format json > "$d/n8n.json"
assert_loopback n8n-poc "$d/n8n.json"
jq -e --arg data "$d/data" '[.services.n8n.volumes[] | select(.target == "/home/node/.n8n") | .source] == [$data]' "$d/n8n.json" >/dev/null
docker-compose -p excalidraw --project-directory "$d/bundle/excalidraw" -f "$d/bundle/excalidraw/docker-compose.yml" config --format json > "$d/excalidraw.json"
assert_loopback excalidraw "$d/excalidraw.json"
jq -e '.name == "excalidraw"' "$d/excalidraw.json" >/dev/null
mkdir -p "$d/bundle/synthetic"
cat > "$d/bundle/synthetic/docker-compose.yml" <<'EOF'
services:
  synthetic:
    image: busybox
    ports: ["5999:80"]
EOF
docker-compose -p synthetic --project-directory "$d/bundle/synthetic" -f "$d/bundle/synthetic/docker-compose.yml" config --format json > "$d/synthetic.json"
if loopback_only "$d/synthetic.json"; then
  print -u2 'Synthetic non-loopback port unexpectedly passed the loopback check'
  exit 1
fi
# A failing assertion must still remove the suite directory.
mkdir -p "$d/cleanup-tmp"
cleanup_status=0
TMPDIR="$d/cleanup-tmp" COMPOSE_CONTRACT_INJECT_FAILURE=1 /bin/zsh "${0:A}" > "$d/cleanup.out" 2>&1 || cleanup_status=$?
if (( cleanup_status == 0 )) || ! grep -Fq 'synthetic-injected publishes no ports' "$d/cleanup.out" ||
   [[ -n "$(find "$d/cleanup-tmp" -mindepth 1 -print -quit)" ]]; then
  cat "$d/cleanup.out" >&2
  print -u2 -- "A failing assertion exited $cleanup_status or left: $(find "$d/cleanup-tmp" -mindepth 1 -maxdepth 1)"
  exit 1
fi
print 'All Compose contract tests passed.'
