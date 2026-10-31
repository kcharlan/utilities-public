#!/bin/zsh
#
# Propagate dependency updates from this repository's docker/ projects to the
# deployed copy and the stacks running from it, in two gated phases:
#
#   refresh  Update lockfiles within their declared ranges, audit them,
#            test-build the images under throwaway Compose project names and
#            run the stack tests. Changes only repository files.
#   deploy   From committed source only: copy tracked docker/ files into the
#            deployed copy with backups, rerun update.sh for each stack that
#            was running, and confirm it is running again.
#
# See docker/README.md and docs/local_deployment_sync.md.

set -euo pipefail

readonly SCRIPT_DIR="${0:A:h}"
readonly PROG="${0:t}"
readonly REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
readonly DOCKER_SRC="$REPO_ROOT/docker"
readonly DEPLOY_ROOT="${PROPAGATE_DEPLOY_ROOT:-$HOME/docker}"
readonly BACKUP_PARENT="${PROPAGATE_BACKUP_ROOT:-$HOME/.utilities-deploy-backups}"

# Every top-level docker/ project. Deploy refuses tracked projects missing here
# so a new stack is never copied without a decision about how it updates.
typeset -ra STACKS=(
  actual-data
  docker-disk-compact
  excalidraw
  llm_collector
  llm_proxy
  mermaid
  n8n-poc
  webserver
)

# Running Compose project name and Compose file (relative to docker/).
typeset -rA STACK_COMPOSE_PROJECT=(
  excalidraw excalidraw
  llm_collector llm_collector_container
  llm_proxy llm_proxy
  n8n-poc n8n-poc
  webserver webserver
)
typeset -rA STACK_COMPOSE_FILE=(
  excalidraw excalidraw/docker-compose.yml
  llm_collector llm_collector/llm_collector_container/docker-compose.yml
  llm_proxy llm_proxy/docker-compose.yml
  n8n-poc n8n-poc/docker-compose.yml
  webserver webserver/docker-compose.yml
)
# Stacks run with plain `docker run` instead of Compose.
typeset -rA STACK_CONTAINER=(
  actual-data actual
  mermaid mermaid
)
# Each stack's own rebuild/restart/health script (relative to docker/).
typeset -rA STACK_UPDATER=(
  actual-data actual-data/update.sh
  excalidraw excalidraw/update.sh
  llm_collector llm_collector/llm_collector_container/update.sh
  llm_proxy llm_proxy/update.sh
  mermaid mermaid/update.sh
  n8n-poc n8n-poc/update.sh
  webserver webserver/update.sh
)
# Stacks with their own source-to-deployment tool. Deploy never copies them;
# it updates them only when the deployed copy already matches source.
typeset -rA STACK_SYNC_TOOL=(
  llm_collector docker/llm_collector/migrate.sh
)

# stack|directory under docker/|lock kind
typeset -ra REFRESH_TARGETS=(
  'webserver|webserver/index|npm'
  'webserver|webserver/app_node|npm'
  'webserver|webserver/app_py|uv-pip-compile'
  'llm_proxy|llm_proxy|uv-lock'
)
# Services built by the refresh check build; empty means all services.
typeset -rA CHECK_BUILD_SERVICES=(
  webserver 'index app_py app_node'
  llm_proxy ''
)

COMMAND=
DRY_RUN=false
typeset -a SELECTED=()
typeset -a SUMMARY=()
typeset -i PROBLEMS=0
STEP_FAILURE=
BACKUP_DIR=

log() { print -r -- "[propagate] $*"; }
warn() { print -ru2 -- "[propagate] WARNING: $*"; }
die() { print -ru2 -- "[propagate] ERROR: $*"; exit 1; }

usage() {
  cat <<EOF
Usage: $PROG refresh [--stack NAME]... [--dry-run]
       $PROG deploy  [--stack NAME]... [--dry-run]
       $PROG --help

refresh  Update docker/ lockfiles within their declared ranges, audit them,
         test-build images under throwaway Compose project names and run the
         stack tests. Changes only repository files; review and commit the
         result before deploying.
deploy   Requires no uncommitted tracked changes under docker/. Copies tracked
         files into \$PROPAGATE_DEPLOY_ROOT (default ~/docker), backing up each
         replaced file under \$PROPAGATE_BACKUP_ROOT (default
         ~/.utilities-deploy-backups), reruns update.sh for every selected
         stack that was running and confirms it is running again. Stopped
         stacks receive files but stay stopped.

--stack NAME  Limit to one stack; repeatable. Default: every stack.
--dry-run     Print the plan without running tools or changing files.

Stacks: ${(j:, :)STACKS}
EOF
}

usage_error() {
  print -ru2 -- "$PROG: $*"
  usage >&2
  exit 2
}

parse_args() {
  (( $# )) || usage_error "missing command"
  case "$1" in
    --help|-h) usage; exit 0 ;;
    refresh|deploy) COMMAND="$1" ;;
    *) usage_error "unknown command: $1" ;;
  esac
  shift
  local name
  while (( $# )); do
    case "$1" in
      --dry-run) DRY_RUN=true ;;
      --help|-h) usage; exit 0 ;;
      --stack|--stack=*)
        if [[ "$1" == --stack=* ]]; then
          name="${1#--stack=}"
        else
          (( $# >= 2 )) || usage_error "--stack needs a name"
          name="$2"
          shift
        fi
        (( ${STACKS[(Ie)$name]} )) || usage_error "unknown stack: $name"
        (( ${SELECTED[(Ie)$name]} )) || SELECTED+=("$name")
        ;;
      *) usage_error "unknown option: $1" ;;
    esac
    shift
  done
  (( ${#SELECTED} )) || SELECTED=("${STACKS[@]}")
}

# record STACK STATUS DETAIL; STATUS is ok, planned, skipped, FAILED or
# ACTION NEEDED. The last two make the run exit non-zero.
record() {
  SUMMARY+=("$1"$'\t'"$2"$'\t'"$3")
  [[ "$2" == FAILED || "$2" == "ACTION NEEDED" ]] && PROBLEMS+=1
  return 0
}

print_summary() {
  local line stack summary_status detail problem_pass
  print
  log "Summary"
  for problem_pass in true false; do
    for line in "${SUMMARY[@]}"; do
      IFS=$'\t' read -r stack summary_status detail <<< "$line"
      if [[ "$summary_status" == FAILED || "$summary_status" == "ACTION NEEDED" ]]; then
        [[ "$problem_pass" == true ]] || continue
      else
        [[ "$problem_pass" == false ]] || continue
      fi
      printf '  %-20s %-14s %s\n' "$stack" "$summary_status" "$detail"
    done
  done
}

# run_in DIR COMMAND... prints the command, then runs it in DIR unless this is
# a dry run.
run_in() {
  local dir="$1"
  shift
  local shown="${dir#$REPO_ROOT/}"
  [[ "$dir" == "$REPO_ROOT" ]] && shown=.
  if [[ "$DRY_RUN" == true ]]; then
    log "  would run (in $shown): ${(j: :)${(q-)@}}"
    return 0
  fi
  log "  \$ (in $shown) ${(j: :)${(q-)@}}"
  (cd "$dir" && "$@")
}

require_tools() {
  local tool
  for tool in "$@"; do
    command -v "$tool" >/dev/null 2>&1 || die "required command not found: $tool"
  done
}

# ---------------------------------------------------------------- refresh

stack_has_refresh() {
  local entry
  for entry in "${REFRESH_TARGETS[@]}"; do
    [[ "${entry%%|*}" == "$1" ]] && return 0
  done
  return 1
}

refresh_lock() {
  local dir="$1" kind="$2" audit_dir rc
  case "$kind" in
    npm)
      run_in "$dir" npm update --package-lock-only --ignore-scripts --no-audit --no-fund || return 1
      run_in "$dir" npm audit --omit=dev --package-lock-only || return 1
      ;;
    uv-pip-compile)
      # UV_PYTHON_DOWNLOADS rather than a flag keeps the lock's recorded
      # compile command unchanged.
      run_in "$dir" env UV_PYTHON_DOWNLOADS=never uv pip compile --upgrade \
        --python-version 3.14 --universal --generate-hashes \
        requirements.txt --output-file requirements.lock || return 1
      run_in "$dir" uvx --no-python-downloads pip-audit --disable-pip --no-deps \
        -r requirements.lock || return 1
      ;;
    uv-lock)
      run_in "$dir" env UV_PYTHON_DOWNLOADS=never uv lock --upgrade || return 1
      if [[ "$DRY_RUN" == true ]]; then
        audit_dir="<temporary directory>"
      else
        audit_dir="$(mktemp -d "${TMPDIR:-/tmp}/propagate-audit.XXXXXX")" || return 1
      fi
      rc=0
      run_in "$dir" env UV_PYTHON_DOWNLOADS=never uv export --frozen --all-extras \
        --no-hashes --no-emit-project --format requirements-txt \
        --output-file "$audit_dir/requirements.txt" &&
        run_in "$dir" uvx --no-python-downloads pip-audit --disable-pip --no-deps \
          -r "$audit_dir/requirements.txt" || rc=$?
      [[ "$DRY_RUN" == true ]] || rm -rf -- "$audit_dir"
      return "$rc"
      ;;
    *)
      log "  unknown lock kind: $kind"
      return 1
      ;;
  esac
}

# Builds the stack's images from repository source under a throwaway Compose
# project, proving the refreshed locks install, then removes those images.
# A distinct project name keeps the live images (built from ~/docker under the
# same directory names) untouched.
check_build() {
  local stack="$1"
  local project="propagate-check-$stack"
  local compose_dir="$DOCKER_SRC/${STACK_COMPOSE_FILE[$stack]:h}"
  local -a services=(${=CHECK_BUILD_SERVICES[$stack]})
  local scratch rc=0
  if [[ "$DRY_RUN" == true ]]; then
    scratch="<empty temporary webroot>"
  else
    scratch="$(mktemp -d "${TMPDIR:-/tmp}/propagate-webroot.XXXXXX")" || return 1
  fi
  # WEBROOT_PATH satisfies the webserver Compose file's required variable
  # without exposing the real webroot to the check build.
  run_in "$compose_dir" env WEBROOT_PATH="$scratch" \
    docker compose -p "$project" build "${services[@]}" || rc=$?
  run_in "$compose_dir" env WEBROOT_PATH="$scratch" \
    docker compose -p "$project" down --rmi local ||
    warn "could not remove $project images; remove them with docker image rm"
  [[ "$DRY_RUN" == true ]] || rm -rf -- "$scratch"
  return "$rc"
}

# Images a stack's tests start with `docker run --pull=never`. A check build
# does not leave its base images as named local images, so refresh pulls these
# before the tests. Defaults and overrides mirror nginx-routing.test.mjs.
stack_test_images() {
  case "$1" in
    webserver)
      print -l -- "${NGINX_TEST_IMAGE:-nginx:stable-alpine}" \
        "${NGINX_TEST_NODE_IMAGE:-node:24-alpine}"
      ;;
  esac
}

pull_test_images() {
  local image
  for image in "${(@f)$(stack_test_images "$1")}"; do
    [[ -n "$image" ]] || continue
    run_in "$REPO_ROOT" docker pull "$image" || return 1
  done
}

run_stack_tests() {
  case "$1" in
    webserver)
      run_in "$REPO_ROOT" node --test docker/webserver/tests/nginx-routing.test.mjs
      ;;
    llm_proxy)
      run_in "$DOCKER_SRC/llm_proxy" env UV_PYTHON_DOWNLOADS=never \
        uv run --frozen --extra dev python -m pytest -q
      ;;
  esac
}

refresh_stack() {
  local stack="$1" entry rest dir kind
  for entry in "${REFRESH_TARGETS[@]}"; do
    [[ "${entry%%|*}" == "$stack" ]] || continue
    rest="${entry#*|}"
    dir="${rest%%|*}"
    kind="${rest#*|}"
    log "Refreshing docker/$dir ($kind)"
    if ! refresh_lock "$DOCKER_SRC/$dir" "$kind"; then
      STEP_FAILURE="lock refresh or audit failed in docker/$dir"
      return 1
    fi
  done
  log "Test-building $stack images"
  if ! check_build "$stack"; then
    STEP_FAILURE="test build failed for $stack"
    return 1
  fi
  if ! pull_test_images "$stack"; then
    STEP_FAILURE="could not pull $stack test images"
    return 1
  fi
  log "Running $stack tests"
  if ! run_stack_tests "$stack"; then
    STEP_FAILURE="$stack tests failed"
    return 1
  fi
}

cmd_refresh() {
  local stack
  if [[ "$DRY_RUN" != true ]]; then
    require_tools git docker npm uv uvx node
    if [[ -n "$(git -C "$REPO_ROOT" status --porcelain -- docker)" ]]; then
      warn "docker/ already has uncommitted changes; they will appear in the review diff"
    fi
  fi
  for stack in "${SELECTED[@]}"; do
    if ! stack_has_refresh "$stack"; then
      record "$stack" skipped "no range-refreshable lockfiles"
      continue
    fi
    STEP_FAILURE=
    if refresh_stack "$stack"; then
      if [[ "$DRY_RUN" == true ]]; then
        record "$stack" planned "refresh, audit, test build and tests"
      else
        record "$stack" ok "locks refreshed, audited, test-built and tested"
      fi
    else
      record "$stack" FAILED "$STEP_FAILURE"
    fi
  done
  print_summary
  if [[ "$DRY_RUN" != true ]]; then
    print
    log "Changes under docker/:"
    git -C "$REPO_ROOT" diff --stat=200 -- docker
    print
    log "Review the diff, commit it, then run: docker/$PROG deploy"
  fi
  (( PROBLEMS == 0 ))
}

# ----------------------------------------------------------------- deploy

typeset -a INVENTORY_PATHS=()
typeset -A RUNNING_COMPOSE=()
typeset -A RUNNING_CONTAINERS=()

# Reads the stage-0 index entries under docker/ and rejects anything other
# than regular files and unknown top-level projects.
load_inventory() {
  local record meta name mode stage top relative
  local raw
  raw="$(git -C "$REPO_ROOT" ls-files -s -z -- docker | tr '\0' '\n')" ||
    die "could not list tracked docker/ files"
  for record in "${(f)raw}"; do
    [[ -n "$record" ]] || continue
    meta="${record%%$'\t'*}"
    name="${record#*$'\t'}"
    mode="${meta%% *}"
    stage="${meta##* }"
    [[ "$stage" == 0 ]] || die "unmerged index entry: $name"
    [[ "$mode" == 100644 || "$mode" == 100755 ]] ||
      die "unsupported tracked file type ($mode): $name"
    relative="${name#docker/}"
    if [[ "$relative" == */* ]]; then
      top="${relative%%/*}"
      [[ "$top" == tests || "$top" == docs ]] ||
        (( ${STACKS[(Ie)$top]} )) ||
        die "unknown docker project: $top (add it to STACKS in $PROG)"
    fi
    INVENTORY_PATHS+=("$relative")
  done
}

# The tracked files (relative to docker/) owned by a stack; "" means the
# shared files outside any stack directory.
stack_files() {
  local relative top
  for relative in "${INVENTORY_PATHS[@]}"; do
    if [[ "$relative" == */* ]]; then
      top="${relative%%/*}"
      (( ${STACKS[(Ie)$top]} )) || top=
    else
      top=
    fi
    [[ "$top" == "$1" ]] && print -r -- "$relative"
  done
  return 0
}

file_mode() { stat -f '%Lp' "$1"; }

# Prints "same", "new" or "changed" for one tracked file.
file_state() {
  local source_file="$DOCKER_SRC/$1" destination="$DEPLOY_ROOT/$1"
  if [[ ! -e "$destination" && ! -L "$destination" ]]; then
    print new
  elif [[ -L "$destination" || ! -f "$destination" ]]; then
    print unsafe
  elif cmp -s "$source_file" "$destination" &&
       [[ "$(file_mode "$source_file")" == "$(file_mode "$destination")" ]]; then
    print same
  else
    print changed
  fi
}

# Rejects destinations whose resolved parent escapes the deployed copy.
destination_is_contained() {
  local parent="${${:-$DEPLOY_ROOT/$1}:h}" root="${DEPLOY_ROOT:A}"
  while [[ ! -e "$parent" ]]; do parent="${parent:h}"; done
  [[ "${parent:A}" == "$root" || "${parent:A}" == "$root"/* ]]
}

ensure_backup_dir() {
  [[ -z "$BACKUP_DIR" ]] || return 0
  if [[ ! -d "$BACKUP_PARENT" ]]; then
    mkdir -p -m 700 "$BACKUP_PARENT" || return 1
  fi
  BACKUP_DIR="$BACKUP_PARENT/docker-$(date +%Y%m%d-%H%M%S)"
  [[ ! -e "$BACKUP_DIR" ]] || BACKUP_DIR="$BACKUP_DIR-$$"
  mkdir -m 700 "$BACKUP_DIR"
}

backup_file() {
  local relative="$1" target
  ensure_backup_dir || return 1
  target="$BACKUP_DIR/$relative"
  mkdir -p -m 700 "${target:h}" &&
    cp -p "$DEPLOY_ROOT/$relative" "$target" &&
    chmod 600 "$target"
}

# Pruning is best-effort and must never follow user-created directory links.
prune_docker_backups() {
  local root="${BACKUP_PARENT:a}" part current=/ entry name stamp ordered dir mode
  local -a candidates=() sorted=()
  for part in "${(@s:/:)root}"; do
    [[ -n "$part" ]] || continue
    current="${current%/}/$part"
    if [[ -L "$current" ]]; then
      if [[ "$(uname -s)" != Darwin || ( "$current" != /tmp && "$current" != /var ) || ! -d "$current" ]]; then
        warn "cannot prune backups through linked path: $current"; return 0
      fi
    elif [[ ! -d "$current" ]]; then
      warn "cannot inspect backup directory: $current"; return 0
    fi
  done
  mode="$(stat -f '%Lp' "$root")" || { warn "cannot stat $root"; return 0; }
  if [[ ! -w "$root" || ! -x "$root" ]] || (( (8#$mode & 8#300) != 8#300 )); then
    warn "backup directory is not writable and searchable: $root"; return 0
  fi
  for entry in "$root"/*(N); do
    name="${entry:t}"
    [[ ! -L "$entry" && -d "$entry" && "$name" =~ '^docker-[0-9]{8}-[0-9]{6}(-[0-9]+)?$' ]] || continue
    stamp="$(stat -f '%m' "$entry")" || { warn "cannot stat $entry"; return 0; }
    candidates+=("$(printf '%020d\t%s' "$stamp" "$name")")
  done
  (( ${#candidates} > 2 )) || return 0
  ordered="$(printf '%s\n' "${candidates[@]}" | LC_ALL=C sort -r)" || { warn "cannot sort backups in $root"; return 0; }
  sorted=("${(@f)ordered}")
  for entry in "${sorted[@]:2}"; do
    name="${entry#*$'\t'}"
    dir="$root/$name"
    if [[ -L "$dir" || ! -d "$dir" ]]; then warn "backup changed: $dir"; continue; fi
    if ! find -P "$dir" -type d -exec chmod u+rwx {} +; then
      warn "cannot prepare backup for removal: $dir"; continue
    fi
    rm -rf -- "$dir" || warn "cannot remove backup: $dir"
  done
}

# Replaces one deployed file atomically, keeping the source file's mode.
install_file() {
  local relative="$1" destination="$DEPLOY_ROOT/$1" staged
  mkdir -p "${destination:h}" || return 1
  staged="${destination:h}/.${destination:t}.propagate-$$"
  cp -p "$DOCKER_SRC/$relative" "$staged" &&
    mv -f "$staged" "$destination" ||
    { rm -f -- "$staged"; return 1; }
}

# Copies one stack's tracked files. Prints nothing for unchanged files.
deploy_files() {
  local stack="$1" relative state
  local -i copied=0 backed_up=0
  local -a files=("${(@f)$(stack_files "$stack")}")
  files=(${files:#})
  for relative in "${files[@]}"; do
    state="$(file_state "$relative")"
    [[ "$state" == same ]] && continue
    if [[ "$state" == unsafe ]] || ! destination_is_contained "$relative"; then
      STEP_FAILURE="refusing to replace symlink or non-file: ~${DEPLOY_ROOT#$HOME}/$relative"
      return 1
    fi
    if [[ "$DRY_RUN" == true ]]; then
      log "  would copy ($state) $relative"
      copied+=1
      continue
    fi
    if [[ "$state" == changed ]]; then
      backup_file "$relative" || { STEP_FAILURE="backup failed for $relative"; return 1; }
      backed_up+=1
    fi
    install_file "$relative" || { STEP_FAILURE="copy failed for $relative"; return 1; }
    log "  copied ($state) $relative"
    copied+=1
  done
  COPY_NOTE="$copied file(s) copied, $backed_up backed up"
  [[ "$DRY_RUN" == true ]] && COPY_NOTE="$copied file(s) to copy"
  return 0
}

# Diverged files for a stack that is synchronized by its own tool.
stack_diverged() {
  local relative
  for relative in "${(@f)$(stack_files "$1")}"; do
    [[ -n "$relative" ]] || continue
    [[ "$(file_state "$relative")" == same ]] || return 0
  done
  return 1
}

snapshot_running() {
  local json line name config
  RUNNING_COMPOSE=()
  RUNNING_CONTAINERS=()
  json="$(docker compose ls --format json)" || die "docker compose ls failed; is Docker running?"
  for line in "${(@f)$(jq -r '.[] | select(.Status | test("running")) | "\(.Name)\t\(.ConfigFiles)"' <<< "$json")}"; do
    [[ -n "$line" ]] || continue
    name="${line%%$'\t'*}"
    config="${line#*$'\t'}"
    RUNNING_COMPOSE[$name]="$config"
  done
  for name in "${(@f)$(docker ps --format '{{.Names}}')}"; do
    [[ -n "$name" ]] && RUNNING_CONTAINERS[$name]=1
  done
  return 0
}

# Prints running, stopped, or "elsewhere:<config files>".
stack_runtime() {
  local stack="$1" project="${STACK_COMPOSE_PROJECT[$1]-}" container="${STACK_CONTAINER[$1]-}"
  local expected config
  if [[ -n "$project" && -n "${RUNNING_COMPOSE[$project]-}" ]]; then
    expected="$DEPLOY_ROOT/${STACK_COMPOSE_FILE[$stack]}"
    for config in "${(@s:,:)RUNNING_COMPOSE[$project]}"; do
      [[ "${config:A}" == "${expected:A}" ]] && { print running; return; }
    done
    print "elsewhere:${RUNNING_COMPOSE[$project]}"
  elif [[ -n "$container" && -n "${RUNNING_CONTAINERS[$container]-}" ]]; then
    print running
  else
    print stopped
  fi
}

cmd_deploy() {
  local stack dirty runtime updater update_status
  local -a to_update=() updated=()
  local -A copy_notes=()
  require_tools git jq docker
  [[ -d "$DEPLOY_ROOT" && ! -L "$DEPLOY_ROOT" ]] ||
    die "deployed copy not found (or is a symlink): $DEPLOY_ROOT"

  dirty="$(git -C "$REPO_ROOT" status --porcelain --untracked-files=no -- docker)"
  if [[ -n "$dirty" ]]; then
    print -ru2 -- "$dirty"
    die "docker/ has uncommitted changes; commit them before deploying"
  fi
  load_inventory
  snapshot_running

  log "Copying shared docker/ files"
  COPY_NOTE=
  STEP_FAILURE=
  if deploy_files ""; then
    record "(shared)" "$([[ $DRY_RUN == true ]] && print planned || print ok)" "$COPY_NOTE"
  else
    record "(shared)" FAILED "$STEP_FAILURE"
  fi

  for stack in "${SELECTED[@]}"; do
    [[ -d "$DOCKER_SRC/$stack" ]] || continue
    if [[ -n "${STACK_SYNC_TOOL[$stack]-}" ]]; then
      if stack_diverged "$stack"; then
        record "$stack" "ACTION NEEDED" \
          "deployed copy differs from source; run ${STACK_SYNC_TOOL[$stack]}"
        continue
      fi
      copy_notes[$stack]="deployed copy matches source"
    else
      log "Copying $stack"
      COPY_NOTE=
      STEP_FAILURE=
      if ! deploy_files "$stack"; then
        record "$stack" FAILED "$STEP_FAILURE"
        continue
      fi
      copy_notes[$stack]="$COPY_NOTE"
    fi

    runtime="$(stack_runtime "$stack")"
    if [[ -z "${STACK_UPDATER[$stack]-}" ]]; then
      if [[ -z "${STACK_COMPOSE_PROJECT[$stack]-}${STACK_CONTAINER[$stack]-}" ]]; then
        record "$stack" "$([[ $DRY_RUN == true ]] && print planned || print ok)" \
          "${copy_notes[$stack]}; no container runtime"
      elif [[ "$runtime" == stopped ]]; then
        record "$stack" "$([[ $DRY_RUN == true ]] && print planned || print ok)" \
          "${copy_notes[$stack]}; not running"
      else
        record "$stack" "ACTION NEEDED" "${copy_notes[$stack]}; running but has no update.sh; update it manually"
      fi
    elif [[ "$runtime" == stopped ]]; then
      record "$stack" "$([[ $DRY_RUN == true ]] && print planned || print ok)" \
        "${copy_notes[$stack]}; not running, left stopped"
    elif [[ "$runtime" == elsewhere:* ]]; then
      record "$stack" "ACTION NEEDED" \
        "${copy_notes[$stack]}; running from ${runtime#elsewhere:}, not $DEPLOY_ROOT"
    else
      to_update+=("$stack")
    fi
  done

  for stack in "${to_update[@]}"; do
    updater="$DEPLOY_ROOT/${STACK_UPDATER[$stack]}"
    if [[ "$DRY_RUN" == true ]]; then
      log "Would run $updater"
      record "$stack" planned "${copy_notes[$stack]}; would run update.sh"
      continue
    fi
    if [[ ! -f "$updater" || ! -x "$updater" ]]; then
      record "$stack" FAILED "${copy_notes[$stack]}; $updater is missing or not executable"
      continue
    fi
    log "Updating $stack: $updater"
    update_status=0
    "$updater" || update_status=$?
    if (( update_status != 0 )); then
      record "$stack" FAILED \
        "${copy_notes[$stack]}; update.sh exited $update_status${BACKUP_DIR:+; backups in $BACKUP_DIR}"
      continue
    fi
    updated+=("$stack")
  done

  # Confirm every successfully updated stack came back from the deployed copy.
  if (( ${#updated} )); then
    snapshot_running
    for stack in "${updated[@]}"; do
      if [[ "$(stack_runtime "$stack")" == running ]]; then
        record "$stack" ok "${copy_notes[$stack]}; rebuilt by update.sh"
      else
        record "$stack" FAILED \
          "${copy_notes[$stack]}; not running after update${BACKUP_DIR:+; backups in $BACKUP_DIR}"
      fi
    done
  fi

  print_summary
  [[ -z "$BACKUP_DIR" ]] || log "Backups of replaced files: $BACKUP_DIR"
  if [[ -n "$BACKUP_DIR" && "$DRY_RUN" != true ]] && (( PROBLEMS == 0 )); then
    prune_docker_backups
  fi
  if [[ "$DRY_RUN" != true ]]; then
    log "Rescan dependencies in Git Fleet to confirm the refreshed versions."
  fi
  (( PROBLEMS == 0 ))
}

parse_args "$@"
case "$COMMAND" in
  refresh) cmd_refresh ;;
  deploy) cmd_deploy ;;
esac
