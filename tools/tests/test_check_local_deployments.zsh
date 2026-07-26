#!/bin/zsh

set -euo pipefail

readonly TEST_SCRIPT_DIR="${0:A:h}"
readonly REPO_UNDER_TEST="${TEST_SCRIPT_DIR:h:h}"
readonly AUDIT_SOURCE="$REPO_UNDER_TEST/tools/check_local_deployments.zsh"

umask 077
suite_parent="${TMPDIR:-/tmp}"
suite_root="$(mktemp -d "$suite_parent/check-local-deployments-tests.XXXXXX")"
readonly SUITE_ROOT="${suite_root:A}"

cleanup_suite() {
  local saved_status=$?
  if [[ -n "${SUITE_ROOT:-}" &&
        "$SUITE_ROOT" == "${suite_parent:A}"/check-local-deployments-tests.* &&
        -d "$SUITE_ROOT" &&
        ! -L "$SUITE_ROOT" ]]; then
    rm -rf -- "$SUITE_ROOT"
  fi
  return "$saved_status"
}
trap cleanup_suite EXIT

fail() {
  print -u2 -- "FAIL: $*"
  exit 1
}

assert_contains() {
  local file="$1"
  local expected="$2"
  local label="${3:-$expected}"
  grep -Fq -- "$expected" "$file" ||
    fail "$label: expected text not found: $expected"
}

assert_not_contains() {
  local file="$1"
  local unexpected="$2"
  local label="${3:-$unexpected}"
  if grep -Fq -- "$unexpected" "$file"; then
    fail "$label: unexpected text found: $unexpected"
  fi
}

assert_occurrences() {
  local file="$1"
  local expected="$2"
  local text="$3"
  local actual
  actual="$(grep -Fc -- "$text" "$file" || true)"
  [[ "$actual" == "$expected" ]] ||
    fail "expected $expected occurrence(s) of '$text', found $actual"
}

assert_status() {
  local expected="$1"
  local actual="$2"
  local label="${3:-command}"
  if [[ "$actual" != "$expected" ]]; then
    if [[ -f "${AUDIT_STDOUT:-}" ]]; then
      print -u2 -- "--- audit stdout ---"
      sed -n '1,200p' "$AUDIT_STDOUT" >&2
    fi
    if [[ -f "${AUDIT_STDERR:-}" ]]; then
      print -u2 -- "--- audit stderr ---"
      sed -n '1,200p' "$AUDIT_STDERR" >&2
    fi
    fail "$label: expected status $expected, found $actual"
  fi
}

assert_mode() {
  local expected="$1"
  local object_path="$2"
  local actual
  actual="$(stat -f '%Mp%Lp' "$object_path")" ||
    fail "could not read mode for $object_path"
  [[ "$actual" == "$expected" ]] ||
    fail "$object_path: expected mode $expected, found $actual"
}

fixture_counter=0
FIXTURE_ROOT=
FIXTURE_REPO=
FIXTURE_HOME=
FIXTURE_SCRIPTS=
FIXTURE_LOCAL=
FIXTURE_TMP=
FIXTURE_ZDOTDIR=
AUDIT_STDOUT=
AUDIT_STDERR=
AUDIT_STATUS=

typeset -a COPY_MAPPINGS=(
  'abacus usage/de-abacus.py|de-abacus.py'
  'div_conv/div_conv|div_conv'
  'dloc/dloc|dloc'
  'docker/docker-disk-compact/docker-disk-compact.zsh|docker-disk-compact.zsh'
  'editdb/editdb|editdb'
  'etf_montecarlo/etf_montecarlo|etf_montecarlo'
  'expense_dock/expense_dock|expense_dock'
  'harscope/harscope|harscope'
  'jtree/jtree|jtree'
  'launchmaster/launchmaster|launchmaster'
  'media-dater/media-dater|media-dater'
  'moneydance backup rotation/moneydance_rotate_backups.sh|moneydance_rotate_backups.sh'
  'router-log-analyzer/router_log_analyze.py|router_log_analyze.py'
  'routerview/routerview|routerview'
  'storage_monitor/storage_monitor|storage_monitor'
  'trim_last/trim_last|trim_last'
  'usage-monthly-csv/usage-monthly-csv|usage-monthly-csv'
  'worktree-helper/worktree|worktree'
)

typeset -a HOME_PROJECTS=(
  apple-health-extract
  docker
  mem_snapshots
  mls-tracker
  tax2
  transcription
  vid-compiler
  video-scenes
)

write_synthetic_file() {
  local file_path="$1"
  local label="$2"
  mkdir -p -- "${file_path:h}"
  print -r -- "synthetic fixture: $label" > "$file_path"
}

build_model_zipapp() {
  local staging="$FIXTURE_ROOT/model-staging"
  local archive="$FIXTURE_ROOT/model.zip"
  local target="$FIXTURE_SCRIPTS/model-sentinel"

  rm -rf -- "$staging"
  mkdir -p -- "$staging/model_sentinel"
  cp -p -- "$FIXTURE_REPO/model_sentinel/__main__.py" "$staging/__main__.py"
  cp -p -- "$FIXTURE_REPO"/model_sentinel/model_sentinel/*.py \
    "$staging/model_sentinel/"
  (
    cd "$staging"
    zip -q -X "$archive" __main__.py model_sentinel/ model_sentinel/*.py
  )
  printf '#!/usr/bin/env python3\n' > "$target"
  /bin/cat "$archive" >> "$target"
  zip -q -A "$target"
  chmod 755 "$target"
}

new_fixture() {
  fixture_counter=$((fixture_counter + 1))
  FIXTURE_ROOT="$SUITE_ROOT/fixture-$fixture_counter"
  FIXTURE_REPO="$FIXTURE_ROOT/repo"
  FIXTURE_HOME="$FIXTURE_ROOT/home"
  FIXTURE_SCRIPTS="$FIXTURE_HOME/Library/Scripts"
  FIXTURE_LOCAL="$FIXTURE_HOME"
  FIXTURE_TMP="$FIXTURE_ROOT/tmp"
  FIXTURE_ZDOTDIR="$FIXTURE_ROOT/zdot"
  AUDIT_STDOUT="$FIXTURE_ROOT/audit.stdout"
  AUDIT_STDERR="$FIXTURE_ROOT/audit.stderr"
  AUDIT_STATUS=

  mkdir -p -- \
    "$FIXTURE_REPO/tools" \
    "$FIXTURE_SCRIPTS" \
    "$FIXTURE_TMP" \
    "$FIXTURE_ZDOTDIR" \
    "$FIXTURE_HOME/.config" \
    "$FIXTURE_HOME/.local/state"
  cp -p -- "$AUDIT_SOURCE" "$FIXTURE_REPO/tools/check_local_deployments.zsh"

  local mapping source_relative deployed_name source_file deployed_file
  for mapping in "${COPY_MAPPINGS[@]}"; do
    source_relative="${mapping%%|*}"
    deployed_name="${mapping#*|}"
    source_file="$FIXTURE_REPO/$source_relative"
    deployed_file="$FIXTURE_SCRIPTS/$deployed_name"
    write_synthetic_file "$source_file" "$source_relative"
    chmod 755 "$source_file"
    cp -p -- "$source_file" "$deployed_file"
  done

  write_synthetic_file \
    "$FIXTURE_REPO/model_sentinel/__main__.py" \
    "model sentinel entrypoint"
  write_synthetic_file \
    "$FIXTURE_REPO/model_sentinel/model_sentinel/__init__.py" \
    "model sentinel package"
  write_synthetic_file \
    "$FIXTURE_REPO/model_sentinel/model_sentinel/audit.py" \
    "model sentinel audit module"
  build_model_zipapp

  local project placeholder
  for project in "${HOME_PROJECTS[@]}"; do
    placeholder="$FIXTURE_REPO/$project/synthetic-placeholder.txt"
    write_synthetic_file "$placeholder" "$project placeholder"
    mkdir -p -- "$FIXTURE_LOCAL/$project"
    cp -p -- "$placeholder" "$FIXTURE_LOCAL/$project/synthetic-placeholder.txt"
  done

  write_synthetic_file \
    "$FIXTURE_LOCAL/docker/webserver/.env" \
    "SYNTHETIC_WEB_SECRET=not-a-secret"
  write_synthetic_file \
    "$FIXTURE_HOME/.config/llm_collector/secret.env" \
    "SYNTHETIC_COLLECTOR_SECRET=not-a-secret"
  write_synthetic_file \
    "$FIXTURE_LOCAL/docker/n8n-poc/.env" \
    "SYNTHETIC_N8N_SECRET=not-a-secret"
  chmod 600 \
    "$FIXTURE_LOCAL/docker/webserver/.env" \
    "$FIXTURE_HOME/.config/llm_collector/secret.env" \
    "$FIXTURE_LOCAL/docker/n8n-poc/.env"
  mkdir -p -- "$FIXTURE_HOME/.local/state/n8n-poc"
  chmod 700 "$FIXTURE_HOME/.local/state/n8n-poc"

  git -C "$FIXTURE_REPO" init -q
  git -C "$FIXTURE_REPO" config user.name "Synthetic Audit Tester"
  git -C "$FIXTURE_REPO" config user.email "audit-tester@example.invalid"
  git -C "$FIXTURE_REPO" add .
  git -C "$FIXTURE_REPO" commit -qm "synthetic passing baseline"

  local tracked_file
  for project in "${HOME_PROJECTS[@]}"; do
    while IFS= read -r -d '' tracked_file; do
      mkdir -p -- "$FIXTURE_LOCAL/${tracked_file:h}"
      cp -p -- "$FIXTURE_REPO/$tracked_file" "$FIXTURE_LOCAL/$tracked_file"
    done < <(git -C "$FIXTURE_REPO" ls-files -z -- "$project")
  done
}

run_audit() {
  local shim_dir="${1:-}"
  local fixture_path="/usr/bin:/bin:/usr/sbin:/sbin"
  if [[ -n "$shim_dir" ]]; then
    fixture_path="$shim_dir:$fixture_path"
  fi

  local resolved
  resolved="$(env -i \
    HOME="$FIXTURE_HOME" \
    PATH="$fixture_path" \
    LC_ALL=C \
    GIT_CONFIG_NOSYSTEM=1 \
    GIT_CONFIG_GLOBAL=/dev/null \
    GIT_OPTIONAL_LOCKS=0 \
    /usr/bin/git -C "$FIXTURE_REPO" rev-parse --show-toplevel)" ||
    fail "fixture repository could not be resolved"
  [[ "${resolved:A}" == "${FIXTURE_REPO:A}" ]] ||
    fail "fixture repository resolved to an unexpected path"

  if (
    cd "$FIXTURE_REPO"
    env -i \
      HOME="$FIXTURE_HOME" \
      XDG_CONFIG_HOME="$FIXTURE_HOME/.config" \
      TMPDIR="$FIXTURE_TMP" \
      PATH="$fixture_path" \
      LC_ALL=C \
      ZDOTDIR="$FIXTURE_ZDOTDIR" \
      CDPATH= \
      ENV= \
      ZIPOPT= \
      ZIPINFOOPT= \
      UNZIPOPT= \
      GIT_CONFIG_NOSYSTEM=1 \
      GIT_CONFIG_GLOBAL=/dev/null \
      GIT_OPTIONAL_LOCKS=0 \
      UTILITIES_SCRIPTS_DIR="$FIXTURE_SCRIPTS" \
      UTILITIES_LOCAL_ROOT="$FIXTURE_LOCAL" \
      /bin/zsh -f "$FIXTURE_REPO/tools/check_local_deployments.zsh"
  ) > "$AUDIT_STDOUT" 2> "$AUDIT_STDERR"; then
    AUDIT_STATUS=0
  else
    AUDIT_STATUS=$?
  fi
}

snapshot_fixture() {
  local output="$1"
  (
    cd "$FIXTURE_ROOT"
    {
      print -r -- "index $(git -C "$FIXTURE_REPO" ls-files --stage -z | shasum -a 256)"
      find repo home -mindepth 1 \
        ! -path 'repo/.git/*' \
        ! -path 'repo/.git' \
        -print0 |
        sort -z |
        while IFS= read -r -d '' object_path; do
          local type mode digest="-"
          if [[ -L "$object_path" ]]; then
            type=symlink
            digest="$(readlink "$object_path" | shasum -a 256)"
          elif [[ -f "$object_path" ]]; then
            type=file
            digest="$(shasum -a 256 "$object_path" | awk '{print $1}')"
          elif [[ -d "$object_path" ]]; then
            type=directory
          else
            type=other
          fi
          mode="$(stat -f '%Mp%Lp' "$object_path")"
          print -r -- "$type $mode $digest $object_path"
        done
    } > "$output"
  )
}

assert_fixture_unchanged() {
  local before="$1"
  local after="$2"
  cmp -s "$before" "$after" ||
    fail "audit mutated fixture source, deployment, or index state"
}

test_passing_baseline() {
  new_fixture
  local before="$FIXTURE_ROOT/before.snapshot"
  local after="$FIXTURE_ROOT/after.snapshot"
  snapshot_fixture "$before"
  run_audit
  snapshot_fixture "$after"

  assert_status 0 "$AUDIT_STATUS" "passing baseline"
  local mapping deployed_name
  for mapping in "${COPY_MAPPINGS[@]}"; do
    deployed_name="${mapping#*|}"
    assert_contains "$AUDIT_STDOUT" "OK: $deployed_name"
  done
  assert_occurrences "$AUDIT_STDOUT" 1 "OK: model-sentinel zipapp"
  local project
  for project in "${HOME_PROJECTS[@]}"; do
    assert_contains "$AUDIT_STDOUT" "OK: ~/$project tracked files"
  done
  assert_contains "$AUDIT_STDOUT" "Local deployment audit: PASS"
  assert_not_contains "$AUDIT_STDOUT" "SYNTHETIC_WEB_SECRET"
  assert_not_contains "$AUDIT_STDERR" "SYNTHETIC_WEB_SECRET"
  assert_fixture_unchanged "$before" "$after"
}

test_missing_direct_copy() {
  new_fixture
  rm -- "$FIXTURE_SCRIPTS/de-abacus.py"
  local before="$FIXTURE_ROOT/before.snapshot"
  local after="$FIXTURE_ROOT/after.snapshot"
  snapshot_fixture "$before"
  run_audit
  snapshot_fixture "$after"

  assert_status 1 "$AUDIT_STATUS" "missing direct copy"
  assert_contains "$AUDIT_STDERR" "FAIL: de-abacus.py is missing"
  assert_not_contains "$AUDIT_STDOUT" "OK: de-abacus.py"
  assert_fixture_unchanged "$before" "$after"
}

test_project_byte_drift() {
  new_fixture
  print -r -- "synthetic deployment drift" \
    > "$FIXTURE_LOCAL/tax2/synthetic-placeholder.txt"
  local before="$FIXTURE_ROOT/before.snapshot"
  local after="$FIXTURE_ROOT/after.snapshot"
  snapshot_fixture "$before"
  run_audit
  snapshot_fixture "$after"

  assert_status 1 "$AUDIT_STATUS" "project byte drift"
  assert_contains "$AUDIT_STDERR" "FAIL: tax2 has 1 missing or differing tracked files"
  assert_not_contains "$AUDIT_STDOUT" "OK: ~/tax2 tracked files"
  assert_fixture_unchanged "$before" "$after"
}

test_passing_baseline
test_missing_direct_copy
test_project_byte_drift

print -- "check_local_deployments tests: PASS"
