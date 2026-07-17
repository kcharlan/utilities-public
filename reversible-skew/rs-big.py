#!/usr/bin/env python3
import argparse, struct, sys

# --- Dependencies for high-performance routines ---
try:
    import pydivsufsort
    _HAVE_DIVSUFSORT = True
except ImportError:
    _HAVE_DIVSUFSORT = False
    import warnings
    warnings.warn("pydivsufsort not installed; falling back to naive BWT.", ImportWarning)

from numba import njit

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
    rots = [data[i:] + data[:i] for i in range(n)]
    rots.sort()
    last = bytes(r[-1] for r in rots)
    primary = rots.index(data)
    return last, primary


def bwt_inverse(last_column: bytes, primary_index: int) -> bytes:
    n = len(last_column)
    if n == 0:
        return b''
    counts = {}
    for c in last_column:
        counts[c] = counts.get(c, 0) + 1
    symbols = sorted(counts)
    C = {}
    cum = 0
    for c in symbols:
        C[c] = cum
        cum += counts[c]
    occ = {}
    ranks = [0] * n
    for i, c in enumerate(last_column):
        occ[c] = occ.get(c, 0) + 1
        ranks[i] = occ[c]
    res = bytearray(n)
    idx = primary_index
    for i in range(n - 1, -1, -1):
        c = last_column[idx]
        res[i] = c
        idx = C[c] + ranks[idx] - 1
    return bytes(res)

# --- JIT-accelerated MTF & RLE encode/decode ---
@njit
def mtf_encode_jit(data):
    symbols = list(range(256))
    out = []
    for b in data:
        # linear search
        idx = 0
        for j in range(len(symbols)):
            if symbols[j] == b:
                idx = j
                break
        out.append(idx)
        sym = symbols.pop(idx)
        symbols.insert(0, sym)
    return out

@njit
def mtf_decode_jit(indices):
    symbols = list(range(256))
    n = len(indices)
    out = [0] * n
    for i in range(n):
        idx = indices[i]
        b = symbols[idx]
        out[i] = b
        sym = symbols.pop(idx)
        symbols.insert(0, sym)
    return out

@njit
def rle_encode_jit(indices, max_run):
    out = []
    i = 0
    n = len(indices)
    while i < n:
        v = indices[i]
        run = 1
        while i + run < n and indices[i + run] == v and run < max_run:
            run += 1
        out.append((v, run))
        i += run
    return out

@njit
def rle_decode_jit(pairs):
    # count total length
    total = 0
    for v, run in pairs:
        total += run
    out = [0] * total
    idx = 0
    for v, run in pairs:
        for k in range(run):
            out[idx] = v
            idx += 1
    return out

# --- pure-Python I/O helpers ---

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

# --- Transform & inverse ---
SENTINEL = 0xFFFFFFFF

def transform(infile, outfile, block_size, max_run, verbose=False, whole_file=False):
    total = passed = 0
    with open(infile, 'rb') as fin, open(outfile, 'wb') as fout:
        blocks = [fin.read()] if whole_file else []
        if not whole_file:
            while True:
                b = fin.read(block_size)
                if not b: break
                blocks.append(b)

        for block in blocks:
            total += 1
            last, primary = bwt_transform(block)
            mtf = mtf_encode_jit(last)
            rle = rle_encode_jit(mtf, max_run)
            payload = len(rle) * 2
            # optional self-validation omitted for speed
            if payload >= len(block):
                passed += 1
                if verbose: print(f"Block {total}: RAW (len={len(block)})")
                fout.write(struct.pack('>I', SENTINEL))
                fout.write(struct.pack('>I', len(block)))
                fout.write(block)
            else:
                if verbose: print(f"Block {total}: XFORM {len(block)}→{payload}")
                fout.write(struct.pack('>I', primary))
                fout.write(struct.pack('>I', payload))
                write_rle(fout, rle)
    pct = (passed/total*100) if total else 0
    print(f"Transform done: {passed}/{total} blocks passthrough ({pct:.1f}%)")


def inverse(infile, outfile, verbose=False, whole_file=False):
    idx = 0
    with open(infile, 'rb') as fin, open(outfile, 'wb') as fout:
        while True:
            hdr = fin.read(8)
            if not hdr: break
            idx += 1
            primary, payload = struct.unpack('>II', hdr)
            mode = 'RAW' if primary == SENTINEL else 'XFORM'
            if verbose: print(f"Block {idx}: {mode}, payload={payload}")
            if primary == SENTINEL:
                fout.write(fin.read(payload))
            else:
                pairs = read_rle(fin, payload)
                mtf = rle_decode_jit(pairs)
                last = mtf_decode_jit(mtf)
                data = bwt_inverse(last, primary)
                fout.write(data)

# --- CLI ---
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="High-speed rs-big (Numba-accelerated)")
    subs = parser.add_subparsers(dest='cmd', required=True)

    t = subs.add_parser('transform', help='Skew-transform input')
    t.add_argument('-i','--input', required=True)
    t.add_argument('-o','--output',required=True)
    t.add_argument('-b','--block-size', type=parse_size, default='4M')
    t.add_argument('--rle-max-run', type=int, default=255)
    t.add_argument('-w','--whole-file', action='store_true')
    t.add_argument('-v','--verbose', action='store_true')

    u = subs.add_parser('inverse', help='Recover original')
    u.add_argument('-i','--input',required=True)
    u.add_argument('-o','--output',required=True)
    u.add_argument('-w','--whole-file', action='store_true')
    u.add_argument('-v','--verbose', action='store_true')

    args = parser.parse_args()
    if args.cmd == 'transform':
        transform(args.input, args.output,
                  args.block_size, args.rle_max_run,
                  verbose=args.verbose, whole_file=args.whole_file)
    else:
        inverse(args.input, args.output,
                verbose=args.verbose, whole_file=args.whole_file)
