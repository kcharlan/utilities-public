# Design: HTML Documentation Linearizer

## Purpose

The HTML Documentation Linearizer converts a structured, multi-page HTML documentation site, such as a FHIR Implementation Guide, into one linear Markdown document. The result is portable, searchable, usable offline, and suitable as input to other document-conversion tools.

The implementation is a single Python command-line script, `linearize.py`. It uses Beautiful Soup for HTML parsing and `html2text` for final Markdown conversion.

## Input and output

The positional input is the path to a documentation root containing a `site/` subdirectory. The tool reads UTF-8 HTML files from that subdirectory. A root-level redirecting `index.html` is not required or inspected.

The optional `-o`/`--output` argument selects the Markdown output path and defaults to `linearized_output.md`. The tool also recreates an `assets/` directory beside the output file. Because that directory is deleted before processing and copied files are flattened to base filenames, callers must not keep unrelated files there and should avoid inputs with duplicate asset filenames.

## Processing pipeline

The pipeline is **discover → extract and transform → convert → assemble**.

### Page discovery

When `site/toc.html` exists and contains `#segment-content .col-12`, its local links ending in `.html` are the authoritative ordered page list. Duplicate links are removed while retaining first occurrence. `index.html` is prepended if absent, and `toc.html` is removed.

If the ToC is absent or lacks the expected container, recursive glob discovery is used instead. This fallback:

- Includes `site/**/*.html`.
- Excludes generated `.json.html`, `.xml.html`, and `.ttl.html` asset views.
- Sorts paths lexically, with `index.html` first when present.

Discovery is deliberately local and navigation-driven; the tool does not crawl links transitively or fetch remote pages.

### Content extraction and cleanup

For each discovered page, the tool selects `#segment-content .col-12`. If that selector is absent it falls back to `<body>`; a page with neither is skipped with a warning.

Before conversion, the script mutates the selected HTML:

- The first `<h2>` receives a stable page anchor based on the page path.
- Heading numbers represented only by CSS are made visible in text. The page prefix is read from `--heading-prefix:"…"` in a `<style>` element or `counter-reset: section …` on the selected content element, then counters are applied to `<h2>` through `<h6>`.
- Buttons, embedded data-URI images, known decorative images, and hierarchy icons are removed.
- `ipp_` usage controls are removed while matching `ipp2_` content is unhidden and unwrapped.
- Tables are converted to raw Markdown blocks before `html2text` runs. Dedicated transforms handle `waffle` and `dict` tables; the general transform expands column spans, chooses the first header row (or first row), and escapes pipe characters.

The table conversion intentionally favors readable plain text over exact HTML layout. Row spans are not reconstructed, and rich cell markup is reduced to cell text.

### Links and assets

Links whose path exactly matches an included HTML page are changed to a generated page anchor. External links, same-page fragment links, and local HTML links outside the discovered set are left unchanged.

Local `<img>` sources are copied to the output assets directory unless they are remote, embedded, or removed as decoration. Local links are copied only when their extension is one of:

`.json`, `.xml`, `.ttl`, `.csv`, `.xlsx`, `.zip`, `.tgz`, `.png`, `.jpg`, `.jpeg`, `.gif`

Each copied reference is rewritten to `<assets-directory-name>/<base-filename>`. Missing assets produce warnings and retain their original references.

### Markdown conversion and assembly

The transformed content block is passed to `html2text` with links enabled and line wrapping disabled. Nonempty page results are joined in discovery order with Markdown horizontal rules and written as UTF-8.

## Failure behavior

The command exits with an error when:

- The input does not contain a `site/` directory.
- Discovery returns no pages.
- The output file cannot be written.

Individual missing pages, missing assets, and pages with no usable content emit warnings so processing can continue.

## Constraints

- The parser targets the HTML conventions used by the source documentation generator; differently structured sites may fall back to processing the entire body.
- Asset directory structure is not preserved, so equal base filenames collide.
- Only the supported linked-asset extensions are relocated.
- The tool does not download remote content.
- Page identity and link matching use the literal relative paths discovered from the ToC or glob fallback; no general URL normalization is performed.
