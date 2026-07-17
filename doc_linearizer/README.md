# HTML Documentation Linearizer

Command-line tool that flattens a multi-page HTML documentation site (such as a FHIR Implementation Guide) into a single Markdown file. The input directory must contain a `site/` subdirectory with the HTML pages.

Key behaviors:
- Uses `site/toc.html` to determine the exact page order and scope, so the flattened document mirrors the navigation the authors intended.
- Preserves the CSS-driven numbering (e.g., “2.1.3”) by reading the page-specific heading counters and rewriting each heading before conversion.
- Converts all HTML tables (including “waffle”/”dict”/metadata tables) into Markdown so complex grids stay readable after flattening.
- Copies referenced assets (images, JSON/XML/ZIP/etc.) into an `assets/` directory alongside the output and rewrites links accordingly.
- Rewrites internal cross-page links as anchor links within the single output file.
- Strips decorative chrome (spacer gifs, copy buttons, nav icons) and expands “Show Usage” toggle panels so the Markdown contains only the content users would read on the site.
- Falls back to glob-based file discovery if `toc.html` is not present.

## Dependencies

- `beautifulsoup4` -- HTML parsing
- `html2text` -- HTML-to-Markdown conversion

## Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Usage
```bash
# default output = linearized_output.md (plus ./assets)
python linearize.py /path/to/ig-root

# specify a different destination (assets will sit next to this path)
python linearize.py /path/to/ig-root -o docs/flat_guide.md
```

The script prints progress as it walks the ToC. After completion you will have:
- `<output>.md`: concatenated Markdown with heading numbers and normalized tables.
- `<output dir>/assets/`: copies of every non-HTML asset referenced by the IG (images, NDJSON, XML, etc.) with rewritten links in the Markdown.
