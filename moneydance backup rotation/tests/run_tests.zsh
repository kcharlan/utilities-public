#!/bin/zsh

set -u
set -o pipefail

typeset -a MONEYDANCE_TEST_ENV_VARS=(
  MONEYDANCE_NAS_SERVER
  MONEYDANCE_NAS_SHARE_NAME
  MONEYDANCE_REQUIRED_NAS_SHARES
  MONEYDANCE_BACKUP_DIRECTORY_NAME
  MONEYDANCE_BACKUP_FILENAME_SUFFIX
  MONEYDANCE_MAX_DAYS_TO_KEEP
  MONEYDANCE_DRY_RUN
  MONEYDANCE_LOG_FILE
  MONEYDANCE_USE_SYSLOG
  MONEYDANCE_MOUNT_BIN
  MONEYDANCE_STAT_BIN
  MONEYDANCE_FIND_BIN
  MONEYDANCE_DATE_BIN
  MONEYDANCE_RM_BIN
  MONEYDANCE_LOGGER_BIN
  MONEYDANCE_DIRNAME_BIN
  MONEYDANCE_MKDIR_BIN
  MONEYDANCE_MKTEMP_BIN
)

# Tests must never inherit operational settings or command overrides from the
# invoking user. XDG_CONFIG_HOME is also cleared so per-test HOME controls the
# default config location deterministically.
for variable_name in "${MONEYDANCE_TEST_ENV_VARS[@]}"; do
  unset "${variable_name}"
done
unset XDG_CONFIG_HOME

if [[ "${1:-}" == "--internal-ambient-isolation-probe" ]]; then
  integer probe_leaks=0
  for variable_name in "${MONEYDANCE_TEST_ENV_VARS[@]}"; do
    if /usr/bin/printenv "${variable_name}" >/dev/null 2>&1; then
      (( probe_leaks += 1 ))
    fi
  done
  (( probe_leaks == 0 ))
  exit $?
fi

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
SCRIPT="${PROJECT_DIR}/moneydance_rotate_backups.sh"

integer passed=0
integer failed=0

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  (( failed += 1 ))
}

pass() {
  printf 'PASS: %s\n' "$1"
  (( passed += 1 ))
}

assert_status() {
  local name="$1"
  local expected="$2"
  local actual="$3"
  if [[ "${actual}" -eq "${expected}" ]]; then
    pass "${name}"
  else
    fail "${name} (expected status ${expected}, got ${actual})"
  fi
}

assert_file_exists() {
  local name="$1"
  local path="$2"
  if [[ -f "${path}" ]]; then
    pass "${name}"
  else
    fail "${name} (missing fixture file)"
  fi
}

assert_file_missing() {
  local name="$1"
  local path="$2"
  if [[ ! -e "${path}" ]]; then
    pass "${name}"
  else
    fail "${name} (fixture file still exists)"
  fi
}

assert_contains() {
  local name="$1"
  local haystack="$2"
  local needle="$3"
  if [[ "${haystack}" == *"${needle}"* ]]; then
    pass "${name}"
  else
    fail "${name} (expected message not found)"
  fi
}

assert_not_contains() {
  local name="$1"
  local haystack="$2"
  local needle="$3"
  if [[ "${haystack}" != *"${needle}"* ]]; then
    pass "${name}"
  else
    fail "${name} (private fixture value was printed)"
  fi
}

PTY_STATUS=0
PTY_TRANSCRIPT=""
PTY_NONTTY_STDOUT=""
run_with_pty() {
  local timeout_seconds="$1"
  local tty_mode="$2"
  shift 2
  local transcript_file="${test_root}/pty-transcript-${RANDOM}-${RANDOM}"
  local stdout_file="${test_root}/pty-stdout-${RANDOM}-${RANDOM}"
  local child_pid deadline
  integer timed_out=0
  typeset -a pty_command=()

  PTY_STATUS=124
  PTY_TRANSCRIPT=""
  PTY_NONTTY_STDOUT=""
  case "${tty_mode}" in
    both)
      pty_command=("$@")
      ;;
    stdin-only)
      pty_command=(/bin/zsh -c 'non_tty_stdout="$1"; shift; "$@" > "${non_tty_stdout}"' pty-stdin-only "${stdout_file}" "$@")
      ;;
    stdout-only)
      pty_command=(/bin/zsh -c '"$@" < /dev/null' pty-stdout-only "$@")
      ;;
    *)
      return 2
      ;;
  esac

  /usr/bin/script -q /dev/null "${pty_command[@]}" < /dev/null > "${transcript_file}" 2>&1 &
  child_pid=$!
  deadline=$(( SECONDS + timeout_seconds ))
  while /bin/kill -0 "${child_pid}" 2>/dev/null; do
    (( SECONDS < deadline )) || break
    /bin/sleep 0.02
  done

  if /bin/kill -0 "${child_pid}" 2>/dev/null; then
    timed_out=1
    /bin/kill -TERM "${child_pid}" 2>/dev/null || true
    deadline=$(( SECONDS + 1 ))
    while /bin/kill -0 "${child_pid}" 2>/dev/null && (( SECONDS < deadline )); do
      /bin/sleep 0.02
    done
  fi
  if /bin/kill -0 "${child_pid}" 2>/dev/null; then
    /bin/kill -KILL "${child_pid}" 2>/dev/null || true
    deadline=$(( SECONDS + 1 ))
    while /bin/kill -0 "${child_pid}" 2>/dev/null && (( SECONDS < deadline )); do
      /bin/sleep 0.02
    done
  fi
  if /bin/kill -0 "${child_pid}" 2>/dev/null; then
    PTY_TRANSCRIPT="$(<"${transcript_file}")"
    [[ ! -f "${stdout_file}" ]] || PTY_NONTTY_STDOUT="$(<"${stdout_file}")"
    return 125
  fi
  wait "${child_pid}"
  PTY_STATUS=$?
  PTY_TRANSCRIPT="$(<"${transcript_file}")"
  [[ ! -f "${stdout_file}" ]] || PTY_NONTTY_STDOUT="$(<"${stdout_file}")"
  if (( timed_out )); then
    PTY_STATUS=124
    return 124
  fi
  return 0
}

make_mount_mock() {
  local target="$1"
  local mount_point="$2"
  local marker="$3"
  local mount_source="${4:-//synthetic-nas/SYNTHETIC_SHARE}"
  make_mount_inventory_mock \
    "${target}" \
    "${marker}" \
    "${mount_source} on ${mount_point} (smbfs)" \
    "//synthetic-nas/SYNTHETIC_COMPANION on ${test_root:-/tmp}/synthetic-companion (smbfs)"
}

make_mount_inventory_mock() {
  local target="$1"
  local marker="$2"
  shift 2

  cat > "${target}" <<EOF
#!/bin/zsh
print -r -- invoked >> "${marker}"
EOF
  local mount_line
  for mount_line in "$@"; do
    printf 'print -r -- %q\n' "${mount_line}" >> "${target}"
  done
  chmod 755 "${target}"
}

make_config() {
  local target="$1"
  local dry_run="${2:-0}"
  cat > "${target}" <<EOF
NAS_SERVER=synthetic-nas
NAS_SHARE_NAME=SYNTHETIC_SHARE
REQUIRED_NAS_SHARES=SYNTHETIC_SHARE,SYNTHETIC_COMPANION
BACKUP_DIRECTORY_NAME=SYNTHETIC_BACKUPS
BACKUP_FILENAME_SUFFIX=.SYNTHETIC-BACKUP
MAX_DAYS_TO_KEEP=2
DRY_RUN=${dry_run}
USE_SYSLOG=0
EOF
}

test_root="$(mktemp -d -t moneydance-rotation-tests.XXXXXX)"
trap 'rm -rf -- "${test_root}"' EXIT

run_with_pty 5 both /bin/zsh -c 'exit 37'
pty_nonzero_helper_status=$?
assert_status "PTY helper itself succeeds for a completed nonzero child" 0 "${pty_nonzero_helper_status}"
assert_status "PTY helper preserves a distinctive child status" 37 "${PTY_STATUS}"

run_with_pty 5 both /bin/zsh -c '[[ -t 0 && -t 1 ]]'
assert_status "PTY helper provides TTY stdin and stdout together" 0 "${PTY_STATUS}"
run_with_pty 5 stdin-only /bin/zsh -c '[[ -t 0 && ! -t 1 ]]'
assert_status "PTY helper can provide only TTY stdin" 0 "${PTY_STATUS}"
run_with_pty 5 stdout-only /bin/zsh -c '[[ ! -t 0 && -t 1 ]]'
assert_status "PTY helper can provide only TTY stdout" 0 "${PTY_STATUS}"

pty_timeout_start=${SECONDS}
run_with_pty 1 both /bin/zsh -c 'trap "" TERM; while :; do /bin/sleep 10; done'
pty_timeout_helper_status=$?
pty_timeout_elapsed=$(( SECONDS - pty_timeout_start ))
assert_status "PTY helper reports a hard timeout" 124 "${pty_timeout_helper_status}"
assert_status "PTY helper reports timeout separately from child status" 124 "${PTY_STATUS}"
if (( pty_timeout_elapsed <= 4 )); then
  pass "PTY helper bounds TERM grace, KILL, and reap"
else
  fail "PTY helper bounds TERM grace, KILL, and reap (elapsed ${pty_timeout_elapsed}s)"
fi

typeset -A cleared_environment_variables=()
for variable_name in "${MONEYDANCE_TEST_ENV_VARS[@]}"; do
  cleared_environment_variables[${variable_name}]=1
done
integer uncleared_supported_variables=0
typeset -a supported_environment_variables=(
  "${(@f)$(/usr/bin/grep -Eo 'MONEYDANCE_[A-Z_]+' "${SCRIPT}" | /usr/bin/sort -u)}"
)
for variable_name in "${supported_environment_variables[@]}"; do
  if [[ -z "${cleared_environment_variables[${variable_name}]:-}" ]]; then
    (( uncleared_supported_variables += 1 ))
  fi
done
if (( uncleared_supported_variables == 0 )); then
  pass "test runner clears every supported MONEYDANCE environment override"
else
  fail "test runner clears every supported MONEYDANCE environment override"
fi

typeset -a hostile_ambient_environment=()
for variable_name in "${MONEYDANCE_TEST_ENV_VARS[@]}"; do
  hostile_ambient_environment+=("${variable_name}=SYNTHETIC-HOSTILE-VALUE")
done
ambient_probe_output="$(
  /usr/bin/env \
    "${hostile_ambient_environment[@]}" \
    /bin/zsh "${0:A}" --internal-ambient-isolation-probe 2>&1
)"
ambient_probe_status=$?
if [[ "${ambient_probe_status}" -eq 0 ]]; then
  pass "hostile ambient MONEYDANCE overrides cannot contaminate the suite"
else
  fail "hostile ambient MONEYDANCE overrides cannot contaminate the suite (${ambient_probe_output})"
fi

help_marker="${test_root}/help-mount-called"
help_mount="${test_root}/help-mount"
make_mount_mock "${help_mount}" "${test_root}/unused" "${help_marker}"
help_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${help_mount}" "${SCRIPT}" --help 2>&1)"
help_status=$?
assert_status "--help exits successfully" 0 "${help_status}"
assert_contains "--help describes dry-run" "${help_output}" "--dry-run"
if [[ ! -e "${help_marker}" ]]; then
  pass "--help performs no mount lookup"
else
  fail "--help performs no mount lookup"
fi

missing_marker="${test_root}/missing-mount-called"
missing_mount="${test_root}/missing-mount"
make_mount_mock "${missing_mount}" "${test_root}/unused" "${missing_marker}"
missing_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${missing_mount}" "${SCRIPT}" 2>&1)"
missing_status=$?
if [[ "${missing_status}" -ne 0 ]]; then
  pass "missing configuration fails closed"
else
  fail "missing configuration fails closed (expected nonzero status)"
fi
assert_contains "missing configuration is visible" "${missing_output}" "Configuration is required"
if [[ ! -e "${missing_marker}" ]]; then
  pass "missing configuration performs no mount lookup"
else
  fail "missing configuration performs no mount lookup"
fi

malicious_config="${test_root}/malicious.conf"
injection_marker="${test_root}/injection-ran"
cat > "${malicious_config}" <<EOF
NAS_SERVER=synthetic-nas
NAS_SHARE_NAME=\$(touch "${injection_marker}")
REQUIRED_NAS_SHARES=\$(touch "${injection_marker}"),SYNTHETIC_COMPANION
BACKUP_DIRECTORY_NAME=SYNTHETIC_BACKUPS
BACKUP_FILENAME_SUFFIX=.SYNTHETIC-BACKUP
MAX_DAYS_TO_KEEP=2
EOF
malicious_output="$(HOME="${test_root}/empty-home" "${SCRIPT}" --config "${malicious_config}" --dry-run 2>&1)"
malicious_status=$?
if [[ "${malicious_status}" -ne 0 && ! -e "${injection_marker}" ]]; then
  pass "configuration values are parsed without execution"
else
  fail "configuration values are parsed without execution"
fi

invalid_config="${test_root}/invalid-retention.conf"
invalid_mount_marker="${test_root}/invalid-mount-called"
invalid_mount="${test_root}/invalid-mount"
make_mount_mock "${invalid_mount}" "${test_root}/unused" "${invalid_mount_marker}"
cat > "${invalid_config}" <<'EOF'
 NAS_SERVER = synthetic-nas
 NAS_SHARE_NAME = SYNTHETIC_SHARE
 REQUIRED_NAS_SHARES = SYNTHETIC_SHARE, SYNTHETIC_COMPANION
 BACKUP_DIRECTORY_NAME = SYNTHETIC_BACKUPS
 BACKUP_FILENAME_SUFFIX = .SYNTHETIC-BACKUP
 MAX_DAYS_TO_KEEP = 0
EOF
invalid_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${invalid_mount}" "${SCRIPT}" --config "${invalid_config}" 2>&1)"
invalid_status=$?
if [[ "${invalid_status}" -ne 0 ]]; then
  pass "invalid retention fails closed"
else
  fail "invalid retention fails closed"
fi
if [[ ! -e "${invalid_mount_marker}" ]]; then
  pass "invalid configuration performs no mount lookup"
else
  fail "invalid configuration performs no mount lookup"
fi
assert_not_contains "validation output does not print configured host" "${invalid_output}" "synthetic-nas"

missing_suffix_config="${test_root}/missing-suffix.conf"
missing_suffix_marker="${test_root}/missing-suffix-mount-called"
missing_suffix_mount="${test_root}/missing-suffix-mount"
make_mount_mock "${missing_suffix_mount}" "${test_root}/unused" "${missing_suffix_marker}"
cat > "${missing_suffix_config}" <<'EOF'
NAS_SERVER=synthetic-nas
NAS_SHARE_NAME=SYNTHETIC_SHARE
REQUIRED_NAS_SHARES=SYNTHETIC_SHARE,SYNTHETIC_COMPANION
BACKUP_DIRECTORY_NAME=SYNTHETIC_BACKUPS
MAX_DAYS_TO_KEEP=2
EOF
missing_suffix_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${missing_suffix_mount}" "${SCRIPT}" --config "${missing_suffix_config}" 2>&1)"
missing_suffix_status=$?
if [[ "${missing_suffix_status}" -ne 0 && ! -e "${missing_suffix_marker}" ]]; then
  pass "missing backup filename suffix fails before mount lookup"
else
  fail "missing backup filename suffix fails before mount lookup"
fi

example_output="$(
  HOME="${test_root}/empty-home" \
  MONEYDANCE_MOUNT_BIN=/usr/bin/true \
  "${SCRIPT}" --config "${PROJECT_DIR}/config.example" --dry-run 2>&1
)"
example_status=$?
assert_status "tracked synthetic example is valid configuration" 0 "${example_status}"
assert_not_contains "example run does not print synthetic host" "${example_output}" "SYNTHETIC-NAS-HOST"
assert_contains "tracked synthetic example remains non-destructive" "$(<"${PROJECT_DIR}/config.example")" "DRY_RUN=1"

required_shares_mount_marker="${test_root}/required-shares-mount-called"
required_shares_mount="${test_root}/required-shares-mount"
make_mount_mock "${required_shares_mount}" "${test_root}/unused" "${required_shares_mount_marker}"

missing_required_shares_config="${test_root}/missing-required-shares.conf"
cat > "${missing_required_shares_config}" <<'EOF'
NAS_SERVER=synthetic-nas
NAS_SHARE_NAME=SYNTHETIC_PRIMARY
BACKUP_DIRECTORY_NAME=SYNTHETIC_BACKUPS
BACKUP_FILENAME_SUFFIX=.SYNTHETIC-BACKUP
EOF
missing_required_shares_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${required_shares_mount}" "${SCRIPT}" --config "${missing_required_shares_config}" 2>&1)"
missing_required_shares_status=$?
assert_status "file configuration requires REQUIRED_NAS_SHARES" 2 "${missing_required_shares_status}"
if [[ ! -e "${required_shares_mount_marker}" ]]; then
  pass "missing REQUIRED_NAS_SHARES fails before mount lookup"
else
  fail "missing REQUIRED_NAS_SHARES fails before mount lookup"
fi

typeset -a invalid_required_share_lists=(
  'SYNTHETIC_PRIMARY,,SYNTHETIC_COMPANION'
  'SYNTHETIC_PRIMARY,SYNTHETIC_PRIMARY'
  'SYNTHETIC_PRIMARY,SYNTHETIC/COMPANION'
  'SYNTHETIC_COMPANION,SYNTHETIC_TERTIARY'
)
typeset -a invalid_required_share_names=(
  'empty item'
  'duplicate item'
  'unsupported characters'
  'missing primary share'
)
invalid_required_shares_config="${test_root}/invalid-required-shares.conf"
cat > "${invalid_required_shares_config}" <<'EOF'
NAS_SERVER=synthetic-nas
NAS_SHARE_NAME=SYNTHETIC_PRIMARY
BACKUP_DIRECTORY_NAME=SYNTHETIC_BACKUPS
BACKUP_FILENAME_SUFFIX=.SYNTHETIC-BACKUP
EOF
integer required_share_case_index
for (( required_share_case_index = 1; required_share_case_index <= ${#invalid_required_share_lists[@]}; required_share_case_index += 1 )); do
  /bin/rm -f -- "${required_shares_mount_marker}"
  invalid_required_shares_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${required_shares_mount}" MONEYDANCE_REQUIRED_NAS_SHARES="${invalid_required_share_lists[${required_share_case_index}]}" "${SCRIPT}" --config "${invalid_required_shares_config}" 2>&1)"
  invalid_required_shares_status=$?
  assert_status "REQUIRED_NAS_SHARES rejects ${invalid_required_share_names[${required_share_case_index}]}" 2 "${invalid_required_shares_status}"
  if [[ ! -e "${required_shares_mount_marker}" ]]; then
    pass "${invalid_required_share_names[${required_share_case_index}]} fails before mount lookup"
  else
    fail "${invalid_required_share_names[${required_share_case_index}]} fails before mount lookup"
  fi
done

normalized_required_shares_config="${test_root}/normalized-required-shares.conf"
cat > "${normalized_required_shares_config}" <<'EOF'
NAS_SERVER=synthetic-nas
NAS_SHARE_NAME=SYNTHETIC_PRIMARY
REQUIRED_NAS_SHARES= SYNTHETIC_COMPANION , SYNTHETIC_PRIMARY
BACKUP_DIRECTORY_NAME=SYNTHETIC_BACKUPS
BACKUP_FILENAME_SUFFIX=.SYNTHETIC-BACKUP
EOF
/bin/rm -f -- "${required_shares_mount_marker}"
normalized_required_shares_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${required_shares_mount}" "${SCRIPT}" --config "${normalized_required_shares_config}" --dry-run 2>&1)"
normalized_required_shares_status=$?
assert_status "REQUIRED_NAS_SHARES normalizes whitespace around valid items" 0 "${normalized_required_shares_status}"
if [[ -e "${required_shares_mount_marker}" ]]; then
  pass "normalized REQUIRED_NAS_SHARES reaches mount lookup"
else
  fail "normalized REQUIRED_NAS_SHARES reaches mount lookup"
fi

required_shares_override_config="${test_root}/required-shares-override.conf"
cat > "${required_shares_override_config}" <<'EOF'
NAS_SERVER=synthetic-nas
NAS_SHARE_NAME=SYNTHETIC_PRIMARY
REQUIRED_NAS_SHARES=SYNTHETIC_FILE_ONLY
BACKUP_DIRECTORY_NAME=SYNTHETIC_BACKUPS
BACKUP_FILENAME_SUFFIX=.SYNTHETIC-BACKUP
EOF
/bin/rm -f -- "${required_shares_mount_marker}"
required_shares_override_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${required_shares_mount}" MONEYDANCE_REQUIRED_NAS_SHARES='SYNTHETIC_PRIMARY,SYNTHETIC_COMPANION' "${SCRIPT}" --config "${required_shares_override_config}" --dry-run 2>&1)"
required_shares_override_status=$?
assert_status "MONEYDANCE_REQUIRED_NAS_SHARES overrides the file value" 0 "${required_shares_override_status}"
if [[ -e "${required_shares_mount_marker}" ]]; then
  pass "valid REQUIRED_NAS_SHARES override reaches mount lookup"
else
  fail "valid REQUIRED_NAS_SHARES override reaches mount lookup"
fi

bad_log_config="${test_root}/bad-log.conf"
bad_log_marker="${test_root}/bad-log-mount-called"
bad_log_mount="${test_root}/bad-log-mount"
make_mount_mock "${bad_log_mount}" "${test_root}/unused" "${bad_log_marker}"
cat > "${bad_log_config}" <<'EOF'
NAS_SERVER=synthetic-nas
NAS_SHARE_NAME=SYNTHETIC_SHARE
REQUIRED_NAS_SHARES=SYNTHETIC_SHARE,SYNTHETIC_COMPANION
BACKUP_DIRECTORY_NAME=SYNTHETIC_BACKUPS
BACKUP_FILENAME_SUFFIX=.SYNTHETIC-BACKUP
LOG_FILE=relative.log
EOF
bad_log_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${bad_log_mount}" "${SCRIPT}" --config "${bad_log_config}" 2>&1)"
bad_log_status=$?
if [[ "${bad_log_status}" -ne 0 && ! -e "${bad_log_marker}" ]]; then
  pass "relative LOG_FILE fails before mount lookup"
else
  fail "relative LOG_FILE fails before mount lookup"
fi

config="${test_root}/config"
make_config "${config}"

failed_mount_marker="${test_root}/failed-mount-called"
failed_mount="${test_root}/failed-mount"
cat > "${failed_mount}" <<EOF
#!/bin/zsh
print -r -- invoked > "${failed_mount_marker}"
exit 23
EOF
chmod 755 "${failed_mount}"
failed_mount_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${failed_mount}" "${SCRIPT}" --config "${config}" --dry-run 2>&1)"
failed_mount_status=$?
if [[ "${failed_mount_status}" -ne 0 && -e "${failed_mount_marker}" ]]; then
  pass "mount command failure is reported as an error"
else
  fail "mount command failure is reported as an error"
fi
assert_not_contains "mount failure does not print configured host" "${failed_mount_output}" "synthetic-nas"

mount_point="${test_root}/mount with spaces"
backup_dir="${mount_point}/SYNTHETIC_BACKUPS"
mkdir -p "${backup_dir}"
private_name="PRIVATE-ACCOUNT-1234.SYNTHETIC-BACKUP"
old_file="${backup_dir}/${private_name}"
middle_file="${backup_dir}/SYNTHETIC-MIDDLE.SYNTHETIC-BACKUP"
new_file="${backup_dir}/SYNTHETIC-NEW.SYNTHETIC-BACKUP"
nonmatching_file="${backup_dir}/MUST-SURVIVE.txt"
touch -t 203701010101 "${old_file}"
touch -t 203701020101 "${middle_file}"
touch -t 203701030101 "${new_file}"
touch -t 203601010101 "${nonmatching_file}"

mount_marker="${test_root}/mount-called"
mount_mock="${test_root}/mount-mock"
make_mount_mock "${mount_mock}" "${mount_point}" "${mount_marker}" "//synthetic-user@synthetic-nas/SYNTHETIC_SHARE"

inventory_mount_point="${test_root}/inventory primary"
inventory_backup_dir="${inventory_mount_point}/SYNTHETIC_BACKUPS"
inventory_companion_mount_point="${test_root}/inventory companion"
mkdir -p "${inventory_backup_dir}" "${inventory_companion_mount_point}"
inventory_old_file="${inventory_backup_dir}/SYNTHETIC-OLD.SYNTHETIC-BACKUP"
inventory_middle_file="${inventory_backup_dir}/SYNTHETIC-MIDDLE.SYNTHETIC-BACKUP"
inventory_new_file="${inventory_backup_dir}/SYNTHETIC-NEW.SYNTHETIC-BACKUP"
touch -t 203701020101 "${inventory_middle_file}"
touch -t 203701030101 "${inventory_new_file}"
escaped_inventory_mount_point="${inventory_mount_point// /\\040}"
escaped_inventory_companion_mount_point="${inventory_companion_mount_point// /\\040}"

reset_inventory_candidate() {
  touch -t 203701010101 "${inventory_old_file}"
}

inventory_config="${test_root}/inventory-config"
cat > "${inventory_config}" <<'EOF'
NAS_SERVER=synthetic-nas
NAS_SHARE_NAME=SYNTHETIC_SHARE
REQUIRED_NAS_SHARES=SYNTHETIC_SHARE,SYNTHETIC_COMPANION
BACKUP_DIRECTORY_NAME=SYNTHETIC_BACKUPS
BACKUP_FILENAME_SUFFIX=.SYNTHETIC-BACKUP
MAX_DAYS_TO_KEEP=2
DRY_RUN=0
USE_SYSLOG=0
EOF

candidate_config_dir="${test_root}/SYNTHETIC-PRIVATE-CONFIG-PATH"
candidate_config="${candidate_config_dir}/candidate-config"
candidate_log="${test_root}/SYNTHETIC-PRIVATE-LOG-PATH/candidate-diagnostic.log"
mkdir -p "${candidate_config_dir}"
cat > "${candidate_config}" <<EOF
NAS_SERVER=synthetic-configured-private-host
NAS_SHARE_NAME=SYNTHETIC-PRIVATE-PRIMARY
REQUIRED_NAS_SHARES= SYNTHETIC-PRIVATE-COMPANION , SYNTHETIC-PRIVATE-PRIMARY
BACKUP_DIRECTORY_NAME=SYNTHETIC-PRIVATE-BACKUPS
BACKUP_FILENAME_SUFFIX=.SYNTHETIC-BACKUP
MAX_DAYS_TO_KEEP=1
DRY_RUN=0
LOG_FILE=${candidate_log}
USE_SYSLOG=1
EOF
candidate_config_before="$(<"${candidate_config}")"

candidate_one_primary="${test_root}/synthetic-private-candidate-one-primary"
candidate_one_companion="${test_root}/synthetic-private-candidate-one-companion"
candidate_one_backup_dir="${candidate_one_primary}/SYNTHETIC-PRIVATE-BACKUPS"
candidate_two_primary="${test_root}/synthetic-private-candidate-two-primary"
candidate_two_companion="${test_root}/synthetic-private-candidate-two-companion"
candidate_two_backup_dir="${candidate_two_primary}/SYNTHETIC-PRIVATE-BACKUPS"
invalid_candidate_primary="${test_root}/synthetic-private-invalid-primary"
partial_candidate_primary="${test_root}/synthetic-private-partial-primary"
split_candidate_companion="${test_root}/synthetic-private-split-companion"
mkdir -p \
  "${candidate_one_backup_dir}" \
  "${candidate_one_companion}" \
  "${candidate_two_backup_dir}" \
  "${candidate_two_companion}" \
  "${invalid_candidate_primary}" \
  "${partial_candidate_primary}/SYNTHETIC-PRIVATE-BACKUPS" \
  "${split_candidate_companion}"
candidate_one_backup_file="${candidate_one_backup_dir}/SYNTHETIC-PRIVATE-OLD.SYNTHETIC-BACKUP"
candidate_two_backup_file="${candidate_two_backup_dir}/SYNTHETIC-PRIVATE-OLD.SYNTHETIC-BACKUP"
partial_backup_file="${partial_candidate_primary}/SYNTHETIC-PRIVATE-BACKUPS/SYNTHETIC-PRIVATE-OLD.SYNTHETIC-BACKUP"
touch -t 203701010101 "${candidate_one_backup_file}" "${candidate_two_backup_file}" "${partial_backup_file}"

candidate_rm_marker="${test_root}/candidate-rm-called"
candidate_rm="${test_root}/candidate-rm"
cat > "${candidate_rm}" <<EOF
#!/bin/zsh
print -r -- "\$*" >> "${candidate_rm_marker}"
exec /bin/rm "\$@"
EOF
chmod 755 "${candidate_rm}"

candidate_logger_marker="${test_root}/candidate-logger-recording"
candidate_logger="${test_root}/candidate-logger"
cat > "${candidate_logger}" <<EOF
#!/bin/zsh
print -r -- "\$*" >> "${candidate_logger_marker}"
EOF
chmod 755 "${candidate_logger}"

candidate_scan_marker="${test_root}/candidate-retention-scan-called"
candidate_scan_spy="${test_root}/candidate-retention-scan-spy"
cat > "${candidate_scan_spy}" <<EOF
#!/bin/zsh
print -r -- "\$*" >> "${candidate_scan_marker}"
exit 97
EOF
chmod 755 "${candidate_scan_spy}"

unique_candidate_marker="${test_root}/unique-candidate-mount-called"
unique_candidate_mount="${test_root}/unique-candidate-mount"
make_mount_inventory_mock \
  "${unique_candidate_mount}" \
  "${unique_candidate_marker}" \
  "//synthetic-configured-private-host/SYNTHETIC-PRIVATE-PRIMARY on ${invalid_candidate_primary} (smbfs)" \
  "//synthetic-candidate-private-one/SYNTHETIC-PRIVATE-COMPANION on ${candidate_one_companion} (smbfs)" \
  "//synthetic-candidate-private-one/SYNTHETIC-PRIVATE-PRIMARY on ${candidate_one_primary} (smbfs)"
# A real child diagnostic containing private values must be suppressed by the script.
printf 'print -r -- %q >&2\n' "child diagnostic ${candidate_one_primary} synthetic-candidate-private-one" >> "${unique_candidate_mount}"

unique_candidate_stdout="${test_root}/unique-candidate.stdout"
unique_candidate_stderr="${test_root}/unique-candidate.stderr"
HOME="${test_root}/empty-home" \
  MONEYDANCE_MOUNT_BIN="${unique_candidate_mount}" \
  MONEYDANCE_RM_BIN="${candidate_rm}" \
  MONEYDANCE_FIND_BIN="${candidate_scan_spy}" \
  MONEYDANCE_STAT_BIN="${candidate_scan_spy}" \
  MONEYDANCE_LOGGER_BIN="${candidate_logger}" \
  "${SCRIPT}" --config "${candidate_config}" > "${unique_candidate_stdout}" 2> "${unique_candidate_stderr}"
unique_candidate_status=$?
unique_candidate_stdout_text="$(<"${unique_candidate_stdout}")"
unique_candidate_stderr_text="$(<"${unique_candidate_stderr}")"
candidate_log_text="$(<"${candidate_log}")"
candidate_logger_text="$(<"${candidate_logger_marker}")"
assert_status "one fully valid replacement candidate is recognized safely" 0 "${unique_candidate_status}"
assert_contains "unique replacement outcome offers explicit repair inspection" "${unique_candidate_stdout_text}" "--repair-config"
assert_file_exists "unique replacement discovery preserves candidate backups" "${candidate_one_backup_file}"
if [[ ! -e "${candidate_rm_marker}" ]]; then
  pass "unique replacement discovery never invokes removal"
else
  fail "unique replacement discovery never invokes removal"
fi
if [[ ! -e "${candidate_scan_marker}" ]]; then
  pass "unique replacement discovery never scans retention files"
else
  fail "unique replacement discovery never scans retention files"
fi
if [[ "$(<"${candidate_config}")" == "${candidate_config_before}" ]]; then
  pass "unique replacement discovery does not mutate configuration"
else
  fail "unique replacement discovery does not mutate configuration"
fi

typeset -a candidate_private_tokens=(
  synthetic-configured-private-host
  synthetic-candidate-private-one
  SYNTHETIC-PRIVATE-COMPANION
  SYNTHETIC-PRIVATE-PRIMARY
  SYNTHETIC-PRIVATE-BACKUPS
  SYNTHETIC-PRIVATE-CONFIG-PATH
  SYNTHETIC-PRIVATE-LOG-PATH
  "${candidate_config}"
  "${candidate_log}"
  "${candidate_one_primary}"
  "${candidate_one_companion}"
  "${candidate_one_backup_dir}"
)
for private_token in "${candidate_private_tokens[@]}"; do
  assert_not_contains "noninteractive stdout redacts ${private_token}" "${unique_candidate_stdout_text}" "${private_token}"
  assert_not_contains "noninteractive stderr redacts ${private_token}" "${unique_candidate_stderr_text}" "${private_token}"
  assert_not_contains "configured log redacts ${private_token}" "${candidate_log_text}" "${private_token}"
  assert_not_contains "logger diagnostic redacts ${private_token}" "${candidate_logger_text}" "${private_token}"
done

config_open_race_path="${candidate_config_dir}/SYNTHETIC-PRIVATE-CONFIG-RACE"
cp "${candidate_config}" "${config_open_race_path}"
config_open_zdotdir="${test_root}/config-open-zdotdir"
mkdir -p "${config_open_zdotdir}"
cat > "${config_open_zdotdir}/.zshenv" <<'EOF'
TRAPDEBUG() {
  case "${ZSH_DEBUG_CMD}" in
    ('[[ -f "${config_path}" && -r "${config_path}" ]]'*)
      SYNTHETIC_TEST_CONFIG_CHECKED=1
      ;;
    ('exec {config_stderr_fd}>&2'*|'while IFS= read -r raw_line'*)
      if [[ "${SYNTHETIC_TEST_CONFIG_CHECKED:-0}" -eq 1 ]]; then
        /bin/mv -- "${SYNTHETIC_TEST_CONFIG_RACE_PATH}" "${SYNTHETIC_TEST_CONFIG_RACE_PATH}.moved" 2>/dev/null
        unfunction TRAPDEBUG
      fi
      ;;
  esac
}
EOF
config_open_mount_marker="${test_root}/config-open-mount-called"
config_open_mount="${test_root}/config-open-mount"
make_mount_inventory_mock "${config_open_mount}" "${config_open_mount_marker}"
config_open_stdout="${test_root}/config-open.stdout"
config_open_stderr="${test_root}/config-open.stderr"
/usr/bin/env \
  ZDOTDIR="${config_open_zdotdir}" \
  SYNTHETIC_TEST_CONFIG_RACE_PATH="${config_open_race_path}" \
  HOME="${test_root}/empty-home" \
  MONEYDANCE_MOUNT_BIN="${config_open_mount}" \
  "${SCRIPT}" --config "${config_open_race_path}" > "${config_open_stdout}" 2> "${config_open_stderr}"
config_open_status=$?
config_open_stdout_text="$(<"${config_open_stdout}")"
config_open_stderr_text="$(<"${config_open_stderr}")"
assert_status "configuration descriptor-open failure uses configuration exit status" 2 "${config_open_status}"
assert_contains "configuration descriptor-open failure is generic" "${config_open_stderr_text}" "Configuration file could not be opened safely"
assert_not_contains "configuration descriptor-open stdout redacts private path" "${config_open_stdout_text}" "${config_open_race_path}"
assert_not_contains "configuration descriptor-open stderr redacts private path" "${config_open_stderr_text}" "${config_open_race_path}"
if [[ ! -e "${config_open_mount_marker}" ]]; then
  pass "configuration descriptor-open failure occurs before mount lookup"
else
  fail "configuration descriptor-open failure occurs before mount lookup"
fi

dirname_failure="${test_root}/dirname-failure"
cat > "${dirname_failure}" <<'EOF'
#!/bin/zsh
print -r -- "dirname child diagnostic $*" >&2
exit 91
EOF
chmod 755 "${dirname_failure}"
dirname_failure_stdout="${test_root}/dirname-failure.stdout"
dirname_failure_stderr="${test_root}/dirname-failure.stderr"
: > "${candidate_logger_marker}"
HOME="${test_root}/empty-home" \
  MONEYDANCE_MOUNT_BIN="${unique_candidate_mount}" \
  MONEYDANCE_DIRNAME_BIN="${dirname_failure}" \
  MONEYDANCE_LOGGER_BIN="${candidate_logger}" \
  "${SCRIPT}" --config "${candidate_config}" > "${dirname_failure_stdout}" 2> "${dirname_failure_stderr}"
dirname_failure_status=$?
dirname_failure_stdout_text="$(<"${dirname_failure_stdout}")"
dirname_failure_stderr_text="$(<"${dirname_failure_stderr}")"
dirname_failure_logger_text="$(<"${candidate_logger_marker}")"
assert_status "logging dirname failure is an operational error" 1 "${dirname_failure_status}"
assert_contains "logging dirname failure is replaced with generic text" "${dirname_failure_stderr_text}" "Unable to initialize private logging"
for private_token in "${candidate_private_tokens[@]}"; do
  assert_not_contains "dirname-failure stdout redacts ${private_token}" "${dirname_failure_stdout_text}" "${private_token}"
  assert_not_contains "dirname-failure stderr redacts ${private_token}" "${dirname_failure_stderr_text}" "${private_token}"
  assert_not_contains "dirname-failure logger redacts ${private_token}" "${dirname_failure_logger_text}" "${private_token}"
done

: > "${candidate_log}"
: > "${candidate_logger_marker}"
run_with_pty 10 both \
  /usr/bin/env \
  HOME="${test_root}/empty-home" \
  MONEYDANCE_MOUNT_BIN="${unique_candidate_mount}" \
  MONEYDANCE_RM_BIN="${candidate_rm}" \
  MONEYDANCE_FIND_BIN="${candidate_scan_spy}" \
  MONEYDANCE_STAT_BIN="${candidate_scan_spy}" \
  MONEYDANCE_LOGGER_BIN="${candidate_logger}" \
  "${SCRIPT}" --config "${candidate_config}"
pty_helper_status=$?
assert_status "PTY helper completes before its timeout" 0 "${pty_helper_status}"
assert_status "PTY helper returns the child status separately" 0 "${PTY_STATUS}"
assert_contains "terminal detail shows configured host" "${PTY_TRANSCRIPT}" "synthetic-configured-private-host"
assert_contains "terminal detail shows unique candidate" "${PTY_TRANSCRIPT}" "synthetic-candidate-private-one"
assert_contains "terminal detail preserves normalized required-share order" "${PTY_TRANSCRIPT}" "SYNTHETIC-PRIVATE-COMPANION, SYNTHETIC-PRIVATE-PRIMARY"
assert_contains "terminal detail shows validated backup directory" "${PTY_TRANSCRIPT}" "${candidate_one_backup_dir}"
assert_contains "terminal detail states that no files changed" "${PTY_TRANSCRIPT}" "No configuration or backup files were changed"
assert_contains "terminal detail instructs explicit repair mode" "${PTY_TRANSCRIPT}" "--repair-config"
candidate_pty_log_text="$(<"${candidate_log}")"
candidate_pty_logger_text="$(<"${candidate_logger_marker}")"
for private_token in "${candidate_private_tokens[@]}"; do
  assert_not_contains "post-PTY configured log redacts ${private_token}" "${candidate_pty_log_text}" "${private_token}"
  assert_not_contains "post-PTY logger diagnostic redacts ${private_token}" "${candidate_pty_logger_text}" "${private_token}"
done

run_with_pty 10 stdin-only \
  /usr/bin/env \
  HOME="${test_root}/empty-home" \
  MONEYDANCE_MOUNT_BIN="${unique_candidate_mount}" \
  MONEYDANCE_RM_BIN="${candidate_rm}" \
  MONEYDANCE_FIND_BIN="${candidate_scan_spy}" \
  MONEYDANCE_STAT_BIN="${candidate_scan_spy}" \
  MONEYDANCE_LOGGER_BIN="${candidate_logger}" \
  "${SCRIPT}" --config "${candidate_config}"
assert_status "stdin-only PTY invocation completes" 0 "$?"
assert_status "stdin-only PTY child exits safely" 0 "${PTY_STATUS}"
assert_not_contains "TTY stdin cannot expose details through non-TTY stdout" "${PTY_NONTTY_STDOUT}" "synthetic-configured-private-host"
assert_not_contains "TTY stderr cannot expose details when stdout is non-TTY" "${PTY_TRANSCRIPT}" "synthetic-candidate-private-one"

run_with_pty 10 stdout-only \
  /usr/bin/env \
  HOME="${test_root}/empty-home" \
  MONEYDANCE_MOUNT_BIN="${unique_candidate_mount}" \
  MONEYDANCE_RM_BIN="${candidate_rm}" \
  MONEYDANCE_FIND_BIN="${candidate_scan_spy}" \
  MONEYDANCE_STAT_BIN="${candidate_scan_spy}" \
  MONEYDANCE_LOGGER_BIN="${candidate_logger}" \
  "${SCRIPT}" --config "${candidate_config}"
assert_status "stdout-only PTY invocation completes" 0 "$?"
assert_status "stdout-only PTY child exits safely" 0 "${PTY_STATUS}"
assert_contains "TTY stdout permits details when stdin is non-TTY" "${PTY_TRANSCRIPT}" "synthetic-candidate-private-one"

partial_candidate_mount="${test_root}/partial-candidate-mount"
make_mount_inventory_mock \
  "${partial_candidate_mount}" \
  "${test_root}/partial-candidate-mount-called" \
  "//synthetic-partial-private-host/SYNTHETIC-PRIVATE-PRIMARY on ${partial_candidate_primary} (smbfs)"
partial_candidate_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${partial_candidate_mount}" MONEYDANCE_RM_BIN="${candidate_rm}" MONEYDANCE_FIND_BIN="${candidate_scan_spy}" MONEYDANCE_STAT_BIN="${candidate_scan_spy}" MONEYDANCE_LOGGER_BIN="${candidate_logger}" "${SCRIPT}" --config "${candidate_config}" 2>&1)"
partial_candidate_status=$?
assert_status "partial replacement host is a safe no-op" 0 "${partial_candidate_status}"
assert_not_contains "partial replacement host produces no repair recommendation" "${partial_candidate_output}" "--repair-config"
assert_file_exists "partial replacement host preserves backups" "${partial_backup_file}"
if [[ ! -e "${candidate_scan_marker}" ]]; then
  pass "zero-candidate mismatch never scans retention files"
else
  fail "zero-candidate mismatch never scans retention files"
fi

split_candidate_mount="${test_root}/split-candidate-mount"
make_mount_inventory_mock \
  "${split_candidate_mount}" \
  "${test_root}/split-candidate-mount-called" \
  "//synthetic-split-private-a/SYNTHETIC-PRIVATE-PRIMARY on ${partial_candidate_primary} (smbfs)" \
  "//synthetic-split-private-b/SYNTHETIC-PRIVATE-COMPANION on ${split_candidate_companion} (smbfs)"
split_candidate_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${split_candidate_mount}" MONEYDANCE_RM_BIN="${candidate_rm}" MONEYDANCE_LOGGER_BIN="${candidate_logger}" "${SCRIPT}" --config "${candidate_config}" 2>&1)"
split_candidate_status=$?
assert_status "shares split across replacement hosts are a safe no-op" 0 "${split_candidate_status}"
assert_not_contains "split replacement shares produce no repair recommendation" "${split_candidate_output}" "--repair-config"
assert_file_exists "split replacement shares preserve backups" "${partial_backup_file}"

invalid_directory_mount="${test_root}/invalid-directory-candidate-mount"
make_mount_inventory_mock \
  "${invalid_directory_mount}" \
  "${test_root}/invalid-directory-candidate-mount-called" \
  "//synthetic-invalid-private-host/SYNTHETIC-PRIVATE-COMPANION on ${split_candidate_companion} (smbfs)" \
  "//synthetic-invalid-private-host/SYNTHETIC-PRIVATE-PRIMARY on ${invalid_candidate_primary} (smbfs)"
invalid_directory_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${invalid_directory_mount}" MONEYDANCE_RM_BIN="${candidate_rm}" MONEYDANCE_LOGGER_BIN="${candidate_logger}" "${SCRIPT}" --config "${candidate_config}" 2>&1)"
invalid_directory_status=$?
assert_status "replacement with invalid backup directory is a safe no-op" 0 "${invalid_directory_status}"
assert_not_contains "invalid replacement directory produces no repair recommendation" "${invalid_directory_output}" "--repair-config"
assert_file_exists "invalid replacement directory preserves unrelated backups" "${candidate_one_backup_file}"

multiple_candidate_mount="${test_root}/multiple-candidate-mount"
make_mount_inventory_mock \
  "${multiple_candidate_mount}" \
  "${test_root}/multiple-candidate-mount-called" \
  "//synthetic-candidate-private-two/SYNTHETIC-PRIVATE-PRIMARY on ${candidate_two_primary} (smbfs)" \
  "//synthetic-candidate-private-one/SYNTHETIC-PRIVATE-COMPANION on ${candidate_one_companion} (smbfs)" \
  "//synthetic-candidate-private-two/SYNTHETIC-PRIVATE-COMPANION on ${candidate_two_companion} (smbfs)" \
  "//synthetic-candidate-private-one/SYNTHETIC-PRIVATE-PRIMARY on ${candidate_one_primary} (smbfs)"
multiple_candidate_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${multiple_candidate_mount}" MONEYDANCE_RM_BIN="${candidate_rm}" MONEYDANCE_FIND_BIN="${candidate_scan_spy}" MONEYDANCE_STAT_BIN="${candidate_scan_spy}" MONEYDANCE_LOGGER_BIN="${candidate_logger}" "${SCRIPT}" --config "${candidate_config}" 2>&1)"
multiple_candidate_status=$?
assert_status "multiple fully valid replacement hosts are a safe no-op" 0 "${multiple_candidate_status}"
assert_not_contains "multiple candidates produce no repair recommendation" "${multiple_candidate_output}" "--repair-config"
assert_file_exists "multiple candidate outcome preserves first candidate backup" "${candidate_one_backup_file}"
assert_file_exists "multiple candidate outcome preserves second candidate backup" "${candidate_two_backup_file}"
if [[ ! -e "${candidate_scan_marker}" ]]; then
  pass "multiple-candidate mismatch never scans retention files"
else
  fail "multiple-candidate mismatch never scans retention files"
fi
if [[ ! -e "${candidate_rm_marker}" ]]; then
  pass "every replacement-discovery outcome avoids removal"
else
  fail "every replacement-discovery outcome avoids removal"
fi
if [[ "$(<"${candidate_config}")" == "${candidate_config_before}" ]]; then
  pass "every replacement-discovery outcome leaves configuration unchanged"
else
  fail "every replacement-discovery outcome leaves configuration unchanged"
fi

run_with_pty 10 both \
  /usr/bin/env \
  HOME="${test_root}/empty-home" \
  MONEYDANCE_MOUNT_BIN="${multiple_candidate_mount}" \
  MONEYDANCE_RM_BIN="${candidate_rm}" \
  MONEYDANCE_FIND_BIN="${candidate_scan_spy}" \
  MONEYDANCE_STAT_BIN="${candidate_scan_spy}" \
  MONEYDANCE_LOGGER_BIN="${candidate_logger}" \
  "${SCRIPT}" --config "${candidate_config}"
assert_status "multiple-candidate PTY helper completes before timeout" 0 "$?"
assert_status "multiple-candidate PTY invocation exits safely" 0 "${PTY_STATUS}"
assert_contains "multiple candidates retain mount-table first-seen order" "${PTY_TRANSCRIPT}" "synthetic-candidate-private-two, synthetic-candidate-private-one"
assert_not_contains "multiple-candidate terminal gives no unique repair instruction" "${PTY_TRANSCRIPT}" "--repair-config"

complete_inventory_marker="${test_root}/complete-inventory-called"
complete_inventory_mount="${test_root}/complete-inventory-mount"
make_mount_inventory_mock \
  "${complete_inventory_mount}" \
  "${complete_inventory_marker}" \
  "//synthetic-nas/SYNTHETIC_SHARE on ${escaped_inventory_mount_point} (smbfs)" \
  "//synthetic-nas/SYNTHETIC_COMPANION on ${escaped_inventory_companion_mount_point} (smbfs)"
reset_inventory_candidate
complete_inventory_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${complete_inventory_mount}" "${SCRIPT}" --config "${inventory_config}" 2>&1)"
complete_inventory_status=$?
assert_status "all required shares on the configured host allow retention analysis" 0 "${complete_inventory_status}"
assert_file_missing "complete configured-host mount set permits deletion" "${inventory_old_file}"

missing_companion_marker="${test_root}/missing-companion-called"
missing_companion_mount="${test_root}/missing-companion-mount"
make_mount_inventory_mock \
  "${missing_companion_mount}" \
  "${missing_companion_marker}" \
  "//synthetic-nas/SYNTHETIC_SHARE on ${escaped_inventory_mount_point} (smbfs)"
reset_inventory_candidate
missing_companion_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${missing_companion_mount}" "${SCRIPT}" --config "${inventory_config}" 2>&1)"
assert_status "missing companion share is a safe no-op" 0 "$?"
assert_file_exists "missing companion share preserves purge candidates" "${inventory_old_file}"

missing_primary_marker="${test_root}/missing-primary-called"
missing_primary_mount="${test_root}/missing-primary-mount"
make_mount_inventory_mock \
  "${missing_primary_mount}" \
  "${missing_primary_marker}" \
  "//synthetic-nas/SYNTHETIC_COMPANION on ${escaped_inventory_companion_mount_point} (smbfs)"
reset_inventory_candidate
missing_primary_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${missing_primary_mount}" "${SCRIPT}" --config "${inventory_config}" 2>&1)"
assert_status "missing primary share is a safe no-op" 0 "$?"
assert_file_exists "missing primary share preserves purge candidates" "${inventory_old_file}"

split_hosts_marker="${test_root}/split-hosts-called"
split_hosts_mount="${test_root}/split-hosts-mount"
make_mount_inventory_mock \
  "${split_hosts_mount}" \
  "${split_hosts_marker}" \
  "//synthetic-nas/SYNTHETIC_SHARE on ${escaped_inventory_mount_point} (smbfs)" \
  "//synthetic-other/SYNTHETIC_COMPANION on ${escaped_inventory_companion_mount_point} (smbfs)"
reset_inventory_candidate
split_hosts_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${split_hosts_mount}" "${SCRIPT}" --config "${inventory_config}" 2>&1)"
assert_status "required shares split across hosts are a safe no-op" 0 "$?"
assert_file_exists "split-host required shares preserve purge candidates" "${inventory_old_file}"

near_match_marker="${test_root}/near-match-called"
near_match_mount="${test_root}/near-match-mount"
make_mount_inventory_mock \
  "${near_match_mount}" \
  "${near_match_marker}" \
  "//synthetic-nas-extra/SYNTHETIC_SHARE on ${escaped_inventory_mount_point} (smbfs)" \
  "//Synthetic-nas/SYNTHETIC_SHARE on ${escaped_inventory_mount_point} (smbfs)" \
  "//synthetic-nas/SYNTHETIC_SHARE_EXTRA on ${escaped_inventory_mount_point} (smbfs)" \
  "//synthetic-nas/synthetic_share on ${escaped_inventory_mount_point} (smbfs)" \
  "//synthetic-nas/SYNTHETIC_COMPAN on ${escaped_inventory_companion_mount_point} (smbfs)"
reset_inventory_candidate
near_match_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${near_match_mount}" "${SCRIPT}" --config "${inventory_config}" 2>&1)"
assert_status "similar and differently cased host and share names are a safe no-op" 0 "$?"
assert_file_exists "near-match host and share names preserve purge candidates" "${inventory_old_file}"

spaced_inventory_config="${test_root}/spaced-inventory-config"
cat > "${spaced_inventory_config}" <<'EOF'
NAS_SERVER=synthetic-nas
NAS_SHARE_NAME=SYNTHETIC PRIMARY
REQUIRED_NAS_SHARES=SYNTHETIC PRIMARY,SYNTHETIC COMPANION
BACKUP_DIRECTORY_NAME=SYNTHETIC_BACKUPS
BACKUP_FILENAME_SUFFIX=.SYNTHETIC-BACKUP
MAX_DAYS_TO_KEEP=2
DRY_RUN=0
USE_SYSLOG=0
EOF
qualified_inventory_marker="${test_root}/qualified-inventory-called"
qualified_inventory_mount="${test_root}/qualified-inventory-mount"
make_mount_inventory_mock \
  "${qualified_inventory_mount}" \
  "${qualified_inventory_marker}" \
  "//synthetic-user@synthetic-nas/SYNTHETIC\\040PRIMARY on ${escaped_inventory_mount_point} (smbfs, nodev)" \
  "//synthetic-user@synthetic-nas/SYNTHETIC\\040COMPANION on ${escaped_inventory_companion_mount_point} (smbfs, nodev)"
reset_inventory_candidate
qualified_inventory_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${qualified_inventory_mount}" "${SCRIPT}" --config "${spaced_inventory_config}" 2>&1)"
assert_status "qualified sources and literal escaped spaces work for both required shares" 0 "$?"
assert_file_missing "qualified escaped complete mount set permits deletion" "${inventory_old_file}"

other_host_primary="${test_root}/other-host-primary"
other_host_companion="${test_root}/other-host-companion"
mkdir -p "${other_host_primary}" "${other_host_companion}"
coexisting_hosts_marker="${test_root}/coexisting-hosts-called"
coexisting_hosts_mount="${test_root}/coexisting-hosts-mount"
make_mount_inventory_mock \
  "${coexisting_hosts_mount}" \
  "${coexisting_hosts_marker}" \
  "//synthetic-other/SYNTHETIC_SHARE on ${other_host_primary} (smbfs)" \
  "//synthetic-other/SYNTHETIC_COMPANION on ${other_host_companion} (smbfs)" \
  "//synthetic-nas/SYNTHETIC_SHARE on ${escaped_inventory_mount_point} (smbfs)" \
  "//synthetic-nas/SYNTHETIC_COMPANION on ${escaped_inventory_companion_mount_point} (smbfs)"
reset_inventory_candidate
coexisting_hosts_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${coexisting_hosts_mount}" "${SCRIPT}" --config "${inventory_config}" 2>&1)"
assert_status "configured host wins when another complete host coexists" 0 "$?"
assert_file_missing "configured complete host binds retention to its primary share" "${inventory_old_file}"

companion_backup_mount_point="${test_root}/companion-backup-mount"
companion_backup_dir="${companion_backup_mount_point}/SYNTHETIC_BACKUPS"
primary_without_backup="${test_root}/primary-without-backup"
mkdir -p "${companion_backup_dir}" "${primary_without_backup}"
companion_backup_candidate="${companion_backup_dir}/SYNTHETIC-OLD.SYNTHETIC-BACKUP"
touch -t 203701010101 "${companion_backup_candidate}"
touch -t 203701020101 "${companion_backup_dir}/SYNTHETIC-MIDDLE.SYNTHETIC-BACKUP"
touch -t 203701030101 "${companion_backup_dir}/SYNTHETIC-NEW.SYNTHETIC-BACKUP"
primary_binding_marker="${test_root}/primary-binding-called"
primary_binding_mount="${test_root}/primary-binding-mount"
make_mount_inventory_mock \
  "${primary_binding_mount}" \
  "${primary_binding_marker}" \
  "//synthetic-nas/SYNTHETIC_COMPANION on ${companion_backup_mount_point} (smbfs)" \
  "//synthetic-nas/SYNTHETIC_SHARE on ${primary_without_backup} (smbfs)"
primary_binding_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${primary_binding_mount}" "${SCRIPT}" --config "${inventory_config}" 2>&1)"
assert_status "backup directory is validated only under the primary share" 0 "$?"
assert_file_exists "companion-share backup directory is never purged" "${companion_backup_candidate}"

duplicate_primary_marker="${test_root}/duplicate-primary-called"
duplicate_primary_mount="${test_root}/duplicate-primary-mount"
make_mount_inventory_mock \
  "${duplicate_primary_mount}" \
  "${duplicate_primary_marker}" \
  "//synthetic-nas/SYNTHETIC_SHARE on ${escaped_inventory_mount_point} (smbfs)" \
  "//synthetic-nas/SYNTHETIC_SHARE on ${test_root}/inaccessible-duplicate (smbfs)" \
  "//synthetic-nas/SYNTHETIC_COMPANION on ${escaped_inventory_companion_mount_point} (smbfs)"
reset_inventory_candidate
duplicate_primary_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${duplicate_primary_mount}" "${SCRIPT}" --config "${inventory_config}" 2>&1)"
assert_status "duplicate primary mounts are a safe no-op" 0 "$?"
assert_file_exists "accessible plus inaccessible primary duplicates preserve candidates" "${inventory_old_file}"

duplicate_companion_marker="${test_root}/duplicate-companion-called"
duplicate_companion_mount="${test_root}/duplicate-companion-mount"
make_mount_inventory_mock \
  "${duplicate_companion_mount}" \
  "${duplicate_companion_marker}" \
  "//synthetic-nas/SYNTHETIC_SHARE on ${escaped_inventory_mount_point} (smbfs)" \
  "//synthetic-nas/SYNTHETIC_COMPANION on ${escaped_inventory_companion_mount_point} (smbfs)" \
  "//synthetic-nas/SYNTHETIC_COMPANION on ${test_root}/inaccessible-companion-duplicate (smbfs)"
reset_inventory_candidate
duplicate_companion_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${duplicate_companion_mount}" "${SCRIPT}" --config "${inventory_config}" 2>&1)"
assert_status "duplicate companion mounts are a safe no-op" 0 "$?"
assert_file_exists "companion duplicates preserve purge candidates" "${inventory_old_file}"

ignored_lines_marker="${test_root}/ignored-lines-called"
ignored_lines_mount="${test_root}/ignored-lines-mount"
make_mount_inventory_mock \
  "${ignored_lines_mount}" \
  "${ignored_lines_marker}" \
  "//synthetic-nas/SYNTHETIC_SHARE on ${escaped_inventory_mount_point} (apfs, local)" \
  "//synthetic-nas/SYNTHETIC_SHARE ${escaped_inventory_mount_point} (smbfs)" \
  "malformed //synthetic-nas/SYNTHETIC_SHARE on ${escaped_inventory_mount_point}" \
  "//synthetic-nas/SYNTHETIC_COMPANION on ${escaped_inventory_companion_mount_point} (smbfs)"
reset_inventory_candidate
ignored_lines_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${ignored_lines_mount}" "${SCRIPT}" --config "${inventory_config}" 2>&1)"
assert_status "malformed and non-SMB mount lines are ignored safely" 0 "$?"
assert_file_exists "ignored mount-like lines cannot authorize deletion" "${inventory_old_file}"

late_smbfs_marker="${test_root}/late-smbfs-called"
late_smbfs_mount="${test_root}/late-smbfs-mount"
make_mount_inventory_mock \
  "${late_smbfs_mount}" \
  "${late_smbfs_marker}" \
  "//synthetic-nas/SYNTHETIC_SHARE on ${escaped_inventory_mount_point} (apfs, local, smbfs)" \
  "//synthetic-nas/SYNTHETIC_COMPANION on ${escaped_inventory_companion_mount_point} (apfs, local, smbfs)"
reset_inventory_candidate
late_smbfs_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${late_smbfs_mount}" "${SCRIPT}" --config "${inventory_config}" 2>&1)"
assert_status "later smbfs option under a non-SMB type is ignored safely" 0 "$?"
assert_file_exists "later smbfs option cannot authorize deletion" "${inventory_old_file}"

spaced_smbfs_type_marker="${test_root}/spaced-smbfs-type-called"
spaced_smbfs_type_mount="${test_root}/spaced-smbfs-type-mount"
make_mount_inventory_mock \
  "${spaced_smbfs_type_mount}" \
  "${spaced_smbfs_type_marker}" \
  "//synthetic-nas/SYNTHETIC_SHARE on ${escaped_inventory_mount_point} ( smbfs, nodev )" \
  "//synthetic-nas/SYNTHETIC_COMPANION on ${escaped_inventory_companion_mount_point} ( smbfs, nodev )"
reset_inventory_candidate
spaced_smbfs_type_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${spaced_smbfs_type_mount}" "${SCRIPT}" --config "${inventory_config}" 2>&1)"
assert_status "first SMB type tolerates ordinary surrounding spaces" 0 "$?"
assert_file_missing "spaced first SMB type permits deletion" "${inventory_old_file}"

empty_user_marker="${test_root}/empty-user-called"
empty_user_mount="${test_root}/empty-user-mount"
make_mount_inventory_mock \
  "${empty_user_mount}" \
  "${empty_user_marker}" \
  "//@synthetic-nas/SYNTHETIC_SHARE on ${escaped_inventory_mount_point} (smbfs)" \
  "//@synthetic-nas/SYNTHETIC_COMPANION on ${escaped_inventory_companion_mount_point} (smbfs)"
reset_inventory_candidate
empty_user_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${empty_user_mount}" "${SCRIPT}" --config "${inventory_config}" 2>&1)"
assert_status "empty-user SMB authorities are ignored safely" 0 "$?"
assert_file_exists "empty-user SMB authorities cannot authorize deletion" "${inventory_old_file}"

multiple_at_marker="${test_root}/multiple-at-called"
multiple_at_mount="${test_root}/multiple-at-mount"
make_mount_inventory_mock \
  "${multiple_at_mount}" \
  "${multiple_at_marker}" \
  "//synthetic-user@@synthetic-nas/SYNTHETIC_SHARE on ${escaped_inventory_mount_point} (smbfs)" \
  "//synthetic-user@@synthetic-nas/SYNTHETIC_COMPANION on ${escaped_inventory_companion_mount_point} (smbfs)"
reset_inventory_candidate
multiple_at_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${multiple_at_mount}" "${SCRIPT}" --config "${inventory_config}" 2>&1)"
assert_status "multiple-at SMB authorities are ignored safely" 0 "$?"
assert_file_exists "multiple-at SMB authorities cannot authorize deletion" "${inventory_old_file}"

empty_host_marker="${test_root}/empty-host-called"
empty_host_mount="${test_root}/empty-host-mount"
make_mount_inventory_mock \
  "${empty_host_mount}" \
  "${empty_host_marker}" \
  "//synthetic-user@/SYNTHETIC_SHARE on ${escaped_inventory_mount_point} (smbfs)" \
  "//synthetic-user@/SYNTHETIC_COMPANION on ${escaped_inventory_companion_mount_point} (smbfs)"
reset_inventory_candidate
empty_host_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${empty_host_mount}" "${SCRIPT}" --config "${inventory_config}" 2>&1)"
assert_status "empty-host SMB authorities are ignored safely" 0 "$?"
assert_file_exists "empty-host SMB authorities cannot authorize deletion" "${inventory_old_file}"

reset_inventory_candidate
/bin/rm -f -- "${complete_inventory_marker}"
single_read_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${complete_inventory_mount}" "${SCRIPT}" --config "${inventory_config}" --dry-run 2>&1)"
single_read_status=$?
assert_status "single mount-table read run succeeds" 0 "${single_read_status}"
mount_invocation_count="$(wc -l < "${complete_inventory_marker}" | tr -d '[:space:]')"
if [[ "${mount_invocation_count}" -eq 1 ]]; then
  pass "mount command is invoked exactly once per run"
else
  fail "mount command is invoked exactly once per run (got ${mount_invocation_count})"
fi

linked_backup_target="${test_root}/misconfigured-outside"
mkdir -p "${linked_backup_target}"
linked_backup_file="${linked_backup_target}/OUTSIDE.SYNTHETIC-BACKUP"
touch -t 203501010101 "${linked_backup_file}"
ln -s "${linked_backup_target}" "${mount_point}/SYNTHETIC_LINK"
linked_config="${test_root}/linked-config"
cat > "${linked_config}" <<'EOF'
NAS_SERVER=synthetic-nas
NAS_SHARE_NAME=SYNTHETIC_SHARE
REQUIRED_NAS_SHARES=SYNTHETIC_SHARE,SYNTHETIC_COMPANION
BACKUP_DIRECTORY_NAME=SYNTHETIC_LINK
BACKUP_FILENAME_SUFFIX=.SYNTHETIC-BACKUP
MAX_DAYS_TO_KEEP=1
DRY_RUN=0
EOF
linked_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${mount_mock}" "${SCRIPT}" --config "${linked_config}" 2>&1)"
linked_status=$?
assert_status "symbolic-link backup directory is rejected safely" 0 "${linked_status}"
assert_file_exists "misconfigured linked directory cannot delete outside files" "${linked_backup_file}"

dry_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${mount_mock}" "${SCRIPT}" --config "${config}" --dry-run 2>&1)"
dry_status=$?
if [[ "${dry_status}" -eq 0 ]]; then
  pass "configured dry run succeeds"
else
  fail "configured dry run succeeds (status ${dry_status}: ${dry_output})"
fi
assert_file_exists "dry run preserves purge candidate" "${old_file}"
assert_contains "dry run reports that no files were deleted" "${dry_output}" "no files were deleted"
assert_not_contains "dry run does not print backup filenames" "${dry_output}" "${private_name}"

unqualified_marker="${test_root}/unqualified-mount-called"
unqualified_mount="${test_root}/unqualified-mount"
escaped_mount_point="${mount_point// /\\040}"
make_mount_mock "${unqualified_mount}" "${escaped_mount_point}" "${unqualified_marker}"
unqualified_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${unqualified_mount}" "${SCRIPT}" --config "${config}" --dry-run 2>&1)"
unqualified_status=$?
assert_status "unqualified exact SMB mount is accepted" 0 "${unqualified_status}"
assert_contains "unqualified mount reaches retention analysis" "${unqualified_output}" "Dry run enabled"

spaced_share_config="${test_root}/spaced-share-config"
cat > "${spaced_share_config}" <<'EOF'
NAS_SERVER=synthetic-nas
NAS_SHARE_NAME=SYNTHETIC SHARE
REQUIRED_NAS_SHARES=SYNTHETIC SHARE,SYNTHETIC_COMPANION
BACKUP_DIRECTORY_NAME=SYNTHETIC_BACKUPS
BACKUP_FILENAME_SUFFIX=.SYNTHETIC-BACKUP
MAX_DAYS_TO_KEEP=2
DRY_RUN=1
USE_SYSLOG=0
EOF

qualified_spaced_marker="${test_root}/qualified-spaced-mount-called"
qualified_spaced_mount="${test_root}/qualified-spaced-mount"
make_mount_mock \
  "${qualified_spaced_mount}" \
  "${escaped_mount_point}" \
  "${qualified_spaced_marker}" \
  '//synthetic-user@synthetic-nas/SYNTHETIC\040SHARE'
qualified_spaced_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${qualified_spaced_mount}" "${SCRIPT}" --config "${spaced_share_config}" 2>&1)"
qualified_spaced_status=$?
assert_status "username-qualified SMB source accepts an escaped share-name space" 0 "${qualified_spaced_status}"
assert_contains "qualified escaped share reaches retention analysis" "${qualified_spaced_output}" "Dry run enabled"

unqualified_spaced_marker="${test_root}/unqualified-spaced-mount-called"
unqualified_spaced_mount="${test_root}/unqualified-spaced-mount"
make_mount_mock \
  "${unqualified_spaced_mount}" \
  "${escaped_mount_point}" \
  "${unqualified_spaced_marker}" \
  '//synthetic-nas/SYNTHETIC\040SHARE'
unqualified_spaced_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${unqualified_spaced_mount}" "${SCRIPT}" --config "${spaced_share_config}" 2>&1)"
unqualified_spaced_status=$?
assert_status "unqualified SMB source accepts an escaped share-name space" 0 "${unqualified_spaced_status}"
assert_contains "unqualified escaped share reaches retention analysis" "${unqualified_spaced_output}" "Dry run enabled"

wrong_mount_marker="${test_root}/wrong-mount-called"
wrong_mount="${test_root}/wrong-mount"
make_mount_mock "${wrong_mount}" "${mount_point}" "${wrong_mount_marker}" "//synthetic-user@synthetic-nas-extra/SYNTHETIC_SHARE"
wrong_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${wrong_mount}" "${SCRIPT}" --config "${config}" 2>&1)"
wrong_status=$?
assert_status "similar but nonexact SMB host is rejected safely" 0 "${wrong_status}"
assert_file_exists "nonexact SMB host cannot trigger deletion" "${old_file}"

stat_fail="${test_root}/stat-fail"
cat > "${stat_fail}" <<'EOF'
#!/bin/zsh
exit 1
EOF
chmod 755 "${stat_fail}"
stat_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${mount_mock}" MONEYDANCE_STAT_BIN="${stat_fail}" "${SCRIPT}" --config "${config}" 2>&1)"
stat_status=$?
if [[ "${stat_status}" -ne 0 ]]; then
  pass "unclassifiable file metadata fails closed"
else
  fail "unclassifiable file metadata fails closed"
fi
assert_file_exists "metadata failure prevents deletion" "${old_file}"
assert_not_contains "metadata failure does not print backup filename" "${stat_output}" "${private_name}"

date_fail="${test_root}/date-fail"
cat > "${date_fail}" <<'EOF'
#!/bin/zsh
if [[ "$1" == "-u" ]]; then
  /bin/date "$@"
else
  exit 1
fi
EOF
chmod 755 "${date_fail}"
date_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${mount_mock}" MONEYDANCE_DATE_BIN="${date_fail}" "${SCRIPT}" --config "${config}" 2>&1)"
date_status=$?
if [[ "${date_status}" -ne 0 ]]; then
  pass "unclassifiable file date fails closed"
else
  fail "unclassifiable file date fails closed"
fi
assert_file_exists "date classification failure prevents deletion" "${old_file}"
assert_not_contains "date failure does not print backup filename" "${date_output}" "${private_name}"

env_output="$(
  HOME="${test_root}/empty-home" \
  MONEYDANCE_MOUNT_BIN="${mount_mock}" \
  MONEYDANCE_NAS_SERVER="synthetic-nas" \
  MONEYDANCE_NAS_SHARE_NAME="SYNTHETIC_SHARE" \
  MONEYDANCE_REQUIRED_NAS_SHARES="SYNTHETIC_SHARE,SYNTHETIC_COMPANION" \
  MONEYDANCE_BACKUP_DIRECTORY_NAME="SYNTHETIC_BACKUPS" \
  MONEYDANCE_BACKUP_FILENAME_SUFFIX=".SYNTHETIC-BACKUP" \
  MONEYDANCE_MAX_DAYS_TO_KEEP=2 \
  "${SCRIPT}" 2>&1
)"
env_status=$?
assert_status "environment-only configuration succeeds" 0 "${env_status}"
assert_file_exists "environment-only invocation defaults to dry run" "${old_file}"
assert_contains "safe default reports dry run" "${env_output}" "Dry run enabled"

missing_env_required_shares_marker="${test_root}/missing-env-required-shares-mount-called"
missing_env_required_shares_mount="${test_root}/missing-env-required-shares-mount"
make_mount_mock "${missing_env_required_shares_mount}" "${mount_point}" "${missing_env_required_shares_marker}"
missing_env_required_shares_output="$(
  HOME="${test_root}/empty-home" \
  MONEYDANCE_MOUNT_BIN="${missing_env_required_shares_mount}" \
  MONEYDANCE_NAS_SERVER="synthetic-nas" \
  MONEYDANCE_NAS_SHARE_NAME="SYNTHETIC_SHARE" \
  MONEYDANCE_BACKUP_DIRECTORY_NAME="SYNTHETIC_BACKUPS" \
  MONEYDANCE_BACKUP_FILENAME_SUFFIX=".SYNTHETIC-BACKUP" \
  "${SCRIPT}" 2>&1
)"
missing_env_required_shares_status=$?
assert_status "environment-only configuration requires REQUIRED_NAS_SHARES" 2 "${missing_env_required_shares_status}"
if [[ ! -e "${missing_env_required_shares_marker}" ]]; then
  pass "environment-only missing REQUIRED_NAS_SHARES fails before mount lookup"
else
  fail "environment-only missing REQUIRED_NAS_SHARES fails before mount lookup"
fi

find_fail="${test_root}/find-fail"
cat > "${find_fail}" <<'EOF'
#!/bin/zsh
exit 17
EOF
chmod 755 "${find_fail}"
find_fail_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${mount_mock}" MONEYDANCE_FIND_BIN="${find_fail}" "${SCRIPT}" --config "${config}" 2>&1)"
find_fail_status=$?
if [[ "${find_fail_status}" -ne 0 ]]; then
  pass "find failure exits nonzero"
else
  fail "find failure exits nonzero"
fi
assert_contains "find failure is visibly reported" "${find_fail_output}" "Failed to enumerate backup files"
assert_file_exists "find failure prevents candidate deletion" "${old_file}"
assert_file_exists "find failure preserves retained files" "${middle_file}"
assert_file_exists "find failure preserves the newest retained file" "${new_file}"
assert_file_exists "find failure preserves nonmatching files" "${nonmatching_file}"

rm_fail="${test_root}/rm-fail"
cat > "${rm_fail}" <<'EOF'
#!/bin/zsh
exit 19
EOF
chmod 755 "${rm_fail}"
rm_fail_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${mount_mock}" MONEYDANCE_RM_BIN="${rm_fail}" "${SCRIPT}" --config "${config}" 2>&1)"
rm_fail_status=$?
if [[ "${rm_fail_status}" -ne 0 ]]; then
  pass "removal failure exits nonzero"
else
  fail "removal failure exits nonzero"
fi
assert_contains "removal failure is visibly reported" "${rm_fail_output}" "could not be safely revalidated or removed"
assert_file_exists "removal failure preserves purge candidate" "${old_file}"
assert_file_exists "removal failure preserves retained files" "${middle_file}"
assert_file_exists "removal failure preserves the newest retained file" "${new_file}"
assert_file_exists "removal failure preserves nonmatching files" "${nonmatching_file}"

standalone_dir="${test_root}/Library/Scripts"
mkdir -p "${standalone_dir}"
standalone_script="${standalone_dir}/moneydance_rotate_backups.sh"
cp "${SCRIPT}" "${standalone_script}"
chmod 755 "${standalone_script}"
standalone_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${mount_mock}" "${standalone_script}" --config "${config}" --dry-run 2>&1)"
standalone_status=$?
assert_status "copied standalone script has no repository dependency" 0 "${standalone_status}"
assert_contains "standalone copy performs retention analysis" "${standalone_output}" "Dry run enabled"

standalone_home="${test_root}/standalone-home"
standalone_default_config_dir="${standalone_home}/.config/moneydance-backup-rotation"
mkdir -p "${standalone_default_config_dir}"
make_config "${standalone_default_config_dir}/config" 1
standalone_default_output="$(HOME="${standalone_home}" MONEYDANCE_MOUNT_BIN="${mount_mock}" "${standalone_script}" 2>&1)"
standalone_default_status=$?
assert_status "copied script loads default config from temporary HOME" 0 "${standalone_default_status}"
assert_contains "copied script default config performs retention analysis" "${standalone_default_output}" "Dry run enabled"

race_stat="${test_root}/race-stat"
race_seen="${test_root}/race-stat-seen"
cat > "${race_stat}" <<EOF
#!/bin/zsh
if [[ "\${3:-}" == "${old_file}" ]]; then
  if [[ -e "${race_seen}" ]]; then
    /usr/bin/touch -t 203701030101 "${old_file}"
  else
    /usr/bin/touch "${race_seen}"
  fi
fi
exec /usr/bin/stat "\$@"
EOF
chmod 755 "${race_stat}"
race_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${mount_mock}" MONEYDANCE_STAT_BIN="${race_stat}" "${SCRIPT}" --config "${config}" 2>&1)"
race_status=$?
assert_status "candidate eligibility is revalidated before deletion" 0 "${race_status}"
assert_file_exists "candidate moved into a retained day is not deleted" "${old_file}"
assert_contains "changed purge-day candidate is visibly skipped" "${race_output}" "Skipped 1 candidate"
touch -t 203701010101 "${old_file}"

outside_dir="${test_root}/outside-backup-tree"
mkdir -p "${outside_dir}"
outside_file="${outside_dir}/OUTSIDE.SYNTHETIC-BACKUP"
touch -t 203501010101 "${outside_file}"
linked_dir="${backup_dir}/LINKED-DIRECTORY"
ln -s "${outside_dir}" "${linked_dir}"
linked_file="${backup_dir}/LINKED-FILE.SYNTHETIC-BACKUP"
ln -s "${outside_file}" "${linked_file}"

run_output="$(HOME="${test_root}/empty-home" MONEYDANCE_MOUNT_BIN="${mount_mock}" "${SCRIPT}" --config "${config}" 2>&1)"
run_status=$?
if [[ "${run_status}" -eq 0 ]]; then
  pass "configured normal run succeeds"
else
  fail "configured normal run succeeds (status ${run_status}: ${run_output})"
fi
assert_file_missing "normal run removes only the oldest retained day" "${old_file}"
assert_file_exists "normal run preserves middle day" "${middle_file}"
assert_file_exists "normal run preserves newest day" "${new_file}"
assert_file_exists "normal run preserves nonmatching files" "${nonmatching_file}"
assert_file_exists "normal run does not traverse a linked directory" "${outside_file}"
if [[ -L "${linked_file}" ]]; then
  pass "normal run preserves a matching-name symbolic link"
else
  fail "normal run preserves a matching-name symbolic link"
fi
assert_not_contains "normal run does not print backup filenames" "${run_output}" "${private_name}"

printf '\n%d passed; %d failed\n' "${passed}" "${failed}"
(( failed == 0 ))
