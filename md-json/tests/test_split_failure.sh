#!/bin/bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
python=${PYTHON:-"$root/.venv/bin/python"}
d=$(mktemp -d "${TMPDIR:-/tmp}/audit-XXXXXX")
trap 'rm -r -- "${d:?}"' EXIT
cat > "$d/input.json" <<'JSON'
{"all_items":[{"obj_type":"acct","id":"a","name":"SYNTHETIC A","type":"b"},{"obj_type":"acct","id":"b","name":"SYNTHETIC B","type":"e"},{"obj_type":"txn","acctid":"a","0.acctid":"b","0.samt":"bad","0.pamt":"1"}]}
JSON
printf 'preserve existing output\n' > "$d/output.csv"
if "$python" "$root/md_converter.py" --input "$d/input.json" --output "$d/output.csv" > "$d/log" 2>&1; then
    echo 'invalid split unexpectedly succeeded' >&2
    exit 1
fi
grep -qi 'split' "$d/log"
grep -qx 'preserve existing output' "$d/output.csv"
sed 's/"0.samt":"bad"/"0.samt":"-1"/' "$d/input.json" > "$d/valid.json"
"$python" "$root/md_converter.py" --input "$d/valid.json" --output "$d/output.csv" > "$d/log"
grep -q 'SYNTHETIC A' "$d/output.csv"
grep -q 'SYNTHETIC B' "$d/output.csv"
sed 's/"0.acctid":"b"/"0.acctid":"missing"/' "$d/valid.json" > "$d/missing.json"
cp "$d/output.csv" "$d/expected.csv"
if "$python" "$root/md_converter.py" --input "$d/missing.json" --output "$d/output.csv" > "$d/log" 2>&1; then
    echo 'unknown split account unexpectedly succeeded' >&2
    exit 1
fi
grep -qi 'split' "$d/log"
cmp "$d/expected.csv" "$d/output.csv"
