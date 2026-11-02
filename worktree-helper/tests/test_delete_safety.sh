#!/usr/bin/env bash
set -euo pipefail
tool="$(cd "$(dirname "$0")/.." && pwd)/worktree"
d=$(mktemp -d "${TMPDIR:-/tmp}/audit-XXXXXX")
trap 'rm -r -- "${d:?}"' EXIT
export HOME="$d/home" UV_PYTHON_DOWNLOADS=never
mkdir -p "$HOME" "$d/repo"
git -C "$d/repo" init -q
git -C "$d/repo" config user.email synthetic@example.invalid
git -C "$d/repo" config user.name Synthetic
printf 'ignored\n' > "$d/repo/.gitignore"
git -C "$d/repo" add .gitignore
git -C "$d/repo" commit -qm initial
git -C "$d/repo" worktree add -q --detach "$d/wt"
printf 'detached\n' > "$d/wt/change"
git -C "$d/wt" add change
git -C "$d/wt" commit -qm detached
if "$tool" --delete --repo "$d/repo" --worktree "$d/wt" --yes; then
  echo 'detached commit was deleted' >&2; exit 1
fi
git -C "$d/wt" branch saved
printf 'private\n' > "$d/wt/ignored"
if "$tool" --delete --repo "$d/repo" --worktree "$d/wt" --yes; then
  echo 'ignored file was deleted' >&2; exit 1
fi
"$tool" --delete --repo "$d/repo" --worktree "$d/wt" --yes --force
[[ ! -e "$d/wt" ]]
git -C "$d/repo" rev-parse --verify saved >/dev/null
echo 'delete safety passed'
