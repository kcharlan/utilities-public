# docpipe

A fully local, free document conversion pipeline for macOS. Converts PDF, DOCX, PPTX, HTML, and XLSX into a canonical, model-friendly representation (Markdown + structured JSON).

Python setup requires only [uv](https://docs.astral.sh/uv/) (`brew install uv`) — the launcher uses a PEP 723 inline-metadata header, and uv resolves its Python packages into the shared cache on first run. PDF conversion additionally requires Poppler; Pandoc enables fallback paths, as detailed below.

## Environment Dependencies

### Required

- **[uv](https://docs.astral.sh/uv/)** (`brew install uv`) — manages the Python interpreter and dependencies via the launcher's PEP 723 header; you never need to activate a venv or run pip manually.

### Optional (Homebrew)

These are external CLI tools that docpipe shells out to. If missing, docpipe warns at runtime and skips the affected backend — it does not crash.

| Tool | Install command | What it enables |
|------|----------------|-----------------|
| **poppler** | `brew install poppler` | PDF text extraction (`pdftotext`), PDF page-to-image rendering (`pdftoppm`), PDF metadata (`pdfinfo`). **Required for PDF conversion.** |
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
| `pandas` | DataFrame/CSV support for XLSX |
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

# Strict mode: fail if any fallback/degraded warning occurs
./docpipe convert --input /path/to/file.html --out /path/to/output/ --strict
```

On first run, uv resolves the dependencies into its shared cache (may briefly hit the network). Subsequent runs start instantly.

## Supported Formats

| Format | Text | Tables | Images | Notes |
|--------|------|--------|--------|-------|
| PDF | Yes (`pdftotext`) | Layout-preserved | Optional (`pdftoppm`) | Best for born-digital PDFs |
| DOCX | Yes (`python-docx`) | Yes (CSV/Markdown) | Embedded extraction | Pandoc fallback on error |
| PPTX | Yes (`python-pptx`) | Yes (shape tables) | Not supported | Includes speaker notes |
| HTML | Yes (Readability) | Yes (via markdownify) | Not extracted | markdownify primary, Pandoc fallback |
| XLSX | Yes (`openpyxl`) | Yes (CSV per sheet) | Not supported | `data_only=True` for computed values |
| XLS | Not supported | — | — | Convert to XLSX manually |

## Output Structure

For an input `MyFile.pdf`, produces:

```
output_dir/
├── MyFile.opencode.md      # Markdown body with headings, tables, image refs
├── MyFile.opencode.json    # Structured JSON: metadata, segments, tables, assets
└── MyFile.assets/          # Extracted images (only if --images flag used)
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
| `--strict` | `false` | Treat warnings as errors (exit non-zero, no output files written) |
| `--verbose` | `false` | Show detailed logging and tracebacks on error |

## Environment Prep Checklist

```bash
# 1) Verify Python
python3 --version

# 2) Install external tools (recommended)
brew install poppler pandoc

# 3) Verify external tools
which pdftotext pdftoppm pdfinfo pandoc

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
   cp /Users/example/source/utilities/docpipe/opencode_tool/convert_document.ts .opencode/tools/convert_document.ts
   ```

   **Global copy** (tool available in all OpenCode sessions):
   ```bash
   mkdir -p ~/.config/opencode/tools
   cp /Users/example/source/utilities/docpipe/opencode_tool/convert_document.ts ~/.config/opencode/tools/convert_document.ts
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

- The `docpipe` executable must be accessible at the path specified in the tool file. By default it resolves to `<worktree>/docpipe/docpipe`. If you've placed docpipe elsewhere, edit the `docpipePath` line in `convert_document.ts`.
- OpenCode uses [Bun](https://bun.sh) as its runtime, which is installed with OpenCode. No additional Bun/Node setup is needed.

### Alternative: MCP server (future)

For a more structured integration, docpipe could be exposed as an MCP server. This would require adding a `mcp-serve` subcommand that speaks JSON-RPC over stdio, then configuring it in `opencode.json`:

```json
{
  "mcp": {
    "docpipe": {
      "type": "local",
      "command": ["/path/to/docpipe", "mcp-serve"],
      "enabled": true
    }
  }
}
```

This is not implemented in v1 but is a natural extension.

## Troubleshooting

**"pdftotext not found"** — Install poppler: `brew install poppler`

**"Conversion failed" on DOCX** — If `python-docx` can't parse the file, install Pandoc for the fallback path: `brew install pandoc`

**XLS files** — Not supported. Convert to XLSX using LibreOffice (`soffice --headless --convert-to xlsx input.xls`) or Excel, then run docpipe on the XLSX.

**First run is slow** — Normal. uv is resolving and caching the dependencies. Subsequent runs are instant.

**Reset the runtime** — If something goes wrong with the Python environment, clear uv's cache for the script with `uv cache clean` and run docpipe again.

## Tests (pytest)

Unit tests cover CLI parser + strict-mode behavior.

```bash
cd /Users/example/source/utilities/docpipe
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```
