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
    rm -r -- "${SUITE_ROOT:?}"
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
  chmod 644 "$1"
}

write_updater() {
  local stack="$1" target="$REPO/docker/$2"
  mkdir -p "${target:h}"
  cat > "$target" <<EOF
#!/bin/zsh
print -r -- "update $stack \${PROPAGATE_STACK_ROOT:-\${0:A:h}}/\${0:t}" >> "\$CALL_LOG"
[[ "\${FAKE_FAIL_UPDATE:-}" == "$stack" ]] && exit 7
if [[ "\${FAKE_DROP_STACK:-}" == "$stack" ]]; then
  jq '[.[] | select(.Name != "${STACK_PROJECT[$stack]:-none}")]' "\$STATE_DIR/compose.json" > "\$STATE_DIR/compose.next"
  mv "\$STATE_DIR/compose.next" "\$STATE_DIR/compose.json"
fi
if [[ "\${FAKE_BUNDLE_CONFIG:-}" == "$stack" ]]; then
  jq --arg path "\${0:A:h}/docker-compose.yml" 'map(if .Name == "${STACK_PROJECT[$stack]:-none}" then .ConfigFiles = \$path else . end)' "\$STATE_DIR/compose.json" > "\$STATE_DIR/compose.next"
  mv "\$STATE_DIR/compose.next" "\$STATE_DIR/compose.json"
fi
if [[ "\${FAKE_CLEAR_REFERENCES:-}" == "$stack" ]]; then
  print '[]' > "\$STATE_DIR/all-compose.json"
  : > "\$STATE_DIR/all-ids.txt"
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
if [[ "$*" == "compose ls --all --format json" ]]; then [[ "${FAKE_REFERENCE_FAILURE:-0}" == 0 ]] || exit 1; cat "$STATE_DIR/all-compose.json"; exit 0; fi
if [[ "$*" == "compose ls --format json" ]]; then cat "$STATE_DIR/compose.json"; exit 0; fi
if [[ "$*" == "ps -aq" ]]; then [[ "${FAKE_REFERENCE_FAILURE:-0}" == 0 ]] || exit 1; cat "$STATE_DIR/all-ids.txt"; exit 0; fi
if [[ "$1" == inspect && $# -ge 2 ]]; then [[ "${FAKE_REFERENCE_FAILURE:-0}" == 0 ]] || exit 1; cat "$STATE_DIR/inspect.json"; exit 0; fi
if [[ "$*" == "compose config --format json" ]]; then print -r -- "{\"services\":{\"n8n\":{\"environment\":{\"N8N_ENCRYPTION_KEY\":\"synthetic-key\"}}}}"; exit 0; fi
if [[ "$*" == "compose config --quiet" || "$*" == "compose pull" || "$*" == "compose up -d --wait --wait-timeout 180" || "$*" == "compose ps" ]]; then exit 0; fi
if [[ "$1" == ps && "$2" == --format && "$3" == "{{.Names}}" && $# == 3 ]]; then [[ "${FAKE_PS_RC:-0}" == 0 ]] || exit "$FAKE_PS_RC"; cat "$STATE_DIR/containers.txt"; exit 0; fi
if [[ "$1" == pull && $# == 2 ]]; then exit "${FAKE_PULL_RC:-0}"; fi
if [[ "$*" == "compose -p propagate-check-webserver build index app_py app_node" || "$*" == "compose -p propagate-check-llm_proxy build" ]]; then exit "${FAKE_BUILD_RC:-0}"; fi
if [[ "$*" == "compose -p propagate-check-webserver down --rmi local" || "$*" == "compose -p propagate-check-llm_proxy down --rmi local" ]]; then exit 0; fi
print -ru2 -- "stub docker: unexpected call: $*"; exit 97'
  write_stub npm '
if [[ "$1" == update ]]; then print -- "// refreshed" >> package-lock.json; fi
if [[ "$1" == ci ]]; then exit "${FAKE_NPM_CI_RC:-0}"; fi
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
  print '[]' > "$STATE/all-compose.json"
  : > "$STATE/all-ids.txt"
  print '[]' > "$STATE/inspect.json"
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
  write_updater n8n-poc n8n-poc/update.sh

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
  run_script refresh --keep-source-bundles
  assert_status 2
  assert_contains "$CASE/out" 'only valid for deploy'
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
  line="$(grep -Fn -- "$2" "$1" | head -1 | cut -d: -f1 || true)"
  [[ -n "$line" ]] || fail "expected '$2' in ${1:t}"
  print -r -- "$line"
}

test_refresh_installs_refreshed_index_dependencies_before_webserver_tests() {
  new_case refresh_index_dependencies
  run_script refresh --stack webserver
  assert_status 0
  local log="$CASE/calls.log" src="$REPO/docker" update install tests
  update="$(line_of "$log" "npm $src/webserver/index :: update --package-lock-only")"
  install="$(line_of "$log" "npm $src/webserver/index :: ci --ignore-scripts --no-audit --no-fund")"
  tests="$(line_of "$log" "node $REPO :: --test docker/webserver/tests/nginx-routing.test.mjs docker/webserver/tests/index-server.test.mjs")"
  (( update < install && install < tests )) || fail 'refreshed dependencies must be installed before webserver tests'
}

test_refresh_npm_ci_failure_skips_webserver_tests() {
  new_case refresh_index_install_fail
  FAKE_NPM_CI_RC=1 run_script refresh --stack webserver
  assert_status 1
  assert_contains "$CASE/out" 'webserver tests failed'
  assert_contains "$CASE/out" 'FAILED'
  assert_not_contains "$CASE/calls.log" "node $REPO :: --test"
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

test_deploy_rejects_invalid_compose_runtime_records() {
  new_case deploy_invalid_compose_records
  commit_change webserver/index/package-lock.json '// committed change'
  local original invalid
  original="$(<"$DEPLOY/webserver/index/package-lock.json")"
  for invalid in '{}' '[null]' '[{}]' \
    '[{"Status":"running(1)","ConfigFiles":"/synthetic/compose.yml"}]' \
    '[{"Name":"webserver","ConfigFiles":"/synthetic/compose.yml"}]' \
    '[{"Name":"webserver","Status":"running(1)"}]' \
    '[{"Name":null,"Status":"running(1)","ConfigFiles":"/synthetic/compose.yml"}]' \
    '[{"Name":3,"Status":"running(1)","ConfigFiles":"/synthetic/compose.yml"}]' \
    '[{"Name":"webserver","Status":null,"ConfigFiles":"/synthetic/compose.yml"}]' \
    '[{"Name":"webserver","Status":3,"ConfigFiles":"/synthetic/compose.yml"}]' \
    '[{"Name":"webserver","Status":"running(1)","ConfigFiles":null}]' \
    '[{"Name":"webserver","Status":"running(1)","ConfigFiles":3}]' \
    '[{"Name":"","Status":"running(1)","ConfigFiles":"/synthetic/compose.yml"}]' \
    '[{"Name":"webserver","Status":"","ConfigFiles":"/synthetic/compose.yml"}]' \
    '[{"Name":"webserver","Status":"running(1)","ConfigFiles":""}]' \
    '[{"Name":" ","Status":"running(1)","ConfigFiles":"/synthetic/compose.yml"}]' \
    '[{"Name":"webserver","Status":"unknown","ConfigFiles":"/synthetic/compose.yml"}]' \
    '[{"Name":"webserver","Status":"running(1)","ConfigFiles":" "}]'; do
    print -r -- "$invalid" > "$STATE/compose.json"
    : > "$CASE/calls.log"
    run_script deploy --stack webserver
    assert_status 1
    assert_contains "$CASE/out" 'could not parse docker compose ls output'
    assert_not_contains "$CASE/calls.log" 'update '
    [[ "$(<"$DEPLOY/webserver/index/package-lock.json")" == "$original" ]] || fail 'invalid state copied files'
    [[ ! -e "$HOME_DIR/.utilities-deploy-backups" ]] || fail 'invalid state created backups'
  done
}

test_deploy_accepts_valid_stopped_compose_record() {
  new_case deploy_stopped_record
  print -r -- "[{\"Name\":\"webserver\",\"Status\":\"exited(1)\",\"ConfigFiles\":\"$DEPLOY/webserver/docker-compose.yml\"}]" > "$STATE/compose.json"
  run_script deploy --stack webserver
  assert_status 0
  assert_contains "$CASE/out" 'not running, left stopped'
  assert_not_contains "$CASE/calls.log" 'update webserver'
  print -r -- "[{\"Name\":\"webserver\",\"Status\":\"running(1), exited(1)\",\"ConfigFiles\":\"$DEPLOY/webserver/docker-compose.yml\"}]" > "$STATE/compose.json"
  run_script deploy --stack webserver
  assert_status 0
  assert_contains "$CASE/calls.log" 'update webserver'
}

test_deploy_refuses_unknown_runtime_state() {
  new_case deploy_ps_failure
  FAKE_PS_RC=1 run_script deploy
  assert_status 1
  assert_contains "$CASE/out" 'docker ps failed'
  assert_not_contains "$CASE/calls.log" 'update '
  [[ ! -e "$HOME_DIR/.utilities-deploy-backups" ]] || fail 'runtime failure created backups'
  : > "$CASE/calls.log"
  print -r -- 'not json' > "$STATE/compose.json"
  run_script deploy
  assert_status 1
  assert_contains "$CASE/out" 'could not parse docker compose ls output'
  assert_not_contains "$CASE/calls.log" 'update '
}

test_deploy_does_not_reuse_tampered_bundle() {
  new_case deploy_tampered_bundle
  run_script deploy --stack webserver
  assert_status 0
  local commit bundle
  commit="$(fixture_git rev-parse HEAD)"
  local bundles=("$HOME_DIR"/.utilities-deploy-bundles/docker-$commit-*(N/))
  (( ${#bundles} == 1 )) || fail 'expected one bundle'
  bundle="$bundles[1]"
  print 'changed' >> "$bundle/docker/webserver/update.sh"
  : > "$CASE/calls.log"
  run_script deploy --stack webserver
  assert_status 0
  assert_contains "$CASE/calls.log" 'update webserver'
  bundles=("$HOME_DIR"/.utilities-deploy-bundles/docker-$commit-*(N/))
  (( ${#bundles} == 2 )) || fail 'expected a fresh bundle'
}

test_deploy_recognizes_running_bundle_on_next_run() {
  new_case deploy_running_bundle
  FAKE_BUNDLE_CONFIG=webserver run_script deploy --stack webserver
  assert_status 0
  assert_contains "$STATE/compose.json" '.utilities-deploy-bundles/'
  : > "$CASE/calls.log"
  FAKE_BUNDLE_CONFIG=webserver run_script deploy --stack webserver
  assert_status 0
  assert_contains "$CASE/calls.log" 'update webserver'
}

test_deploy_rejects_unmarked_bundle_runtime() {
  new_case deploy_unmarked_bundle
  local fake="$HOME_DIR/.utilities-deploy-bundles/fake/docker/webserver"
  mkdir -p "$fake"
  print -r -- "[{\"Name\":\"webserver\",\"Status\":\"running(1)\",\"ConfigFiles\":\"$fake/docker-compose.yml\"}]" > "$STATE/compose.json"
  run_script deploy --stack webserver
  assert_status 1
  assert_contains "$CASE/out" 'ACTION NEEDED'
  assert_not_contains "$CASE/calls.log" 'update webserver'
}

test_bundle_retention_preserves_all_references() {
  new_case bundle_retention
  local commit root name i day
  commit="$(fixture_git rev-parse HEAD)"
  root="$HOME_DIR/.utilities-deploy-bundles"
  for i in {1..10}; do
    name="$root/docker-$commit-00000$i"
    mkdir -p "$name"
    (umask 022; fixture_git archive "$commit" docker | tar -xf - -C "$name")
    print "$commit" > "$name/.ready"
    print "$commit" > "$name/.complete"
    day="$(printf '%02d' "$i")"
    touch -t "202001${day}0101" "$name"
  done
  print unexpected > "$root/docker-$commit-000004/unknown-user-file"
  touch -t 202001040101 "$root/docker-$commit-000004"
  print 'aaaaaaaaaaaa' > "$STATE/all-ids.txt"
  print -r -- "[{\"Mounts\":[{\"Source\":\"$root/docker-$commit-000001/docker/webserver/app_py\"}],\"Config\":{\"Labels\":{\"com.docker.compose.project.config_files\":\"$root/docker-$commit-000003/docker/webserver/docker-compose.yml\"}}}]" > "$STATE/inspect.json"
  print -r -- "[{\"ConfigFiles\":\"$root/docker-$commit-000002/docker/webserver/docker-compose.yml\"}]" > "$STATE/all-compose.json"
  FAKE_CLEAR_REFERENCES=webserver run_script deploy --stack webserver
  assert_status 0
  [[ -d "$root/docker-$commit-000001" && -d "$root/docker-$commit-000002" && -d "$root/docker-$commit-000003" ]] || fail 'initial recovery reference removed'
  [[ -f "$root/docker-$commit-000004/unknown-user-file" ]] || fail 'removed unverified bundle'
  [[ ! -e "$root/docker-$commit-000005" ]] || fail 'oldest verified unused bundle retained'
  [[ -d "$root/docker-$commit-000006" && -d "$root/docker-$commit-000007" && -d "$root/docker-$commit-000008" && -d "$root/docker-$commit-000009" && -d "$root/docker-$commit-0000010" ]] || fail 'newer bundles removed'
}

test_bundle_retention_preserves_ancestor_mounts() {
  local mode commit root i name source
  for mode in parent root control; do
    new_case "bundle_ancestor_$mode"
    commit="$(fixture_git rev-parse HEAD)"
    root="$HOME_DIR/.utilities-deploy-bundles"
    for i in {1..7}; do
      name="$root/docker-$commit-00000$i"
      mkdir -p "$name"
      (umask 022; fixture_git archive "$commit" docker | tar -xf - -C "$name")
      print "$commit" > "$name/.ready"
      print "$commit" > "$name/.complete"
      touch -t "2020010${i}0101" "$name"
    done
    if [[ "$mode" != control ]]; then
      source="$root"; [[ "$mode" == root ]] && source=/
      print 'aaaaaaaaaaaa' > "$STATE/all-ids.txt"
      print -r -- "[{\"Mounts\":[{\"Source\":\"$source\"}],\"Config\":{\"Labels\":{}}}]" > "$STATE/inspect.json"
    fi
    run_script deploy --stack webserver
    assert_status 0
    if [[ "$mode" == control ]]; then
      [[ ! -e "$root/docker-$commit-000001" && ! -e "$root/docker-$commit-000002" ]] || fail 'control did not prune eligible bundles'
    else
      for i in {1..7}; do [[ -d "$root/docker-$commit-00000$i" ]] || fail "$mode mount lost a bundle"; done
    fi
  done
}

test_bundle_retention_skips_failed_inspection() {
  new_case bundle_reference_failure
  local commit root i
  commit="$(fixture_git rev-parse HEAD)"
  root="$HOME_DIR/.utilities-deploy-bundles"
  for i in {1..7}; do
    mkdir -p "$root/docker-$commit-00000$i"
    (umask 022; fixture_git archive "$commit" docker | tar -xf - -C "$root/docker-$commit-00000$i")
    print "$commit" > "$root/docker-$commit-00000$i/.ready"
    print "$commit" > "$root/docker-$commit-00000$i/.complete"
    touch -t "2020010${i}0101" "$root/docker-$commit-00000$i"
  done
  FAKE_REFERENCE_FAILURE=1 run_script deploy --stack webserver
  assert_status 0
  assert_contains "$CASE/out" 'cannot inspect bundle references'
  [[ -d "$root/docker-$commit-000001" ]] || fail 'pruned after inspection failure'
  print 'aaaaaaaaaaaa' > "$STATE/all-ids.txt"
  print '[{"Mounts":"invalid","Config":{"Labels":{}}}]' > "$STATE/inspect.json"
  run_script deploy --stack webserver
  assert_status 0
  assert_contains "$CASE/out" 'cannot inspect bundle references'
  [[ -d "$root/docker-$commit-000001" ]] || fail 'pruned after malformed inspection'
  : > "$STATE/all-ids.txt"
  print '[]' > "$STATE/inspect.json"
  run_script deploy --stack webserver
  assert_status 0
  [[ ! -e "$root/docker-$commit-000001" ]] || fail 'inspection control did not prune eligible bundle'
}

test_bundle_retention_keeps_unknown_and_in_progress() {
  new_case bundle_unknown
  local commit root i
  commit="$(fixture_git rev-parse HEAD)"
  root="$HOME_DIR/.utilities-deploy-bundles"
  for i in {1..7}; do
    mkdir -p "$root/docker-$commit-00000$i"
    (umask 022; fixture_git archive "$commit" docker | tar -xf - -C "$root/docker-$commit-00000$i")
    print "$commit" > "$root/docker-$commit-00000$i/.ready"
    print "$commit" > "$root/docker-$commit-00000$i/.complete"
    touch -t "2020010${i}0101" "$root/docker-$commit-00000$i"
  done
  print "$commit" > "$root/docker-$commit-000001/.in-progress"
  mkdir "$root/unrecognized"
  run_script deploy --stack webserver
  assert_status 0
  [[ -d "$root/docker-$commit-000001" && -d "$root/unrecognized" ]] || fail 'removed in-progress or unknown bundle'
  [[ ! -e "$root/docker-$commit-000002" ]] || fail 'in-progress control did not prune eligible bundle'
}

test_deploy_keeps_source_bundles_when_requested() {
  new_case bundle_keep_optout
  local commit root i
  commit="$(fixture_git rev-parse HEAD)"
  root="$HOME_DIR/.utilities-deploy-bundles"
  for i in {1..7}; do
    mkdir -p "$root/docker-$commit-00000$i"
    (umask 022; fixture_git archive "$commit" docker | tar -xf - -C "$root/docker-$commit-00000$i")
    print "$commit" > "$root/docker-$commit-00000$i/.ready"
    print "$commit" > "$root/docker-$commit-00000$i/.complete"
    touch -t "2020010${i}0101" "$root/docker-$commit-00000$i"
  done
  run_script deploy --stack webserver --keep-source-bundles
  assert_status 0
  for i in {1..7}; do [[ -d "$root/docker-$commit-00000$i" ]] || fail 'opt-out pruned a bundle'; done
  run_script deploy --stack webserver
  assert_status 0
  [[ ! -e "$root/docker-$commit-000001" ]] || fail 'opt-out control did not prune eligible bundle'
}

test_deploy_never_executes_modified_deployed_updater() {
  new_case deploy_tampered_updater
  cat > "$REPO/docker/actual-data/update.sh" <<'EOF'
#!/bin/zsh
print -r -- 'update actual-data' >> "$CALL_LOG"
print -l -r -- '#!/bin/zsh' 'print tampered >> "$CALL_LOG"' > "$HOME/docker/webserver/update.sh"
chmod 755 "$HOME/docker/webserver/update.sh"
EOF
  chmod 755 "$REPO/docker/actual-data/update.sh"
  fixture_git commit -q -am 'Add synthetic updater mutation'
  run_script deploy --stack actual-data --stack webserver
  assert_status 0
  ! grep -Fxq 'tampered' "$CASE/calls.log" || fail 'deployed updater was executed'
  assert_contains "$CASE/calls.log" 'update webserver'
}

test_deploy_uses_committed_helper_and_build_inputs() {
  new_case deploy_tampered_inputs
  write_file "$REPO/docker/webserver/helper.sh" 'print trusted-helper >> "$CALL_LOG"'
  write_file "$REPO/docker/webserver/Dockerfile" 'trusted-build-input'
  write_file "$REPO/docker/webserver/docker-compose.yml" 'trusted-compose'
  cat > "$REPO/docker/actual-data/update.sh" <<'EOF'
#!/bin/zsh
print 'print untrusted-helper >> "$CALL_LOG"' > "$HOME/docker/webserver/helper.sh"
print untrusted-build-input > "$HOME/docker/webserver/Dockerfile"
print untrusted-compose > "$HOME/docker/webserver/docker-compose.yml"
EOF
  cat > "$REPO/docker/webserver/update.sh" <<'EOF'
#!/bin/zsh
here="${0:A:h}"
. "$here/helper.sh"
cat "$here/Dockerfile" "$here/docker-compose.yml" >> "$CALL_LOG"
EOF
  chmod 755 "$REPO/docker/actual-data/update.sh" "$REPO/docker/webserver/update.sh"
  fixture_git add docker/webserver/helper.sh docker/webserver/Dockerfile
  fixture_git commit -q -am 'Add synthetic trusted input fixture'
  run_script deploy --stack actual-data --stack webserver
  assert_status 0
  assert_contains "$CASE/calls.log" 'trusted-helper'
  assert_contains "$CASE/calls.log" 'trusted-build-input'
  assert_contains "$CASE/calls.log" 'trusted-compose'
  ! grep -Eq '^untrusted-' "$CASE/calls.log" || fail 'used a mutable deployed input'
}

test_deploy_refuses_non_main_and_detached_head() {
  new_case deploy_branch
  fixture_git checkout -qb feature
  run_script deploy
  assert_status 1
  assert_contains "$CASE/out" 'main branch'
  [[ ! -s "$CASE/calls.log" ]] || fail 'non-main deploy invoked tools'
  fixture_git checkout -q --detach
  run_script deploy
  assert_status 1
  assert_contains "$CASE/out" 'main branch'
}

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
  local bundles=("$HOME_DIR"/.utilities-deploy-bundles/docker-*(N/))
  (( ${#bundles} == 1 )) || fail 'expected one failed bundle'
  [[ -f "$bundles[1]/.in-progress" && ! -e "$bundles[1]/.complete" ]] || fail 'failed bundle was marked complete'
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
  local target="$DEPLOY/webserver/index/package-lock.json"
  rm -- "${target:?}"
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
  sed -i '' '/^  n8n-poc n8n-poc\/update.sh$/d' "$REPO/docker/propagate-updates.zsh"
  fixture_git commit -q -am 'Remove updater mapping'
  cat > "$STATE/compose.json" <<EOF
[{"Name":"n8n-poc","Status":"running(1)","ConfigFiles":"$DEPLOY/n8n-poc/docker-compose.yml"}]
EOF
  run_script deploy --stack n8n-poc
  assert_status 1
  assert_contains "$CASE/out" "no update.sh"
}

test_deploy_updates_running_n8n() {
  new_case deploy_n8n_running
  print -r -- "[{\"Name\":\"n8n-poc\",\"Status\":\"running(1)\",\"ConfigFiles\":\"$DEPLOY/n8n-poc/docker-compose.yml\"}]" > "$STATE/compose.json"
  run_script deploy --stack n8n-poc
  assert_status 0
  assert_contains "$CASE/calls.log" "update n8n-poc $DEPLOY/n8n-poc/update.sh"
}

test_real_n8n_updater_stops_when_up_fails() {
  new_case n8n_real
  local dir="$CASE/n8n"
  mkdir "$dir"
  cp "$TEST_SCRIPT_DIR:h/n8n-poc/"{up.sh,update.sh} "$dir/"
  : > "$dir/.env"
  (cd "$dir" && PATH="$CASE/bin:$PATH" CALL_LOG="$CASE/calls.log" STATE_DIR="$STATE" ./update.sh) > "$CASE/out" 2>&1 || fail "updater failed with config"
  assert_contains "$CASE/calls.log" "compose ps"
  : > "$CASE/calls.log"
  local env_file="$dir/.env"
  rm -- "${env_file:?}"
  local rc=0
  (cd "$dir" && PATH="$CASE/bin:$PATH" CALL_LOG="$CASE/calls.log" STATE_DIR="$STATE" ./update.sh) > "$CASE/out" 2>&1 || rc=$?
  [[ "$rc" == 2 ]] || fail "missing config returned $rc"
  assert_contains "$CASE/out" "Missing private config"
  assert_not_contains "$CASE/calls.log" "compose ps"
}

test_deploy_keeps_two_newest_backups() {
  new_case deploy_retention
  local root="$HOME_DIR/.utilities-deploy-backups" name
  for name in docker-20200101-010101 docker-20200102-010101 docker-20200103-010101 docker-20200103-010101-123 docker-20200104-010101-extra unrelated; do
    write_file "$root/$name/marker" "$name"
    touch -t 202001010101 "$root/$name"
  done
  mkdir "$root/docker-20200101-010101/readonly"
  chmod 500 "$root/docker-20200101-010101/readonly"
  ln -s "$CASE" "$root/docker-20200105-010101"
  commit_change webserver/index/package-lock.json '// changed'
  FAKE_FAIL_UPDATE=webserver run_script deploy --stack webserver
  assert_status 1
  [[ -f "$root/docker-20200101-010101/marker" ]] || fail 'failed deploy pruned backups'
  for name in "$root"/docker-20*(N/); do touch -t 201901010101 "$name"; done
  touch -t 202001010101 "$root"/docker-202001*(N/)
  run_script deploy --stack webserver --dry-run
  assert_status 0
  [[ -f "$root/docker-20200101-010101/marker" ]] || fail 'dry run pruned backups'
  commit_change webserver/index/package-lock.json '// changed again'
  run_script deploy --stack webserver
  assert_status 0
  [[ ! -e "$root/docker-20200101-010101" && ! -e "$root/docker-20200102-010101" && ! -e "$root/docker-20200103-010101" ]] || fail 'old backups survived'
  [[ -f "$root/docker-20200103-010101-123/marker" && -f "$root/docker-20200104-010101-extra/marker" && -f "$root/unrelated/marker" && -L "$root/docker-20200105-010101" ]] || fail 'protected entries removed'
}

test_prune_refuses_linked_root() {
  new_case linked_backup_root
  local root="$HOME_DIR/.utilities-deploy-backups" target="$CASE/backups" name
  mkdir "$target"
  ln -s "$target" "$root"
  for name in docker-20200101-010101 docker-20200102-010101 docker-20200103-010101; do
    write_file "$target/$name/marker" safe
  done
  commit_change webserver/index/package-lock.json '// changed'
  run_script deploy --stack webserver
  assert_status 0
  assert_contains "$CASE/out" 'cannot prune backups through linked path'
  [[ -f "$target/docker-20200101-010101/marker" ]] || fail 'linked root contents changed'
}

test_prune_orders_fractional_mtimes_before_names() {
  new_case fractional_backup_times
  local root="$HOME_DIR/.utilities-deploy-backups"
  write_file "$root/docker-20200101-010101/marker" newer
  write_file "$root/docker-20200102-010101/marker" older
  perl -MTime::HiRes=utime -e 'utime 1577836800.9, 1577836800.9, $ARGV[0] or die $!; utime 1577836800.1, 1577836800.1, $ARGV[1] or die $!' \
    "$root/docker-20200101-010101" "$root/docker-20200102-010101"
  commit_change webserver/index/package-lock.json '// changed'
  run_script deploy --stack webserver
  assert_status 0
  [[ -f "$root/docker-20200101-010101/marker" && ! -e "$root/docker-20200102-010101" ]] ||
    fail 'fractional modification times did not take precedence over names'
}

test_staged_publication_failures_preserve_destination() {
  local failure
  for failure in copy move; do
    new_case "staged_${failure}_failure"
    commit_change webserver/index/package-lock.json '// changed'
    cp -p "$DEPLOY/webserver/index/package-lock.json" "$CASE/original"
    if [[ "$failure" == copy ]]; then
      write_stub cp 'if [[ "${@: -1}" == *.propagate-* ]]; then exit 41; fi; exec /bin/cp "$@"'
    else
      write_stub mv 'if [[ "$1" == -f && "$2" == *.propagate-* ]]; then exit 42; fi; exec /bin/mv "$@"'
    fi
    run_script deploy --stack webserver
    assert_status 1
    assert_contains "$CASE/out" 'copy failed for'
    assert_same_file "$CASE/original" "$DEPLOY/webserver/index/package-lock.json"
    [[ -z "$(find "$DEPLOY" -name '*.propagate-*' -print)" ]] || fail 'staged file remains'
  done
}

test_prune_refuses_unwritable_root() {
  new_case unwritable_backup_root
  local root="$HOME_DIR/.utilities-deploy-backups" name
  for name in docker-20200101-010101 docker-20200102-010101 docker-20200103-010101; do
    write_file "$root/$name/marker" safe
  done
  commit_change webserver/index/package-lock.json '// changed'
  # The updater runs after backup creation; simulate permissions changing then.
  sed -i '' '/^exit 0/i\
chmod 500 "$HOME/.utilities-deploy-backups"\
' "$DEPLOY/webserver/update.sh"
  # Keep the deployed updater in sync with the fixture's source so it is run.
  cp -p "$DEPLOY/webserver/update.sh" "$REPO/docker/webserver/update.sh"
  fixture_git commit -q -am 'Change updater permissions fixture'
  run_script deploy --stack webserver
  chmod 700 "$root"
  assert_status 0
  assert_contains "$CASE/out" 'not writable and searchable'
  [[ -f "$root/docker-20200101-010101/marker" ]] || fail 'unwritable root contents changed'
}

test_prune_warns_and_preserves_contents_on_removal_error() {
  new_case prune_failure
  local root="$HOME_DIR/.utilities-deploy-backups" name
  for name in docker-20200101-010101 docker-20200102-010101 docker-20200103-010101; do
    write_file "$root/$name/marker" safe
    touch -t 202001010101 "$root/$name"
  done
  write_stub rm 'exit 1'
  commit_change webserver/index/package-lock.json '// changed'
  run_script deploy --stack webserver
  assert_status 0
  assert_contains "$CASE/out" 'cannot remove backup'
  [[ -f "$root/docker-20200101-010101/marker" ]] || fail 'failed removal lost contents'
}

tests=(${(ok)functions[(I)test_*]})
for test_name in "${tests[@]}"; do
  "$test_name"
  print -- "ok - $test_name"
done
print -- "All ${#tests} propagate-updates tests passed."
