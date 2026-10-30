#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd "$(dirname "$0")/.." && pwd)
scratch_dir=$(mktemp -d "${TMPDIR:-/tmp}/doc-linearizer-test.XXXXXX")
trap 'rm -r -- "$scratch_dir"' EXIT

mkdir -p "$scratch_dir/input/site" "$scratch_dir/output" "$scratch_dir/caller"
cat > "$scratch_dir/input/site/toc.html" <<'HTML'
<div id="segment-content"><div class="col-12"><a href="index.html">Index</a></div></div>
HTML
cat > "$scratch_dir/input/site/index.html" <<'HTML'
<html><body><div id="segment-content"><div class="col-12"><h2>Synthetic Launcher Heading</h2></div></div></body></html>
HTML

cd "$scratch_dir/caller"
UV_PYTHON_DOWNLOADS=never "$project_dir/linearize.py" "$scratch_dir/input" -o "$scratch_dir/output/guide.md"
grep -Fq 'Synthetic Launcher Heading' "$scratch_dir/output/guide.md"
