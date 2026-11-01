#!/bin/bash
set -euo pipefail
project=$(cd "$(dirname "$0")/.." && pwd)
d=$(mktemp -d "${TMPDIR:-/tmp}/audit-XXXXXX")
trap 'rm -r -- "${d:?}"' EXIT
for cmd in uv shasum; do command -v "$cmd" >/dev/null; done
export UV_PYTHON_DOWNLOADS=never
cd "$d"
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
done
