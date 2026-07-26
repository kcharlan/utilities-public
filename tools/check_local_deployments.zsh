#!/bin/zsh

set -euo pipefail
umask 077
zmodload zsh/system

REPO_ROOT="${0:A:h:h}"
SCRIPTS_DIR="${UTILITIES_SCRIPTS_DIR:-$HOME/Library/Scripts}"
LOCAL_ROOT="${UTILITIES_LOCAL_ROOT:-$HOME}"
failures=0

report_failure() {
  print -u2 -- "FAIL: $*"
  failures=$((failures + 1))
}

initialize_audit_tmp() {
  local raw_parent="${TMPDIR:-/tmp}"
  local resolved_parent candidate resolved_candidate owner

  if [[ "$raw_parent" != "/" ]]; then
    raw_parent="${raw_parent%/}"
  fi
  if ! resolved_parent="$(cd -P -- "$raw_parent" 2>/dev/null && pwd -P)"; then
    return 1
  fi
  [[ -d "$resolved_parent" && ! -L "$resolved_parent" ]] || return 1
  case "$resolved_parent" in
    /|"$HOME"|"$REPO_ROOT"|"$SCRIPTS_DIR"|"$LOCAL_ROOT")
      return 1
      ;;
  esac

  if ! candidate="$(mktemp -d \
    "$resolved_parent/utilities-deployment-audit.XXXXXX" 2>/dev/null)"; then
    return 1
  fi
  [[ -n "$candidate" && "$candidate" != "/" && ! -L "$candidate" ]] ||
    return 1
  if ! resolved_candidate="$(cd -P -- "$candidate" 2>/dev/null && pwd -P)"; then
    return 1
  fi
  [[ "$resolved_candidate" == "$resolved_parent"/utilities-deployment-audit.* ]] ||
    return 1
  [[ "${resolved_candidate:h}" == "$resolved_parent" ]] || return 1
  [[ -d "$resolved_candidate" && ! -L "$resolved_candidate" ]] || return 1
  if ! owner="$(stat -f '%u' "$resolved_candidate" 2>/dev/null)"; then
    return 1
  fi
  [[ "$owner" == "$EUID" ]] || return 1

  audit_tmp_parent_candidate="$resolved_parent"
  audit_tmp_candidate="$resolved_candidate"
}

cleanup_audit_tmp() {
  local saved_status=$?
  trap - EXIT HUP INT TERM
  if [[ "${sysparams[pid]}" == "${AUDIT_OWNER_PID:-}" ]] &&
      [[ -n "${AUDIT_TMP:-}" &&
        -n "${AUDIT_TMP_PARENT:-}" &&
        "$AUDIT_TMP" != "/" &&
        "$AUDIT_TMP" == "$AUDIT_TMP_PARENT"/utilities-deployment-audit.* &&
        "${AUDIT_TMP:h}" == "$AUDIT_TMP_PARENT" &&
        -d "$AUDIT_TMP" &&
        ! -L "$AUDIT_TMP" ]]; then
    local owner
    if owner="$(stat -f '%u' "$AUDIT_TMP" 2>/dev/null)" &&
        [[ "$owner" == "$EUID" ]]; then
      rm -rf -- "$AUDIT_TMP"
    fi
  fi
  return "$saved_status"
}

if ! initialize_audit_tmp; then
  print -u2 -- "FAIL: could not initialize private audit temporary directory"
  exit 1
fi
typeset -gr AUDIT_TMP_PARENT="$audit_tmp_parent_candidate"
typeset -gr AUDIT_TMP="$audit_tmp_candidate"
typeset -gr AUDIT_OWNER_PID="$sysparams[pid]"
unset audit_tmp_parent_candidate audit_tmp_candidate
trap cleanup_audit_tmp EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
audit_tmp_mode=
if ! chmod 700 "$AUDIT_TMP" 2>/dev/null ||
    ! audit_tmp_mode="$(stat -f '%Mp%Lp' "$AUDIT_TMP" 2>/dev/null)" ||
    [[ "$audit_tmp_mode" != 0700 ]]; then
  print -u2 -- "FAIL: could not initialize private audit temporary directory"
  exit 1
fi
unset audit_tmp_mode

full_mode() {
  local raw_mode
  raw_mode="$(stat -f '%Mp%Lp' "$1")" || return
  printf '%04o\n' "$((8#$raw_mode))"
}

file_size() {
  stat -f '%z' "$1"
}

compare_bytes() {
  cmp -s -- "$1" "$2"
}

copy_mappings=(
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

for mapping in "${copy_mappings[@]}"; do
  source_relative="${mapping%%|*}"
  deployed_name="${mapping#*|}"
  source_file="$REPO_ROOT/$source_relative"
  deployed_file="$SCRIPTS_DIR/$deployed_name"
  artifact_ok=true

  if [[ ! -e "$deployed_file" && ! -L "$deployed_file" ]]; then
    report_failure "$deployed_name is missing"
    artifact_ok=false
  elif [[ -L "$deployed_file" || ! -f "$deployed_file" ]]; then
    report_failure \
      "$deployed_name has unsupported deployment type (expected regular non-symlink file)"
    artifact_ok=false
  else
    if compare_bytes "$source_file" "$deployed_file"; then
      :
    else
      comparison_status=$?
      if (( comparison_status == 1 )); then
        report_failure "$deployed_name bytes differ from $source_relative"
      else
        report_failure "$deployed_name byte comparison failed"
      fi
      artifact_ok=false
    fi

    source_mode=
    deployed_mode=
    if ! source_mode="$(full_mode "$source_file" 2>/dev/null)"; then
      report_failure "$deployed_name source mode inspection failed"
      artifact_ok=false
    fi
    if ! deployed_mode="$(full_mode "$deployed_file" 2>/dev/null)"; then
      report_failure "$deployed_name deployed mode inspection failed"
      artifact_ok=false
    fi
    if [[ -n "$source_mode" &&
          -n "$deployed_mode" &&
          "$source_mode" != "$deployed_mode" ]]; then
      report_failure \
        "$deployed_name mode differs: source $source_mode, deployed $deployed_mode"
      artifact_ok=false
    fi
  fi

  if [[ "$artifact_ok" == true ]]; then
    print -- "OK: $deployed_name"
  fi
done

model_zipapp="$SCRIPTS_DIR/model-sentinel"
model_zipapp_ok=true
model_can_inspect=false
if [[ ! -e "$model_zipapp" && ! -L "$model_zipapp" ]]; then
  report_failure "model-sentinel zipapp is missing"
  model_zipapp_ok=false
elif [[ -L "$model_zipapp" || ! -f "$model_zipapp" ]]; then
  report_failure \
    "model-sentinel zipapp has unsupported deployment type (expected regular non-symlink file)"
  model_zipapp_ok=false
else
  if [[ -r "$model_zipapp" ]]; then
    model_can_inspect=true
  else
    report_failure "model-sentinel zipapp is not readable by the audit process"
    model_zipapp_ok=false
  fi
  model_mode=
  if ! model_mode="$(full_mode "$model_zipapp" 2>/dev/null)"; then
    report_failure "model-sentinel zipapp mode inspection failed"
    model_zipapp_ok=false
  else
    if (( (8#$model_mode & 8#0100) == 0 )); then
      report_failure \
        "model-sentinel zipapp owner execute bit is not set (mode $model_mode)"
      model_zipapp_ok=false
    fi
    if [[ ! -x "$model_zipapp" ]]; then
      report_failure "model-sentinel zipapp is not executable by the audit process"
      model_zipapp_ok=false
    fi
  fi
fi

if [[ "$model_can_inspect" == true ]]; then
  verify_dir="$AUDIT_TMP/model-extract"
  mkdir -m 700 -- "$verify_dir"
  if ! unzip -q "$model_zipapp" -d "$verify_dir" </dev/null; then
    report_failure "model-sentinel is not a readable zipapp"
    model_zipapp_ok=false
  else
    if compare_bytes \
      "$verify_dir/__main__.py" \
      "$REPO_ROOT/model_sentinel/__main__.py"; then
      :
    else
      comparison_status=$?
      if (( comparison_status == 1 )); then
        report_failure "model-sentinel __main__.py is stale"
      else
        report_failure "model-sentinel __main__.py comparison failed"
      fi
      model_zipapp_ok=false
    fi
    for source_file in "$REPO_ROOT"/model_sentinel/model_sentinel/*.py; do
      if compare_bytes \
        "$source_file" \
        "$verify_dir/model_sentinel/${source_file:t}"; then
        :
      else
        comparison_status=$?
        if (( comparison_status == 1 )); then
          report_failure "model-sentinel module ${source_file:t} is stale"
        else
          report_failure \
            "model-sentinel module ${source_file:t} comparison failed"
        fi
        model_zipapp_ok=false
      fi
    done
  fi
fi
if [[ "$model_zipapp_ok" == true ]]; then
  print -- "OK: model-sentinel zipapp"
fi

home_projects=(
  apple-health-extract
  docker
  mem_snapshots
  mls-tracker
  tax2
  transcription
  vid-compiler
  video-scenes
)

for project in "${home_projects[@]}"; do
  project_missing=0
  project_type_failures=0
  project_byte_differences=0
  project_mode_differences=0
  project_stale=0
  project_source_state_failures=0
  project_operational_errors=0

  while IFS= read -r -d '' tracked_file; do
    source_file="$REPO_ROOT/$tracked_file"
    [[ -f "$source_file" ]] || continue
    deployed_file="$LOCAL_ROOT/$tracked_file"
    if [[ ! -e "$deployed_file" && ! -L "$deployed_file" ]]; then
      project_missing=$((project_missing + 1))
      continue
    fi
    if [[ -L "$deployed_file" || ! -f "$deployed_file" ]]; then
      project_type_failures=$((project_type_failures + 1))
      continue
    fi

    if compare_bytes "$source_file" "$deployed_file"; then
      :
    else
      comparison_status=$?
      if (( comparison_status == 1 )); then
        project_byte_differences=$((project_byte_differences + 1))
      else
        project_operational_errors=$((project_operational_errors + 1))
      fi
    fi

    source_mode=
    deployed_mode=
    if ! source_mode="$(full_mode "$source_file" 2>/dev/null)"; then
      project_operational_errors=$((project_operational_errors + 1))
    fi
    if ! deployed_mode="$(full_mode "$deployed_file" 2>/dev/null)"; then
      project_operational_errors=$((project_operational_errors + 1))
    fi
    if [[ -n "$source_mode" &&
          -n "$deployed_mode" &&
          "$source_mode" != "$deployed_mode" ]]; then
      project_mode_differences=$((project_mode_differences + 1))
    fi
  done < <(
    git -C "$REPO_ROOT" \
      ls-files --cached --others --exclude-standard -z -- "$project"
  )

  if (( project_missing ||
        project_type_failures ||
        project_byte_differences ||
        project_mode_differences ||
        project_stale ||
        project_source_state_failures ||
        project_operational_errors )); then
    report_failure \
      "$project deployment drift (missing files: $project_missing, deployment-type failures: $project_type_failures, byte differences: $project_byte_differences, mode differences: $project_mode_differences, stale formerly tracked files: $project_stale, source-state failures: $project_source_state_failures, operational errors: $project_operational_errors)"
  else
    print -- "OK: ~/$project tracked files"
  fi
done

private_files=(
  "$LOCAL_ROOT/docker/webserver/.env"
  "$LOCAL_ROOT/.config/llm_collector/secret.env"
  "$LOCAL_ROOT/docker/n8n-poc/.env"
)
for private_file in "${private_files[@]}"; do
  private_label="${private_file#$LOCAL_ROOT/}"
  if [[ ! -e "$private_file" && ! -L "$private_file" ]]; then
    report_failure "required private config is missing: $private_label"
  elif [[ -L "$private_file" || ! -f "$private_file" ]]; then
    report_failure \
      "required private config has unsupported type: $private_label"
  else
    private_mode=
    if ! private_mode="$(full_mode "$private_file" 2>/dev/null)"; then
      report_failure "private config mode inspection failed: $private_label"
    elif [[ "$private_mode" != 0600 ]]; then
      report_failure \
        "private config is not mode 0600: $private_label (mode $private_mode)"
    fi
  fi
done

n8n_state="$LOCAL_ROOT/.local/state/n8n-poc"
if [[ ! -e "$n8n_state" && ! -L "$n8n_state" ]]; then
  report_failure "n8n state directory is missing or not mode 0700"
elif [[ -L "$n8n_state" || ! -d "$n8n_state" ]]; then
  report_failure "n8n state path has unsupported type"
else
  n8n_mode=
  if ! n8n_mode="$(full_mode "$n8n_state" 2>/dev/null)"; then
    report_failure "n8n state directory mode inspection failed"
  elif [[ "$n8n_mode" != 0700 ]]; then
    report_failure "n8n state directory is missing or not mode 0700 (mode $n8n_mode)"
  fi
fi

print -- "Local-only legacy launchers (not compared): fid_div_conv, van_div_conv"

if (( failures )); then
  print -u2 -- "Local deployment audit failed: $failures issue(s)."
  exit 1
fi

print -- "Local deployment audit: PASS"
