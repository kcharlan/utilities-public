# Reversible Skew
Experimentation ground for a reversible Burrows–Wheeler transform (BWT) pipeline with Move-to-Front (MTF) encoding, run-length encoding (RLE), and passthrough fallbacks when compression would expand data.

## Scripts

- `rs.py` – Pure-Python implementation with optional `pydivsufsort` acceleration for suffix arrays. Self-validates every block (round-trip reconstruct + compare) before writing. Includes a `selftest` subcommand for quick verification.
- `rs-big.py` – **(Recommended)** Performance-oriented variant that JIT-compiles the MTF/RLE steps with Numba and skips round-trip validation for speed. No `selftest` subcommand.
- `setup.sh` – Builds `venv/` with Python 3.12 and installs all dependencies (`pydivsufsort` and `numba`).

## Workflow

1. **Setup the environment**
   ```bash
   ./setup.sh
   source venv/bin/activate
   ```

2. **Transform a file**
   ```bash
   python rs-big.py transform -i input.bin -o output.rsbwt -b 4M --rle-max-run 255 -v
   ```
   - Splits the file into fixed-size blocks (`-b`/`--block-size`).
   - Applies BWT → MTF → RLE and writes the primary index + payload length per block.
   - If the compressed payload would be larger than the original block, writes the raw block with a sentinel so the inverse can copy it back.

3. **Invert the transform**
   ```bash
   python rs-big.py inverse -i output.rsbwt -o recovered.bin -v
   ```
   - Restores the original bytes block-by-block using the stored primary index or passthrough sentinel.

4. **Self-test** (`rs.py` only)
   ```bash
   python rs.py selftest
   ```
   - Round-trips 1 MiB of random data through transform + inverse and verifies byte-for-byte equality.

## Options

Both scripts accept the same core flags:

| Flag | Description |
|:---|:---|
| `-i`/`--input` | Input file path (required) |
| `-o`/`--output` | Output file path (required) |
| `-b`/`--block-size` | Block size; accepts raw integers or sizes like `256K`, `4M` (default `4M`) |
| `--rle-max-run` | Max RLE run length, default 255 (fits one byte) |
| `-w`/`--whole-file` | Process the entire file as a single block |
| `-v`/`--verbose` | Print per-block mode (RAW vs XFORM) and payload sizes |

## Dependencies

- `pydivsufsort` dramatically speeds up suffix array construction compared to the naive `O(n^2 log n)` rotation sort.
- `numba` enables the JIT paths in `rs-big.py`. Without it, the script falls back to slower pure-Python loops.

## Implementation Notes

- BWT inverse uses LF-mapping with explicit cumulative counts (`C`) and Occurrence tables.
- Validation in `rs.py` reconstructs each block and compares to the original before writing, guaranteeing reversibility even under rare corner cases.
- Output format: `[primary_index:uint32][payload_len:uint32][payload_bytes...]` repeated per block. Raw blocks are tagged with `primary_index = 0xFFFFFFFF`.

## Ideas for Future Work

- Add secondary entropy coding (e.g., `zlib`, `range coding`) on top of the RLE stream.
- Implement adaptive block sizing based on entropy estimators.
- Surface compression ratios and timings in the CLI output.
