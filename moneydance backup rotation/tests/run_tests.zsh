#!/bin/zsh

set -u
set -o pipefail

typeset -a MONEYDANCE_TEST_ENV_VARS=(
  MONEYDANCE_NAS_SERVER
  MONEYDANCE_NAS_SHARE_NAME
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

make_mount_mock() {
  local target="$1"
  local mount_point="$2"
  local marker="$3"
  local mount_source="${4:-//synthetic-nas/SYNTHETIC_SHARE}"
  cat > "${target}" <<EOF
#!/bin/zsh
print -r -- invoked > "${marker}"
print -r -- '${mount_source} on ${mount_point} (smbfs)'
EOF
  chmod 755 "${target}"
}

make_config() {
  local target="$1"
  local dry_run="${2:-0}"
  cat > "${target}" <<EOF
NAS_SERVER=synthetic-nas
NAS_SHARE_NAME=SYNTHETIC_SHARE
BACKUP_DIRECTORY_NAME=SYNTHETIC_BACKUPS
BACKUP_FILENAME_SUFFIX=.SYNTHETIC-BACKUP
MAX_DAYS_TO_KEEP=2
DRY_RUN=${dry_run}
USE_SYSLOG=0
EOF
}

test_root="$(mktemp -d -t moneydance-rotation-tests.XXXXXX)"
trap 'rm -rf -- "${test_root}"' EXIT

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

bad_log_config="${test_root}/bad-log.conf"
bad_log_marker="${test_root}/bad-log-mount-called"
bad_log_mount="${test_root}/bad-log-mount"
make_mount_mock "${bad_log_mount}" "${test_root}/unused" "${bad_log_marker}"
cat > "${bad_log_config}" <<'EOF'
NAS_SERVER=synthetic-nas
NAS_SHARE_NAME=SYNTHETIC_SHARE
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

linked_backup_target="${test_root}/misconfigured-outside"
mkdir -p "${linked_backup_target}"
linked_backup_file="${linked_backup_target}/OUTSIDE.SYNTHETIC-BACKUP"
touch -t 203501010101 "${linked_backup_file}"
ln -s "${linked_backup_target}" "${mount_point}/SYNTHETIC_LINK"
linked_config="${test_root}/linked-config"
cat > "${linked_config}" <<'EOF'
NAS_SERVER=synthetic-nas
NAS_SHARE_NAME=SYNTHETIC_SHARE
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
  MONEYDANCE_BACKUP_DIRECTORY_NAME="SYNTHETIC_BACKUPS" \
  MONEYDANCE_BACKUP_FILENAME_SUFFIX=".SYNTHETIC-BACKUP" \
  MONEYDANCE_MAX_DAYS_TO_KEEP=2 \
  "${SCRIPT}" 2>&1
)"
env_status=$?
assert_status "environment-only configuration succeeds" 0 "${env_status}"
assert_file_exists "environment-only invocation defaults to dry run" "${old_file}"
assert_contains "safe default reports dry run" "${env_output}" "Dry run enabled"

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
