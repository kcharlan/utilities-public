# PDF Split by Size

Shell utility that divides a PDF into sequential, page-aligned chunks while
preserving page order. Each chunk stays at or below a requested file size unless
a single source page is already larger than that limit.

## Requirements

- `zsh`
- `qpdf`
- BSD-compatible `stat` with `-f%z` support (available by default on macOS)

The script is not currently compatible with the GNU `stat` command normally
installed on Linux. The source PDF must be readable by `qpdf`; the script does
not accept a password for encrypted PDFs.

## Usage

```bash
./pdf-split-by-size.sh BigDoc.pdf 10M BigDoc_part
# -> BigDoc_part_1.pdf, BigDoc_part_2.pdf, ...
```

Arguments:

1. `input.pdf` – Source document.
2. `max_size` – Upper bound per chunk (`500K`, `10M`, `1G`, or a raw byte count).
3. `output_prefix` (optional) – Defaults to `chunk`.

Output files are written to the current directory unless the prefix includes a
path. Their names follow `<output_prefix>_<number>.pdf`.

## How it works

- Size suffixes are case-insensitive and use powers of 1024 (`K`, `M`, and `G`).
- Starting at the first unprocessed page, the script uses `qpdf` to create
  progressively larger candidate page ranges in a temporary directory.
- When the next candidate exceeds the limit, the last fitting range is written
  as the next numbered output file.
- A single page that exceeds the requested size is written as its own chunk.
- Temporary files are removed when the script exits.

## Tips

- Candidate PDFs are regenerated as pages are added, so large documents may
  take time to process. Local storage will generally be faster.
- Combine with `gs` (Ghostscript) to downsample images before splitting if you need smaller pieces.
