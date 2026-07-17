#!/bin/zsh

set -euo pipefail

PROJECT_DIR="${0:A:h:h}"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

mkdir -p "$TEST_ROOT/config/llm_collector" "$TEST_ROOT/state"
cat >"$TEST_ROOT/config/llm_collector/secret.env" <<'EOF'
API_KEY=SYNTHETIC_TEST_KEY
EOF

for shell_name in bash zsh; do
  HOME="$TEST_ROOT/home" \
  XDG_CONFIG_HOME="$TEST_ROOT/config" \
  XDG_STATE_HOME="$TEST_ROOT/state" \
  "$shell_name" -c '
    set -u
    source "$1/local_config.sh"
    load_llm_collector_env
    test "$PROJECT_ROOT" = "$1"
    test "$API_KEY" = "SYNTHETIC_TEST_KEY"  # pragma: allowlist secret
    test "$LLM_COLLECTOR_DATA_DIR" = "$XDG_STATE_HOME/llm_collector"
  ' shell-test "$PROJECT_DIR"
done

print -- "llm_collector local_config shell tests: PASS"
