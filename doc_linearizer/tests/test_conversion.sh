#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd "$(dirname "$0")/.." && pwd)
scratch_dir=$(mktemp -d "${TMPDIR:-/tmp}/doc-linearizer-conversion.XXXXXX")
trap 'rm -r -- "${scratch_dir:?}"' EXIT
mkdir -p "$scratch_dir/input/site" "$scratch_dir/output"
printf '<html><body><h1>Index</h1></body></html>\n' > "$scratch_dir/input/site/index.html"
cat > "$scratch_dir/input/site/toc.html" <<'HTML'
<div id="segment-content"><div class="col-12"><a href="a.html">A</a><a href="b.html">B</a><a href="quote&quot;page.html">Quote</a><a href="entity&amp;copy;page.html">Entity</a></div></div>
HTML
cat > "$scratch_dir/input/site/a.html" <<'HTML'
<html><body><h2>Page A</h2><a href="b.html">Page B</a><a href="b.html#sec">Section B</a><a href="#local">Local</a><p id="local">Local section</p><a href="quote&quot;page.html">Quote</a><a href="entity&amp;copy;page.html">Entity</a></body></html>
HTML
printf '<html><body><h1>Quoted</h1></body></html>\n' > "$scratch_dir/input/site/quote\"page.html"
printf '<html><body><h1>Entity</h1></body></html>\n' > "$scratch_dir/input/site/entity&copy;page.html"
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
ruby -r rexml/document - "$output" <<'RUBY'
text = File.read(ARGV.fetch(0))
anchors = text.lines.grep(/^<a id=/).map do |line|
  REXML::Document.new(line).root.attributes['id']
end
['page-quote"page', 'page-entity&copy;page'].each do |id|
  abort "missing parsed anchor #{id.inspect}" unless anchors.include?(id)
  abort "missing link to #{id.inspect}" unless text.include?("](##{id})")
end
text.scan(/\]\(#([^)]*)\)/).flatten.each do |id|
  abort "missing anchor for #{id.inspect}" unless anchors.include?(id)
end
RUBY

# Check numbering and table output against the documented conversion contract.
mkdir -p "$scratch_dir/contracts/site" "$scratch_dir/contracts-output"
cat > "$scratch_dir/contracts/site/index.html" <<'HTML'
<html><head><style>:root{--heading-prefix:"4"}</style></head><body>
<h2>Overview</h2><h3>Scope</h3><h3>Terms</h3><h4>Detail</h4>
<table><tr><th>Key</th><th>Value</th></tr><tr><td colspan="2">Spanning a|b</td></tr></table>
<table class="dict"><thead><tr><th>Name</th><th>Card</th></tr></thead><tbody><tr><td>Example</td><td>1</td></tr></tbody></table>
<table class="waffle"><tbody><tr><td>First</td><td>Second</td></tr><tr><td colspan="2">Group</td></tr><tr><td>Alpha</td><td>Beta</td></tr></tbody></table>
</body></html>
HTML
UV_PYTHON_DOWNLOADS=never UV_OFFLINE=1 "$project_dir/linearize.py" "$scratch_dir/contracts" -o "$scratch_dir/contracts-output/guide.md"
contract_output="$scratch_dir/contracts-output/guide.md"
for expected in '## 4 Overview' '### 4.1 Scope' '### 4.2 Terms' '#### 4.2.1 Detail' \
  '| Key | Value |' '|---|---|' '| Spanning a\|b |  |' \
  '| Name | Card |' '| Example | 1 |' '| **Group** |  |' '| Alpha | Beta |'; do
  if ! grep -Fxq "$expected" "$contract_output"; then
    printf 'missing expected line: %s\n' "$expected" >&2; cat "$contract_output" >&2; exit 1
  fi
done
awk '/^\| Name \| Card \|$/ {if (getline <= 0 || $0 != "|---|---|") exit 1; if (getline <= 0 || $0 != "| Example | 1 |") exit 1; found=1} END {if (!found) exit 1}' "$contract_output"

# The table of contents orders pages, with an omitted index inserted first.
mkdir -p "$scratch_dir/order/site" "$scratch_dir/order-output"
printf '<html><body><p>Index sentinel</p></body></html>\n' > "$scratch_dir/order/site/index.html"
printf '<html><body><p>Page A sentinel</p></body></html>\n' > "$scratch_dir/order/site/a.html"
printf '<html><body><p>Page B sentinel</p></body></html>\n' > "$scratch_dir/order/site/b.html"
printf '<div id="segment-content"><div class="col-12"><a href="b.html">B</a><a href="a.html">A</a></div></div>\n' > "$scratch_dir/order/site/toc.html"
UV_PYTHON_DOWNLOADS=never UV_OFFLINE=1 "$project_dir/linearize.py" "$scratch_dir/order" -o "$scratch_dir/order-output/guide.md"
awk '/Index sentinel/ {if (state != 0) exit 1; state=1} /Page B sentinel/ {if (state != 1) exit 1; state=2} /Page A sentinel/ {if (state != 2) exit 1; state=3} END {if (state != 3) exit 1}' "$scratch_dir/order-output/guide.md"

# Glob discovery includes ordinary pages and excludes generated asset views.
mkdir -p "$scratch_dir/glob/site" "$scratch_dir/glob-output"
printf '<html><body><p>Glob index</p></body></html>\n' > "$scratch_dir/glob/site/index.html"
printf '<html><body><p>Glob page</p></body></html>\n' > "$scratch_dir/glob/site/a.html"
printf '<html><body><p>Generated asset sentinel</p></body></html>\n' > "$scratch_dir/glob/site/x.json.html"
UV_PYTHON_DOWNLOADS=never UV_OFFLINE=1 "$project_dir/linearize.py" "$scratch_dir/glob" -o "$scratch_dir/glob-output/guide.md"
grep -Fq 'Glob index' "$scratch_dir/glob-output/guide.md"
grep -Fq 'Glob page' "$scratch_dir/glob-output/guide.md"
if grep -Fq 'Generated asset sentinel' "$scratch_dir/glob-output/guide.md"; then
  printf 'generated asset view was included\n' >&2; exit 1
fi

# Preserve both blockquote structure and literal backslashes in table cells.
mkdir -p "$scratch_dir/context/site" "$scratch_dir/context-output"
cat > "$scratch_dir/context/site/index.html" <<'HTML'
<html><body>
<table><tr><th>Kind</th><th>Value</th></tr><tr><td>pipe</td><td>a|b</td></tr><tr><td>backslash pipe</td><td>a\|b</td></tr></table>
<table class="dict"><thead><tr><th>Kind</th><th>Value</th></tr></thead><tbody><tr><td>dict</td><td>a\|b</td></tr></tbody></table>
<table class="waffle"><tbody><tr><td>Kind</td><td>Value</td></tr><tr><td>waffle</td><td>a\|b</td></tr></tbody></table>
<blockquote><table><tr><th>A</th><th>B</th></tr><tr><td>one</td><td>two</td></tr></table></blockquote>
</body></html>
HTML
UV_PYTHON_DOWNLOADS=never UV_OFFLINE=1 "$project_dir/linearize.py" "$scratch_dir/context" -o "$scratch_dir/context-output/guide.md"
context_output="$scratch_dir/context-output/guide.md"
context_failed=0
for expected in '> | A | B |' '> |---|---|' '> | one | two |'; do
  if ! grep -Fxq "$expected" "$context_output"; then
    printf 'missing quoted table line: %s\n' "$expected" >&2; context_failed=1
  fi
done
for expected in '| pipe | a\|b |' '| backslash pipe | a\\\|b |' '| dict | a\\\|b |' '| waffle | a\\\|b |'; do
  if ! grep -Fxq "$expected" "$context_output"; then
    printf 'missing escaped cell line: %s\n' "$expected" >&2; context_failed=1
  fi
done
if [ "$context_failed" -ne 0 ]; then cat "$context_output" >&2; exit 1; fi
awk '/^> \| A \| B \|$/ {if (getline <= 0 || $0 != "> |---|---|") exit 1; if (getline <= 0 || $0 != "> | one | two |") exit 1; found=1} END {if (!found) exit 1}' "$context_output"

# Tables that begin list items must not leak tokens or lose their cells.
mkdir -p "$scratch_dir/lists/site" "$scratch_dir/lists-output"
cat > "$scratch_dir/lists/site/index.html" <<'HTML'
<html><body>
<ul><li><table><tr><th>Unordered A</th><th>Unordered B</th></tr><tr><td>Unordered one</td><td>Unordered two</td></tr></table></li></ul>
<ol><li><table><tr><th>Ordered A</th><th>Ordered B</th></tr><tr><td>Ordered one</td><td>Ordered two</td></tr></table></li></ol>
</body></html>
HTML
UV_PYTHON_DOWNLOADS=never UV_OFFLINE=1 "$project_dir/linearize.py" "$scratch_dir/lists" -o "$scratch_dir/lists-output/guide.md"
list_output="$scratch_dir/lists-output/guide.md"
list_failed=0
if grep -Eq 'LINEARIZEDTABLE[[:xdigit:]]+END' "$list_output"; then
  printf 'unresolved table placeholder in list output\n' >&2; list_failed=1
fi
for expected in 'Unordered A' 'Unordered B' 'Unordered one' 'Unordered two' 'Ordered A' 'Ordered B' 'Ordered one' 'Ordered two'; do
  if ! grep -Fq "$expected" "$list_output"; then
    printf 'missing list table cell: %s\n' "$expected" >&2; list_failed=1
  fi
done
if [ "$list_failed" -ne 0 ]; then cat "$list_output" >&2; exit 1; fi
awk '
  /^[[:space:]]*\* \| Unordered A \| Unordered B \|$/ {if (getline <= 0 || $0 !~ /^[[:space:]]+\|---\|---\|$/) exit 1; if (getline <= 0 || $0 !~ /^[[:space:]]+\| Unordered one \| Unordered two \|$/) exit 1; unordered=1}
  /^[[:space:]]*1\. \| Ordered A \| Ordered B \|$/ {if (getline <= 0 || $0 !~ /^[[:space:]]+\|---\|---\|$/) exit 1; if (getline <= 0 || $0 !~ /^[[:space:]]+\| Ordered one \| Ordered two \|$/) exit 1; ordered=1}
  END {if (!unordered || !ordered) exit 1}
' "$list_output"
