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
LOG_FILE=""
USE_SYSLOG=0

typeset -a required_nas_shares=()
integer nas_server_assignment_count=0

MOUNT_BIN="${MONEYDANCE_MOUNT_BIN:-/sbin/mount}"
STAT_BIN="${MONEYDANCE_STAT_BIN:-/usr/bin/stat}"
FIND_BIN="${MONEYDANCE_FIND_BIN:-/usr/bin/find}"
DATE_BIN="${MONEYDANCE_DATE_BIN:-/bin/date}"
RM_BIN="${MONEYDANCE_RM_BIN:-/bin/rm}"
LOGGER_BIN="${MONEYDANCE_LOGGER_BIN:-/usr/bin/logger}"
DIRNAME_BIN="${MONEYDANCE_DIRNAME_BIN:-/usr/bin/dirname}"
MKDIR_BIN="${MONEYDANCE_MKDIR_BIN:-/bin/mkdir}"
MKTEMP_BIN="${MONEYDANCE_MKTEMP_BIN:-/usr/bin/mktemp}"

show_help() {
  cat <<'EOF'
Usage: moneydance_rotate_backups.sh [--config PATH] [--dry-run]

Prune backup files older than the newest configured number of backup days.

Options:
  --config PATH  Read settings from PATH instead of the default local config.
  --dry-run      Report the number of files that would be removed; delete none.
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
    log_dir="$("${DIRNAME_BIN}" "${LOG_FILE}")"
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
    "${LOGGER_BIN}" -t "${SCRIPT_NAME}" "${message}"
  fi
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
  integer line_number=0

  [[ -f "${config_path}" && -r "${config_path}" ]] || config_error "Configuration file is not readable."

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
  done < "${config_path}"
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
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      config_error "Unknown option. Run with --help for usage."
      ;;
  esac
done

if [[ -f "${config_path}" ]]; then
  load_config "${config_path}"
elif (( config_explicit )); then
  config_error "The requested configuration file does not exist."
fi

# Explicit environment variables override local config values.
[[ -n "${MONEYDANCE_NAS_SERVER:-}" ]] && NAS_SERVER="${MONEYDANCE_NAS_SERVER}"
[[ -n "${MONEYDANCE_NAS_SHARE_NAME:-}" ]] && NAS_SHARE_NAME="${MONEYDANCE_NAS_SHARE_NAME}"
[[ -n "${MONEYDANCE_REQUIRED_NAS_SHARES:-}" ]] && REQUIRED_NAS_SHARES="${MONEYDANCE_REQUIRED_NAS_SHARES}"
[[ -n "${MONEYDANCE_BACKUP_DIRECTORY_NAME:-}" ]] && BACKUP_DIRECTORY_NAME="${MONEYDANCE_BACKUP_DIRECTORY_NAME}"
[[ -n "${MONEYDANCE_BACKUP_FILENAME_SUFFIX:-}" ]] && BACKUP_FILENAME_SUFFIX="${MONEYDANCE_BACKUP_FILENAME_SUFFIX}"
[[ -n "${MONEYDANCE_MAX_DAYS_TO_KEEP:-}" ]] && MAX_DAYS_TO_KEEP="${MONEYDANCE_MAX_DAYS_TO_KEEP}"
[[ -n "${MONEYDANCE_DRY_RUN:-}" ]] && DRY_RUN="${MONEYDANCE_DRY_RUN}"
[[ -n "${MONEYDANCE_LOG_FILE:-}" ]] && LOG_FILE="${MONEYDANCE_LOG_FILE}"
[[ -n "${MONEYDANCE_USE_SYSLOG:-}" ]] && USE_SYSLOG="${MONEYDANCE_USE_SYSLOG}"
(( cli_dry_run )) && DRY_RUN=1

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

mount_line=""
mount_point=""
while IFS= read -r line; do
  [[ "${line}" == *" on "* ]] || continue
  mount_source="${line%% on *}"
  [[ "${mount_source}" == //*/* ]] || continue

  source_authority_and_share="${mount_source#//}"
  source_authority="${source_authority_and_share%%/*}"
  source_share="${source_authority_and_share#*/}"
  source_host="${source_authority##*@}"

  # macOS mount output represents spaces as the literal sequence \040. Decode
  # only that supported sequence with shell substitution before exact matching;
  # never interpret arbitrary backslash escapes from command output.
  source_share="${source_share//\\040/ }"

  if [[ "${source_host}" == "${NAS_SERVER}" && "${source_share}" == "${NAS_SHARE_NAME}" ]]; then
    mount_line="${line}"
    mount_details="${line#* on }"
    mount_point="${mount_details% \(*}"
    mount_point="${mount_point//\\040/ }"
    break
  fi
done <<< "${mount_output}"
unset mount_output

if [[ -z "${mount_line}" ]]; then
  log_message "WARN" "The configured share is not mounted; skipping cleanup."
  exit 0
fi

if [[ -z "${mount_point}" || ! -d "${mount_point}" ]]; then
  log_message "WARN" "The mount table did not yield an accessible mount point; skipping cleanup."
  exit 0
fi

backup_dir="${mount_point%/}/${BACKUP_DIRECTORY_NAME}"
if [[ ! -d "${backup_dir}" ]]; then
  log_message "WARN" "The configured backup directory was not found; skipping cleanup."
  exit 0
fi
if [[ -L "${backup_dir}" ]]; then
  log_message "WARN" "The configured backup directory is a symbolic link; skipping cleanup."
  exit 0
fi
resolved_backup_dir="${backup_dir:A}"
if [[ ! -r "${backup_dir}" || ! -x "${backup_dir}" ]]; then
  log_message "WARN" "The configured backup directory is not accessible; skipping cleanup."
  exit 0
fi

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
