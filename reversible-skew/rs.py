#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pydivsufsort==0.0.20"]
# ///
import argparse, struct, sys
import contextlib, os, tempfile

# --- Optional fast SA for BWT; naive fallback if missing ---
try:
    import pydivsufsort
    _HAVE_DIVSUFSORT = True
except ImportError:
    _HAVE_DIVSUFSORT = False
    import warnings
    warnings.warn("pydivsufsort not installed; falling back to naive BWT.", ImportWarning)


# --- human-friendly size parsing ---
def parse_size(s: str) -> int:
    s = s.strip()
    if s.isdigit():
        return int(s)
    unit = s[-1].upper()
    num = s[:-1]
    try:
        val = float(num)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid size: '{s}'")
    mult = {'K': 1024, 'M': 1024**2, 'G': 1024**3}
    if unit in mult:
        return int(val * mult[unit])
    raise argparse.ArgumentTypeError(f"Unknown unit '{unit}' in '{s}'")


def parse_rle_max_run(s: str) -> int:
    try:
        value = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid run length: '{s}'")
    if not 1 <= value <= 255:
        raise argparse.ArgumentTypeError("--rle-max-run must be between 1 and 255")
    return value


# --- BWT + inverse (LF-mapping) ---
def bwt_transform(data: bytes):
    n = len(data)
    if n == 0:
        return b'', 0
    if _HAVE_DIVSUFSORT:
        sa = pydivsufsort.divsufsort(data)
        last = bytearray(n)
        primary = None
        for i, si in enumerate(sa):
            last[i] = data[(si - 1) % n]
            if si == 0:
                primary = i
        return bytes(last), primary
    # naive fallback
    rots = [data[i:] + data[:i] for i in range(n)]
    rots.sort()
    last = bytes(r[-1] for r in rots)
    primary = rots.index(data)
    return last, primary

def bwt_inverse(last_column: bytes, primary_index: int) -> bytes:
    n = len(last_column)
    if n == 0:
        return b''
    # build cumulative counts C
    counts = {}
    for c in last_column:
        counts[c] = counts.get(c, 0) + 1
    symbols = sorted(counts)
    C = {}
    cum = 0
    for c in symbols:
        C[c] = cum
        cum += counts[c]
    # build ranks
    occ = {}
    ranks = [0] * n
    for i, c in enumerate(last_column):
        occ[c] = occ.get(c, 0) + 1
        ranks[i] = occ[c]
    # reconstruct
    res = bytearray(n)
    idx = primary_index
    for i in range(n - 1, -1, -1):
        c = last_column[idx]
        res[i] = c
        idx = C[c] + ranks[idx] - 1
    return bytes(res)


# --- pure-Python MTF & RLE encode/decode ---
def mtf_encode(data: bytes):
    symbols = list(range(256))
    out = []
    for b in data:
        idx = symbols.index(b)
        out.append(idx)
        symbols.pop(idx)
        symbols.insert(0, b)
    return out

def mtf_decode(indices):
    symbols = list(range(256))
    out = []
    for idx in indices:
        b = symbols[idx]
        out.append(b)
        symbols.pop(idx)
        symbols.insert(0, b)
    return bytes(out)

def rle_encode(indices, max_run=255):
    out = []
    i = 0
    n = len(indices)
    while i < n:
        v = indices[i]
        run = 1
        while i + run < n and indices[i+run] == v and run < max_run:
            run += 1
        out.append((v, run))
        i += run
    return out

def rle_decode(pairs):
    out = []
    for v, run in pairs:
        out.extend([v] * run)
    return out


# --- I/O helpers ---
def write_rle(f, pairs):
    for v, run in pairs:
        f.write(struct.pack('>BB', v, run))

def read_rle(f, length):
    raw = f.read(length)
    if len(raw) < length:
        raise EOFError(f"Expected {length} RLE bytes, got {len(raw)}")
    pairs = []
    for i in range(0, length, 2):
        v, run = struct.unpack('>BB', raw[i:i+2])
        pairs.append((v, run))
    return pairs


# --- transform/inverse with passthrough, self-validate, verbose ---
SENTINEL = 0xFFFFFFFF

@contextlib.contextmanager
def atomic_output(infile, outfile):
    if os.path.exists(outfile) and os.path.samefile(infile, outfile):
        raise ValueError("input and output refer to the same file")
    fd, temp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(outfile)))
    try:
        with os.fdopen(fd, 'wb') as fout:
            yield fout
        os.replace(temp, outfile)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def transform(infile, outfile, block_size, max_run, verbose=False, whole_file=False):
    total = passed = 0
    with open(infile, 'rb') as fin, atomic_output(infile, outfile) as fout:
        # read blocks
        if whole_file:
            blocks = [fin.read()]
        else:
            blocks = []
            while True:
                blk = fin.read(block_size)
                if not blk:
                    break
                blocks.append(blk)

        for block in blocks:
            total += 1
            # forward transform
            last, primary = bwt_transform(block)
            mtf          = mtf_encode(last)
            rle          = rle_encode(mtf, max_run)
            payload      = len(rle) * 2

            # self-validate
            bad = (payload >= len(block))
            if not bad:
                # invert in-memory
                rec_last  = mtf_decode(rle_decode(rle))
                rec_block = bwt_inverse(rec_last, primary)
                if rec_block != block:
                    bad = True

            if bad:
                passed += 1
                if verbose:
                    print(f"Block {total}: RAW (len={len(block)})")
                fout.write(struct.pack('>I', SENTINEL))
                fout.write(struct.pack('>I', len(block)))
                fout.write(block)
            else:
                if verbose:
                    print(f"Block {total}: XFORM {len(block)}→{payload}")
                fout.write(struct.pack('>I', primary))
                fout.write(struct.pack('>I', payload))
                write_rle(fout, rle)

    pct = (passed / total * 100) if total else 0
    print(f"Transform done: {passed}/{total} blocks passthrough ({pct:.1f}%)")
    return passed, total


def inverse(infile, outfile, verbose=False, whole_file=False):
    idx = 0
    with open(infile, 'rb') as fin, atomic_output(infile, outfile) as fout:
        while True:
            hdr = fin.read(8)
            if not hdr:
                break
            if len(hdr) < 8:
                raise EOFError(f"Expected 8 header bytes, got {len(hdr)}")
            idx += 1
            primary, payload = struct.unpack('>II', hdr)
            mode = 'RAW' if primary == SENTINEL else 'XFORM'
            if verbose:
                print(f"Block {idx}: {mode}, payload={payload}")

            if primary == SENTINEL:
                data = fin.read(payload)
                if len(data) != payload:
                    raise EOFError(f"Expected {payload} raw bytes, got {len(data)}")
                fout.write(data)
            else:
                pairs = read_rle(fin, payload)
                mtf_i = rle_decode(pairs)
                last  = mtf_decode(mtf_i)
                orig  = bwt_inverse(last, primary)
                fout.write(orig)


def selftest():
    unit = b"synthetic reversible skew line\n"
    cases = {
        "random": os.urandom(1 << 20),
        "periodic": (unit * ((1 << 20) // len(unit) + 1))[:1 << 20],
        "varied": b"".join(f"synthetic line {i:06d} value {i * 7 % 1000}\n".encode() for i in range(60000))[:1 << 20],
    }
    with tempfile.TemporaryDirectory() as d:
        for name, data in cases.items():
            src, enc, dec = (os.path.join(d, f"{name}.{ext}") for ext in ("in", "rsbwt", "out"))
            with open(src, "wb") as f:
                f.write(data)
            passed, total = transform(src, enc, 64 * 1024, 255)
            if name == "varied" and passed == total:
                print("SELFTEST FAILED: varied (no block took the transformed path)")
                sys.exit(1)
            inverse(enc, dec)
            with open(dec, "rb") as f:
                if f.read() != data:
                    print(f"SELFTEST FAILED: {name}")
                    sys.exit(1)
    print("SELFTEST PASSED!")


# --- CLI ---
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Blockwise BWT→MTF→RLE skew-transform (self-validating)")
    subs = parser.add_subparsers(dest='cmd', required=True)

    # transform
    t = subs.add_parser('transform', help='Skew-transform input file')
    t.add_argument('-i','--input',     required=True, help='Input file path')
    t.add_argument('-o','--output',    required=True, help='Transformed output')
    t.add_argument('-b','--block-size', type=parse_size, default='4M',
                   help='Block size (e.g. 1M, 512K)')
    t.add_argument('-w','--whole-file', action='store_true',
                   help='Treat entire input as single block')
    t.add_argument('--rle-max-run', type=parse_rle_max_run, default=255,
                   help='Max RLE run length (1-255; default 255)')
    t.add_argument('-v','--verbose',   action='store_true',
                   help='Show per-block debug info')

    # inverse
    u = subs.add_parser('inverse', help='Recover original file')
    u.add_argument('-i','--input',    required=True, help='Transformed input')
    u.add_argument('-o','--output',   required=True, help='Recovered output')
    u.add_argument('-w','--whole-file', action='store_true',
                   help='Inverse of whole-file transform (same as transform)')
    u.add_argument('-v','--verbose',  action='store_true',
                   help='Show per-block debug info')

    # selftest
    subs.add_parser('selftest', help='Round-trip test on random, periodic, and varied data')

    args = parser.parse_args()
    if args.cmd == 'transform':
        transform(args.input, args.output,
                  args.block_size, args.rle_max_run,
                  verbose=args.verbose, whole_file=args.whole_file)
    elif args.cmd == 'inverse':
        inverse(args.input, args.output,
                verbose=args.verbose, whole_file=args.whole_file)
    else:
        selftest()
