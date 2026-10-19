#!/bin/bash
# Scan Git inputs without printing owner literals, paths, or subprocess errors.
set -u
exec 2>/dev/null
fail() { printf '%s\n' 'secrets check: redacted failure'; exit "$1"; }
patterns=${ANKER_CHARGE_MONITOR_SECRETS_FILE:-"$HOME/.config/anker-charge-monitor/secrets-patterns"}
[ -f "$patterns" ] && [ ! -L "$patterns" ] && [ -r "$patterns" ] && [ -s "$patterns" ] || fail 2
LC_ALL=C awk 'length == 0 || /^[[:space:]]*$/ {bad=1} END {exit bad ? 1 : 0}' "$patterns" || fail 2
# Reject links in the patterns path, including directory ancestors.
component=$patterns
while [ -n "$component" ]; do
  [ ! -L "$component" ] || fail 2
  case "$component" in */*) parent=${component%/*}; [ "$parent" != "$component" ] || break; component=$parent;; *) break;; esac
done
umask 077
scratch=$(mktemp -d) || fail 2
trap 'rm -rf "$scratch"' EXIT
# No -q: grep must finish reading every input and report read errors.
match_file() {
  grep -a -F -f "$patterns" -- "$1" >/dev/null
  case $? in 0) fail 1;; 1) ;; *) fail 2;; esac
}
match_path() {
  printf '%s\n' "$1" > "$scratch/path" || fail 2
  match_file "$scratch/path"
}
git rev-parse --show-toplevel > "$scratch/root" || fail 2
root=$(cat "$scratch/root") || fail 2
# Git paths are relative to the caller: run from the project directory.
# Keep the entire neighboring monorepo outside this project scan.
git ls-files -z --cached --others --exclude-standard > "$scratch/working" 2> "$scratch/git-errors" || fail 2
# Git warns but exits zero when it cannot enumerate an untracked directory.
[ ! -s "$scratch/git-errors" ] || fail 2
while IFS= read -r -d '' path; do
  match_path "$path"
  component=$path
  linked=false
  while [ -n "$component" ]; do
    if [ -L "$component" ]; then linked=true; break; fi
    case "$component" in */*) component=${component%/*};; *) break;; esac
  done
  [ "$linked" = false ] || continue
  # A failed existence test cannot distinguish deletion from a blocked ancestor.
  # Check searchable existing parents before accepting an indexed deletion.
  parent=$path
  while [[ "$parent" == */* ]]; do
    parent=${parent%/*}
    if [ -d "$parent" ] && [ ! -x "$parent" ]; then fail 2; fi
  done
  if [ -e "$path" ]; then
    [ -f "$path" ] && [ -r "$path" ] || fail 2
    match_file "$path"
  else
    # Missing untracked entries indicate a read race; indexed deletions are scanned below.
    git ls-files --error-unmatch -- "$path" >/dev/null || fail 2
  fi
done < "$scratch/working"
git ls-files --stage -z > "$scratch/index" 2> "$scratch/git-errors" || fail 2
[ ! -s "$scratch/git-errors" ] || fail 2
while IFS= read -r -d '' record; do
  metadata=${record%%$'\t'*}
  path=${record#*$'\t'}
  [ "$path" != "$record" ] || fail 2
  match_path "$path"
  read -r mode object stage <<< "$metadata"
  [ -n "$object" ] || fail 2
  # Submodules contain no file blob and are not traversed.
  [ "$mode" != 160000 ] || continue
  git show "$object" > "$scratch/blob" || fail 2
  match_file "$scratch/blob"
done < "$scratch/index"
printf 'clean\n'
