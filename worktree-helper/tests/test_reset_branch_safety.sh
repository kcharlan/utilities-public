#!/usr/bin/env bash
set -euo pipefail
tool="$(cd "$(dirname "$0")/.." && pwd)/worktree"
d=$(mktemp -d "${TMPDIR:-/tmp}/audit-XXXXXX")
trap 'rm -r -- "${d:?}"' EXIT
export HOME="$d/home" UV_PYTHON_DOWNLOADS=never
mkdir -p "$HOME" "$d/repo"
git -C "$d/repo" init -q -b main
git -C "$d/repo" config user.email synthetic@example.invalid
git -C "$d/repo" config user.name Synthetic
git -C "$d/repo" commit --allow-empty -qm initial
git -C "$d/repo" checkout -qb feat
git -C "$d/repo" commit --allow-empty -qm feature
feature_sha=$(git -C "$d/repo" rev-parse feat)
git -C "$d/repo" checkout -q main
git -C "$d/repo" branch merged main
set +e
"$tool" --create --repo "$d/repo" --reset-branch feat --from main --path "$d/wt"
status=$?
set -e
[[ $status -eq 2 ]] || { echo "expected refusal with exit 2, got $status" >&2; exit 1; }
[[ $(git -C "$d/repo" rev-parse feat) == "$feature_sha" ]]
[[ ! -e "$d/wt" ]]
set +e
"$tool" --create --repo "$d/repo" --reset-branch feat --path "$d/wt" >"$d/default.out" 2>&1
status=$?
set -e
[[ $status -eq 2 ]]
[[ $(git -C "$d/repo" rev-parse feat) == "$feature_sha" ]]
[[ ! -e "$d/wt" ]]
set +e
"$tool" --create --repo "$d/repo" --reset-branch feat --from missing-ref --path "$d/wt" >"$d/error.out" 2>&1
status=$?
set -e
[[ $status -eq 2 ]]
grep -q 'missing-ref' "$d/error.out"
[[ $(git -C "$d/repo" rev-parse feat) == "$feature_sha" ]]
[[ ! -e "$d/wt" ]]
"$tool" --create --repo "$d/repo" --reset-branch feat --from main --path "$d/wt" --force
[[ $(git -C "$d/repo" rev-parse feat) == "$(git -C "$d/repo" rev-parse main)" ]]
"$tool" --create --repo "$d/repo" --reset-branch merged --from main --path "$d/wt2"
[[ $(git -C "$d/repo" rev-parse merged) == "$(git -C "$d/repo" rev-parse main)" ]]
echo 'reset branch safety passed'
