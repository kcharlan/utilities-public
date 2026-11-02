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
