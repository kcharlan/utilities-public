#!/bin/bash
set -euo pipefail
project=$(cd "$(dirname "$0")/.." && pwd)
d=$(mktemp -d "${TMPDIR:-/tmp}/audit-XXXXXX")
trap 'rm -r -- "${d:?}"' EXIT
for cmd in uv shasum; do command -v "$cmd" >/dev/null; done
export UV_PYTHON_DOWNLOADS=never
cd "$d"
failures=0
for script in "$project/rs.py" "$project/rs-big.py"; do
  for operation in transform inverse; do
    printf 'synthetic input data\n' > input
    hash=$(shasum input | cut -d' ' -f1)
    if "$script" "$operation" -i input -o ./input; then echo 'same file accepted' >&2; exit 1; fi
    [[ $(shasum input | cut -d' ' -f1) == "$hash" ]]
    ln -s input link
    if "$script" "$operation" -i input -o link; then echo 'symlink accepted' >&2; exit 1; fi
    [[ $(shasum input | cut -d' ' -f1) == "$hash" ]]
    rm -- link
    ln input link
    if "$script" "$operation" -i input -o link; then echo 'hard link accepted' >&2; exit 1; fi
    [[ $(shasum input | cut -d' ' -f1) == "$hash" ]]
    rm -- link
  done
  printf 'bad' > invalid
  printf 'existing output' > output
  if "$script" inverse -i invalid -o output; then echo 'invalid stream accepted' >&2; exit 1; fi
  [[ $(cat output) == 'existing output' ]]
  if "$script" inverse -i invalid -o absent; then echo 'invalid stream accepted' >&2; exit 1; fi
  [[ ! -e absent ]]
  head -c 100 /dev/urandom > raw.bin
  "$script" transform -i raw.bin -o raw.rsbwt
  [[ $(od -An -tx1 -N4 raw.rsbwt | tr -d ' \n') == ffffffff ]]
  head -c 98 raw.rsbwt > cut.rsbwt
  rm -f restored
  if "$script" inverse -i cut.rsbwt -o restored; then
    echo "$script: truncated RAW accepted without existing output" >&2
    failures=$((failures + 1))
  fi
  if [[ -e restored ]]; then echo "$script: created truncated output" >&2; failures=$((failures + 1)); fi
  printf 'existing output' > restored
  if "$script" inverse -i cut.rsbwt -o restored; then
    echo "$script: truncated RAW accepted with existing output" >&2
    failures=$((failures + 1))
  fi
  if [[ $(cat restored) != 'existing output' ]]; then echo "$script: replaced existing output" >&2; failures=$((failures + 1)); fi
  if "$script" inverse -i invalid -o restored 2> error; then
    echo "$script: partial header accepted" >&2; failures=$((failures + 1))
  elif ! grep -q 'EOFError: Expected 8 header bytes, got 3' error; then
    echo "$script: partial header did not raise expected EOFError" >&2; failures=$((failures + 1))
  fi
done
(( failures == 0 ))
