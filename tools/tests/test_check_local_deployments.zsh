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
  if ! grep -Fq -- "$expected" "$file"; then
    print -u2 -- "--- $file ---"
    sed -n '1,200p' "$file" >&2
    fail "$label: expected text not found: $expected"
  fi
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

install_fixture_archive() {
  local archive="$1"
  local target="$FIXTURE_SCRIPTS/model-sentinel"
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
  assert_contains "$AUDIT_STDERR" "FAIL: tax2 deployment drift"
  assert_contains "$AUDIT_STDERR" "missing files: 0"
  assert_contains "$AUDIT_STDERR" "byte differences: 1"
  assert_contains "$AUDIT_STDERR" "mode differences: 0"
  assert_not_contains "$AUDIT_STDOUT" "OK: ~/tax2 tracked files"
  assert_fixture_unchanged "$before" "$after"
}

test_direct_mode_drift() {
  new_fixture
  chmod 744 "$FIXTURE_SCRIPTS/de-abacus.py"
  run_audit

  assert_status 1 "$AUDIT_STATUS" "direct mode drift"
  assert_contains \
    "$AUDIT_STDERR" \
    "FAIL: de-abacus.py mode differs: source 0755, deployed 0744"
  assert_not_contains "$AUDIT_STDOUT" "OK: de-abacus.py"
}

test_direct_special_mode_drift() {
  local source_mode deployed_mode
  for source_mode deployed_mode in 4755 0755 2600 0600 1700 0700; do
    new_fixture
    chmod "$source_mode" "$FIXTURE_REPO/abacus usage/de-abacus.py"
    chmod "$deployed_mode" "$FIXTURE_SCRIPTS/de-abacus.py"
    run_audit

    assert_status 1 "$AUDIT_STATUS" "direct special-bit mode drift"
    assert_contains \
      "$AUDIT_STDERR" \
      "FAIL: de-abacus.py mode differs: source $source_mode, deployed $deployed_mode"
    assert_not_contains "$AUDIT_STDOUT" "OK: de-abacus.py"
  done
}

test_project_mode_drift() {
  new_fixture
  chmod 755 "$FIXTURE_REPO/tax2/synthetic-placeholder.txt"
  chmod 744 "$FIXTURE_LOCAL/tax2/synthetic-placeholder.txt"
  run_audit

  assert_status 1 "$AUDIT_STATUS" "project mode drift"
  assert_contains "$AUDIT_STDERR" "tax2 deployment drift"
  assert_contains "$AUDIT_STDERR" "missing files: 0"
  assert_contains "$AUDIT_STDERR" "byte differences: 0"
  assert_contains "$AUDIT_STDERR" "mode differences: 1"
  assert_not_contains "$AUDIT_STDOUT" "OK: ~/tax2 tracked files"
}

test_project_byte_and_mode_dimensions() {
  new_fixture
  print -r -- "synthetic byte and mode drift" \
    > "$FIXTURE_LOCAL/tax2/synthetic-placeholder.txt"
  chmod 744 "$FIXTURE_LOCAL/tax2/synthetic-placeholder.txt"
  chmod 755 "$FIXTURE_REPO/tax2/synthetic-placeholder.txt"
  run_audit

  assert_status 1 "$AUDIT_STATUS" "project byte and mode drift"
  assert_contains "$AUDIT_STDERR" "tax2 deployment drift"
  assert_contains "$AUDIT_STDERR" "missing files: 0"
  assert_contains "$AUDIT_STDERR" "byte differences: 1"
  assert_contains "$AUDIT_STDERR" "mode differences: 1"
}

test_direct_symlink_rejected() {
  new_fixture
  rm -- "$FIXTURE_SCRIPTS/de-abacus.py"
  ln -s "$FIXTURE_REPO/abacus usage/de-abacus.py" \
    "$FIXTURE_SCRIPTS/de-abacus.py"
  run_audit

  assert_status 1 "$AUDIT_STATUS" "direct deployment symlink"
  assert_contains \
    "$AUDIT_STDERR" \
    "FAIL: de-abacus.py has unsupported deployment type"
  assert_not_contains "$AUDIT_STDOUT" "OK: de-abacus.py"
}

test_direct_nonregular_types_rejected() {
  local object_kind
  for object_kind in directory dangling-symlink fifo; do
    new_fixture
    rm -- "$FIXTURE_SCRIPTS/de-abacus.py"
    case "$object_kind" in
      directory)
        mkdir "$FIXTURE_SCRIPTS/de-abacus.py"
        ;;
      dangling-symlink)
        ln -s "$FIXTURE_ROOT/does-not-exist" "$FIXTURE_SCRIPTS/de-abacus.py"
        ;;
      fifo)
        mkfifo "$FIXTURE_SCRIPTS/de-abacus.py"
        ;;
    esac
    run_audit

    assert_status 1 "$AUDIT_STATUS" "direct deployment $object_kind"
    assert_contains \
      "$AUDIT_STDERR" \
      "FAIL: de-abacus.py has unsupported deployment type"
    assert_not_contains "$AUDIT_STDOUT" "OK: de-abacus.py"
  done
}

test_model_owner_execute_required() {
  new_fixture
  chmod 0011 "$FIXTURE_SCRIPTS/model-sentinel"
  run_audit

  assert_status 1 "$AUDIT_STATUS" "model sentinel owner execute"
  assert_contains \
    "$AUDIT_STDERR" \
    "FAIL: model-sentinel zipapp owner execute bit is not set (mode 0011)"
  assert_not_contains "$AUDIT_STDOUT" "OK: model-sentinel zipapp"
}

test_model_owner_executable_modes() {
  local executable_mode
  for executable_mode in 0100 0111; do
    new_fixture
    chmod "$executable_mode" "$FIXTURE_SCRIPTS/model-sentinel"
    run_audit

    assert_status 1 "$AUDIT_STATUS" "unreadable model sentinel mode $executable_mode"
    assert_contains \
      "$AUDIT_STDERR" \
      "FAIL: model-sentinel zipapp is not readable by the audit process"
    assert_not_contains \
      "$AUDIT_STDERR" \
      "model-sentinel zipapp owner execute bit is not set"
    assert_not_contains "$AUDIT_STDOUT" "OK: model-sentinel zipapp"
  done

  for executable_mode in 0700 0755; do
    new_fixture
    chmod "$executable_mode" "$FIXTURE_SCRIPTS/model-sentinel"
    run_audit

    assert_status 0 "$AUDIT_STATUS" "model sentinel mode $executable_mode"
    assert_occurrences "$AUDIT_STDOUT" 1 "OK: model-sentinel zipapp"
  done
}

test_compare_operational_error() {
  new_fixture
  local shim_dir="$FIXTURE_ROOT/shims"
  mkdir -p -- "$shim_dir"
  {
    print '#!/bin/zsh'
    print 'if [[ "$*" == *de-abacus.py* ]]; then'
    print '  exit 2'
    print 'fi'
    print 'exec /usr/bin/cmp "$@"'
  } > "$shim_dir/cmp"
  chmod 755 "$shim_dir/cmp"
  run_audit "$shim_dir"

  assert_status 1 "$AUDIT_STATUS" "comparison operational error"
  assert_contains \
    "$AUDIT_STDERR" \
    "FAIL: de-abacus.py byte comparison failed"
  assert_not_contains "$AUDIT_STDOUT" "OK: de-abacus.py"
  assert_contains "$AUDIT_STDOUT" "OK: div_conv"
  assert_contains "$AUDIT_STDERR" "Local deployment audit failed:"
}

test_stat_operational_error() {
  new_fixture
  local shim_dir="$FIXTURE_ROOT/shims"
  mkdir -p -- "$shim_dir"
  {
    print '#!/bin/zsh'
    print 'if [[ "$*" == *de-abacus.py* ]]; then'
    print '  exit 2'
    print 'fi'
    print 'exec /usr/bin/stat "$@"'
  } > "$shim_dir/stat"
  chmod 755 "$shim_dir/stat"
  run_audit "$shim_dir"

  assert_status 1 "$AUDIT_STATUS" "stat operational error"
  assert_contains \
    "$AUDIT_STDERR" \
    "FAIL: de-abacus.py source mode inspection failed"
  assert_contains \
    "$AUDIT_STDERR" \
    "FAIL: de-abacus.py deployed mode inspection failed"
  assert_not_contains "$AUDIT_STDOUT" "OK: de-abacus.py"
  assert_contains "$AUDIT_STDOUT" "OK: div_conv"
  assert_contains "$AUDIT_STDERR" "Local deployment audit failed:"
}

test_protected_modes_and_types() {
  new_fixture
  chmod 2600 "$FIXTURE_LOCAL/docker/webserver/.env"
  chmod 1700 "$FIXTURE_HOME/.local/state/n8n-poc"
  run_audit
  assert_status 1 "$AUDIT_STATUS" "protected special modes"
  assert_contains \
    "$AUDIT_STDERR" \
    "private config is not mode 0600: docker/webserver/.env (mode 2600)"
  assert_contains \
    "$AUDIT_STDERR" \
    "n8n state directory is missing or not mode 0700 (mode 1700)"

  new_fixture
  local private_target="$FIXTURE_ROOT/private-target"
  write_synthetic_file "$private_target" "synthetic private target"
  chmod 600 "$private_target"
  rm "$FIXTURE_LOCAL/docker/webserver/.env"
  ln -s "$private_target" "$FIXTURE_LOCAL/docker/webserver/.env"
  run_audit
  assert_status 1 "$AUDIT_STATUS" "protected config symlink"
  assert_contains \
    "$AUDIT_STDERR" \
    "required private config has unsupported type: docker/webserver/.env"

  new_fixture
  local state_target="$FIXTURE_ROOT/state-target"
  mkdir "$state_target"
  chmod 700 "$state_target"
  rmdir "$FIXTURE_HOME/.local/state/n8n-poc"
  ln -s "$state_target" "$FIXTURE_HOME/.local/state/n8n-poc"
  run_audit
  assert_status 1 "$AUDIT_STATUS" "protected state symlink"
  assert_contains "$AUDIT_STDERR" "n8n state path has unsupported type"
}

test_hostile_mktemp_targets_rejected() {
  local target_kind fixed_target
  for target_kind in root repository deployment existing symlink; do
    new_fixture
    case "$target_kind" in
      root)
        fixed_target=/
        ;;
      repository)
        fixed_target="$FIXTURE_REPO"
        ;;
      deployment)
        fixed_target="$FIXTURE_HOME"
        ;;
      existing)
        fixed_target="$FIXTURE_ROOT/unrelated"
        mkdir "$fixed_target"
        ;;
      symlink)
        mkdir "$FIXTURE_ROOT/unrelated"
        fixed_target="$FIXTURE_ROOT/temp-symlink"
        ln -s "$FIXTURE_ROOT/unrelated" "$fixed_target"
        ;;
    esac
    local marker="$FIXTURE_ROOT/unrelated-marker"
    print -r -- "must remain" > "$marker"
    local shim_dir="$FIXTURE_ROOT/shims"
    mkdir -p "$shim_dir"
    {
      print '#!/bin/zsh'
      printf "print -r -- %q\n" "$fixed_target"
    } > "$shim_dir/mktemp"
    chmod 755 "$shim_dir/mktemp"

    run_audit "$shim_dir"
    assert_status 1 "$AUDIT_STATUS" "hostile mktemp target $target_kind"
    assert_contains \
      "$AUDIT_STDERR" \
      "FAIL: could not initialize private audit temporary directory"
    assert_contains "$marker" "must remain"
    [[ -e "$fixed_target" || -L "$fixed_target" ]] ||
      fail "hostile mktemp target was removed: $target_kind"
  done
}

test_tmp_cleanup_after_chmod_failure() {
  new_fixture
  local shim_dir="$FIXTURE_ROOT/shims"
  mkdir -p "$shim_dir"
  {
    print '#!/bin/zsh'
    print 'if [[ "$*" == *utilities-deployment-audit.* ]]; then'
    print '  exit 2'
    print 'fi'
    print 'exec /bin/chmod "$@"'
  } > "$shim_dir/chmod"
  chmod 755 "$shim_dir/chmod"
  run_audit "$shim_dir"

  assert_status 1 "$AUDIT_STATUS" "audit temporary chmod failure"
  assert_contains \
    "$AUDIT_STDERR" \
    "FAIL: could not initialize private audit temporary directory"
  if find "$FIXTURE_TMP" -mindepth 1 -print -quit | grep -q .; then
    fail "audit temporary directory remained after chmod failure"
  fi
}

test_untracked_project_source_ignored() {
  new_fixture
  write_synthetic_file \
    "$FIXTURE_REPO/tax2/untracked-local.txt" \
    "untracked project source"
  run_audit

  assert_status 0 "$AUDIT_STATUS" "untracked project source"
  assert_contains "$AUDIT_STDOUT" "OK: ~/tax2 tracked files"
}

test_staged_project_addition_audited() {
  new_fixture
  write_synthetic_file \
    "$FIXTURE_REPO/tax2/staged-addition.txt" \
    "staged project addition"
  git -C "$FIXTURE_REPO" add tax2/staged-addition.txt
  run_audit

  assert_status 1 "$AUDIT_STATUS" "staged project addition"
  assert_contains "$AUDIT_STDERR" "tax2 deployment drift"
  assert_contains "$AUDIT_STDERR" "missing files: 1"
  assert_not_contains "$AUDIT_STDOUT" "OK: ~/tax2 tracked files"
}

test_direct_source_requires_index_membership() {
  new_fixture
  local source="$FIXTURE_REPO/abacus usage/de-abacus.py"
  local saved="$FIXTURE_ROOT/de-abacus.source"
  cp -p "$source" "$saved"
  git -C "$FIXTURE_REPO" rm -q "abacus usage/de-abacus.py"
  git -C "$FIXTURE_REPO" commit -qm "remove synthetic direct source"
  mkdir -p "${source:h}"
  cp -p "$saved" "$source"
  run_audit

  assert_status 1 "$AUDIT_STATUS" "unindexed direct source"
  assert_contains \
    "$AUDIT_STDERR" \
    "FAIL: de-abacus.py source is not a supported stage-0 index file"
  assert_not_contains "$AUDIT_STDOUT" "OK: de-abacus.py"
}

test_untracked_model_module_excluded() {
  new_fixture
  write_synthetic_file \
    "$FIXTURE_REPO/model_sentinel/model_sentinel/untracked.py" \
    "untracked model module"
  print -r -- "model_sentinel/model_sentinel/untracked.py" \
    > "$FIXTURE_REPO/.gitignore"
  git -C "$FIXTURE_REPO" add .gitignore
  git -C "$FIXTURE_REPO" commit -qm "ignore synthetic model module"
  run_audit

  assert_status 0 "$AUDIT_STATUS" "untracked model module"
  assert_occurrences "$AUDIT_STDOUT" 1 "OK: model-sentinel zipapp"
}

test_staged_model_module_audited() {
  new_fixture
  write_synthetic_file \
    "$FIXTURE_REPO/model_sentinel/model_sentinel/staged_module.py" \
    "staged model module"
  git -C "$FIXTURE_REPO" add \
    model_sentinel/model_sentinel/staged_module.py
  run_audit

  assert_status 1 "$AUDIT_STATUS" "staged model module"
  assert_contains \
    "$AUDIT_STDERR" \
    "model-sentinel module staged_module.py is missing from the archive"
  assert_not_contains "$AUDIT_STDOUT" "OK: model-sentinel zipapp"
}

test_missing_tracked_sources_fail() {
  new_fixture
  rm "$FIXTURE_REPO/tax2/synthetic-placeholder.txt"
  rm "$FIXTURE_REPO/model_sentinel/model_sentinel/audit.py"
  run_audit

  assert_status 1 "$AUDIT_STATUS" "missing tracked working-tree sources"
  assert_contains "$AUDIT_STDERR" "tax2 deployment drift"
  assert_contains "$AUDIT_STDERR" "source-state failures: 1"
  assert_contains \
    "$AUDIT_STDERR" \
    "model-sentinel module audit.py source is missing or unsupported"
  assert_not_contains "$AUDIT_STDOUT" "OK: ~/tax2 tracked files"
  assert_not_contains "$AUDIT_STDOUT" "OK: model-sentinel zipapp"
}

test_staged_project_deletion_fails_source_state() {
  new_fixture
  git -C "$FIXTURE_REPO" rm -q tax2/synthetic-placeholder.txt
  run_audit

  assert_status 1 "$AUDIT_STATUS" "staged project deletion"
  assert_contains "$AUDIT_STDERR" "tax2 deployment drift"
  assert_contains "$AUDIT_STDERR" "source-state failures: 1"
  assert_contains "$AUDIT_STDERR" "stale formerly tracked files: 0"
  assert_not_contains "$AUDIT_STDOUT" "OK: ~/tax2 tracked files"
}

test_tracked_source_symlink_rejected() {
  new_fixture
  local target="$FIXTURE_ROOT/synthetic-source-target"
  write_synthetic_file "$target" "source symlink target"
  rm "$FIXTURE_REPO/tax2/synthetic-placeholder.txt"
  ln -s "$target" "$FIXTURE_REPO/tax2/synthetic-placeholder.txt"
  git -C "$FIXTURE_REPO" add tax2/synthetic-placeholder.txt
  run_audit

  assert_status 1 "$AUDIT_STATUS" "tracked source symlink"
  assert_contains "$AUDIT_STDERR" "tax2 deployment drift"
  assert_contains "$AUDIT_STDERR" "source-state failures: 1"
  assert_not_contains "$AUDIT_STDOUT" "OK: ~/tax2 tracked files"
}

test_git_index_collection_failure_suppresses_dependent_ok() {
  new_fixture
  local shim_dir="$FIXTURE_ROOT/shims"
  mkdir -p "$shim_dir"
  {
    print '#!/bin/zsh'
    print 'if [[ "$*" == *"ls-files --stage"* ]]; then'
    print '  exit 128'
    print 'fi'
    print 'exec /usr/bin/git "$@"'
  } > "$shim_dir/git"
  chmod 755 "$shim_dir/git"
  run_audit "$shim_dir"

  assert_status 1 "$AUDIT_STATUS" "Git index collection failure"
  assert_contains \
    "$AUDIT_STDERR" \
    "FAIL: validated Git index snapshot collection failed"
  assert_not_contains "$AUDIT_STDOUT" "OK: de-abacus.py"
  assert_not_contains "$AUDIT_STDOUT" "OK: model-sentinel zipapp"
  assert_not_contains "$AUDIT_STDOUT" "OK: ~/tax2 tracked files"
  assert_contains \
    "$AUDIT_STDOUT" \
    "Local-only legacy launchers (not compared):"
  assert_contains "$AUDIT_STDERR" "Local deployment audit failed:"
}

commit_project_file() {
  local relative="$1"
  local label="$2"
  write_synthetic_file "$FIXTURE_REPO/$relative" "$label"
  mkdir -p "$FIXTURE_LOCAL/${relative:h}"
  cp -p "$FIXTURE_REPO/$relative" "$FIXTURE_LOCAL/$relative"
  git -C "$FIXTURE_REPO" add "$relative"
  git -C "$FIXTURE_REPO" commit -qm "add $label"
}

delete_project_source() {
  local relative="$1"
  git -C "$FIXTURE_REPO" rm -q "$relative"
  git -C "$FIXTURE_REPO" commit -qm "delete synthetic project source"
}

test_genuine_stale_project_file() {
  new_fixture
  local relative="docker/docs/retired-synthetic.md"
  commit_project_file "$relative" "retired synthetic documentation"
  delete_project_source "$relative"
  run_audit

  assert_status 1 "$AUDIT_STATUS" "genuine stale project file"
  assert_contains "$AUDIT_STDERR" "docker deployment drift"
  assert_contains "$AUDIT_STDERR" "stale formerly tracked files: 1"
  assert_not_contains "$AUDIT_STDOUT" "$relative"
  assert_not_contains "$AUDIT_STDERR" "$relative"
}

test_deleted_and_absent_is_not_stale() {
  new_fixture
  local relative="docker/docs/removed-everywhere.md"
  commit_project_file "$relative" "removed synthetic documentation"
  delete_project_source "$relative"
  rm "$FIXTURE_LOCAL/$relative"
  run_audit

  assert_status 0 "$AUDIT_STATUS" "deleted and absent project file"
  assert_contains "$AUDIT_STDOUT" "OK: ~/docker tracked files"
}

test_tracked_gitignore_suppresses_intentional_local_transition() {
  new_fixture
  local relative="docker/output/generated-synthetic.json"
  commit_project_file "$relative" "generated synthetic output"
  git -C "$FIXTURE_REPO" rm -q "$relative"
  print -r -- "/output/generated-synthetic.json" \
    > "$FIXTURE_REPO/docker/.gitignore"
  git -C "$FIXTURE_REPO" add docker/.gitignore
  git -C "$FIXTURE_REPO" commit -qm "make synthetic output local-only"
  cp -p \
    "$FIXTURE_REPO/docker/.gitignore" \
    "$FIXTURE_LOCAL/docker/.gitignore"
  run_audit

  assert_status 0 "$AUDIT_STATUS" "intentional local transition"
  assert_contains "$AUDIT_STDOUT" "OK: ~/docker tracked files"
}

test_untracked_same_path_does_not_hide_stale_file() {
  new_fixture
  local relative="docker/docs/untracked-collision.md"
  commit_project_file "$relative" "untracked collision source"
  delete_project_source "$relative"
  write_synthetic_file "$FIXTURE_REPO/$relative" "untracked replacement"
  run_audit

  assert_status 1 "$AUDIT_STATUS" "untracked same-path collision"
  assert_contains "$AUDIT_STDERR" "stale formerly tracked files: 1"
}

test_indexed_readd_suppresses_historical_deletion() {
  new_fixture
  local relative="docker/docs/readded-synthetic.md"
  commit_project_file "$relative" "initial re-add source"
  delete_project_source "$relative"
  write_synthetic_file "$FIXTURE_REPO/$relative" "current indexed re-add"
  git -C "$FIXTURE_REPO" add "$relative"
  cp -p "$FIXTURE_REPO/$relative" "$FIXTURE_LOCAL/$relative"
  run_audit

  assert_status 0 "$AUDIT_STATUS" "indexed source re-add"
  assert_contains "$AUDIT_STDOUT" "OK: ~/docker tracked files"
}

test_duplicate_deletion_history_counts_once() {
  new_fixture
  local relative="docker/docs/deleted-twice.md"
  commit_project_file "$relative" "first delete source"
  delete_project_source "$relative"
  write_synthetic_file "$FIXTURE_REPO/$relative" "second delete source"
  git -C "$FIXTURE_REPO" add "$relative"
  git -C "$FIXTURE_REPO" commit -qm "re-add synthetic source"
  git -C "$FIXTURE_REPO" rm -q "$relative"
  git -C "$FIXTURE_REPO" commit -qm "delete synthetic source again"
  run_audit

  assert_status 1 "$AUDIT_STATUS" "duplicate deletion history"
  assert_contains "$AUDIT_STDERR" "stale formerly tracked files: 1"
  assert_not_contains "$AUDIT_STDERR" "stale formerly tracked files: 2"
}

test_rename_origin_is_stale() {
  new_fixture
  local old_relative="docker/docs/old-synthetic-name.md"
  local new_relative="docker/docs/new-synthetic-name.md"
  commit_project_file "$old_relative" "renamed synthetic source"
  mkdir -p "$FIXTURE_REPO/${new_relative:h}"
  git -C "$FIXTURE_REPO" mv "$old_relative" "$new_relative"
  git -C "$FIXTURE_REPO" commit -qm "rename synthetic source"
  cp -p "$FIXTURE_REPO/$new_relative" "$FIXTURE_LOCAL/$new_relative"
  run_audit

  assert_status 1 "$AUDIT_STATUS" "rename-origin stale path"
  assert_contains "$AUDIT_STDERR" "stale formerly tracked files: 1"
}

test_ignore_negation_does_not_hide_stale_file() {
  new_fixture
  local relative="docker/docs/negated-synthetic.md"
  commit_project_file "$relative" "negated ignore source"
  git -C "$FIXTURE_REPO" rm -q "$relative"
  {
    print -r -- "docker/docs/*.md"
    print -r -- "!docker/docs/negated-synthetic.md"
  } > "$FIXTURE_REPO/.gitignore"
  git -C "$FIXTURE_REPO" add .gitignore
  git -C "$FIXTURE_REPO" commit -qm "re-include synthetic stale path"
  run_audit

  assert_status 1 "$AUDIT_STATUS" "winning ignore negation"
  assert_contains "$AUDIT_STDERR" "stale formerly tracked files: 1"
}

test_untracked_ignore_sources_are_not_authoritative() {
  local ignore_kind
  for ignore_kind in nested info global; do
    new_fixture
    local relative="docker/docs/non-authoritative-$ignore_kind.md"
    commit_project_file "$relative" "non-authoritative ignore source"
    delete_project_source "$relative"
    case "$ignore_kind" in
      nested)
        mkdir -p "$FIXTURE_REPO/docker/docs"
        print -r -- "non-authoritative-nested.md" \
          > "$FIXTURE_REPO/docker/docs/.gitignore"
        ;;
      info)
        print -r -- "$relative" \
          >> "$FIXTURE_REPO/.git/info/exclude"
        ;;
      global)
        local global_ignore="$FIXTURE_HOME/global-ignore"
        print -r -- "$relative" > "$global_ignore"
        git -C "$FIXTURE_REPO" config core.excludesFile "$global_ignore"
        ;;
    esac
    run_audit

    assert_status 1 "$AUDIT_STATUS" "non-authoritative $ignore_kind ignore"
    assert_contains "$AUDIT_STDERR" "stale formerly tracked files: 1"
  done
}

test_side_branch_only_deletion_is_excluded() {
  new_fixture
  local main_branch
  main_branch="$(git -C "$FIXTURE_REPO" symbolic-ref --short HEAD)"
  git -C "$FIXTURE_REPO" switch -q -c synthetic-side-branch
  local relative="docker/docs/side-branch-only.md"
  commit_project_file "$relative" "side branch only source"
  delete_project_source "$relative"
  git -C "$FIXTURE_REPO" switch -q "$main_branch"
  run_audit

  assert_status 0 "$AUDIT_STATUS" "side-branch-only deletion"
  assert_contains "$AUDIT_STDOUT" "OK: ~/docker tracked files"
}

test_stale_pathname_with_spaces_is_not_printed() {
  new_fixture
  local relative="docker/docs/retired synthetic name.md"
  commit_project_file "$relative" "spaced stale pathname"
  delete_project_source "$relative"
  run_audit

  assert_status 1 "$AUDIT_STATUS" "stale pathname with spaces"
  assert_contains "$AUDIT_STDERR" "stale formerly tracked files: 1"
  assert_not_contains "$AUDIT_STDOUT" "$relative"
  assert_not_contains "$AUDIT_STDERR" "$relative"
}

test_shallow_history_fails_coverage() {
  new_fixture
  local source_repo="$FIXTURE_REPO"
  local shallow_repo="$FIXTURE_ROOT/shallow-repo"
  git clone -q --depth=1 "file://$source_repo" "$shallow_repo"
  FIXTURE_REPO="$shallow_repo"
  AUDIT_STDOUT="$FIXTURE_ROOT/shallow-audit.stdout"
  AUDIT_STDERR="$FIXTURE_ROOT/shallow-audit.stderr"
  run_audit

  assert_status 1 "$AUDIT_STATUS" "shallow Git history"
  assert_contains "$AUDIT_STDERR" "shallow Git history"
  assert_contains "$AUDIT_STDERR" "stale-file audit is incomplete"
  assert_not_contains "$AUDIT_STDOUT" "Local deployment audit: PASS"
}

test_model_archive_rejects_untracked_extra_module() {
  new_fixture
  write_synthetic_file \
    "$FIXTURE_REPO/model_sentinel/model_sentinel/extra.py" \
    "untracked extra archive module"
  build_model_zipapp
  run_audit

  assert_status 1 "$AUDIT_STATUS" "untracked extra archive module"
  assert_contains \
    "$AUDIT_STDERR" \
    "model-sentinel archive contains unexpected entries"
  assert_not_contains "$AUDIT_STDOUT" "OK: model-sentinel zipapp"
}

test_model_archive_rejects_deleted_index_module() {
  new_fixture
  git -C "$FIXTURE_REPO" rm -q \
    model_sentinel/model_sentinel/audit.py
  git -C "$FIXTURE_REPO" commit -qm "delete synthetic model module"
  run_audit

  assert_status 1 "$AUDIT_STATUS" "deleted module remains in archive"
  assert_contains \
    "$AUDIT_STDERR" \
    "model-sentinel archive contains unexpected entries"
  assert_not_contains "$AUDIT_STDOUT" "OK: model-sentinel zipapp"
}

test_model_archive_requires_exact_preamble() {
  new_fixture
  local zipapp="$FIXTURE_SCRIPTS/model-sentinel"
  local remainder="$FIXTURE_ROOT/model-remainder"
  /usr/bin/tail -c +2 "$zipapp" > "$remainder"
  printf '?' > "$zipapp"
  /bin/cat "$remainder" >> "$zipapp"
  chmod 755 "$zipapp"
  run_audit

  assert_status 1 "$AUDIT_STATUS" "incorrect model zipapp preamble"
  assert_contains \
    "$AUDIT_STDERR" \
    "model-sentinel zipapp has an invalid executable preamble"
  assert_not_contains "$AUDIT_STDOUT" "OK: model-sentinel zipapp"
}

test_model_archive_content_mismatches() {
  new_fixture
  local source="$FIXTURE_REPO/model_sentinel/__main__.py"
  local changed="$FIXTURE_ROOT/changed-entrypoint"
  /usr/bin/tr 's' 'S' < "$source" > "$changed"
  mv "$changed" "$source"
  run_audit
  assert_status 1 "$AUDIT_STATUS" "model entrypoint content mismatch"
  assert_contains "$AUDIT_STDERR" "model-sentinel __main__.py is stale"
  assert_not_contains "$AUDIT_STDOUT" "OK: model-sentinel zipapp"

  new_fixture
  source="$FIXTURE_REPO/model_sentinel/model_sentinel/audit.py"
  changed="$FIXTURE_ROOT/changed-module"
  /usr/bin/tr 's' 'S' < "$source" > "$changed"
  mv "$changed" "$source"
  run_audit
  assert_status 1 "$AUDIT_STATUS" "model module content mismatch"
  assert_contains "$AUDIT_STDERR" "model-sentinel module audit.py is stale"
  assert_not_contains "$AUDIT_STDOUT" "OK: model-sentinel zipapp"
}

test_model_archive_rejects_duplicate_entry() {
  new_fixture
  local staging="$FIXTURE_ROOT/model-staging"
  local archive="$FIXTURE_ROOT/duplicate.zip"
  (
    cd "$staging"
    /usr/bin/tar --no-recursion -acf "$archive" \
      __main__.py \
      model_sentinel/ \
      model_sentinel/__init__.py \
      model_sentinel/audit.py \
      __main__.py
  )
  install_fixture_archive "$archive"
  run_audit

  assert_status 1 "$AUDIT_STATUS" "duplicate archive entry"
  assert_contains \
    "$AUDIT_STDERR" \
    "model-sentinel archive contains duplicate entries"
  assert_not_contains "$AUDIT_STDOUT" "OK: model-sentinel zipapp"
}

test_model_archive_rejects_traversal_entry_without_writes() {
  new_fixture
  local staging="$FIXTURE_ROOT/model-staging"
  local archive="$FIXTURE_ROOT/traversal.zip"
  local outside="$FIXTURE_ROOT/escape"
  print -r -- "must not be written" > "$outside"
  (
    cd "$staging"
    zip -q -X "$archive" \
      __main__.py \
      model_sentinel/ \
      model_sentinel/*.py \
      ../escape
  )
  install_fixture_archive "$archive"
  local before_digest
  before_digest="$(shasum -a 256 "$outside")"
  run_audit

  assert_status 1 "$AUDIT_STATUS" "archive traversal entry"
  assert_contains \
    "$AUDIT_STDERR" \
    "model-sentinel archive contains unexpected entries"
  [[ "$(shasum -a 256 "$outside")" == "$before_digest" ]] ||
    fail "archive traversal test changed an external file"
  assert_not_contains "$AUDIT_STDOUT" "OK: model-sentinel zipapp"
}

test_model_archive_rejects_expected_symlink_entry() {
  new_fixture
  local staging="$FIXTURE_ROOT/model-staging"
  local archive="$FIXTURE_ROOT/symlink.zip"
  rm "$staging/model_sentinel/audit.py"
  ln -s __init__.py "$staging/model_sentinel/audit.py"
  (
    cd "$staging"
    zip -q -X -y "$archive" \
      __main__.py \
      model_sentinel/ \
      model_sentinel/*.py
  )
  install_fixture_archive "$archive"
  run_audit

  assert_status 1 "$AUDIT_STATUS" "archive symlink entry"
  assert_contains \
    "$AUDIT_STDERR" \
    "model-sentinel archive entry type or size is invalid"
  assert_not_contains "$AUDIT_STDOUT" "OK: model-sentinel zipapp"
}

test_model_archive_rejects_encrypted_entries() {
  new_fixture
  local staging="$FIXTURE_ROOT/model-staging"
  local archive="$FIXTURE_ROOT/encrypted.zip"
  (
    cd "$staging"
    zip -q -X -P conspicuously-synthetic-password "$archive" \
      __main__.py \
      model_sentinel/ \
      model_sentinel/*.py
  )
  install_fixture_archive "$archive"
  run_audit

  assert_status 1 "$AUDIT_STATUS" "encrypted archive entries"
  assert_contains \
    "$AUDIT_STDERR" \
    "model-sentinel archive entry encryption state is invalid"
  assert_not_contains "$AUDIT_STDOUT" "OK: model-sentinel zipapp"
}

test_model_archive_rejects_truncation() {
  new_fixture
  local zipapp="$FIXTURE_SCRIPTS/model-sentinel"
  local truncated="$FIXTURE_ROOT/truncated"
  local current_size
  current_size="$(stat -f '%z' "$zipapp")"
  /usr/bin/head -c "$((current_size - 12))" "$zipapp" > "$truncated"
  mv "$truncated" "$zipapp"
  chmod 755 "$zipapp"
  run_audit

  assert_status 1 "$AUDIT_STATUS" "truncated archive"
  assert_contains "$AUDIT_STDERR" "model-sentinel archive inventory could not be read"
  assert_not_contains "$AUDIT_STDOUT" "OK: model-sentinel zipapp"
}

test_model_archive_bounds_streamed_output() {
  new_fixture
  local shim_dir="$FIXTURE_ROOT/shims"
  mkdir -p "$shim_dir"
  {
    print '#!/bin/zsh'
    printf 'fixture_repo=%q\n' "$FIXTURE_REPO"
    print 'entry="${3:-}"'
    print 'if [[ "$entry" == __main__.py ]]; then'
    print '  /bin/cat "$fixture_repo/model_sentinel/__main__.py"'
    print 'else'
    print '  /bin/cat "$fixture_repo/model_sentinel/model_sentinel/${entry:t}"'
    print 'fi'
    print "printf 'X'"
  } > "$shim_dir/unzip"
  chmod 755 "$shim_dir/unzip"
  run_audit "$shim_dir"

  assert_status 1 "$AUDIT_STATUS" "archive decompression overrun"
  assert_contains \
    "$AUDIT_STDERR" \
    "model-sentinel archive entry streamed size is invalid"
  assert_not_contains "$AUDIT_STDOUT" "OK: model-sentinel zipapp"
  if find "$FIXTURE_TMP" -mindepth 1 -print -quit | grep -q .; then
    fail "bounded archive stream left audit temporary files behind"
  fi
}

test_passing_baseline
test_missing_direct_copy
test_project_byte_drift
test_direct_mode_drift
test_direct_special_mode_drift
test_project_mode_drift
test_project_byte_and_mode_dimensions
test_direct_symlink_rejected
test_direct_nonregular_types_rejected
test_model_owner_execute_required
test_model_owner_executable_modes
test_compare_operational_error
test_stat_operational_error
test_protected_modes_and_types
test_hostile_mktemp_targets_rejected
test_tmp_cleanup_after_chmod_failure
test_untracked_project_source_ignored
test_staged_project_addition_audited
test_direct_source_requires_index_membership
test_untracked_model_module_excluded
test_staged_model_module_audited
test_missing_tracked_sources_fail
test_staged_project_deletion_fails_source_state
test_tracked_source_symlink_rejected
test_git_index_collection_failure_suppresses_dependent_ok
test_genuine_stale_project_file
test_deleted_and_absent_is_not_stale
test_tracked_gitignore_suppresses_intentional_local_transition
test_untracked_same_path_does_not_hide_stale_file
test_indexed_readd_suppresses_historical_deletion
test_duplicate_deletion_history_counts_once
test_rename_origin_is_stale
test_ignore_negation_does_not_hide_stale_file
test_untracked_ignore_sources_are_not_authoritative
test_side_branch_only_deletion_is_excluded
test_stale_pathname_with_spaces_is_not_printed
test_shallow_history_fails_coverage
test_model_archive_rejects_untracked_extra_module
test_model_archive_rejects_deleted_index_module
test_model_archive_requires_exact_preamble
test_model_archive_content_mismatches
test_model_archive_rejects_duplicate_entry
test_model_archive_rejects_traversal_entry_without_writes
test_model_archive_rejects_expected_symlink_entry
test_model_archive_rejects_encrypted_entries
test_model_archive_rejects_truncation
test_model_archive_bounds_streamed_output

print -- "check_local_deployments tests: PASS"
