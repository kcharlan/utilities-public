#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd "$(dirname "$0")/.." && pwd)
scratch_dir=$(mktemp -d "${TMPDIR:-/tmp}/doc-linearizer-conversion.XXXXXX")
trap 'rm -r -- "${scratch_dir:?}"' EXIT
mkdir -p "$scratch_dir/input/site" "$scratch_dir/output"
printf '<html><body><h1>Index</h1></body></html>\n' > "$scratch_dir/input/site/index.html"
cat > "$scratch_dir/input/site/toc.html" <<'HTML'
<div id="segment-content"><div class="col-12"><a href="a.html">A</a><a href="b.html">B</a></div></div>
HTML
cat > "$scratch_dir/input/site/a.html" <<'HTML'
<html><body><h2>Page A</h2><a href="b.html">Page B</a><a href="b.html#sec">Section B</a><a href="#local">Local</a><p id="local">Local section</p></body></html>
HTML
cat > "$scratch_dir/input/site/b.html" <<'HTML'
<html><body><h1>Page B</h1><p id="sec">Section B</p></body></html>
HTML
UV_PYTHON_DOWNLOADS=never UV_OFFLINE=1 "$project_dir/linearize.py" "$scratch_dir/input" -o "$scratch_dir/output/guide.md"
output="$scratch_dir/output/guide.md"
for label in 'Page B' 'Section B'; do
  if ! grep -Fq "[$label](#page-b)" "$output"; then
    printf 'missing page anchor link for %s\n' "$label" >&2; cat "$output" >&2; exit 1
  fi
done
if ! grep -Fq '<a id="page-b"></a>' "$output"; then
  printf 'missing page-b anchor\n' >&2; exit 1
fi
grep -oE '\]\(#[^)]*\)' "$output" | while IFS= read -r link; do
  anchor=${link#\](#}
  anchor=${anchor%)}
  if ! grep -Fq "id=\"$anchor\"" "$output"; then
    printf 'missing anchor for %s\n' "$link" >&2; exit 1
  fi
done
