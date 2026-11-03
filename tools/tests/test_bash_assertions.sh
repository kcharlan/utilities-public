#!/bin/bash
# macOS Bash 3.2 does not stop a `set -e` script when a standalone `[[ ... ]]`
# line fails, so such an assertion can never fail a test. Require an explicit
# failure handler on every one in tracked Bash scripts.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)

# Prints file:line for each standalone [[ ... ]] in a Bash script that uses set -e.
find_vacuous() {
  local file
  for file in "$@"; do
    head -n 1 "$file" | grep -q 'bash' || continue
    grep -q 'set -e' "$file" || continue
    { grep -nE '^[[:space:]]*\[\[.*\]\][[:space:]]*$' "$file" || true; } | sed "s|^|$file:|" | cut -d: -f1,2
  done
}

scratch=$(mktemp -d "${TMPDIR:-/tmp}/bash-assertions-test.XXXXXX")
trap 'rm -rf -- "$scratch"' EXIT
printf '#!/bin/bash\nset -e\n[[ 1 == 2 ]]\n[[ 1 == 1 ]] || exit 1\n' > "$scratch/synthetic.sh"
detected=$(find_vacuous "$scratch/synthetic.sh")
[[ $detected == "$scratch/synthetic.sh:3" ]] || { echo "FAIL: guard self-check found '$detected'" >&2; exit 1; }

cd "$root"
files=()
while IFS= read -r file; do files+=("$file"); done < <(git ls-files '*.sh' '*.bash')
found=$(find_vacuous "${files[@]}")
if [[ -n $found ]]; then
  echo 'FAIL: standalone [[ ... ]] assertions need an explicit failure handler:' >&2
  echo "$found" >&2
  exit 1
fi
echo 'bash assertion guard passed'
