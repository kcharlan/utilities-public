# HTML Documentation Linearizer

Command-line tool that flattens a multi-page HTML documentation site, such as a FHIR Implementation Guide, into a single Markdown file. The input directory must contain a `site/` subdirectory with the HTML pages.

## Behavior

- Uses links in the main content area of `site/toc.html` to determine page scope and order. It inserts `index.html` first when the ToC omits it and excludes `toc.html`.
- Falls back to recursively discovering HTML files when `toc.html` is missing or does not have the expected content container. The fallback excludes generated `.json.html`, `.xml.html`, and `.ttl.html` asset views.
- Extracts `#segment-content .col-12` from each page, falling back to the page body.
- Preserves CSS-driven heading numbers by reading `--heading-prefix` or a `counter-reset: section` value and inserting the resulting numbers into headings before conversion.
- Converts HTML tables, including `waffle` and `dict` tables, into Markdown tables.
- Copies local images and links to supported data/archive assets into an `assets/` directory beside the output, then rewrites those references.
- Rewrites links between included HTML pages to point to page anchors in the combined document.
- Removes common decorative controls and images and exposes hidden usage content before conversion.

Table conversion favors readable cell text over HTML layout: column spans are
expanded, but row spans and rich cell markup are not preserved. Internal link
matching uses literal discovered page paths, without general URL normalization.
Each page anchor is attached to the page's first `<h2>`, so links to a page
without one point to a missing anchor.

## Setup

Install [uv](https://docs.astral.sh/uv/) (`brew install uv`). It resolves Python and the script's dependencies on first run.

## Usage

Run these commands from `doc_linearizer/`:

```bash
# Default output: ./linearized_output.md and ./assets/
./linearize.py /path/to/ig-root

# Place the Markdown and assets directory under docs/
./linearize.py /path/to/ig-root -o docs/flat_guide.md
```

The script prints discovery and per-page progress. On success it creates:

- The requested Markdown file, containing the converted pages separated by horizontal rules.
- `<output directory>/assets/`, containing copied local images and supported linked assets.

The assets directory is deleted and recreated on every run. Do not use an existing `assets/` directory beside the output for unrelated files. Copied assets are flattened to their base filenames, so source files with the same name can overwrite one another.

Supported linked asset extensions are `.json`, `.xml`, `.ttl`, `.csv`, `.xlsx`, `.zip`, `.tgz`, `.png`, `.jpg`, `.jpeg`, and `.gif`. Local `<img>` sources are also copied regardless of extension. Remote URLs are not copied, and embedded `data:` images are removed as decorative.
