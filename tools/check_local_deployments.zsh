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

run_git_capture() {
  local label="$1"
  local output_file="$2"
  shift 2
  local error_file="$AUDIT_TMP/git-command.stderr"

  if /usr/bin/env -i \
    HOME="$HOME" \
    PATH="$PATH" \
    LC_ALL=C \
    GIT_CONFIG_NOSYSTEM=1 \
    GIT_CONFIG_GLOBAL=/dev/null \
    GIT_OPTIONAL_LOCKS=0 \
    git -C "$REPO_ROOT" "$@" \
    > "$output_file" 2> "$error_file"; then
    return 0
  fi
  : > "$output_file"
  report_failure "$label"
  return 1
}

run_zipinfo_capture() {
  local output_file="$1"
  shift
  local error_file="$AUDIT_TMP/zipinfo-command.stderr"

  /usr/bin/env -i \
    HOME="$HOME" \
    PATH="$PATH" \
    LC_ALL=C \
    ZIPOPT= \
    ZIPINFOOPT= \
    UNZIPOPT= \
    zipinfo "$@" \
    </dev/null > "$output_file" 2> "$error_file"
}

stream_archive_entry() {
  setopt localoptions pipefail
  local archive_file="$1"
  local entry_name="$2"
  local byte_limit="$3"
  local output_file="$4"
  local unzip_error="$AUDIT_TMP/unzip-command.stderr"
  local sink_error="$AUDIT_TMP/archive-sink.stderr"
  local -a stream_statuses

  /usr/bin/env -i \
    HOME="$HOME" \
    PATH="$PATH" \
    LC_ALL=C \
    ZIPOPT= \
    ZIPINFOOPT= \
    UNZIPOPT= \
    unzip -p "$archive_file" "$entry_name" \
    </dev/null 2> "$unzip_error" |
    /usr/bin/head -c "$byte_limit" \
      > "$output_file" 2> "$sink_error"
  stream_statuses=("${pipestatus[@]}")
  (( ${#stream_statuses[@]} == 2 &&
      stream_statuses[1] == 0 &&
      stream_statuses[2] == 0 ))
}

typeset -a direct_source_paths audited_scopes index_paths
typeset -a invalid_index_paths pending_deletion_paths model_module_paths
typeset -A index_membership index_modes index_oids
typeset -A invalid_index_membership source_state_invalid pending_deletions
typeset -A stale_counts stale_history_operational_errors

for mapping in "${copy_mappings[@]}"; do
  direct_source_paths+=("${mapping%%|*}")
done
audited_scopes=(
  "${direct_source_paths[@]}"
  model_sentinel/__main__.py
  model_sentinel/model_sentinel
  ':(glob)**/.gitignore'
  "${home_projects[@]}"
)

git_snapshot_ok=true
git_head_ok=true
git_top_file="$AUDIT_TMP/git-top-level"
if run_git_capture \
  "repository top-level resolution failed" \
  "$git_top_file" \
  rev-parse --show-toplevel; then
  resolved_git_top=
  IFS= read -r resolved_git_top < "$git_top_file" || true
  if [[ -z "$resolved_git_top" || "${resolved_git_top:A}" != "$REPO_ROOT" ]]; then
    report_failure "repository top-level does not match the audit source root"
    git_snapshot_ok=false
  fi
else
  git_snapshot_ok=false
fi

git_head_file="$AUDIT_TMP/git-head"
if [[ "$git_snapshot_ok" == true ]]; then
  if ! run_git_capture \
    "committed baseline required for deployment audit" \
    "$git_head_file" \
    rev-parse --verify HEAD; then
    git_snapshot_ok=false
    git_head_ok=false
  fi
else
  git_head_ok=false
fi

index_snapshot="$AUDIT_TMP/index-snapshot"
if [[ "$git_snapshot_ok" == true ]]; then
  if run_git_capture \
    "validated Git index snapshot collection failed" \
    "$index_snapshot" \
    ls-files --stage --sparse -z -- "${audited_scopes[@]}"; then
    while IFS= read -r -d '' index_record; do
      if [[ "$index_record" != *$'\t'* ]]; then
        report_failure "validated Git index snapshot is malformed"
        git_snapshot_ok=false
        break
      fi
      index_metadata="${index_record%%$'\t'*}"
      index_pathname="${index_record#*$'\t'}"
      index_mode_value="${index_metadata%% *}"
      index_remainder="${index_metadata#* }"
      index_oid_value="${index_remainder%% *}"
      index_stage_value="${index_remainder##* }"
      if [[ -z "$index_pathname" ||
            "$index_mode_value" != <-> ||
            "$index_stage_value" != <-> ||
            -z "$index_oid_value" ||
            "$index_oid_value" == *[^0-9a-f]* ]]; then
        report_failure "validated Git index snapshot is malformed"
        git_snapshot_ok=false
        break
      fi
      if [[ "$index_stage_value" != 0 ||
            ( "$index_mode_value" != 100644 &&
              "$index_mode_value" != 100755 ) ]]; then
        if [[ -z "${invalid_index_membership[$index_pathname]-}" ]]; then
          invalid_index_membership[$index_pathname]=1
          invalid_index_paths+=("$index_pathname")
        fi
        continue
      fi
      index_membership[$index_pathname]=1
      index_modes[$index_pathname]="$index_mode_value"
      index_oids[$index_pathname]="$index_oid_value"
      index_paths+=("$index_pathname")
    done < "$index_snapshot"
  else
    git_snapshot_ok=false
  fi
fi

if [[ "$git_snapshot_ok" == true ]]; then
  for indexed_path in "${index_paths[@]}"; do
    indexed_source="$REPO_ROOT/$indexed_path"
    if [[ -L "$indexed_source" || ! -f "$indexed_source" ]]; then
      source_state_invalid[$indexed_path]=1
    fi
  done
fi

pending_snapshot="$AUDIT_TMP/pending-deletions"
if [[ "$git_snapshot_ok" == true && "$git_head_ok" == true ]]; then
  if run_git_capture \
    "pending source deletion collection failed" \
    "$pending_snapshot" \
    diff --cached --no-renames --diff-filter=D --name-only -z \
    HEAD -- "${audited_scopes[@]}"; then
    while IFS= read -r -d '' pending_path; do
      if [[ -z "$pending_path" ]]; then
        report_failure "pending source deletion collection is malformed"
        git_snapshot_ok=false
        break
      fi
      if [[ -z "${pending_deletions[$pending_path]-}" ]]; then
        pending_deletions[$pending_path]=1
        pending_deletion_paths+=("$pending_path")
      fi
    done < "$pending_snapshot"
  else
    git_snapshot_ok=false
  fi
fi

stale_history_available=true
shallow_file="$AUDIT_TMP/git-shallow"
if [[ "$git_snapshot_ok" == true && "$git_head_ok" == true ]]; then
  if run_git_capture \
    "shallow-history detection failed" \
    "$shallow_file" \
    rev-parse --is-shallow-repository; then
    shallow_value=
    IFS= read -r shallow_value < "$shallow_file" || true
    if [[ "$shallow_value" == true ]]; then
      report_failure \
        "shallow Git history detected; stale-file audit is incomplete"
      stale_history_available=false
    elif [[ "$shallow_value" != false ]]; then
      report_failure "shallow-history detection returned an invalid result"
      stale_history_available=false
    fi
  else
    stale_history_available=false
  fi
else
  stale_history_available=false
fi

check_repository_ignore() {
  local candidate="$1"
  local input_file="$2"
  local output_file="$3"
  local error_file="$AUDIT_TMP/check-ignore.stderr"

  print -rn -- "$candidate"$'\0' > "$input_file"
  if /usr/bin/env -i \
    HOME="$HOME" \
    PATH="$PATH" \
    LC_ALL=C \
    GIT_CONFIG_NOSYSTEM=1 \
    GIT_CONFIG_GLOBAL=/dev/null \
    GIT_OPTIONAL_LOCKS=0 \
    git -C "$REPO_ROOT" \
      -c core.excludesFile=/dev/null \
      check-ignore --no-index -z -v --stdin \
      < "$input_file" > "$output_file" 2> "$error_file"; then
    return 0
  else
    local ignore_status=$?
  fi
  if (( ignore_status == 1 )); then
    : > "$output_file"
    return 1
  fi
  : > "$output_file"
  return "$ignore_status"
}

if [[ "$stale_history_available" == true ]]; then
  history_number=0
  for project in "${home_projects[@]}"; do
    stale_counts[$project]=0
    stale_history_operational_errors[$project]=0
    history_number=$((history_number + 1))
    history_file="$AUDIT_TMP/history-$history_number"
    if ! run_git_capture \
      "$project stale-file history collection failed" \
      "$history_file" \
      log --first-parent --diff-merges=first-parent --no-renames \
      --diff-filter=D --format= --name-only -z HEAD -- "$project"; then
      stale_history_operational_errors[$project]=1
      continue
    fi

    typeset -A project_deleted_paths
    project_deleted_paths=()
    while IFS= read -r -d '' deleted_path; do
      [[ -n "$deleted_path" ]] || continue
      project_deleted_paths[$deleted_path]=1
    done < "$history_file"

    history_candidate_number=0
    for deleted_path in "${(k)project_deleted_paths[@]}"; do
      if [[ -n "${pending_deletions[$deleted_path]-}" ||
            -n "${index_membership[$deleted_path]-}" ]]; then
        continue
      fi

      deployed_candidate="$LOCAL_ROOT/$deleted_path"
      ignore_candidate="$deleted_path"
      if [[ ! -L "$deployed_candidate" && -d "$deployed_candidate" ]]; then
        ignore_candidate="$deleted_path/"
      fi
      history_candidate_number=$((history_candidate_number + 1))
      ignore_input="$AUDIT_TMP/ignore-$history_number-$history_candidate_number.in"
      ignore_output="$AUDIT_TMP/ignore-$history_number-$history_candidate_number.out"

      ignored_by_repository=false
      if check_repository_ignore \
        "$ignore_candidate" \
        "$ignore_input" \
        "$ignore_output"; then
        typeset -a ignore_fields
        ignore_fields=()
        while IFS= read -r -d '' ignore_field; do
          ignore_fields+=("$ignore_field")
        done < "$ignore_output"
        if (( ${#ignore_fields[@]} != 4 )); then
          report_failure "$project ignore classification output is malformed"
          stale_history_operational_errors[$project]=$((stale_history_operational_errors[$project] + 1))
          continue
        fi
        ignore_source="${ignore_fields[1]}"
        ignore_pattern="${ignore_fields[3]}"
        ignore_returned="${ignore_fields[4]}"
        if [[ "$ignore_returned" != "$ignore_candidate" ]]; then
          report_failure "$project ignore classification pathname mismatch"
          stale_history_operational_errors[$project]=$((stale_history_operational_errors[$project] + 1))
          continue
        fi
        if [[ -n "$ignore_source" &&
              "$ignore_source" != /* &&
              "$ignore_source" != ../* &&
              "$ignore_source" == *.gitignore &&
              -n "${index_membership[$ignore_source]-}" &&
              "$ignore_pattern" != '!'* ]]; then
          ignored_by_repository=true
        fi
      else
        ignore_status=$?
        if (( ignore_status > 1 )); then
          report_failure "$project ignore classification command failed"
          stale_history_operational_errors[$project]=$((stale_history_operational_errors[$project] + 1))
          continue
        fi
      fi

      if [[ "$ignored_by_repository" == true ]]; then
        continue
      fi
      if [[ -e "$deployed_candidate" || -L "$deployed_candidate" ]]; then
        stale_counts[$project]=$((stale_counts[$project] + 1))
      fi
    done
  done
else
  for project in "${home_projects[@]}"; do
    stale_counts[$project]=0
    stale_history_operational_errors[$project]=1
  done
fi

for mapping in "${copy_mappings[@]}"; do
  source_relative="${mapping%%|*}"
  deployed_name="${mapping#*|}"
  source_file="$REPO_ROOT/$source_relative"
  deployed_file="$SCRIPTS_DIR/$deployed_name"
  artifact_ok=true

  if [[ "$git_snapshot_ok" != true ]]; then
    continue
  elif [[ -n "${pending_deletions[$source_relative]-}" ]]; then
    report_failure \
      "$deployed_name source is pending deletion: $source_relative"
    continue
  elif [[ -n "${invalid_index_membership[$source_relative]-}" ||
          -z "${index_membership[$source_relative]-}" ]]; then
    report_failure \
      "$deployed_name source is not a supported stage-0 index file: $source_relative"
    continue
  elif [[ -n "${source_state_invalid[$source_relative]-}" ]]; then
    report_failure \
      "$deployed_name source is missing or unsupported: $source_relative"
    continue
  elif [[ ! -e "$deployed_file" && ! -L "$deployed_file" ]]; then
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
model_source_ok=true
if [[ "$git_snapshot_ok" != true ]]; then
  model_zipapp_ok=false
  model_source_ok=false
elif [[ -n "${pending_deletions[model_sentinel/__main__.py]-}" ]]; then
  report_failure "model-sentinel __main__.py source is pending deletion"
  model_zipapp_ok=false
  model_source_ok=false
elif [[ -n "${invalid_index_membership[model_sentinel/__main__.py]-}" ||
        -z "${index_membership[model_sentinel/__main__.py]-}" ]]; then
  report_failure \
    "model-sentinel __main__.py is not a supported stage-0 index file"
  model_zipapp_ok=false
  model_source_ok=false
elif [[ -n "${source_state_invalid[model_sentinel/__main__.py]-}" ]]; then
  report_failure "model-sentinel __main__.py source is missing or unsupported"
  model_zipapp_ok=false
  model_source_ok=false
fi

if [[ "$git_snapshot_ok" == true ]]; then
  for indexed_path in "${index_paths[@]}"; do
    if [[ "$indexed_path" == model_sentinel/model_sentinel/*.py ]]; then
      model_relative="${indexed_path#model_sentinel/model_sentinel/}"
      if [[ "$model_relative" == */* ]]; then
        continue
      fi
      model_stem="${model_relative%.py}"
      if [[ "$model_relative" != *.py ||
            -z "$model_stem" ||
            "${model_stem[1]}" != [A-Za-z_] ||
            "$model_stem" == *[^A-Za-z0-9_]* ]]; then
        report_failure \
          "model-sentinel module has unsupported source pathname"
        model_zipapp_ok=false
        model_source_ok=false
        continue
      fi
      model_module_paths+=("$indexed_path")
      if [[ -n "${source_state_invalid[$indexed_path]-}" ]]; then
        report_failure \
          "model-sentinel module ${indexed_path:t} source is missing or unsupported"
        model_zipapp_ok=false
        model_source_ok=false
      fi
    fi
  done
  for invalid_path in "${invalid_index_paths[@]}"; do
    if [[ "$invalid_path" == model_sentinel/model_sentinel/* ]]; then
      report_failure \
        "model-sentinel module ${invalid_path:t} has unsupported index type or stage"
      model_zipapp_ok=false
      model_source_ok=false
    fi
  done
  for pending_path in "${pending_deletion_paths[@]}"; do
    if [[ "$pending_path" == model_sentinel/model_sentinel/*.py ]]; then
      report_failure \
        "model-sentinel module ${pending_path:t} source is pending deletion"
      model_zipapp_ok=false
      model_source_ok=false
    fi
  done
fi

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
  model_preamble_expected="$AUDIT_TMP/model-preamble-expected"
  model_preamble_actual="$AUDIT_TMP/model-preamble-actual"
  printf '#!/usr/bin/env python3\nPK\003\004' > "$model_preamble_expected"
  if ! /usr/bin/head -c 27 "$model_zipapp" \
      > "$model_preamble_actual" 2> "$AUDIT_TMP/model-preamble.stderr" ||
      ! compare_bytes "$model_preamble_expected" "$model_preamble_actual"; then
    report_failure "model-sentinel zipapp has an invalid executable preamble"
    model_zipapp_ok=false
  fi

  model_inventory_ok="$model_source_ok"
  typeset -a expected_archive_entries expected_regular_entries
  typeset -A expected_archive_sources expected_archive_types
  typeset -A expected_archive_sizes archive_inventory_counts
  expected_archive_entries=(__main__.py model_sentinel/)
  expected_regular_entries=(__main__.py)
  expected_archive_sources[__main__.py]=model_sentinel/__main__.py
  expected_archive_types[__main__.py]=file
  expected_archive_types[model_sentinel/]=directory
  expected_archive_sizes[model_sentinel/]=0

  for model_module_path in "${model_module_paths[@]}"; do
    archive_entry="model_sentinel/${model_module_path:t}"
    expected_archive_entries+=("$archive_entry")
    expected_regular_entries+=("$archive_entry")
    expected_archive_sources[$archive_entry]="$model_module_path"
    expected_archive_types[$archive_entry]=file
  done

  expected_total_size=0
  if [[ "$model_source_ok" == true ]]; then
    for archive_entry in "${expected_regular_entries[@]}"; do
      archive_source="$REPO_ROOT/${expected_archive_sources[$archive_entry]}"
      archive_source_size=
      if ! archive_source_size="$(file_size "$archive_source" 2>/dev/null)" ||
          [[ "$archive_source_size" != <-> ]]; then
        report_failure "model-sentinel source size inspection failed"
        model_zipapp_ok=false
        model_inventory_ok=false
        continue
      fi
      expected_archive_sizes[$archive_entry]="$archive_source_size"
      expected_total_size=$((expected_total_size + archive_source_size))
    done
  fi

  inventory_list="$AUDIT_TMP/model-inventory.list"
  if ! run_zipinfo_capture "$inventory_list" -1 "$model_zipapp"; then
    report_failure "model-sentinel archive inventory could not be read"
    model_zipapp_ok=false
    model_inventory_ok=false
  else
    inventory_unexpected=false
    while IFS= read -r inventory_entry ||
        [[ -n "$inventory_entry" ]]; do
      if [[ -z "${expected_archive_types[$inventory_entry]-}" ]]; then
        inventory_unexpected=true
        continue
      fi
      archive_inventory_counts[$inventory_entry]=$((\
        ${archive_inventory_counts[$inventory_entry]:-0} + 1))
    done < "$inventory_list"

    if [[ "$inventory_unexpected" == true ]]; then
      report_failure "model-sentinel archive contains unexpected entries"
      model_zipapp_ok=false
      model_inventory_ok=false
    fi
    for archive_entry in "${expected_archive_entries[@]}"; do
      inventory_count="${archive_inventory_counts[$archive_entry]:-0}"
      if (( inventory_count == 0 )); then
        if [[ "$archive_entry" == __main__.py ]]; then
          report_failure "model-sentinel __main__.py is missing from the archive"
        elif [[ "$archive_entry" == model_sentinel/ ]]; then
          report_failure "model-sentinel package directory entry is missing"
        else
          report_failure \
            "model-sentinel module ${archive_entry:t} is missing from the archive"
        fi
        model_zipapp_ok=false
        model_inventory_ok=false
      elif (( inventory_count != 1 )); then
        report_failure "model-sentinel archive contains duplicate entries"
        model_zipapp_ok=false
        model_inventory_ok=false
      fi
    done
  fi

  advertised_total_size=0
  if [[ "$model_inventory_ok" == true ]]; then
    archive_detail_number=0
    for archive_entry in "${expected_archive_entries[@]}"; do
      archive_detail_number=$((archive_detail_number + 1))
      detail_file="$AUDIT_TMP/model-detail-$archive_detail_number"
      verbose_file="$AUDIT_TMP/model-verbose-$archive_detail_number"
      if ! run_zipinfo_capture \
        "$detail_file" -l "$model_zipapp" "$archive_entry"; then
        report_failure "model-sentinel archive entry metadata could not be read"
        model_zipapp_ok=false
        model_inventory_ok=false
        continue
      fi

      detail_records=0
      detail_permissions=
      advertised_size=
      while IFS= read -r detail_line ||
          [[ -n "$detail_line" ]]; do
        if [[ "$detail_line" == [-d]* ]]; then
          detail_fields=(${=detail_line})
          if (( ${#detail_fields[@]} < 10 )); then
            detail_records=99
            break
          fi
          detail_records=$((detail_records + 1))
          detail_permissions="${detail_fields[1]}"
          advertised_size="${detail_fields[4]}"
        fi
      done < "$detail_file"
      expected_type="${expected_archive_types[$archive_entry]}"
      expected_size="${expected_archive_sizes[$archive_entry]}"
      if (( detail_records != 1 )) ||
          [[ "$advertised_size" != <-> ]] ||
          { [[ "$expected_type" == file ]] &&
            [[ "${detail_permissions[1]}" != - ]]; } ||
          { [[ "$expected_type" == directory ]] &&
            [[ "${detail_permissions[1]}" != d ]]; } ||
          [[ "$advertised_size" != "$expected_size" ]]; then
        report_failure "model-sentinel archive entry type or size is invalid"
        model_zipapp_ok=false
        model_inventory_ok=false
        continue
      fi
      advertised_total_size=$((advertised_total_size + advertised_size))

      if ! run_zipinfo_capture \
        "$verbose_file" -v "$model_zipapp" "$archive_entry"; then
        report_failure "model-sentinel archive security metadata could not be read"
        model_zipapp_ok=false
        model_inventory_ok=false
        continue
      fi
      security_count="$(grep -Fc \
        'file security status:                           not encrypted' \
        "$verbose_file" || true)"
      if [[ "$security_count" != 1 ]]; then
        report_failure "model-sentinel archive entry encryption state is invalid"
        model_zipapp_ok=false
        model_inventory_ok=false
      fi
    done
    if (( advertised_total_size != expected_total_size )); then
      report_failure "model-sentinel archive total advertised size is invalid"
      model_zipapp_ok=false
      model_inventory_ok=false
    fi
  fi

  if [[ "$model_inventory_ok" == true ]]; then
    stream_number=0
    for archive_entry in "${expected_regular_entries[@]}"; do
      stream_number=$((stream_number + 1))
      expected_size="${expected_archive_sizes[$archive_entry]}"
      streamed_file="$AUDIT_TMP/model-entry-$stream_number"
      if ! stream_archive_entry \
        "$model_zipapp" \
        "$archive_entry" \
        "$((expected_size + 1))" \
        "$streamed_file"; then
        report_failure "model-sentinel archive entry streaming failed"
        model_zipapp_ok=false
        continue
      fi
      streamed_size=
      if ! streamed_size="$(file_size "$streamed_file" 2>/dev/null)" ||
          [[ "$streamed_size" != "$expected_size" ]]; then
        report_failure "model-sentinel archive entry streamed size is invalid"
        model_zipapp_ok=false
        continue
      fi
      archive_source="$REPO_ROOT/${expected_archive_sources[$archive_entry]}"
      if compare_bytes "$archive_source" "$streamed_file"; then
        :
      else
        comparison_status=$?
        if [[ "$archive_entry" == __main__.py ]]; then
          artifact_label="model-sentinel __main__.py"
        else
          artifact_label="model-sentinel module ${archive_entry:t}"
        fi
        if (( comparison_status == 1 )); then
          report_failure "$artifact_label is stale"
        else
          report_failure "$artifact_label comparison failed"
        fi
        model_zipapp_ok=false
      fi
    done
  fi
fi
if [[ "$model_zipapp_ok" == true ]]; then
  print -- "OK: model-sentinel zipapp"
fi

for project in "${home_projects[@]}"; do
  project_missing=0
  project_type_failures=0
  project_byte_differences=0
  project_mode_differences=0
  project_stale="${stale_counts[$project]:-0}"
  project_source_state_failures=0
  project_operational_errors="${stale_history_operational_errors[$project]:-0}"

  if [[ "$git_snapshot_ok" != true ]]; then
    if (( project_operational_errors == 0 )); then
      project_operational_errors=1
    fi
  else
    for tracked_file in "${index_paths[@]}"; do
      if [[ "$tracked_file" != "$project"/* ]]; then
        continue
      fi
      source_file="$REPO_ROOT/$tracked_file"
      if [[ -n "${source_state_invalid[$tracked_file]-}" ]]; then
        project_source_state_failures=$((project_source_state_failures + 1))
        continue
      fi
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
    done

    for invalid_path in "${invalid_index_paths[@]}"; do
      if [[ "$invalid_path" == "$project"/* ]]; then
        project_source_state_failures=$((project_source_state_failures + 1))
      fi
    done
    for pending_path in "${pending_deletion_paths[@]}"; do
      if [[ "$pending_path" == "$project"/* ]]; then
        project_source_state_failures=$((project_source_state_failures + 1))
      fi
    done
  fi

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
