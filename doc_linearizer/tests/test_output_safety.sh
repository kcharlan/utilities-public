#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd "$(dirname "$0")/.." && pwd)
scratch_dir=$(mktemp -d "${TMPDIR:-/tmp}/doc-linearizer-safety.XXXXXX")
trap 'rm -r -- "${scratch_dir:?}"' EXIT
mkdir -p "$scratch_dir/input/site/assets" "$scratch_dir/output" "$scratch_dir/outside"
printf 'source asset\n' > "$scratch_dir/input/site/assets/keep.txt"
printf 'outside secret\n' > "$scratch_dir/outside/secret.png"
printf 'safe image\n' > "$scratch_dir/input/site/safe.png"
ln -s "$scratch_dir/outside/secret.png" "$scratch_dir/input/site/escape.png"
cat > "$scratch_dir/input/site/index.html" <<'HTML'
<html><body><h2>Synthetic</h2><img src="safe.png"><img src="../../outside/secret.png"><img src="escape.png"><a href="../../outside/secret.png">outside</a></body></html>
HTML
run() { UV_PYTHON_DOWNLOADS=never "$project_dir/linearize.py" "$@"; }
if run "$scratch_dir/input" -o "$scratch_dir/input/site/index.html"; then
  printf 'expected source output rejection\n' >&2; exit 1
fi
grep -Fq '<h2>Synthetic</h2>' "$scratch_dir/input/site/index.html"
grep -Fq 'source asset' "$scratch_dir/input/site/assets/keep.txt"
ln "$scratch_dir/input/site/index.html" "$scratch_dir/output/alias.md"
if run "$scratch_dir/input" -o "$scratch_dir/output/alias.md"; then
  printf 'expected hardlink output rejection\n' >&2; exit 1
fi
grep -Fq '<h2>Synthetic</h2>' "$scratch_dir/input/site/index.html"
run "$scratch_dir/input" -o "$scratch_dir/output/guide.md"
test -f "$scratch_dir/output/assets/safe.png"
test ! -e "$scratch_dir/output/assets/secret.png"
test ! -e "$scratch_dir/output/assets/escape.png"
printf 'existing output\n' > "$scratch_dir/output/guide.md"
printf 'existing asset\n' > "$scratch_dir/output/assets/keep.txt"
mkdir -p "$scratch_dir/empty/site"
if run "$scratch_dir/empty" -o "$scratch_dir/output/guide.md"; then
  printf 'expected empty input failure\n' >&2; exit 1
fi
grep -Fq 'existing output' "$scratch_dir/output/guide.md"
grep -Fq 'existing asset' "$scratch_dir/output/assets/keep.txt"

# Failure after swapping assets restores the old assets and removes staging.
mkdir -p "$scratch_dir/rollback/assets" "$scratch_dir/rollback/guide.md"
printf 'existing asset\n' > "$scratch_dir/rollback/assets/keep.txt"
if run "$scratch_dir/input" -o "$scratch_dir/rollback/guide.md"; then
  printf 'expected directory output failure\n' >&2; exit 1
fi
test "$(cat "$scratch_dir/rollback/assets/keep.txt")" = 'existing asset'
if find "$scratch_dir/rollback" -maxdepth 1 -name '.linearize-*' | grep -q .; then
  printf 'staging directory remained after rollback\n' >&2; exit 1
fi
cat > "$scratch_dir/input/site/toc.html" <<'HTML'
<div id="segment-content"><div class="col-12"><a href="missing.html">Missing</a></div></div>
HTML
if run "$scratch_dir/input" -o "$scratch_dir/output/guide.md"; then
  printf 'expected missing page failure\n' >&2; exit 1
fi
grep -Fq 'existing output' "$scratch_dir/output/guide.md"
grep -Fq 'existing asset' "$scratch_dir/output/assets/keep.txt"
