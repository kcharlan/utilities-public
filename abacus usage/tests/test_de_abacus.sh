#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
scratch="$(mktemp -d "${TMPDIR:-/tmp}/abacus-test.XXXXXX")"
trap 'rm -r -- "$scratch"' EXIT

cat > "$scratch/input.json" <<'JSON'
{"success": true, "result": {"columns": {"date": "Date", "credits": "Credits"}, "log": [{"date": "2030-01-01", "credits": "1.005"}, {"date": "2030-01-02", "credits": null, "newMetric": 3}]}}
JSON

printf '%s\r\n' 'date,credits,newMetric' '2030-01-01,1.01,0' '2030-01-02,0,3.0' > "$scratch/expected.csv"
UV_PYTHON_DOWNLOADS=never "$project_dir/de-abacus.py" "$scratch/input.json" "$scratch/out.csv" 2> "$scratch/stderr"
cmp "$scratch/expected.csv" "$scratch/out.csv"
grep -q 'WARNING:.*newMetric' "$scratch/stderr"

printf '%s\r\n' 'date,credits,newMetric' '2030-01-01,1.01,' '2030-01-02,,3.0' > "$scratch/expected.csv"
UV_PYTHON_DOWNLOADS=never "$project_dir/de-abacus.py" --no-zeros "$scratch/input.json" "$scratch/out.csv" 2> "$scratch/stderr"
cmp "$scratch/expected.csv" "$scratch/out.csv"
grep -q 'WARNING:.*newMetric' "$scratch/stderr"

cat > "$scratch/input.json" <<'JSON'
{"result":{"columns":{"credits":"Credits"},"log":[{"zMetric":7,"date":"2030-01-01","aMetric":5,"credits":1}]}}
JSON
printf '%s\r\n' 'date,credits,aMetric,zMetric' '2030-01-01,1.0,5.0,7.0' > "$scratch/expected.csv"
UV_PYTHON_DOWNLOADS=never "$project_dir/de-abacus.py" "$scratch/input.json" "$scratch/out.csv" 2> "$scratch/stderr"
cmp "$scratch/expected.csv" "$scratch/out.csv"
grep -q 'WARNING:.*aMetric.*date.*zMetric' "$scratch/stderr"
if grep 'WARNING:' "$scratch/stderr" | grep -q '2030-01-01'; then
    echo 'Warning exposed a row value' >&2
    exit 1
fi

cat > "$scratch/input.json" <<'JSON'
{"result":{"log":[{"zMetric":7,"date":"2030-01-01","aMetric":5}]}}
JSON
printf '%s\r\n' 'date,aMetric,zMetric' '2030-01-01,5.0,7.0' > "$scratch/expected.csv"
UV_PYTHON_DOWNLOADS=never "$project_dir/de-abacus.py" "$scratch/input.json" "$scratch/out.csv" 2> "$scratch/stderr"
cmp "$scratch/expected.csv" "$scratch/out.csv"
if grep -q 'WARNING:' "$scratch/stderr"; then
    echo 'Inferred columns unexpectedly produced a warning' >&2
    exit 1
fi

echo 'Abacus converter tests passed'
