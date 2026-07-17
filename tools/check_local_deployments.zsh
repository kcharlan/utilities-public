#!/bin/zsh

set -euo pipefail

REPO_ROOT="${0:A:h:h}"
SCRIPTS_DIR="${UTILITIES_SCRIPTS_DIR:-$HOME/Library/Scripts}"
LOCAL_ROOT="${UTILITIES_LOCAL_ROOT:-$HOME}"
failures=0

report_failure() {
  print -u2 -- "FAIL: $*"
  failures=$((failures + 1))
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
  if [[ ! -f "$deployed_file" ]]; then
    report_failure "$deployed_name is missing"
  elif ! cmp -s "$source_file" "$deployed_file"; then
    report_failure "$deployed_name differs from $source_relative"
  else
    print -- "OK: $deployed_name"
  fi
done

model_zipapp="$SCRIPTS_DIR/model-sentinel"
if [[ ! -f "$model_zipapp" ]]; then
  report_failure "model-sentinel zipapp is missing"
else
  verify_dir="$(mktemp -d)"
  trap 'rm -rf "$verify_dir"' EXIT
  if ! unzip -q "$model_zipapp" -d "$verify_dir"; then
    report_failure "model-sentinel is not a readable zipapp"
  elif ! cmp -s "$verify_dir/__main__.py" "$REPO_ROOT/model_sentinel/__main__.py"; then
    report_failure "model-sentinel __main__.py is stale"
  else
    for source_file in "$REPO_ROOT"/model_sentinel/model_sentinel/*.py; do
      if ! cmp -s "$source_file" "$verify_dir/model_sentinel/${source_file:t}"; then
        report_failure "model-sentinel module ${source_file:t} is stale"
      fi
    done
    print -- "OK: model-sentinel zipapp"
  fi
  rm -rf "$verify_dir"
  trap - EXIT
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
  project_failures=0
  while IFS= read -r -d '' tracked_file; do
    source_file="$REPO_ROOT/$tracked_file"
    # Ignore paths deleted in the working tree but not yet committed. Include
    # non-ignored new source so the audit is also useful before a commit.
    [[ -f "$source_file" ]] || continue
    deployed_file="$LOCAL_ROOT/$tracked_file"
    if [[ ! -f "$deployed_file" ]] || ! cmp -s "$source_file" "$deployed_file"; then
      project_failures=$((project_failures + 1))
    fi
  done < <(git -C "$REPO_ROOT" ls-files --cached --others --exclude-standard -z -- "$project")
  if (( project_failures )); then
    report_failure "$project has $project_failures missing or differing tracked files"
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
  if [[ ! -f "$private_file" ]]; then
    report_failure "required private config is missing: ${private_file#$LOCAL_ROOT/}"
  elif [[ "$(stat -f '%Lp' "$private_file")" != 600 ]]; then
    report_failure "private config is not mode 0600: ${private_file#$LOCAL_ROOT/}"
  fi
done

n8n_state="$LOCAL_ROOT/.local/state/n8n-poc"
if [[ ! -d "$n8n_state" ]] || [[ "$(stat -f '%Lp' "$n8n_state")" != 700 ]]; then
  report_failure "n8n state directory is missing or not mode 0700"
fi

print -- "Local-only legacy launchers (not compared): fid_div_conv, van_div_conv"

if (( failures )); then
  print -u2 -- "Local deployment audit failed: $failures issue(s)."
  exit 1
fi

print -- "Local deployment audit: PASS"
