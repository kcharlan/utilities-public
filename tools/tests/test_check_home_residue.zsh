#!/bin/zsh
set -eu
root=${0:A:h:h:h}
scratch=$(mktemp -d "${TMPDIR:-/tmp}/home-residue-test.XXXXXX")
trap 'rm -rf -- "$scratch"' EXIT
fixture_home="$scratch/home"
mkdir "$fixture_home"
fail() { print -u2 -- "FAIL: $1"; exit 1; }
run() {
  audit_status=0
  output=$(HOME="$fixture_home" zsh "$root/tools/check_home_residue.zsh" 2>&1) || audit_status=$?
}
reset_home() { rm -rf -- "$fixture_home"; mkdir "$fixture_home"; }
check_old() {
  run
  [[ $audit_status == 1 ]] || fail "$1: expected exit 1, got $audit_status: $output"
  [[ $output == *"$1: "*' days old'* && $output == *'check_home_residue: 1 candidate(s)'* ]] || fail "$1: missing name, age or count: $output"
}
mkdir "$fixture_home/.synthetic-task.aB3dEf"
touch -t 202001010000 "$fixture_home/.synthetic-task.aB3dEf"
check_old '.synthetic-task.aB3dEf'
reset_home
touch -t 202001010000 "$fixture_home/.synthetic-task.abcdef"
check_old '.synthetic-task.abcdef'
reset_home
mkdir "$fixture_home/.synthetic-review-aB3dEf9h"
touch -t 202001010000 "$fixture_home/.synthetic-review-aB3dEf9h"
check_old '.synthetic-review-aB3dEf9h'
reset_home
ln -s "$scratch/missing-target" "$fixture_home/.synthetic-task.xY7zQ2"
touch -h -t 202001010000 "$fixture_home/.synthetic-task.xY7zQ2"
check_old '.synthetic-task.xY7zQ2'
reset_home
mkdir "$fixture_home/.synthetic task.aB3dEf"
touch -t 202001010000 "$fixture_home/.synthetic task.aB3dEf"
check_old '.synthetic task.aB3dEf'
reset_home
mkdir "$fixture_home/.synthetic-task.aB3dEf"
touch "$fixture_home/.synthetic-task.aB3dEf/synthetic-marker"
touch -t 202001010000 "$fixture_home/.synthetic-task.aB3dEf"
check_old '.synthetic-task.aB3dEf'
[[ $output != *synthetic-marker* ]] || fail 'inspected directory contents'
touch -t 202001010000 "$fixture_home/.synthetic-task.abcdef"
run
[[ $audit_status == 1 && $output == *'check_home_residue: 2 candidate(s)'* ]] || fail "multiple entries: $audit_status $output"
reset_home
mkdir "$fixture_home/.synthetic-task.aB3dEf" "$fixture_home/.synthetic-review-aB3dEf9h" "$fixture_home/.synthetic task.aB3dEf"
touch "$fixture_home/.synthetic-task.abcdef"
ln -s "$scratch/missing-target" "$fixture_home/.synthetic-task.xY7zQ2"
run
[[ $audit_status == 0 && $output == 'check_home_residue: OK' ]] || fail "recent entries: $audit_status $output"
reset_home
mkdir "$fixture_home/.config" "$fixture_home/.synthetic-tool" "$fixture_home/.synthetic-review-settings"
touch -t 202001010000 "$fixture_home/.config" "$fixture_home/.synthetic-tool" "$fixture_home/.synthetic-review-settings" "$fixture_home/.zshrc.backup"
run
[[ $audit_status == 0 && $output == 'check_home_residue: OK' ]] || fail "unmatched entries: $audit_status $output"
reset_home
run
[[ $audit_status == 0 && $output == 'check_home_residue: OK' ]] || fail "empty home: $audit_status $output"
print 'check_home_residue tests: PASS'
