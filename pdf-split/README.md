# PDF Split by Size
Shell utility that slices a large PDF into sequential chunks capped at a target file size. Ideal for platforms that reject uploads over a given limit while preserving page order.

## Requirements

- macOS or Linux with `zsh`, `qpdf`, and `stat`.
- Source PDF must not be encrypted; `qpdf` needs permission to read pages.

## Usage

```bash
./pdf-split-by-size.sh BigDoc.pdf 10M BigDoc_part
# -> BigDoc_part_1.pdf, BigDoc_part_2.pdf, ...
```

Arguments:

1. `input.pdf` – Source document.
2. `max_size` – Upper bound per chunk (`500K`, `10M`, `1G`, or a raw byte count).
3. `output_prefix` (optional) – Defaults to `chunk`.

The script probes page-by-page using a temporary rendering of candidate ranges to stay under the byte threshold. Single oversized pages are emitted as-is so the loop never stalls.

## Implementation Highlights

- Parses human-friendly size strings (`10M`, `750K`, etc.) via `to_bytes`.
- Uses `mktemp` for throwaway working files and guarantees cleanup with a `trap`.
- Streams blocks through `qpdf --empty --pages` to avoid intermediate full-PDF copies.

## Tips

- Increase performance by running against local SSD storage; the script rewrites each chunk once.
- Combine with `gs` (Ghostscript) to downsample images before splitting if you need smaller pieces.

