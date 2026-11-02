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
git -C "$d/repo" branch tagged "$feature_sha"
git -C "$d/repo" tag tagged main
set +e
"$tool" --create --repo "$d/repo" --reset-branch tagged --from main --path "$d/wt3"
status=$?
set -e
[[ $status -eq 2 ]] || { echo "expected tagged branch refusal with exit 2, got $status" >&2; exit 1; }
[[ $(git -C "$d/repo" rev-parse refs/heads/tagged) == "$feature_sha" ]]
[[ ! -e "$d/wt3" ]]
"$tool" --create --repo "$d/repo" --reset-branch tagged --from main --path "$d/wt3" --force
[[ $(git -C "$d/repo" rev-parse refs/heads/tagged) == "$(git -C "$d/repo" rev-parse refs/heads/main)" ]]
"$tool" --create --repo "$d/repo" --orphan --new-branch synthetic-orphan --path "$d/orphan"
[[ $(git -C "$d/orphan" symbolic-ref HEAD) == refs/heads/synthetic-orphan ]]
if git -C "$d/orphan" rev-parse --verify HEAD >/dev/null 2>&1; then
    echo 'expected orphan HEAD to be unborn' >&2
    exit 1
fi
for invalid_mode in from branch detach; do
    case "$invalid_mode" in
        from) invalid_args=(--new-branch another-orphan --from main) ;;
        branch) invalid_args=(--branch main) ;;
        detach) invalid_args=(--detach) ;;
    esac
    result=0
    "$tool" --create --repo "$d/repo" --orphan "${invalid_args[@]}" --path "$d/invalid-$invalid_mode" >"$d/invalid.out" 2>&1 || result=$?
    [[ $result -eq 2 ]] || { echo "expected orphan $invalid_mode refusal with exit 2, got $result" >&2; exit 1; }
    [[ ! -e "$d/invalid-$invalid_mode" ]]
done
echo 'reset branch safety passed'
