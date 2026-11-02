#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd "$(dirname "$0")/.." && pwd)
scratch=$(mktemp -d "${TMPDIR:-/tmp}/rsk-stream.XXXXXX")
trap 'rm -r -- "$scratch"' EXIT
export UV_PYTHON_DOWNLOADS=never

"$project_dir/rs.py" selftest > "$scratch/selftest.log"
test "$(grep -c 'Transform done:' "$scratch/selftest.log")" -eq 3
grep -q 'SELFTEST PASSED!' "$scratch/selftest.log"

{ for i in $(seq 1 150); do printf 'SYNTHETIC-RSK-%04d\n' "$i"; done; head -c 300 /dev/zero | tr '\0' Z; } > "$scratch/original.bin"
golden="$project_dir/tests/fixtures/synthetic-golden.rsbwt"
for decoder in rs.py rs-big.py; do
    "$project_dir/$decoder" inverse -i "$golden" -o "$scratch/$decoder.golden" --verbose > "$scratch/$decoder.log"
    cmp "$scratch/original.bin" "$scratch/$decoder.golden"
done
grep -q XFORM "$scratch/rs.py.log"

for encoder in rs.py rs-big.py; do
    if [[ $encoder == rs.py ]]; then decoder=rs-big.py; else decoder=rs.py; fi
    "$project_dir/$encoder" transform -i "$scratch/original.bin" -o "$scratch/$encoder.stream" --block-size 1K
    "$project_dir/$decoder" inverse -i "$scratch/$encoder.stream" -o "$scratch/$encoder.cross"
    cmp "$scratch/original.bin" "$scratch/$encoder.cross"
    : > "$scratch/empty"
    "$project_dir/$encoder" transform -i "$scratch/empty" -o "$scratch/$encoder.empty.stream"
    "$project_dir/$encoder" inverse -i "$scratch/$encoder.empty.stream" -o "$scratch/$encoder.empty.out"
    cmp "$scratch/empty" "$scratch/$encoder.empty.out"
done
echo 'Stream format tests passed'
