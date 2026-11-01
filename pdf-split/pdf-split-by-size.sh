#!/usr/bin/env zsh
set -euo pipefail

if (( $# < 2 )); then
  echo "Usage: $0 input.pdf <max_size>(e.g., 10M, 500K, 1G) [output_prefix]"
  exit 1
fi

in="$1"
limit_str="$2"
prefix="${3:-chunk}"

to_bytes() {
  local s="${1:u}" n unit
  if [[ "$s" =~ ^([0-9]+)([KMG]?)$ ]]; then
    n="${match[1]}" ; unit="${match[2]}"
    case "$unit" in
      K) echo $(( n * 1024 )) ;;
      M) echo $(( n * 1024 * 1024 )) ;;
      G) echo $(( n * 1024 * 1024 * 1024 )) ;;
      "") echo $n ;;
    esac
  else
    echo "Invalid size: $1" >&2
    exit 2
  fi
}

lim_bytes=$(to_bytes "$limit_str")

# Total pages
pages=$(qpdf --show-npages "$in")

# Every possible chunk name must be safe before any output is published.
for (( chunk = 1; chunk <= pages; chunk++ )); do
  final="${prefix}_$chunk.pdf"
  if [[ "$in" -ef "$final" ]]; then
    echo "Output would overwrite input: $final" >&2
    exit 1
  fi
done

start=1
chunk=1

tmpdir=$(mktemp -d "${prefix:h}/.pdf-split.XXXXXX")
trap 'rm -r -- "${tmpdir:?}"' EXIT

while (( start <= pages )); do
  end=$start
  while :; do
    test_out="$tmpdir/test.pdf"
    # Build a candidate chunk [start..end]
    qpdf --empty --pages "$in" "$start-$end" -- "$test_out" >/dev/null 2>&1
    size=$(stat -f%z "$test_out")

    if (( size > lim_bytes )); then
      if (( end == start )); then
        # Single page exceeds limit — emit it anyway to avoid infinite loop
        break
      fi
      (( end-- ))
      break
    fi

    if (( end >= pages )); then
      break
    fi
    (( end++ ))
  done

  final="${prefix}_$chunk.pdf"
  qpdf --empty --pages "$in" "$start-$end" -- "$tmpdir/chunk_$chunk.pdf"
  (( chunk++ ))
  (( start = end + 1 ))
done

for (( n = 1; n < chunk; n++ )); do
  final="${prefix}_$n.pdf"
  mv -f -- "$tmpdir/chunk_$n.pdf" "$final"
  echo "Wrote $final"
done
