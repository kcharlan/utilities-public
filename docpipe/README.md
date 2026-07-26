# docpipe

A fully local document conversion pipeline for macOS. Converts PDF, DOCX, PPTX, HTML, and XLSX into a canonical, model-friendly representation (Markdown + structured JSON).

Python setup requires only [uv](https://docs.astral.sh/uv/) (`brew install uv`) — the launcher uses a PEP 723 inline-metadata header, and uv resolves its Python packages into the shared cache on first run. Meaningful PDF conversion additionally requires Poppler; Pandoc enables fallback paths, as detailed below.

## Environment Dependencies

### Required

- **[uv](https://docs.astral.sh/uv/)** (`brew install uv`) — manages the Python interpreter and dependencies via the launcher's PEP 723 header; you never need to activate a venv or run pip manually.

### Optional (Homebrew)

These are external CLI tools that docpipe shells out to. If missing, docpipe warns at runtime and skips the affected backend — it does not crash.

| Tool | Install command | What it enables |
|------|----------------|-----------------|
| **poppler** | `brew install poppler` | PDF text extraction (`pdftotext`) and optional page-to-image rendering (`pdftoppm`). docpipe also checks for `pdfinfo`, but v0.1.0 does not emit its metadata. **Required for useful PDF output.** |
| **pandoc** | `brew install pandoc` | Fallback HTML→Markdown conversion. Primary path uses the Python `markdownify` library (auto-installed), so Pandoc is only needed if markdownify fails on a particular HTML file. Also used as DOCX fallback if `python-docx` errors. |

Install both in one shot:

```bash
brew install poppler pandoc
```

### Not required

- **LibreOffice** — would enable PPTX slide image rendering and XLS→XLSX conversion, but is not used in this version. PPTX conversion extracts text/tables/notes without images. XLS files are not supported (convert to XLSX manually or with LibreOffice).
- **Tesseract** — not used. docpipe does not perform OCR.
- **Node.js / npm / Bun** — not needed for docpipe itself. Only needed if you use the OpenCode custom tool wrapper (see below).

### Python packages (auto-installed)

These are declared in the launcher's PEP 723 header and resolved by uv on first run. Listed here for reference only:

| Package | Purpose |
|---------|---------|
| `python-docx` | DOCX text + table extraction |
| `python-pptx` | PPTX slide text, tables, speaker notes |
| `openpyxl` | XLSX sheet extraction |
| `beautifulsoup4` + `lxml` | HTML parsing |
| `readability-lxml` | HTML main-content extraction |
| `markdownify` | HTML→Markdown conversion (primary path) |

## Quick Start

```bash
# Optional: install external tools for PDF + fallback conversion
brew install poppler pandoc

# Convert a PDF
./docpipe convert --input /path/to/file.pdf --out /path/to/output/

# Convert with image extraction (requires poppler)
./docpipe convert --input /path/to/file.pdf --out /path/to/output/ --images

# Markdown output only
./docpipe convert --input /path/to/file.docx --out /path/to/output/ --format md

# JSON output only
./docpipe convert --input /path/to/file.xlsx --out /path/to/output/ --format json

# Strict mode: fail if conversion produces any warning
./docpipe convert --input /path/to/file.html --out /path/to/output/ --strict
```

On first run, uv resolves the dependencies into its shared cache (may briefly hit the network). Subsequent runs start instantly.

## Supported Formats

| Format | Text | Structured tables | Images/assets | Notes |
|--------|------|-------------------|---------------|-------|
| PDF | Yes (`pdftotext -layout`) | No | Page renders with `--images` (`pdftoppm`) | Born-digital PDFs only; no OCR |
| DOCX | Yes (`python-docx`) | CSV | Embedded images with `--images` | Pandoc text fallback on `python-docx` error |
| PPTX | Yes (`python-pptx`) | CSV from table shapes | Not supported | Includes speaker notes |
| HTML | Yes (Readability + markdownify) | CSV from HTML tables | Not supported | Pandoc, then plain text, are fallback paths |
| XLSX | Yes (`openpyxl`) | CSV per sheet | Not supported | Reads cached formula values with `data_only=True` |
| XLS | Not supported | — | — | Convert to XLSX manually |

## Output Structure

For an input `MyFile.pdf`, produces:

```
output_dir/
├── MyFile.opencode.md      # Markdown body with headings, tables, image refs
├── MyFile.opencode.json    # Structured JSON: metadata, segments, tables, assets
└── MyFile.assets/          # Extracted images (supported formats with --images)
    ├── page-001.png
    ├── page-002.png
    └── ...
```

## CLI Reference

```
docpipe convert --input PATH --out DIR [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--input` | *(required)* | Path to input file |
| `--out` | *(required)* | Output directory (created if it doesn't exist) |
| `--images` | `false` | Extract images (PDF page renders, DOCX embedded) |
| `--format` | `md+json` | Output format: `md`, `json`, or `md+json` |
| `--max-page-images` | `50` | Max PDF pages to render as images |
| `--xlsx-max-cells` | `2000000` | Safety cap on cells extracted from XLSX |
| `--strict` | `false` | Treat conversion warnings as errors (exit 2 without writing Markdown/JSON; an image-cap warning can occur after assets are created) |
| `--verbose` | `false` | Show detailed logging and tracebacks on error |

## Environment Prep Checklist

```bash
# 1) Verify uv
uv --version

# 2) Install external tools (recommended)
brew install poppler pandoc

# 3) Verify external tools
command -v pdftotext pdftoppm pdfinfo pandoc

# 4) Run smoke help (first run resolves the uv environment)
./docpipe convert --help
```

## OpenCode Integration

docpipe includes a custom tool definition for [OpenCode](https://opencode.ai) so the LLM can call `convert_document` during coding sessions.

### Setup

1. **Install the tool into OpenCode's tools directory** (choose one):

   **Per-project copy** (tool available only in that project):
   ```bash
   cd /path/to/your/project
   mkdir -p .opencode/tools
   cp /path/to/utilities-public/docpipe/opencode_tool/convert_document.ts .opencode/tools/convert_document.ts
   ```

   **Global copy** (tool available in all OpenCode sessions):
   ```bash
   mkdir -p ~/.config/opencode/tools
   cp /path/to/utilities-public/docpipe/opencode_tool/convert_document.ts ~/.config/opencode/tools/convert_document.ts
   ```

   If you use a symlink, OpenCode may resolve the file from its real path and fail module resolution for `@opencode-ai/plugin`. Copying avoids that issue.

2. **Verify** — start OpenCode and the `convert_document` tool should appear alongside built-in tools. No config file changes needed; OpenCode auto-discovers tools in these directories.

3. **Usage in OpenCode** — the LLM can call `convert_document` with:
   - `input_path`: absolute path to the document
   - `output_dir`: where to write outputs
   - `extract_images`: (optional) boolean
   - `max_page_images`: (optional) number
   - `xlsx_max_cells`: (optional) number
   - `strict`: (optional) boolean; if true, warnings cause conversion failure

   The tool runs `docpipe convert` and returns the Markdown content inline so the LLM can work with it immediately, plus file paths for the full outputs.

### Requirements for the OpenCode tool

- The `docpipe` executable must resolve through one of the locations in the tool file: its configured preferred path, `<current-worktree>/docpipe/docpipe`, or `docpipe` on `PATH`. For a global OpenCode installation used outside this repository, set `preferredPath` in `convert_document.ts` to this launcher's absolute path or make `docpipe` available on `PATH`.
- OpenCode uses [Bun](https://bun.sh) as its runtime, which is installed with OpenCode. No additional Bun/Node setup is needed.

## Troubleshooting

**"pdftotext not found"** — Install poppler: `brew install poppler`

**"Conversion failed" on DOCX** — If `python-docx` can't parse the file, install Pandoc for the fallback path: `brew install pandoc`

**XLS files** — Not supported. Convert to XLSX using LibreOffice (`soffice --headless --convert-to xlsx input.xls`) or Excel, then run docpipe on the XLSX.

**First run is slow** — Normal. uv is resolving and caching the dependencies. Subsequent runs are instant.

**Reset cached dependencies** — If the uv-managed environment appears corrupt, `uv cache clean` clears uv's shared cache; run docpipe again to resolve dependencies. This affects uv's cache beyond docpipe.

## Tests (pytest)

Unit tests cover CLI parser + strict-mode behavior.

```bash
cd /path/to/utilities-public/docpipe
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```
