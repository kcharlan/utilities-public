#!/bin/zsh
#
# Stubbed tests for docker/propagate-updates.zsh. Each case builds a synthetic
# Git repository, a synthetic deployed copy under a temporary HOME, and stub
# docker/npm/uv/uvx/node commands that log their calls. Nothing reaches the
# network, a real container, the real repository or the real ~/docker.

set -euo pipefail

readonly TEST_SCRIPT_DIR="${0:A:h}"
readonly SCRIPT_UNDER_TEST="${TEST_SCRIPT_DIR:h}/propagate-updates.zsh"

umask 077
suite_parent="${TMPDIR:-/tmp}"
suite_root="$(mktemp -d "$suite_parent/propagate-updates-tests.XXXXXX")"
readonly SUITE_ROOT="${suite_root:A}"

cleanup_suite() {
  local saved_status=$?
  if [[ -n "${SUITE_ROOT:-}" &&
        "$SUITE_ROOT" == "${suite_parent:A}"/propagate-updates-tests.* &&
        -d "$SUITE_ROOT" &&
        ! -L "$SUITE_ROOT" ]]; then
    rm -rf -- "$SUITE_ROOT"
  fi
  return "$saved_status"
}
trap cleanup_suite EXIT

export GIT_CONFIG_NOSYSTEM=1
export GIT_CONFIG_GLOBAL=/dev/null

fail() {
  print -u2 -- "FAIL [$CASE_NAME]: $*"
  if [[ -f "${CASE:-}/out" ]]; then
    print -u2 -- "--- script output ---"
    sed -n '1,200p' "$CASE/out" >&2
  fi
  if [[ -f "${CASE:-}/calls.log" ]]; then
    print -u2 -- "--- call log ---"
    sed -n '1,200p' "$CASE/calls.log" >&2
  fi
  exit 1
}

assert_contains() {
  local file="$1" expected="$2"
  [[ -f "$file" ]] && grep -Fq -- "$expected" "$file" ||
    fail "expected '$expected' in ${file:t}"
}

assert_not_contains() {
  local file="$1" unexpected="$2"
  if [[ -f "$file" ]] && grep -Fq -- "$unexpected" "$file"; then
    fail "unexpected '$unexpected' in ${file:t}"
  fi
}

assert_status() {
  [[ "$RUN_STATUS" == "$1" ]] || fail "expected exit status $1, got $RUN_STATUS"
}

assert_same_file() {
  cmp -s "$1" "$2" || fail "files differ: $1 vs $2"
  [[ "$(stat -f '%Lp' "$1")" == "$(stat -f '%Lp' "$2")" ]] ||
    fail "modes differ: $1 vs $2"
}

assert_mode() {
  local actual
  actual="$(stat -f '%Lp' "$1")"
  [[ "$actual" == "$2" ]] || fail "expected mode $2 on $1, got $actual"
}

fixture_git() {
  git -C "$REPO" -c user.name=Fixture -c user.email=fixture@example.invalid \
    -c core.hooksPath=/dev/null -c commit.gpgsign=false "$@"
}

write_file() {
  mkdir -p "${1:h}"
  print -r -- "$2" > "$1"
}

write_updater() {
  local stack="$1" target="$REPO/docker/$2"
  mkdir -p "${target:h}"
  cat > "$target" <<EOF
#!/bin/zsh
print -r -- "update $stack \${0:A}" >> "\$CALL_LOG"
[[ "\${FAKE_FAIL_UPDATE:-}" == "$stack" ]] && exit 7
if [[ "\${FAKE_DROP_STACK:-}" == "$stack" ]]; then
  jq '[.[] | select(.Name != "${STACK_PROJECT[$stack]:-none}")]' "\$STATE_DIR/compose.json" > "\$STATE_DIR/compose.next"
  mv "\$STATE_DIR/compose.next" "\$STATE_DIR/compose.json"
fi
exit 0
EOF
  chmod 755 "$target"
}

typeset -A STACK_PROJECT=(
  webserver webserver
  llm_proxy llm_proxy
  llm_collector llm_collector_container
)

write_stub() {
  local name="$1" body="$2"
  cat > "$CASE/bin/$name" <<EOF
#!/bin/zsh
print -r -- "$name \$PWD :: \$* [UV_PYTHON_DOWNLOADS=\${UV_PYTHON_DOWNLOADS-unset} WEBROOT_PATH=\${WEBROOT_PATH-unset}]" >> "\$CALL_LOG"
$body
exit 0
EOF
  chmod 755 "$CASE/bin/$name"
}

install_stubs() {
  mkdir -p "$CASE/bin"
  write_stub docker '
if [[ "$1" == compose && "$2" == ls ]]; then cat "$STATE_DIR/compose.json"; exit 0; fi
if [[ "$1" == ps ]]; then cat "$STATE_DIR/containers.txt"; exit 0; fi
if [[ "$1" == pull ]]; then exit "${FAKE_PULL_RC:-0}"; fi
if [[ "$1" == compose && " $* " == *" build "* ]]; then exit "${FAKE_BUILD_RC:-0}"; fi'
  write_stub npm '
if [[ "$1" == update ]]; then print -- "// refreshed" >> package-lock.json; fi
if [[ "$1" == audit ]]; then exit "${FAKE_NPM_AUDIT_RC:-0}"; fi'
  write_stub uv '
if [[ "$1" == pip && "$2" == compile ]]; then print -- "# refreshed" >> requirements.lock; fi
if [[ "$1" == lock ]]; then print -- "# refreshed" >> uv.lock; fi
if [[ "$1" == export ]]; then
  while (( $# )); do
    if [[ "$1" == --output-file ]]; then print -- "fastapi==0.0.1" > "$2"; fi
    shift
  done
fi
if [[ "$1" == run ]]; then exit "${FAKE_PYTEST_RC:-0}"; fi'
  write_stub uvx 'exit "${FAKE_PIP_AUDIT_RC:-0}"'
  write_stub node 'exit "${FAKE_NODE_RC:-0}"'
}

# Builds a synthetic repository with every kind of stack the script knows
# about, commits it, and deploys an identical copy under $HOME/docker.
new_case() {
  CASE_NAME="$1"
  CASE="$SUITE_ROOT/$1"
  REPO="$CASE/repo"
  HOME_DIR="$CASE/home"
  DEPLOY="$HOME_DIR/docker"
  STATE="$CASE/state"
  mkdir -p "$REPO/docker" "$DEPLOY" "$STATE"
  : > "$CASE/calls.log"
  git init -q -b main "$REPO"

  cp -p "$SCRIPT_UNDER_TEST" "$REPO/docker/propagate-updates.zsh"
  write_file "$REPO/docker/README.md" "Synthetic docker projects"

  write_updater webserver webserver/update.sh
  write_file "$REPO/docker/webserver/docker-compose.yml" "services: {}"
  write_file "$REPO/docker/webserver/index/package.json" '{"name":"fixture-index"}'
  write_file "$REPO/docker/webserver/index/package-lock.json" '{"lockfileVersion":3}'
  write_file "$REPO/docker/webserver/app_node/package.json" '{"name":"fixture-node"}'
  write_file "$REPO/docker/webserver/app_node/package-lock.json" '{"lockfileVersion":3}'
  write_file "$REPO/docker/webserver/app_py/requirements.txt" "fastapi"
  write_file "$REPO/docker/webserver/app_py/requirements.lock" "fastapi==0.0.1"
  write_file "$REPO/docker/webserver/tests/nginx-routing.test.mjs" "// synthetic"

  write_updater llm_proxy llm_proxy/update.sh
  write_file "$REPO/docker/llm_proxy/docker-compose.yml" "services: {}"
  write_file "$REPO/docker/llm_proxy/pyproject.toml" '[project]'
  write_file "$REPO/docker/llm_proxy/uv.lock" "version = 1"

  write_updater llm_collector llm_collector/llm_collector_container/update.sh
  write_file "$REPO/docker/llm_collector/llm_collector_container/docker-compose.yml" "services: {}"
  write_file "$REPO/docker/llm_collector/collector/requirements.txt" "flask==0.0.1"
  write_file "$REPO/docker/llm_collector/migrate.sh" "#!/bin/zsh"

  write_updater actual-data actual-data/update.sh
  write_updater mermaid mermaid/update.sh
  write_file "$REPO/docker/n8n-poc/docker-compose.yml" "services: {}"

  fixture_git add -A
  fixture_git commit -q -m "Synthetic fixture"

  git -C "$REPO" ls-files -z -- docker | while IFS= read -r -d '' relative; do
    mkdir -p "$HOME_DIR/${relative:h}"
    cp -p "$REPO/$relative" "$HOME_DIR/$relative"
  done
  write_file "$DEPLOY/webserver/.env" "WEBROOT_PATH=/synthetic/webroot"
  chmod 600 "$DEPLOY/webserver/.env"
  write_file "$DEPLOY/llm_proxy/output/local.json" '{"local":true}'

  cat > "$STATE/compose.json" <<EOF
[{"Name":"webserver","Status":"running(4)","ConfigFiles":"$DEPLOY/webserver/docker-compose.yml"},
 {"Name":"llm_collector_container","Status":"running(1)","ConfigFiles":"$DEPLOY/llm_collector/llm_collector_container/docker-compose.yml"}]
EOF
  print -l actual webserver-web-1 > "$STATE/containers.txt"

  install_stubs
}

run_script() {
  RUN_STATUS=0
  (
    cd "$CASE"
    HOME="$HOME_DIR" PATH="$CASE/bin:$PATH" CALL_LOG="$CASE/calls.log" \
      STATE_DIR="$STATE" "$REPO/docker/propagate-updates.zsh" "$@"
  ) > "$CASE/out" 2>&1 || RUN_STATUS=$?
}

commit_change() {
  print -r -- "$2" >> "$REPO/docker/$1"
  fixture_git commit -q -am "Change $1"
}

backup_dir() {
  local dirs=("$HOME_DIR"/.utilities-deploy-backups/docker-*(N/))
  (( ${#dirs} == 1 )) || fail "expected one backup directory, found ${#dirs}"
  print -r -- "${dirs[1]}"
}

# --- usage ---------------------------------------------------------------

test_help_and_usage_errors() {
  new_case help
  run_script --help
  assert_status 0
  assert_contains "$CASE/out" "Usage:"
  run_script
  assert_status 2
  run_script deploy --stack nonexistent
  assert_status 2
  assert_contains "$CASE/out" "unknown stack: nonexistent"
  run_script frobnicate
  assert_status 2
}

# --- refresh -------------------------------------------------------------

test_refresh_runs_each_lock_audit_build_and_suite() {
  new_case refresh_all
  local before_deployed
  before_deployed="$(cd "$DEPLOY" && find . -type f -exec cksum {} + | sort)"
  run_script refresh
  assert_status 0
  local log="$CASE/calls.log" src="$REPO/docker"
  assert_contains "$log" "npm $src/webserver/index :: update --package-lock-only --ignore-scripts"
  assert_contains "$log" "npm $src/webserver/index :: audit --omit=dev --package-lock-only"
  assert_contains "$log" "npm $src/webserver/app_node :: update --package-lock-only --ignore-scripts"
  assert_contains "$log" "npm $src/webserver/app_node :: audit --omit=dev --package-lock-only"
  assert_contains "$log" "uv $src/webserver/app_py :: pip compile --upgrade --python-version 3.14 --universal --generate-hashes requirements.txt --output-file requirements.lock [UV_PYTHON_DOWNLOADS=never"
  assert_contains "$log" "uvx $src/webserver/app_py :: --no-python-downloads pip-audit --disable-pip --no-deps -r requirements.lock"
  assert_contains "$log" "uv $src/llm_proxy :: lock --upgrade [UV_PYTHON_DOWNLOADS=never"
  assert_contains "$log" "uv $src/llm_proxy :: export --frozen --all-extras --no-hashes --no-emit-project --format requirements-txt --output-file"
  assert_contains "$log" "uv $src/llm_proxy :: run --frozen --extra dev python -m pytest -q [UV_PYTHON_DOWNLOADS=never"
  assert_contains "$log" "docker $src/webserver :: compose -p propagate-check-webserver build index app_py app_node"
  assert_contains "$log" "docker $src/webserver :: compose -p propagate-check-webserver down --rmi local"
  assert_contains "$log" "docker $src/llm_proxy :: compose -p propagate-check-llm_proxy build"
  assert_contains "$log" "node $REPO :: --test docker/webserver/tests/nginx-routing.test.mjs"
  grep -F "compose -p propagate-check-webserver build" "$log" | grep -Fvq "WEBROOT_PATH=unset" ||
    fail "webserver check build needs a WEBROOT_PATH"
  assert_not_contains "$log" "update webserver"
  assert_contains "$REPO/docker/webserver/index/package-lock.json" "// refreshed"
  assert_contains "$REPO/docker/llm_proxy/uv.lock" "# refreshed"
  assert_contains "$CASE/out" "Review the diff"
  assert_contains "$CASE/out" "webserver/index/package-lock.json"
  [[ "$(cd "$DEPLOY" && find . -type f -exec cksum {} + | sort)" == "$before_deployed" ]] ||
    fail "refresh changed the deployed copy"
}

line_of() {
  local line
  line="$(grep -Fn -- "$2" "$1" | head -1 | cut -d: -f1)"
  [[ -n "$line" ]] || fail "expected '$2' in ${1:t}"
  print -r -- "$line"
}

# The routing test runs `docker run --pull=never`, and a check build does not
# leave its base images as named local images, so refresh must pull them first.
test_refresh_pulls_routing_test_images_before_tests() {
  new_case refresh_pull
  run_script refresh --stack webserver
  assert_status 0
  local log="$CASE/calls.log"
  local nginx_pull node_pull routing_test
  nginx_pull="$(line_of "$log" "docker $REPO :: pull nginx:stable-alpine")"
  node_pull="$(line_of "$log" "docker $REPO :: pull node:24-alpine")"
  routing_test="$(line_of "$log" "node $REPO :: --test docker/webserver/tests/nginx-routing.test.mjs")"
  (( nginx_pull < routing_test && node_pull < routing_test )) ||
    fail "test images must be pulled before the routing test runs"
}

test_refresh_pulls_overridden_test_images() {
  new_case refresh_pull_override
  NGINX_TEST_IMAGE=synthetic/nginx:fixture NGINX_TEST_NODE_IMAGE=synthetic/node:fixture \
    run_script refresh --stack webserver
  assert_status 0
  assert_contains "$CASE/calls.log" "pull synthetic/nginx:fixture"
  assert_contains "$CASE/calls.log" "pull synthetic/node:fixture"
  assert_not_contains "$CASE/calls.log" "pull node:24-alpine"
  assert_not_contains "$CASE/calls.log" "pull nginx:stable-alpine"
}

test_refresh_pull_failure_skips_tests() {
  new_case refresh_pull_fail
  FAKE_PULL_RC=1 run_script refresh --stack webserver
  assert_status 1
  assert_contains "$CASE/out" "FAILED"
  assert_contains "$CASE/out" "could not pull webserver test images"
  assert_not_contains "$CASE/calls.log" "node $REPO"
}

test_refresh_stack_filter() {
  new_case refresh_filter
  run_script refresh --stack llm_proxy
  assert_status 0
  assert_not_contains "$CASE/calls.log" "npm "
  assert_not_contains "$CASE/calls.log" "propagate-check-webserver"
  assert_contains "$CASE/calls.log" "lock --upgrade"
}

test_refresh_failure_is_reported_and_other_stacks_continue() {
  new_case refresh_fail
  FAKE_NPM_AUDIT_RC=1 run_script refresh
  assert_status 1
  assert_contains "$CASE/out" "FAILED"
  assert_contains "$CASE/out" "docker/webserver/index"
  assert_not_contains "$CASE/calls.log" "propagate-check-webserver build"
  assert_contains "$CASE/calls.log" "lock --upgrade"
}

test_refresh_cleans_up_check_images_after_build_failure() {
  new_case refresh_build_fail
  FAKE_BUILD_RC=1 run_script refresh --stack webserver
  assert_status 1
  assert_contains "$CASE/calls.log" "compose -p propagate-check-webserver down --rmi local"
  assert_not_contains "$CASE/calls.log" "node $REPO"
}

test_refresh_dry_run_changes_nothing() {
  new_case refresh_dry
  run_script refresh --dry-run
  assert_status 0
  [[ ! -s "$CASE/calls.log" ]] || fail "dry run invoked tools"
  [[ -z "$(git -C "$REPO" status --porcelain)" ]] || fail "dry run changed the repository"
  assert_contains "$CASE/out" "npm update --package-lock-only"
  assert_contains "$CASE/out" "would run (in .): docker pull node:24-alpine"
}

# --- deploy --------------------------------------------------------------

test_deploy_refuses_uncommitted_changes() {
  new_case deploy_dirty
  print -- "// local edit" >> "$REPO/docker/webserver/index/package-lock.json"
  run_script deploy
  assert_status 1
  assert_contains "$CASE/out" "uncommitted"
  assert_not_contains "$CASE/calls.log" "update "
  [[ ! -e "$HOME_DIR/.utilities-deploy-backups" ]] || fail "dirty deploy created backups"
}

test_deploy_copies_backs_up_and_updates_running_stacks() {
  new_case deploy_main
  local old_lock="$DEPLOY/webserver/index/package-lock.json"
  local old_bytes
  old_bytes="$(<"$old_lock")"
  commit_change webserver/index/package-lock.json "// new"
  commit_change llm_proxy/uv.lock "# new"
  write_file "$REPO/docker/webserver/app_node/NEW.md" "new tracked file"
  fixture_git add -A
  fixture_git commit -q -m "Add file"

  run_script deploy
  assert_status 0
  assert_same_file "$REPO/docker/webserver/index/package-lock.json" "$old_lock"
  assert_same_file "$REPO/docker/llm_proxy/uv.lock" "$DEPLOY/llm_proxy/uv.lock"
  assert_same_file "$REPO/docker/webserver/app_node/NEW.md" "$DEPLOY/webserver/app_node/NEW.md"
  assert_same_file "$REPO/docker/propagate-updates.zsh" "$DEPLOY/propagate-updates.zsh"

  local backup
  backup="$(backup_dir)"
  assert_mode "$backup" 700
  assert_mode "$backup/webserver/index/package-lock.json" 600
  [[ "$(<"$backup/webserver/index/package-lock.json")" == "$old_bytes" ]] ||
    fail "backup does not hold the replaced bytes"
  [[ ! -e "$backup/webserver/app_node/NEW.md" ]] || fail "new file was backed up"

  [[ "$(<"$DEPLOY/webserver/.env")" == "WEBROOT_PATH=/synthetic/webroot" ]] ||
    fail "local-only .env changed"
  assert_mode "$DEPLOY/webserver/.env" 600
  [[ -f "$DEPLOY/llm_proxy/output/local.json" ]] || fail "local-only output removed"

  local log="$CASE/calls.log"
  assert_contains "$log" "update webserver $DEPLOY/webserver/update.sh"
  assert_contains "$log" "update llm_collector $DEPLOY/llm_collector/llm_collector_container/update.sh"
  assert_contains "$log" "update actual-data $DEPLOY/actual-data/update.sh"
  assert_not_contains "$log" "update llm_proxy"
  assert_not_contains "$log" "update mermaid"
  assert_contains "$CASE/out" "not running"
  assert_contains "$CASE/out" "Git Fleet"
}

test_deploy_restores_modes() {
  new_case deploy_modes
  chmod 644 "$DEPLOY/webserver/update.sh"
  run_script deploy --stack webserver
  assert_status 0
  assert_mode "$DEPLOY/webserver/update.sh" 755
  assert_mode "$(backup_dir)/webserver/update.sh" 600
}

test_deploy_leaves_diverged_collector_to_migrate() {
  new_case deploy_collector
  commit_change llm_collector/collector/requirements.txt "gunicorn==0.0.1"
  run_script deploy
  assert_status 1
  assert_contains "$CASE/out" "ACTION NEEDED"
  assert_contains "$CASE/out" "llm_collector/migrate.sh"
  assert_not_contains "$DEPLOY/llm_collector/collector/requirements.txt" "gunicorn"
  assert_not_contains "$CASE/calls.log" "update llm_collector"
  assert_contains "$CASE/calls.log" "update webserver"
}

test_deploy_update_failure_is_reported() {
  new_case deploy_update_fail
  commit_change webserver/index/package-lock.json "// new"
  FAKE_FAIL_UPDATE=webserver run_script deploy
  assert_status 1
  assert_contains "$CASE/out" "FAILED"
  assert_contains "$CASE/out" "exited 7"
  assert_contains "$CASE/out" ".utilities-deploy-backups/docker-"
  assert_contains "$CASE/calls.log" "update actual-data"
}

test_deploy_detects_stack_not_running_afterwards() {
  new_case deploy_dropped
  FAKE_DROP_STACK=webserver run_script deploy --stack webserver
  assert_status 1
  assert_contains "$CASE/out" "not running after update"
}

test_deploy_skips_stack_running_from_elsewhere() {
  new_case deploy_elsewhere
  cat > "$STATE/compose.json" <<EOF
[{"Name":"webserver","Status":"running(4)","ConfigFiles":"$REPO/docker/webserver/docker-compose.yml"}]
EOF
  run_script deploy --stack webserver
  assert_status 1
  assert_contains "$CASE/out" "ACTION NEEDED"
  assert_contains "$CASE/out" "$REPO/docker/webserver/docker-compose.yml"
  assert_not_contains "$CASE/calls.log" "update webserver"
}

test_deploy_dry_run_changes_nothing() {
  new_case deploy_dry
  commit_change webserver/index/package-lock.json "// new"
  local before
  before="$(cd "$DEPLOY" && find . -type f -exec cksum {} + | sort)"
  run_script deploy --dry-run
  assert_status 0
  [[ "$(cd "$DEPLOY" && find . -type f -exec cksum {} + | sort)" == "$before" ]] ||
    fail "dry run changed the deployed copy"
  [[ ! -e "$HOME_DIR/.utilities-deploy-backups" ]] || fail "dry run created backups"
  assert_not_contains "$CASE/calls.log" "update "
  assert_contains "$CASE/out" "webserver/index/package-lock.json"
  assert_contains "$CASE/out" "would run"
}

test_deploy_refuses_symlinked_destination() {
  new_case deploy_symlink
  commit_change webserver/index/package-lock.json "// new"
  rm "$DEPLOY/webserver/index/package-lock.json"
  ln -s "$CASE/elsewhere" "$DEPLOY/webserver/index/package-lock.json"
  run_script deploy --stack webserver
  assert_status 1
  assert_contains "$CASE/out" "symlink"
  [[ ! -e "$CASE/elsewhere" ]] || fail "deploy wrote through a symlink"
  assert_not_contains "$CASE/calls.log" "update webserver"
}

test_deploy_rejects_unknown_project() {
  new_case deploy_unknown
  write_file "$REPO/docker/mystery/run.sh" "#!/bin/zsh"
  fixture_git add -A
  fixture_git commit -q -m "Add unknown project"
  run_script deploy
  assert_status 1
  assert_contains "$CASE/out" "unknown docker project: mystery"
  [[ ! -e "$DEPLOY/mystery" ]] || fail "unknown project was deployed"
}

test_deploy_reports_running_stack_without_updater() {
  new_case deploy_n8n
  cat > "$STATE/compose.json" <<EOF
[{"Name":"n8n-poc","Status":"running(1)","ConfigFiles":"$DEPLOY/n8n-poc/docker-compose.yml"}]
EOF
  run_script deploy --stack n8n-poc
  assert_status 1
  assert_contains "$CASE/out" "no update.sh"
}

tests=(${(ok)functions[(I)test_*]})
for test_name in "${tests[@]}"; do
  "$test_name"
  print -- "ok - $test_name"
done
print -- "All ${#tests} propagate-updates tests passed."
