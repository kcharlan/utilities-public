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

# Lifecycle scripts must run Compose from their own directory regardless of
# the caller's working directory. A stub docker records where it was invoked.
mkdir -p "$TEST_ROOT/bin" "$TEST_ROOT/elsewhere"
cat >"$TEST_ROOT/bin/docker" <<'EOF'
#!/bin/sh
printf '%s|%s\n' "$PWD" "$*" >>"$DOCKER_STUB_LOG"
EOF
chmod +x "$TEST_ROOT/bin/docker"

for script_name in up.sh down.sh; do
  : >"$TEST_ROOT/docker.log"
  (
    cd "$TEST_ROOT/elsewhere"
    HOME="$TEST_ROOT/home" \
    XDG_CONFIG_HOME="$TEST_ROOT/config" \
    XDG_STATE_HOME="$TEST_ROOT/state" \
    PATH="$TEST_ROOT/bin:$PATH" \
    DOCKER_STUB_LOG="$TEST_ROOT/docker.log" \
    "$PROJECT_DIR/llm_collector_container/$script_name" >/dev/null
  )
  test -s "$TEST_ROOT/docker.log"
  while IFS='|' read -r invoked_dir invoked_args; do
    if [[ "$invoked_dir" != "$PROJECT_DIR/llm_collector_container" ]]; then
      print -u2 -- "$script_name ran 'docker $invoked_args' in $invoked_dir"
      exit 1
    fi
  done <"$TEST_ROOT/docker.log"
done

print -- "llm_collector local_config shell tests: PASS"
