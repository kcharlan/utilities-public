# Reversible Skew

Experimental command-line tools for a blockwise Burrows–Wheeler transform
(BWT) pipeline with Move-to-Front (MTF) encoding and run-length encoding
(RLE). This is a transform rather than a general-purpose compressor: each
block is stored unchanged when its RLE payload would not be smaller.

## Scripts

- `rs.py` — Reference implementation. It uses `pydivsufsort` when available
  and otherwise falls back to a slow pure-Python cyclic-rotation sort. Before
  writing a transformed block, it reconstructs the block and compares it with
  the original; a failed check causes that block to be stored raw. It also
  provides a `selftest` subcommand.
- `rs-big.py` — Speed-oriented variant. Numba is required and JIT-compiles the
  MTF/RLE operations. `pydivsufsort` remains optional, but the pure-Python
  fallback is impractical for large blocks. It retains the per-block
  reconstruction guard from `rs.py:transform`, using its JIT decode routines,
  and provides a `selftest` subcommand for random, periodic, and varied data.

Both scripts read and write the same block format, so output from either script
can be inverted by the other.

## Setup

Install [uv](https://docs.astral.sh/uv/) (for example, `brew install uv`),
then run the scripts directly. uv selects Python 3.12 and installs the pinned
dependencies on first run.

The `rs.py` launcher installs `pydivsufsort`. If the script is run without it,
the fallback cyclic-rotation sort is suitable only for small inputs.

## Usage

Transform a file:

```bash
./rs.py transform \
  --input input.bin \
  --output output.rsbwt \
  --block-size 4M \
  --rle-max-run 255 \
  --verbose
```

Use `rs-big.py` in the same way for JIT-accelerated MTF/RLE operations. Both
scripts apply the reconstruction guard in `rs.py:transform` before writing
a transformed block; a failed comparison stores the original block instead.

Recover the original file:

```bash
./rs.py inverse \
  --input output.rsbwt \
  --output recovered.bin \
  --verbose
```

Run both scripts' built-in checks:

```bash
./rs.py selftest
./rs-big.py selftest
```

The reference selftest generates 1 MiB of random data, transforms it in
64 KiB blocks, inverts it, and compares the result byte-for-byte. The optimized
selftest checks 1 MiB each of random, periodic, and varied synthetic data and
requires at least one varied block to use the transformed path.

After code or dependency updates, run both selftests and both scripts' `--help`
commands. Cross-decode random, periodic, and varied synthetic fixtures between
the scripts and compare each recovered file with its original using `cmp`.
Also decode a retained valid pre-change synthetic stream with the changed
script and require byte equality. Keep fixtures and generated streams outside
the checkout. These checks form the project's complete compatibility validation.

### Transform options

| Flag | Description |
|:---|:---|
| `-i`, `--input` | Input file path (required). |
| `-o`, `--output` | Output file path (required). |
| `-b`, `--block-size` | Block size as bytes or a `K`, `M`, or `G` value; defaults to `4M`. |
| `--rle-max-run` | Maximum encoded run length; defaults to 255. Values must fit in the format's one-byte run field (1–255). |
| `-w`, `--whole-file` | Read the entire input and encode it as one block, ignoring `--block-size`. |
| `-v`, `--verbose` | Print each block's `RAW` or `XFORM` mode and size information. |

### Inverse options

The inverse command requires `--input` and `--output` and accepts `--verbose`.
Both scripts also accept `--whole-file` for inverse for CLI symmetry, but the
flag does not change decoding: block boundaries are already stored in the
input stream.

## File Format

The output is a sequence of blocks with no file-level header:

```text
[primary_index:uint32 big-endian]
[payload_length:uint32 big-endian]
[payload bytes]
```

For transformed blocks, the payload consists of repeated two-byte
`[MTF index, run length]` pairs. For raw blocks, `primary_index` is
`0xFFFFFFFF` and the payload is the original block. The format does not include
a magic number, version, checksum, or original filename; only invert files
produced by these scripts and use the output filename you want explicitly.

The inverse commands assume a well-formed input stream and are not hardened
parsers for untrusted or corrupted files.
