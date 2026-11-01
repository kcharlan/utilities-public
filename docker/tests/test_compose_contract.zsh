#!/bin/zsh
set -euo pipefail
root="${0:A:h:h}"
d=$(mktemp -d "${TMPDIR:-/tmp}/compose-contract-XXXXXX")
trap 'rm -r -- "${d:?}"' EXIT
d="${d:A}"
mkdir -p "$d/home" "$d/bundle/"{webserver,excalidraw,llm_proxy,n8n-poc,llm_collector/llm_collector_container} "$d/deploy/"{webserver,llm_proxy/output,n8n-poc} "$d/data" "$d/webroot"
for stack in webserver excalidraw llm_proxy n8n-poc; do
  cp "$root/$stack/docker-compose.yml" "$d/bundle/$stack/"
done
cp "$root/llm_proxy/compose.propagate.yml" "$d/bundle/llm_proxy/"
cp "$root/llm_collector/llm_collector_container/docker-compose.yml" "$d/bundle/llm_collector/llm_collector_container/"
print -r -- "WEBROOT_PATH=$d/webroot" > "$d/deploy/webserver/.env"
print -l 'N8N_ENCRYPTION_KEY=synthetic-test-key' "N8N_DATA_DIR=$d/data" > "$d/deploy/n8n-poc/.env"
export HOME="$d/home"
docker-compose -p webserver --project-directory "$d/bundle/webserver" --env-file "$d/deploy/webserver/.env" -f "$d/bundle/webserver/docker-compose.yml" config --format json > "$d/web.json"
jq -e --arg code "$d/bundle/webserver" --arg webroot "$d/webroot" '.services.app_py.build.context == ($code + "/app_py") and .services.app_node.build.context == $code and ([.services.app_py.volumes[] | select(.target == "/app" and .read_only == true) | .source] == [($code + "/app_py")]) and ([.services.web.volumes[] | select(.target == "/etc/nginx/conf.d/default.conf" and .read_only == true) | .source] == [($code + "/nginx/default.conf")]) and ([.services.web.volumes[] | select(.target == "/usr/share/nginx/html") | .source] == [$webroot])' "$d/web.json" >/dev/null
PROPAGATE_PROXY_OUTPUT_DIR="$d/deploy/llm_proxy/output" docker-compose -p llm_proxy --project-directory "$d/bundle/llm_proxy" -f "$d/bundle/llm_proxy/docker-compose.yml" -f "$d/bundle/llm_proxy/compose.propagate.yml" config --format json > "$d/proxy.json"
jq -e --arg code "$d/bundle/llm_proxy" --arg output "$d/deploy/llm_proxy/output" '.services["llm-proxy"].build.context == $code and ([.services["llm-proxy"].volumes[] | select(.target == "/output") | .source] == [$output])' "$d/proxy.json" >/dev/null
API_KEY=synthetic-key LLM_COLLECTOR_DATA_DIR="$d/data" docker-compose -p llm_collector_container --project-directory "$d/bundle/llm_collector/llm_collector_container" -f "$d/bundle/llm_collector/llm_collector_container/docker-compose.yml" config --format json > "$d/collector.json"
jq -e --arg code "$d/bundle/llm_collector" --arg data "$d/data" '.services["llm-collector"].build.context == $code and ([.services["llm-collector"].volumes[] | select(.target == "/var/lib/llm_collector") | .source] == [$data])' "$d/collector.json" >/dev/null
docker-compose -p n8n-poc --project-directory "$d/bundle/n8n-poc" --env-file "$d/deploy/n8n-poc/.env" -f "$d/bundle/n8n-poc/docker-compose.yml" config --format json > "$d/n8n.json"
jq -e --arg data "$d/data" '[.services.n8n.volumes[] | select(.target == "/home/node/.n8n") | .source] == [$data]' "$d/n8n.json" >/dev/null
docker-compose -p excalidraw --project-directory "$d/bundle/excalidraw" -f "$d/bundle/excalidraw/docker-compose.yml" config --format json > "$d/excalidraw.json"
jq -e '.name == "excalidraw"' "$d/excalidraw.json" >/dev/null
print 'All Compose contract tests passed.'
