#!/bin/zsh

set -eu
set -o pipefail
setopt NO_NOMATCH
setopt EXTENDED_GLOB

PATH="/usr/bin:/bin:/usr/sbin:/sbin"

SCRIPT_NAME="moneydance_rotate_backups"
DEFAULT_CONFIG_PATH="${XDG_CONFIG_HOME:-${HOME}/.config}/moneydance-backup-rotation/config"

# Safe defaults. NAS details and the backup directory are deliberately absent.
NAS_SERVER=""
NAS_SHARE_NAME=""
REQUIRED_NAS_SHARES=""
BACKUP_DIRECTORY_NAME=""
BACKUP_FILENAME_SUFFIX=""
MAX_DAYS_TO_KEEP=4
DRY_RUN=1
REPAIR_CONFIG=0
LOG_FILE=""
USE_SYSLOG=0

typeset -a required_nas_shares=()
integer nas_server_assignment_count=0
typeset -A mount_points_by_key=()
typeset -A mount_counts_by_key=()
typeset -a mount_hosts=()
typeset -A seen_mount_hosts=()
typeset -a replacement_hosts=()
typeset -A replacement_backup_dirs=()
typeset -A replacement_resolved_backup_dirs=()
validated_backup_dir=""
resolved_validated_backup_dir=""

MOUNT_BIN="${MONEYDANCE_MOUNT_BIN:-/sbin/mount}"
STAT_BIN="${MONEYDANCE_STAT_BIN:-/usr/bin/stat}"
FIND_BIN="${MONEYDANCE_FIND_BIN:-/usr/bin/find}"
DATE_BIN="${MONEYDANCE_DATE_BIN:-/bin/date}"
RM_BIN="${MONEYDANCE_RM_BIN:-/bin/rm}"
LOGGER_BIN="${MONEYDANCE_LOGGER_BIN:-/usr/bin/logger}"
DIRNAME_BIN="${MONEYDANCE_DIRNAME_BIN:-/usr/bin/dirname}"
MKDIR_BIN="${MONEYDANCE_MKDIR_BIN:-/bin/mkdir}"
MKTEMP_BIN="${MONEYDANCE_MKTEMP_BIN:-/usr/bin/mktemp}"
MV_BIN="${MONEYDANCE_MV_BIN:-/bin/mv}"
CHMOD_BIN="${MONEYDANCE_CHMOD_BIN:-/bin/chmod}"
CMP_BIN="${MONEYDANCE_CMP_BIN:-/usr/bin/cmp}"
OD_BIN="${MONEYDANCE_OD_BIN:-/usr/bin/od}"
GREP_BIN="${MONEYDANCE_GREP_BIN:-/usr/bin/grep}"
ACL_BIN="${MONEYDANCE_ACL_BIN:-/bin/ls}"

show_help() {
  cat <<'EOF'
Usage: moneydance_rotate_backups.sh [--config PATH] [--dry-run] [--repair-config]

Prune backup files older than the newest configured number of backup days.

Options:
  --config PATH  Read settings from PATH instead of the default local config.
  --dry-run      Report the number of files that would be removed; delete none.
  --repair-config  Interactively replace NAS_SERVER with one validated host.
  -h, --help     Show this help and exit without inspecting mounts or files.

Default config:
  $XDG_CONFIG_HOME/moneydance-backup-rotation/config
  or $HOME/.config/moneydance-backup-rotation/config

REQUIRED_NAS_SHARES must be a comma-delimited list of exact SMB share names
and must contain NAS_SHARE_NAME exactly once.

NAS settings may instead be supplied with MONEYDANCE_NAS_SERVER,
MONEYDANCE_NAS_SHARE_NAME, MONEYDANCE_REQUIRED_NAS_SHARES,
MONEYDANCE_BACKUP_DIRECTORY_NAME, and MONEYDANCE_BACKUP_FILENAME_SUFFIX. No
legacy configuration is discovered or migrated automatically.
EOF
}

log_message() {
  local level="$1"
  shift
  local message="$*"
  local timestamp
  timestamp="$(${DATE_BIN} -u "+%Y-%m-%dT%H:%M:%SZ")"
  local formatted="${timestamp} ${SCRIPT_NAME}[$$] [${level}] ${message}"

  printf '%s\n' "${formatted}"

  if [[ -n "${LOG_FILE}" ]]; then
    local log_dir
    if { log_dir="$("${DIRNAME_BIN}" "${LOG_FILE}")"; } 2>/dev/null; then
      :
    else
      printf '%s\n' "${SCRIPT_NAME}: ERROR: Unable to initialize private logging." >&2
      exit 1
    fi
    if [[ ! -d "${log_dir}" ]]; then
      if ! "${MKDIR_BIN}" -p "${log_dir}" 2>/dev/null; then
        printf '%s\n' "${SCRIPT_NAME}: ERROR: Unable to initialize private logging." >&2
        exit 1
      fi
    fi
    if ! { printf '%s\n' "${formatted}" >> "${LOG_FILE}"; } 2>/dev/null; then
      printf '%s\n' "${SCRIPT_NAME}: ERROR: Unable to write private logging." >&2
      exit 1
    fi
  fi

  if [[ "${USE_SYSLOG}" -eq 1 && -x "${LOGGER_BIN}" ]]; then
    "${LOGGER_BIN}" -t "${SCRIPT_NAME}" "${message}" >/dev/null 2>&1 || true
  fi
}

terminal_detail() {
  [[ -t 1 ]] || return 0
  printf '%s\n' "$*"
}

exit_with_error() {
  log_message "ERROR" "$*"
  exit 1
}

config_error() {
  printf '%s\n' "${SCRIPT_NAME}: ERROR: $*" >&2
  exit 2
}

trim_config_value() {
  local value="$1"
  value="${value##[[:space:]]#}"
  value="${value%%[[:space:]]#}"
  printf '%s' "${value}"
}

load_config() {
  local config_path="$1"
  local raw_line line key value
  integer config_fd
  integer config_stderr_fd
  integer config_open_failed=0
  integer line_number=0

  [[ -f "${config_path}" && -r "${config_path}" ]] || config_error "Configuration file is not readable."
  if [[ -n "${repair_snapshot_tmp:-}" && "${config_path}" == "${repair_snapshot_tmp}" ]]; then
    validated_repair_temp "${repair_snapshot_tmp}" snapshot 600 || config_error "Configuration snapshot changed unexpectedly."
    revalidate_config_directory || config_error "Configuration directory changed unexpectedly."
  fi
  exec {config_stderr_fd}>&2
  exec 2>/dev/null
  if exec {config_fd}<"${config_path}"; then
    :
  else
    config_open_failed=1
  fi
  exec 2>&${config_stderr_fd}
  exec {config_stderr_fd}>&-
  (( ! config_open_failed )) || config_error "Configuration file could not be opened safely."

  while IFS= read -r raw_line || [[ -n "${raw_line}" ]]; do
    (( line_number += 1 ))
    line="$(trim_config_value "${raw_line}")"
    [[ -z "${line}" || "${line}" == \#* ]] && continue
    [[ "${line}" == *"="* ]] || config_error "Invalid configuration syntax on line ${line_number}."
    key="$(trim_config_value "${line%%=*}")"
    value="$(trim_config_value "${line#*=}")"

    case "${key}" in
      NAS_SERVER)
        NAS_SERVER="${value}"
        (( nas_server_assignment_count += 1 ))
        ;;
      NAS_SHARE_NAME) NAS_SHARE_NAME="${value}" ;;
      REQUIRED_NAS_SHARES) REQUIRED_NAS_SHARES="${value}" ;;
      BACKUP_DIRECTORY_NAME) BACKUP_DIRECTORY_NAME="${value}" ;;
      BACKUP_FILENAME_SUFFIX) BACKUP_FILENAME_SUFFIX="${value}" ;;
      MAX_DAYS_TO_KEEP) MAX_DAYS_TO_KEEP="${value}" ;;
      DRY_RUN) DRY_RUN="${value}" ;;
      LOG_FILE) LOG_FILE="${value}" ;;
      USE_SYSLOG) USE_SYSLOG="${value}" ;;
      *) config_error "Unknown configuration key on line ${line_number}." ;;
    esac
  done <&${config_fd}
  exec {config_fd}<&-
}

validate_required_nas_shares() {
  local raw_share share
  typeset -a configured_required_shares=("${(@s:,:)REQUIRED_NAS_SHARES}")
  typeset -A seen_required_nas_shares=()
  integer primary_share_count=0

  required_nas_shares=()
  for raw_share in "${configured_required_shares[@]}"; do
    share="$(trim_config_value "${raw_share}")"
    [[ -n "${share}" ]] || config_error "REQUIRED_NAS_SHARES contains an empty item."
    [[ "${share}" != *[^A-Za-z0-9._\ -]* ]] || config_error "REQUIRED_NAS_SHARES contains unsupported characters."
    [[ -z "${seen_required_nas_shares[${share}]:-}" ]] || config_error "REQUIRED_NAS_SHARES contains a duplicate item."

    seen_required_nas_shares[${share}]=1
    required_nas_shares+=("${share}")
    [[ "${share}" != "${NAS_SHARE_NAME}" ]] || (( primary_share_count += 1 ))
  done

  (( primary_share_count == 1 )) || config_error "REQUIRED_NAS_SHARES must contain NAS_SHARE_NAME exactly once."
  REQUIRED_NAS_SHARES="${(j:,:)required_nas_shares}"
}

validate_config() {
  if [[ -z "${NAS_SERVER}" || -z "${NAS_SHARE_NAME}" || -z "${REQUIRED_NAS_SHARES}" || -z "${BACKUP_DIRECTORY_NAME}" || -z "${BACKUP_FILENAME_SUFFIX}" ]]; then
    config_error "Configuration is required. Set the NAS host, primary share, required share list, backup directory, and eligible backup filename suffix in a local config file or MONEYDANCE_* environment variables. No cleanup was attempted."
  fi

  [[ "${NAS_SERVER}" != *[^A-Za-z0-9._-]* ]] || config_error "NAS_SERVER contains unsupported characters."
  [[ "${NAS_SHARE_NAME}" != *[^A-Za-z0-9._\ -]* ]] || config_error "NAS_SHARE_NAME contains unsupported characters."
  validate_required_nas_shares
  [[ "${BACKUP_DIRECTORY_NAME}" != *[^A-Za-z0-9._\ -]* ]] || config_error "BACKUP_DIRECTORY_NAME must be one relative directory name."
  [[ "${BACKUP_DIRECTORY_NAME}" != "." && "${BACKUP_DIRECTORY_NAME}" != ".." ]] || config_error "BACKUP_DIRECTORY_NAME must name a child directory."
  [[ "${BACKUP_FILENAME_SUFFIX}" == .* && "${BACKUP_FILENAME_SUFFIX}" != "." ]] || config_error "BACKUP_FILENAME_SUFFIX must be a nonempty filename extension beginning with a period."
  [[ "${BACKUP_FILENAME_SUFFIX}" != *[^A-Za-z0-9._-]* ]] || config_error "BACKUP_FILENAME_SUFFIX contains unsupported characters."
  [[ "${MAX_DAYS_TO_KEEP}" == <-> && "${MAX_DAYS_TO_KEEP}" -ge 1 ]] || config_error "MAX_DAYS_TO_KEEP must be a positive integer."
  [[ "${DRY_RUN}" == 0 || "${DRY_RUN}" == 1 ]] || config_error "DRY_RUN must be 0 or 1."
  [[ "${USE_SYSLOG}" == 0 || "${USE_SYSLOG}" == 1 ]] || config_error "USE_SYSLOG must be 0 or 1."
  [[ -z "${LOG_FILE}" || "${LOG_FILE}" == /* ]] || config_error "LOG_FILE must be empty or an absolute path."
}

apply_environment_overrides() {
  [[ -n "${MONEYDANCE_NAS_SERVER:-}" ]] && NAS_SERVER="${MONEYDANCE_NAS_SERVER}"
  [[ -n "${MONEYDANCE_NAS_SHARE_NAME:-}" ]] && NAS_SHARE_NAME="${MONEYDANCE_NAS_SHARE_NAME}"
  [[ -n "${MONEYDANCE_REQUIRED_NAS_SHARES:-}" ]] && REQUIRED_NAS_SHARES="${MONEYDANCE_REQUIRED_NAS_SHARES}"
  [[ -n "${MONEYDANCE_BACKUP_DIRECTORY_NAME:-}" ]] && BACKUP_DIRECTORY_NAME="${MONEYDANCE_BACKUP_DIRECTORY_NAME}"
  [[ -n "${MONEYDANCE_BACKUP_FILENAME_SUFFIX:-}" ]] && BACKUP_FILENAME_SUFFIX="${MONEYDANCE_BACKUP_FILENAME_SUFFIX}"
  [[ -n "${MONEYDANCE_MAX_DAYS_TO_KEEP:-}" ]] && MAX_DAYS_TO_KEEP="${MONEYDANCE_MAX_DAYS_TO_KEEP}"
  [[ -n "${MONEYDANCE_DRY_RUN:-}" ]] && DRY_RUN="${MONEYDANCE_DRY_RUN}"
  [[ -n "${MONEYDANCE_LOG_FILE:-}" ]] && LOG_FILE="${MONEYDANCE_LOG_FILE}"
  [[ -n "${MONEYDANCE_USE_SYSLOG:-}" ]] && USE_SYSLOG="${MONEYDANCE_USE_SYSLOG}"
  return 0
}

parse_mount_inventory() {
  local mount_output="$1"
  local line mount_source mount_details mount_point mount_options mount_type
  local source_authority_and_share source_authority source_host source_share key

  mount_points_by_key=()
  mount_counts_by_key=()
  mount_hosts=()
  seen_mount_hosts=()

  while IFS= read -r line; do
    [[ "${line}" == //*" on "*" ("*")" ]] || continue

    mount_source="${line%% on *}"
    mount_details="${line#* on }"
    [[ "${mount_source}" == //*/* && "${mount_details}" == *" ("*")" ]] || continue

    mount_point="${mount_details% \(*}"
    mount_options="${mount_details##* \(}"
    mount_options="${mount_options%\)}"
    [[ -n "${mount_point}" && "${mount_options}" != "${mount_details}" ]] || continue

    mount_type="$(trim_config_value "${mount_options%%,*}")"
    [[ "${mount_type}" == "smbfs" ]] || continue

    source_authority_and_share="${mount_source#//}"
    source_authority="${source_authority_and_share%%/*}"
    source_share="${source_authority_and_share#*/}"
    if [[ "${source_authority}" == *@* ]]; then
      [[ "${source_authority}" != @* && "${source_authority}" != *@ && "${source_authority}" != *@*@* ]] || continue
      source_host="${source_authority#*@}"
    else
      source_host="${source_authority}"
    fi
    [[ -n "${source_authority}" && -n "${source_host}" && -n "${source_share}" ]] || continue
    [[ "${source_share}" != */* && "${source_host}" != *\|* && "${source_share}" != *\|* ]] || continue

    # Decode only the literal escape emitted by macOS mount for spaces.
    source_share="${source_share//\\040/ }"
    mount_point="${mount_point//\\040/ }"
    key="${source_host}|${source_share}"

    if [[ -z "${seen_mount_hosts[${source_host}]:-}" ]]; then
      seen_mount_hosts[${source_host}]=1
      mount_hosts+=("${source_host}")
    fi
    mount_points_by_key[${key}]="${mount_points_by_key[${key}]:-}${mount_point}"$'\n'
    mount_counts_by_key[${key}]=$(( ${mount_counts_by_key[${key}]:-0} + 1 ))
  done <<< "${mount_output}"
}

host_has_required_shares() {
  local host="$1"
  local share key

  for share in "${required_nas_shares[@]}"; do
    key="${host}|${share}"
    (( ${mount_counts_by_key[${key}]:-0} == 1 )) || return 1
  done
  return 0
}

validate_backup_directory_for_host() {
  local host="$1"
  local key="${host}|${NAS_SHARE_NAME}"
  local mount_point backup_dir resolved_mount_point resolved_backup_dir

  validated_backup_dir=""
  resolved_validated_backup_dir=""
  (( ${mount_counts_by_key[${key}]:-0} == 1 )) || return 1

  mount_point="${mount_points_by_key[${key}]:-}"
  mount_point="${mount_point%$'\n'}"
  [[ -n "${mount_point}" && -d "${mount_point}" ]] || return 1

  backup_dir="${mount_point%/}/${BACKUP_DIRECTORY_NAME}"
  [[ -d "${backup_dir}" && ! -L "${backup_dir}" && -r "${backup_dir}" && -x "${backup_dir}" ]] || return 1

  resolved_mount_point="${mount_point:A}"
  resolved_backup_dir="${backup_dir:A}"
  [[ "${resolved_backup_dir}" == "${resolved_mount_point%/}/"* ]] || return 1

  validated_backup_dir="${backup_dir}"
  resolved_validated_backup_dir="${resolved_backup_dir}"
  return 0
}

discover_replacement_candidates() {
  local host

  replacement_hosts=()
  replacement_backup_dirs=()
  replacement_resolved_backup_dirs=()
  for host in "${mount_hosts[@]}"; do
    [[ "${host}" != "${NAS_SERVER}" ]] || continue
    [[ "${host}" != *[^A-Za-z0-9._-]* ]] || continue
    host_has_required_shares "${host}" || continue
    validate_backup_directory_for_host "${host}" || continue

    replacement_hosts+=("${host}")
    replacement_backup_dirs[${host}]="${validated_backup_dir}"
    replacement_resolved_backup_dirs[${host}]="${resolved_validated_backup_dir}"
  done
}

repair_snapshot_tmp=""
repair_candidate_tmp=""
repair_lock_dir=""
repair_lock_owned=0
repair_lock_pid=""
repair_lock_device=""
repair_lock_inode=""
repair_lock_owner=""
repair_lock_marker_device=""
repair_lock_marker_inode=""
repair_lock_marker_owner=""
repair_snapshot_device=""
repair_snapshot_inode=""
repair_snapshot_owner=""
repair_candidate_device=""
repair_candidate_inode=""
repair_candidate_owner=""
config_device=""
config_inode=""
config_owner=""
config_group=""
config_mode=""
config_size=""
config_dir_path=""
config_dir_device=""
config_dir_inode=""
config_dir_owner=""
config_dir_mode=""
inspected_config_dir_path=""
inspected_config_dir_device=""
inspected_config_dir_inode=""
inspected_config_dir_owner=""
inspected_config_dir_mode=""

cleanup_repair_artifacts() {
  local cleanup_path
  local role expected_device expected_inode expected_owner cleanup_metadata cleanup_device cleanup_inode cleanup_owner cleanup_group cleanup_mode cleanup_size cleanup_links
  for role in candidate snapshot; do
    if [[ "${role}" == candidate ]]; then
      cleanup_path="${repair_candidate_tmp:-}"
      expected_device="${repair_candidate_device:-}"
      expected_inode="${repair_candidate_inode:-}"
      expected_owner="${repair_candidate_owner:-}"
    else
      cleanup_path="${repair_snapshot_tmp:-}"
      expected_device="${repair_snapshot_device:-}"
      expected_inode="${repair_snapshot_inode:-}"
      expected_owner="${repair_snapshot_owner:-}"
    fi
    [[ -n "${cleanup_path}" ]] || continue
    cleanup_metadata="$("${STAT_BIN}" -f '%d|%i|%u|%g|%Lp|%z|%l' -- "${cleanup_path}" 2>/dev/null)" || continue
    IFS='|' read -r cleanup_device cleanup_inode cleanup_owner cleanup_group cleanup_mode cleanup_size cleanup_links <<< "${cleanup_metadata}"
    if [[ -f "${cleanup_path}" && ! -L "${cleanup_path}" && "${cleanup_device}" == "${expected_device}" && "${cleanup_inode}" == "${expected_inode}" && "${cleanup_owner}" == "${expected_owner}" && "${cleanup_owner}" == "${EUID}" && "${cleanup_links}" == 1 ]]; then
      /bin/rm -f -- "${cleanup_path}" 2>/dev/null || true
    fi
  done
  if (( ${repair_lock_owned:-0} )) && [[ "${repair_lock_pid:-}" == "$$" && -d "${repair_lock_dir}" && ! -L "${repair_lock_dir}" ]]; then
    cleanup_metadata="$("${STAT_BIN}" -f '%d|%i|%u|%g|%Lp|%z|%l' -- "${repair_lock_dir}" 2>/dev/null)" || return 0
    IFS='|' read -r cleanup_device cleanup_inode cleanup_owner cleanup_group cleanup_mode cleanup_size cleanup_links <<< "${cleanup_metadata}"
    [[ "${cleanup_device}" == "${repair_lock_device}" && "${cleanup_inode}" == "${repair_lock_inode}" && "${cleanup_owner}" == "${repair_lock_owner}" && "${cleanup_owner}" == "${EUID}" ]] || return 0
    local marker_path="${repair_lock_dir}/owner"
    if [[ -n "${repair_lock_marker_inode:-}" ]]; then
      cleanup_metadata="$("${STAT_BIN}" -f '%d|%i|%u|%g|%Lp|%z|%l' -- "${marker_path}" 2>/dev/null)" || return 0
      IFS='|' read -r cleanup_device cleanup_inode cleanup_owner cleanup_group cleanup_mode cleanup_size cleanup_links <<< "${cleanup_metadata}"
      [[ -f "${marker_path}" && ! -L "${marker_path}" && "${cleanup_device}" == "${repair_lock_marker_device}" && "${cleanup_inode}" == "${repair_lock_marker_inode}" && "${cleanup_owner}" == "${repair_lock_marker_owner}" && "${cleanup_owner}" == "${EUID}" && "${cleanup_mode}" == 600 && "${cleanup_links}" == 1 ]] || return 0
      /bin/rm -f -- "${marker_path}" 2>/dev/null || true
    elif [[ -e "${marker_path}" || -L "${marker_path}" ]]; then
      return 0
    fi
    /bin/rmdir -- "${repair_lock_dir}" 2>/dev/null || true
  fi
}

inspect_path_acl() {
  local path="$1"
  local acl_policy="${2:-deny-only}"
  local acl_output acl_line acl_line_trimmed acl_entry_index acl_header_prefix acl_mode_field acl_marker=""
  local acl_header_pattern='^[d-][r-][w-][xSs-][r-][w-][xSs-][r-][w-][xTt-][@+]?[[:space:]]+[0-9]+[[:space:]]+[^[:space:]]+[[:space:]]+[^[:space:]]+[[:space:]]+[0-9]+[[:space:]]+[^[:space:]]+[[:space:]]+[^[:space:]]+[[:space:]]+[^[:space:]]+[[:space:]]+'
  integer acl_index expected_acl_index acl_entry_count
  typeset -a acl_lines=()

  if ! acl_output="$("${ACL_BIN}" -lde -- "${path}" 2>/dev/null)"; then
    return 2
  fi
  acl_lines=("${(@f)acl_output}")
  (( ${#acl_lines[@]} >= 1 )) || return 1
  # The first ls line contains the pathname and is deliberately never parsed
  # as an ACE. Subsequent lines must be indexed macOS ACL entries.
  if [[ "${acl_lines[1]}" =~ "${acl_header_pattern}" ]]; then
    acl_header_prefix="${MATCH}"
  else
    return 1
  fi
  (( ${#acl_lines[1]} > ${#acl_header_prefix} )) || return 1
  if [[ -d "${path}" && ! -L "${path}" ]]; then
    [[ "${acl_header_prefix}" == d* ]] || return 1
  elif [[ -f "${path}" && ! -L "${path}" ]]; then
    [[ "${acl_header_prefix}" == -* ]] || return 1
  else
    return 1
  fi
  acl_mode_field="${acl_header_prefix%%[[:space:]]*}"
  if (( ${#acl_mode_field} == 11 )); then
    acl_marker="${acl_mode_field[11]}"
  elif (( ${#acl_mode_field} != 10 )); then
    return 1
  fi
  acl_entry_count=$(( ${#acl_lines[@]} - 1 ))
  if [[ "${acl_policy}" == no-acl ]]; then
    [[ "${acl_marker}" != + ]] || return 1
    (( acl_entry_count == 0 )) || return 1
    return 0
  fi
  [[ "${acl_policy}" == deny-only ]] || return 1
  # BSD ls uses '+' for ACLs unless '@' takes the marker position for extended
  # attributes; '@' can therefore coexist with zero or more printed ACEs.
  if [[ "${acl_marker}" == + ]]; then
    (( acl_entry_count >= 1 )) || return 1
  elif [[ -z "${acl_marker}" ]]; then
    (( acl_entry_count == 0 )) || return 1
  elif [[ "${acl_marker}" != @ ]]; then
    return 1
  fi
  for (( acl_index = 2; acl_index <= ${#acl_lines[@]}; acl_index += 1 )); do
    acl_line="${acl_lines[${acl_index}]}"
    acl_line_trimmed="${acl_line##[[:space:]]#}"
    acl_entry_index="${acl_line_trimmed%%:*}"
    expected_acl_index=$(( acl_index - 2 ))
    [[ "${acl_entry_index}" == "${expected_acl_index}" ]] || return 1
    if [[ ! "${acl_line}" =~ '^[[:space:]]*[0-9]+:[[:space:]]+(user|group):[^[:space:]]+([[:space:]]+[A-Za-z_]+)*[[:space:]]+(allow|deny)[[:space:]]+[A-Za-z_,]+$' ]]; then
      return 1
    fi
    [[ "${acl_line}" != *[[:space:]]allow[[:space:]]* ]] || return 1
    [[ "${acl_line}" == *[[:space:]]deny[[:space:]]* ]] || return 1
  done
  return 0
}

inspect_safe_config_directory() {
  local requested_dir="${config_path:h}"
  local lexical_dir="${requested_dir:a}"
  local resolved_dir="${requested_dir:A}"
  local current_dir metadata device inode owner mode direct_device direct_inode direct_owner direct_mode
  integer acl_status

  [[ "${lexical_dir}" == "${resolved_dir}" ]] || return 1
  current_dir="${lexical_dir}"
  while true; do
    [[ -d "${current_dir}" && ! -L "${current_dir}" ]] || return 1
    if ! metadata="$("${STAT_BIN}" -f '%d|%i|%u|%Lp' -- "${current_dir}" 2>/dev/null)"; then
      return 1
    fi
    IFS='|' read -r device inode owner mode <<< "${metadata}"
    if [[ -z "${device}" || -z "${inode}" || -z "${owner}" || "${mode}" != <-> ]]; then
      return 1
    fi
    if [[ "${owner}" != "${EUID}" && "${owner}" != 0 ]] || (( (8#${mode} & 8#22) != 0 )); then
      return 1
    fi
    if inspect_path_acl "${current_dir}"; then
      :
    else
      acl_status=$?
      return "${acl_status}"
    fi
    if [[ "${current_dir}" == "${lexical_dir}" ]]; then
      direct_device="${device}"
      direct_inode="${inode}"
      direct_owner="${owner}"
      direct_mode="${mode}"
    fi
    [[ "${current_dir}" == / ]] && break
    current_dir="${current_dir:h}"
  done

  inspected_config_dir_path="${lexical_dir}"
  inspected_config_dir_device="${direct_device}"
  inspected_config_dir_inode="${direct_inode}"
  inspected_config_dir_owner="${direct_owner}"
  inspected_config_dir_mode="${direct_mode}"
  return 0
}

capture_safe_config_directory() {
  if inspect_safe_config_directory; then
    :
  else
    return $?
  fi
  config_dir_path="${inspected_config_dir_path}"
  config_dir_device="${inspected_config_dir_device}"
  config_dir_inode="${inspected_config_dir_inode}"
  config_dir_owner="${inspected_config_dir_owner}"
  config_dir_mode="${inspected_config_dir_mode}"
  config_path="${config_dir_path}/${config_path:t}"
  return 0
}

revalidate_config_directory() {
  inspect_safe_config_directory || return 1
  if [[ "${inspected_config_dir_path}" != "${config_dir_path}" ||
        "${inspected_config_dir_device}" != "${config_dir_device}" ||
        "${inspected_config_dir_inode}" != "${config_dir_inode}" ||
        "${inspected_config_dir_owner}" != "${config_dir_owner}" ||
        "${inspected_config_dir_mode}" != "${config_dir_mode}" ]]; then
    return 1
  fi
  return 0
}

repair_failure() {
  log_message "ERROR" "$1"
  exit 1
}

read_config_metadata() {
  local path="$1"
  local metadata
  if ! metadata="$("${STAT_BIN}" -f '%d|%i|%u|%g|%Lp|%z|%l' -- "${path}" 2>/dev/null)"; then
    return 1
  fi
  IFS='|' read -r config_device config_inode config_owner config_group config_mode config_size config_links <<< "${metadata}"
  [[ -n "${config_device}" && -n "${config_inode}" && -n "${config_owner}" && -n "${config_group}" && -n "${config_mode}" && -n "${config_size}" && "${config_links}" == 1 ]]
}

validate_repair_preconditions() {
  integer acl_status directory_status
  (( ! cli_dry_run )) || config_error "--repair-config cannot be combined with --dry-run."
  [[ -t 0 && -t 1 ]] || config_error "--repair-config requires an interactive terminal on stdin and stdout."
  (( ! ${+MONEYDANCE_NAS_SERVER} )) || config_error "--repair-config cannot be used while MONEYDANCE_NAS_SERVER is set."
  [[ -e "${config_path}" && ! -L "${config_path}" && -f "${config_path}" && -r "${config_path}" && -w "${config_path}" ]] || config_error "The repair configuration must be a readable and writable regular file."
  for required_bin in "${MOUNT_BIN}" "${STAT_BIN}" "${DATE_BIN}" "${MKTEMP_BIN}" "${MV_BIN}" "${CHMOD_BIN}" "${CMP_BIN}" "${OD_BIN}" "${GREP_BIN}" "${ACL_BIN}"; do
    command -v "${required_bin}" >/dev/null 2>&1 || exit_with_error "A required config-repair command is unavailable; no configuration or backup files were changed."
  done
  if capture_safe_config_directory; then
    :
  else
    directory_status=$?
    (( directory_status != 2 )) || exit_with_error "The repair configuration directory could not be inspected safely. No configuration or backup files were changed."
    config_error "The repair configuration directory is not private and stable."
  fi
  read_config_metadata "${config_path}" || config_error "The repair configuration metadata could not be validated."
  [[ "${config_owner}" == "${EUID}" ]] || config_error "The repair configuration must be owned by the invoking user."
  if inspect_path_acl "${config_path}" no-acl; then
    :
  else
    acl_status=$?
    (( acl_status != 2 )) || exit_with_error "The repair configuration ACL could not be inspected safely. No configuration or backup files were changed."
    config_error "The repair configuration ACL is not private."
  fi
}

create_owned_config_temp() {
  local live_config="$1"
  local role="$2"
  local config_dir="${config_dir_path}"
  local config_base="${live_config:t}"
  local prefix="${config_dir}/.${config_base}.${role}."
  local returned returned_absolute existing
  typeset -A existed_before=()
  revalidate_config_directory || return 1
  typeset -a prefix_entries=("${prefix}"*(N))

  for existing in "${prefix_entries[@]}"; do
    existed_before[${existing:a}]=1
  done
  umask 077
  revalidate_config_directory || return 1
  if ! returned="$("${MKTEMP_BIN}" "${prefix}XXXXXX" 2>/dev/null)"; then
    return 1
  fi

  [[ "${returned}" == /* ]] || return 1
  returned_absolute="${returned:a}"
  [[ "${returned}" == "${returned_absolute}" ]] || return 1
  [[ "${returned_absolute:h}" == "${config_dir}" ]] || return 1
  [[ "${returned_absolute:t}" == ".${config_base}.${role}."* ]] || return 1
  [[ "${returned_absolute}" != "${live_config:a}" ]] || return 1
  (( ! ${+existed_before[${returned_absolute}]} )) || return 1
  [[ -f "${returned_absolute}" && ! -L "${returned_absolute}" ]] || return 1

  local temp_metadata temp_device temp_inode temp_owner temp_group temp_mode temp_size temp_links
  if ! temp_metadata="$("${STAT_BIN}" -f '%d|%i|%u|%g|%Lp|%z|%l' -- "${returned_absolute}" 2>/dev/null)"; then
    return 1
  fi
  IFS='|' read -r temp_device temp_inode temp_owner temp_group temp_mode temp_size temp_links <<< "${temp_metadata}"
  [[ "${temp_owner}" == "${EUID}" && "${temp_links}" == 1 ]] || return 1

  if [[ "${role}" == snapshot ]]; then
    repair_snapshot_tmp="${returned_absolute}"
    repair_snapshot_device="${temp_device}"
    repair_snapshot_inode="${temp_inode}"
    repair_snapshot_owner="${temp_owner}"
  else
    repair_candidate_tmp="${returned_absolute}"
    repair_candidate_device="${temp_device}"
    repair_candidate_inode="${temp_inode}"
    repair_candidate_owner="${temp_owner}"
  fi
  REPLY="${returned_absolute}"
}

acquire_repair_lock() {
  local config_dir="${config_dir_path}"
  local config_base="${config_path:t}"
  local candidate_lock="${config_dir}/.${config_base}.repair.lock"
  local lock_metadata lock_device lock_inode lock_owner lock_group lock_mode lock_size lock_links
  local marker_path marker_metadata marker_device marker_inode marker_owner marker_group marker_mode marker_size marker_links
  local current_lock_device current_lock_inode current_lock_owner current_lock_group current_lock_mode current_lock_size current_lock_links
  umask 077
  revalidate_config_directory || return 1
  if ! /bin/mkdir -- "${candidate_lock}" 2>/dev/null; then
    return 1
  fi
  [[ -d "${candidate_lock}" && ! -L "${candidate_lock}" ]] || return 1
  if ! lock_metadata="$("${STAT_BIN}" -f '%d|%i|%u|%g|%Lp|%z|%l' -- "${candidate_lock}" 2>/dev/null)"; then
    return 1
  fi
  IFS='|' read -r lock_device lock_inode lock_owner lock_group lock_mode lock_size lock_links <<< "${lock_metadata}"
  [[ "${lock_owner}" == "${EUID}" && "${lock_mode}" == 700 ]] || return 1
  repair_lock_dir="${candidate_lock}"
  repair_lock_device="${lock_device}"
  repair_lock_inode="${lock_inode}"
  repair_lock_owner="${lock_owner}"
  repair_lock_pid="$$"
  repair_lock_owned=1
  marker_path="${repair_lock_dir}/owner"
  revalidate_config_directory || return 1
  if ! write_lock_owner_marker "${marker_path}" "$$" 2>/dev/null; then
    return 1
  fi
  if ! marker_metadata="$("${STAT_BIN}" -f '%d|%i|%u|%g|%Lp|%z|%l' -- "${marker_path}" 2>/dev/null)"; then
    return 1
  fi
  IFS='|' read -r marker_device marker_inode marker_owner marker_group marker_mode marker_size marker_links <<< "${marker_metadata}"
  [[ -f "${marker_path}" && ! -L "${marker_path}" && "${marker_device}" == "${lock_device}" && "${marker_owner}" == "${EUID}" && "${marker_mode}" == 600 && "${marker_links}" == 1 && "${marker_size}" -gt 0 ]] || return 1
  repair_lock_marker_device="${marker_device}"
  repair_lock_marker_inode="${marker_inode}"
  repair_lock_marker_owner="${marker_owner}"
  if ! lock_metadata="$("${STAT_BIN}" -f '%d|%i|%u|%g|%Lp|%z|%l' -- "${candidate_lock}" 2>/dev/null)"; then
    return 1
  fi
  IFS='|' read -r current_lock_device current_lock_inode current_lock_owner current_lock_group current_lock_mode current_lock_size current_lock_links <<< "${lock_metadata}"
  [[ "${current_lock_device}" == "${lock_device}" && "${current_lock_inode}" == "${lock_inode}" && "${current_lock_owner}" == "${lock_owner}" && "${current_lock_mode}" == 700 ]] || return 1
}

write_lock_owner_marker() {
  local marker_path="$1"
  local owner_pid="$2"
  print -r -- "${owner_pid}" > "${marker_path}"
}

validated_repair_temp() {
  local path="$1"
  local role="$2"
  local expected_mode="${3:-}"
  local metadata device inode owner group mode size links expected_device expected_inode expected_owner
  revalidate_config_directory || return 1
  metadata="$("${STAT_BIN}" -f '%d|%i|%u|%g|%Lp|%z|%l' -- "${path}" 2>/dev/null)" || return 1
  IFS='|' read -r device inode owner group mode size links <<< "${metadata}"
  if [[ "${role}" == snapshot ]]; then
    expected_device="${repair_snapshot_device}"
    expected_inode="${repair_snapshot_inode}"
    expected_owner="${repair_snapshot_owner}"
  else
    expected_device="${repair_candidate_device}"
    expected_inode="${repair_candidate_inode}"
    expected_owner="${repair_candidate_owner}"
  fi
  if [[ ! -f "${path}" || -L "${path}" || "${device}" != "${expected_device}" || "${inode}" != "${expected_inode}" || "${owner}" != "${expected_owner}" || "${owner}" != "${EUID}" || "${links}" != 1 ]]; then
    return 1
  fi
  if [[ -n "${expected_mode}" && "${mode}" != "${expected_mode}" ]]; then
    return 1
  fi
  inspect_path_acl "${path}" no-acl || return 1
  return 0
}

snapshot_repair_config() {
  local before_metadata after_metadata
  typeset -a inspection_status=()
  before_metadata="${config_device}|${config_inode}|${config_owner}|${config_group}|${config_mode}|${config_size}"
  create_owned_config_temp "${config_path}" snapshot || return 1
  revalidate_config_directory || return 1
  if ! "${CHMOD_BIN}" 600 "${repair_snapshot_tmp}" 2>/dev/null; then
    return 1
  fi
  validated_repair_temp "${repair_snapshot_tmp}" snapshot 600 || return 1
  revalidate_config_directory || return 1
  inspect_path_acl "${config_path}" no-acl || return 1
  if ! /bin/cp -- "${config_path}" "${repair_snapshot_tmp}" 2>/dev/null; then
    return 1
  fi
  validated_repair_temp "${repair_snapshot_tmp}" snapshot 600 || return 1
  read_config_metadata "${config_path}" || return 1
  after_metadata="${config_device}|${config_inode}|${config_owner}|${config_group}|${config_mode}|${config_size}"
  [[ "${after_metadata}" == "${before_metadata}" ]] || return 1
  revalidate_config_directory || return 1
  "${CMP_BIN}" -s -- "${config_path}" "${repair_snapshot_tmp}" 2>/dev/null || return 1
  # zsh strings cannot safely represent NUL and other control bytes. Tabs and
  # line endings remain valid config formatting and are preserved byte-for-byte.
  revalidate_config_directory || return 1
  validated_repair_temp "${repair_snapshot_tmp}" snapshot 600 || return 1
  if "${OD_BIN}" -An -v -tu1 "${repair_snapshot_tmp}" 2>/dev/null |
      "${GREP_BIN}" -Eq '(^|[[:space:]])(0|[1-8]|1[124-9]|2[0-9]|3[01]|127)([[:space:]]|$)' 2>/dev/null; then
    inspection_status=("${pipestatus[@]}")
  else
    inspection_status=("${pipestatus[@]}")
  fi
  (( ${#inspection_status[@]} == 2 )) || return 1
  if [[ "${inspection_status[1]}" == 0 && "${inspection_status[2]}" == 0 ]]; then
    return 2
  fi
  [[ "${inspection_status[1]}" == 0 && "${inspection_status[2]}" == 1 ]] || return 1
  return 0
}

metadata_matches_snapshot() {
  local expected="$1"
  local current
  revalidate_config_directory || return 1
  read_config_metadata "${config_path}" || return 1
  inspect_path_acl "${config_path}" no-acl || return 1
  current="${config_device}|${config_inode}|${config_owner}|${config_group}|${config_mode}|${config_size}"
  [[ "${current}" == "${expected}" && ! -L "${config_path}" && -f "${config_path}" ]] || return 1
  validated_repair_temp "${repair_snapshot_tmp}" snapshot 600 || return 1
  revalidate_config_directory || return 1
  "${CMP_BIN}" -s -- "${config_path}" "${repair_snapshot_tmp}" 2>/dev/null
}

write_repair_candidate() {
  local replacement_host="$1"
  local raw_line body parsed_line key raw_value value_without_leading value_trimmed
  local prefix leading trailing line_ending
  integer had_newline leading_count trailing_count replacements=0 snapshot_fd snapshot_stderr_fd open_failed=0

  validated_repair_temp "${repair_snapshot_tmp}" snapshot 600 || return 1
  revalidate_config_directory || return 1
  exec {snapshot_stderr_fd}>&2
  exec 2>/dev/null
  if exec {snapshot_fd}<"${repair_snapshot_tmp}"; then
    :
  else
    open_failed=1
  fi
  exec 2>&${snapshot_stderr_fd}
  exec {snapshot_stderr_fd}>&-
  (( ! open_failed )) || return 1

  while true; do
    if IFS= read -r raw_line; then
      had_newline=1
    else
      had_newline=0
      [[ -n "${raw_line}" ]] || break
    fi

    line_ending=""
    body="${raw_line}"
    if [[ "${body}" == *$'\r' ]]; then
      body="${body%$'\r'}"
      line_ending=$'\r'
    fi
    parsed_line="$(trim_config_value "${body}")"
    if [[ -n "${parsed_line}" && "${parsed_line}" != \#* && "${parsed_line}" == *"="* ]]; then
      key="$(trim_config_value "${parsed_line%%=*}")"
      if [[ "${key}" == NAS_SERVER ]]; then
        prefix="${body%%=*}="
        raw_value="${body#*=}"
        value_without_leading="${raw_value##[[:space:]]#}"
        value_trimmed="${value_without_leading%%[[:space:]]#}"
        leading_count=$(( ${#raw_value} - ${#value_without_leading} ))
        trailing_count=$(( ${#value_without_leading} - ${#value_trimmed} ))
        leading=""
        trailing=""
        (( leading_count == 0 )) || leading="${raw_value[1,leading_count]}"
        (( trailing_count == 0 )) || trailing="${value_without_leading[$(( ${#value_without_leading} - trailing_count + 1 )),-1]}"
        raw_line="${prefix}${leading}${replacement_host}${trailing}${line_ending}"
        (( replacements += 1 ))
      fi
    fi

    print -rn -- "${raw_line}" || return 1
    (( ! had_newline )) || print -rn -- $'\n' || return 1
    (( had_newline )) || break
  done <&${snapshot_fd}
  exec {snapshot_fd}<&-
  (( replacements == 1 )) || return 1
  return 0
}

write_repair_candidate_to_path() {
  local replacement_host="$1"
  local output_path="$2"
  integer output_fd output_stderr_fd open_failed=0 write_status
  validated_repair_temp "${output_path}" candidate 600 || return 1
  revalidate_config_directory || return 1
  exec {output_stderr_fd}>&2
  exec 2>/dev/null
  if exec {output_fd}>"${output_path}"; then
    :
  else
    open_failed=1
  fi
  exec 2>&${output_stderr_fd}
  exec {output_stderr_fd}>&-
  (( ! open_failed )) || return 1
  if write_repair_candidate "${replacement_host}" >&${output_fd}; then
    write_status=0
  else
    write_status=$?
  fi
  exec {output_fd}>&-
  (( write_status == 0 )) || return "${write_status}"
  return 0
}

run_repair_config() {
  local snapshot_result expected_metadata replacement_host answer
  trap cleanup_repair_artifacts EXIT
  trap 'repair_signal_exit 130' INT
  trap 'repair_signal_exit 143' TERM
  acquire_repair_lock || repair_failure "Another config repair is already active, or the private repair lock could not be created. No configuration or backup files were changed."
  expected_metadata="${config_device}|${config_inode}|${config_owner}|${config_group}|${config_mode}|${config_size}"
  if snapshot_repair_config; then
    snapshot_result=0
  else
    snapshot_result=$?
  fi
  if (( snapshot_result == 2 )); then
    config_error "Binary configuration files cannot be repaired."
  elif (( snapshot_result != 0 )); then
    repair_failure "Unable to create a private configuration snapshot. No configuration or backup files were changed."
  fi

  validated_repair_temp "${repair_snapshot_tmp}" snapshot 600 || repair_failure "The private configuration snapshot changed unexpectedly. No configuration or backup files were changed."
  revalidate_config_directory || repair_failure "The configuration directory changed during repair. No configuration or backup files were changed."
  load_config "${repair_snapshot_tmp}"
  (( nas_server_assignment_count == 1 )) || config_error "The repair configuration must contain exactly one active NAS_SERVER assignment."
  apply_environment_overrides
  validate_config
  if [[ -n "${LOG_FILE}" ]]; then
    command -v "${DIRNAME_BIN}" >/dev/null 2>&1 || repair_failure "A private logging command is unavailable. No configuration or backup files were changed."
    command -v "${MKDIR_BIN}" >/dev/null 2>&1 || repair_failure "A private logging command is unavailable. No configuration or backup files were changed."
  fi

  mount_output=""
  if ! mount_output="$("${MOUNT_BIN}" 2>/dev/null)"; then
    repair_failure "Unable to read the mount table. No configuration or backup files were changed."
  fi
  parse_mount_inventory "${mount_output}"
  unset mount_output

  if host_has_required_shares "${NAS_SERVER}" && validate_backup_directory_for_host "${NAS_SERVER}"; then
    ( log_message "INFO" "The configured NAS is valid; no repair is needed." ) >/dev/null 2>&1 || true
    terminal_detail "Configuration: ${config_path}"
    terminal_detail "Configured NAS: ${NAS_SERVER}"
    terminal_detail "No repair is needed; no configuration or backup files were changed."
    exit 0
  fi

  discover_replacement_candidates
  if (( ${#replacement_hosts[@]} != 1 )); then
    repair_failure "Config repair requires exactly one validated replacement candidate. No configuration or backup files were changed."
  fi
  replacement_host="${replacement_hosts[1]}"
  terminal_detail "Configuration: ${config_path}"
  terminal_detail "Current NAS: ${NAS_SERVER}"
  terminal_detail "Replacement NAS: ${replacement_host}"
  terminal_detail "Required shares: ${(j:, :)required_nas_shares}"
  terminal_detail "Validated backup directory: ${replacement_backup_dirs[${replacement_host}]}"
  terminal_detail "Proposal: atomically update only the NAS_SERVER value; backup cleanup will not run."
  printf 'Proceed with this atomic update? [y/N] '
  if ! IFS= read -r answer; then
    answer=""
  fi
  answer="$(trim_config_value "${answer}")"
  answer="${answer:l}"
  if [[ "${answer}" != y && "${answer}" != yes ]]; then
    ( log_message "INFO" "Config repair was cancelled; no configuration or backup files were changed." ) >/dev/null 2>&1 || true
    terminal_detail "Cancelled. The configuration and backup files are unchanged."
    exit 0
  fi

  create_owned_config_temp "${config_path}" candidate || repair_failure "Unable to create a private repair candidate. No configuration or backup files were changed."
  validated_repair_temp "${repair_candidate_tmp}" candidate 600 || repair_failure "The private repair candidate changed unexpectedly. No configuration or backup files were changed."
  if ! write_repair_candidate_to_path "${replacement_host}" "${repair_candidate_tmp}" 2>/dev/null; then
    repair_failure "Unable to write the private repair candidate. No configuration or backup files were changed."
  fi
  validated_repair_temp "${repair_candidate_tmp}" candidate 600 || repair_failure "The private repair candidate changed unexpectedly. No configuration or backup files were changed."
  if ! write_repair_candidate "${replacement_host}" 2>/dev/null | "${CMP_BIN}" -s -- "${repair_candidate_tmp}" - 2>/dev/null; then
    repair_failure "The private repair candidate could not be verified. No configuration or backup files were changed."
  fi
  metadata_matches_snapshot "${expected_metadata}" || repair_failure "The configuration changed during repair; the update was aborted. No backup files were changed."
  validated_repair_temp "${repair_candidate_tmp}" candidate 600 || repair_failure "The private repair candidate changed unexpectedly. No configuration or backup files were changed."
  if ! write_repair_candidate "${replacement_host}" 2>/dev/null | "${CMP_BIN}" -s -- "${repair_candidate_tmp}" - 2>/dev/null; then
    repair_failure "The private repair candidate changed unexpectedly. No configuration or backup files were changed."
  fi
  revalidate_config_directory || repair_failure "The configuration directory changed during repair. No configuration or backup files were changed."
  if ! "${CHMOD_BIN}" "${config_mode}" "${repair_candidate_tmp}" 2>/dev/null; then
    repair_failure "Unable to preserve configuration permissions. No configuration or backup files were changed."
  fi
  validated_repair_temp "${repair_candidate_tmp}" candidate "${config_mode}" || repair_failure "The private repair candidate changed unexpectedly. No configuration or backup files were changed."
  if ! write_repair_candidate "${replacement_host}" 2>/dev/null | "${CMP_BIN}" -s -- "${repair_candidate_tmp}" - 2>/dev/null; then
    repair_failure "The private repair candidate changed unexpectedly. No configuration or backup files were changed."
  fi
  metadata_matches_snapshot "${expected_metadata}" || repair_failure "The configuration changed during repair; the update was aborted. No backup files were changed."
  validated_repair_temp "${repair_candidate_tmp}" candidate "${config_mode}" || repair_failure "The private repair candidate changed unexpectedly. No configuration or backup files were changed."
  revalidate_config_directory || repair_failure "The configuration directory changed during repair; the update was aborted. No backup files were changed."
  if ! "${MV_BIN}" -- "${repair_candidate_tmp}" "${config_path}" 2>/dev/null; then
    repair_failure "Unable to activate the repaired configuration. No configuration or backup files were changed."
  fi
  repair_candidate_tmp=""
  ( log_message "INFO" "The NAS configuration was updated atomically. No backup cleanup was attempted." ) >/dev/null 2>&1 || true
  terminal_detail "Success: NAS_SERVER was updated to ${replacement_host}."
  terminal_detail "The lock and final comparison reduce cooperating-writer risk, but do not eliminate the final stat-to-rename race with uncooperative writers."
  exit 0
}

repair_signal_exit() {
  local signal_status="$1"
  trap - EXIT INT TERM
  cleanup_repair_artifacts
  exit "${signal_status}"
}

config_path="${DEFAULT_CONFIG_PATH}"
config_explicit=0
cli_dry_run=0

while (( $# > 0 )); do
  case "$1" in
    --config)
      (( $# >= 2 )) || config_error "--config requires a path."
      config_path="$2"
      config_explicit=1
      shift 2
      ;;
    --dry-run)
      cli_dry_run=1
      shift
      ;;
    --repair-config)
      REPAIR_CONFIG=1
      shift
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      config_error "Unknown option. Run with --help for usage."
      ;;
  esac
done

if (( REPAIR_CONFIG )); then
  validate_repair_preconditions
fi

if (( REPAIR_CONFIG )); then
  :
elif [[ -f "${config_path}" ]]; then
  load_config "${config_path}"
elif (( config_explicit )); then
  config_error "The requested configuration file does not exist."
fi

if (( ! REPAIR_CONFIG )); then
  # Explicit environment variables override local config values.
  apply_environment_overrides
fi
(( cli_dry_run )) && DRY_RUN=1

if (( REPAIR_CONFIG )); then
  run_repair_config
fi

validate_config

for required_bin in "${MOUNT_BIN}" "${FIND_BIN}" "${STAT_BIN}" "${DATE_BIN}" "${MKTEMP_BIN}"; do
  command -v "${required_bin}" >/dev/null 2>&1 || exit_with_error "A required system command is unavailable; no cleanup was attempted."
done
if (( ! DRY_RUN )); then
  command -v "${RM_BIN}" >/dev/null 2>&1 || exit_with_error "The removal command is unavailable; no cleanup was attempted."
fi
if [[ -n "${LOG_FILE}" ]]; then
  command -v "${DIRNAME_BIN}" >/dev/null 2>&1 || exit_with_error "A logging command is unavailable; no cleanup was attempted."
  command -v "${MKDIR_BIN}" >/dev/null 2>&1 || exit_with_error "A logging command is unavailable; no cleanup was attempted."
fi

mount_output=""
if ! mount_output="$("${MOUNT_BIN}" 2>/dev/null)"; then
  exit_with_error "Unable to read the mount table; no cleanup was attempted."
fi
parse_mount_inventory "${mount_output}"
unset mount_output

if ! host_has_required_shares "${NAS_SERVER}" || ! validate_backup_directory_for_host "${NAS_SERVER}"; then
  discover_replacement_candidates
  if (( ${#replacement_hosts[@]} == 1 )); then
    replacement_host="${replacement_hosts[1]}"
    log_message "WARN" "The configured NAS does not provide all required mounts. Cleanup was skipped. Run interactively with --repair-config to inspect a validated replacement candidate."
    terminal_detail "Configured NAS: ${NAS_SERVER}"
    terminal_detail "Validated replacement candidate: ${replacement_host}"
    terminal_detail "Required shares: ${(j:, :)required_nas_shares}"
    terminal_detail "Validated backup directory: ${replacement_backup_dirs[${replacement_host}]}"
    terminal_detail "No configuration or backup files were changed."
    terminal_detail "Re-run with --repair-config to review and approve updating NAS_SERVER."
  elif (( ${#replacement_hosts[@]} == 0 )); then
    log_message "WARN" "The configured NAS does not provide all required mounts, and no validated replacement candidate was found. Cleanup was skipped."
  else
    log_message "WARN" "The configured NAS does not provide all required mounts, and multiple validated replacement candidates were found. Cleanup was skipped; no repair recommendation was made."
    terminal_detail "Configured NAS: ${NAS_SERVER}"
    terminal_detail "Validated candidates: ${(j:, :)replacement_hosts}"
    terminal_detail "No unique replacement candidate was selected."
    terminal_detail "No configuration or backup files were changed."
  fi
  exit 0
fi

backup_dir="${validated_backup_dir}"
resolved_backup_dir="${resolved_validated_backup_dir}"

log_message "INFO" "Inspecting the configured backup directory."

typeset -a backup_files=()
typeset -a backup_file_days=()
find_output_tmp=""
find_error_tmp=""

cleanup_temp_files() {
  [[ -z "${find_output_tmp:-}" ]] || /bin/rm -f -- "${find_output_tmp}"
  [[ -z "${find_error_tmp:-}" ]] || /bin/rm -f -- "${find_error_tmp}"
}

if ! find_output_tmp="$("${MKTEMP_BIN}" -t "${SCRIPT_NAME}.find.XXXXXX")"; then
  exit_with_error "Unable to initialize the private scan workspace; no cleanup was attempted."
fi
trap cleanup_temp_files EXIT INT TERM
if ! find_error_tmp="$("${MKTEMP_BIN}" -t "${SCRIPT_NAME}.find.err.XXXXXX")"; then
  exit_with_error "Unable to initialize the private scan workspace; no cleanup was attempted."
fi

integer classification_failures=0
if "${FIND_BIN}" -x "${backup_dir}" -type f -print0 > "${find_output_tmp}" 2> "${find_error_tmp}"; then
  while IFS= read -r -d '' file_path; do
    [[ -f "${file_path}" ]] || continue
    [[ "${file_path:t}" == *"${BACKUP_FILENAME_SUFFIX}" ]] || continue
    if ! mtime_epoch="$("${STAT_BIN}" -f "%m" "${file_path}" 2>/dev/null)"; then
      (( classification_failures += 1 ))
      continue
    fi
    if ! file_day="$("${DATE_BIN}" -r "${mtime_epoch}" "+%Y-%m-%d" 2>/dev/null)"; then
      (( classification_failures += 1 ))
      continue
    fi
    backup_files+=("${file_path}")
    backup_file_days+=("${file_day}")
  done < "${find_output_tmp}"
else
  if /usr/bin/grep -q "Operation not permitted" "${find_error_tmp}" 2>/dev/null; then
    exit_with_error "Filesystem access was denied. Grant the invoking shell appropriate access; no files were removed."
  fi
  exit_with_error "Failed to enumerate backup files; no files were removed."
fi
cleanup_temp_files
trap - EXIT INT TERM

if (( classification_failures > 0 )); then
  exit_with_error "Unable to classify ${classification_failures} eligible backup file(s); no files were removed."
fi

typeset -a unique_days=("${(@u)backup_file_days}")
if (( ${#unique_days[@]} == 0 )); then
  log_message "INFO" "No backup files were found."
  exit 0
fi

typeset -a sorted_days=("${(@o)unique_days}")
integer day_count=${#sorted_days[@]}
if (( day_count <= MAX_DAYS_TO_KEEP )); then
  log_message "INFO" "Found ${day_count} day(s) of backups; retention is ${MAX_DAYS_TO_KEEP}. Nothing to purge."
  exit 0
fi

typeset -A keep_days=()
typeset -A purge_days=()
typeset -a days_desc=("${(@O)sorted_days}")
for day in "${days_desc[@]}"; do
  if (( ${#keep_days[@]} < MAX_DAYS_TO_KEEP )); then
    keep_days[$day]=1
  else
    purge_days[$day]=1
  fi
done

typeset -a purge_candidates=()
integer idx=1
while (( idx <= ${#backup_files[@]} )); do
  file="${backup_files[idx]}"
  day="${backup_file_days[idx]}"
  if (( ${+purge_days[$day]} )); then
    purge_candidates+=("${file}")
  fi
  (( idx += 1 ))
done

if (( ${#purge_candidates[@]} == 0 )); then
  log_message "INFO" "No files were identified for purging."
  exit 0
fi

log_message "INFO" "Identified ${#purge_candidates[@]} file(s) older than the newest ${MAX_DAYS_TO_KEEP} backup day(s)."

if (( DRY_RUN )); then
  log_message "INFO" "Dry run enabled; no files were deleted."
  exit 0
fi

integer removed=0
integer removal_failures=0
integer changed_candidates=0
for file in "${purge_candidates[@]}"; do
  resolved_candidate="${file:A}"
  if [[ "${file}" != "${backup_dir}/"* || "${resolved_candidate}" != "${resolved_backup_dir}/"* || ! -f "${file}" || -L "${file}" || "${file:t}" != *"${BACKUP_FILENAME_SUFFIX}" ]]; then
    (( changed_candidates += 1 ))
    continue
  fi

  if ! current_mtime_epoch="$("${STAT_BIN}" -f "%m" "${file}" 2>/dev/null)"; then
    (( removal_failures += 1 ))
    continue
  fi
  if ! current_file_day="$("${DATE_BIN}" -r "${current_mtime_epoch}" "+%Y-%m-%d" 2>/dev/null)"; then
    (( removal_failures += 1 ))
    continue
  fi
  if (( ! ${+purge_days[$current_file_day]} )); then
    (( changed_candidates += 1 ))
    continue
  fi

  if "${RM_BIN}" -f -- "${file}" 2>/dev/null; then
    (( removed += 1 ))
  else
    (( removal_failures += 1 ))
  fi
done

if (( changed_candidates > 0 )); then
  log_message "WARN" "Skipped ${changed_candidates} candidate(s) whose deletion eligibility changed after scanning."
fi
if (( removal_failures > 0 )); then
  exit_with_error "Removed ${removed} file(s), but ${removal_failures} candidate(s) could not be safely revalidated or removed."
fi
log_message "INFO" "Removed ${removed} file(s)."
