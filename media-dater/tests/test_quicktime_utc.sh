#!/bin/bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
d=$(mktemp -d "${TMPDIR:-/tmp}/audit-XXXXXX")
trap 'rm -r -- "${d:?}"' EXIT
mkdir "$d/media"
ffmpeg -loglevel error -f lavfi -i color=c=black:s=16x16:d=1 -c:v mpeg4 "$d/media/synthetic.mov"
TZ=UTC exiftool -overwrite_original '-QuickTime:CreateDate=2037:03:26 01:30:00' "$d/media/synthetic.mov" >/dev/null
"$root/media-dater" --help >/dev/null
TZ=America/New_York "$root/media-dater" --dry-run "$d/media" > "$d/dry-run"
grep -q 'QuickTimeUTC=1' "$d/dry-run"
test -f "$d/media/synthetic.mov"
printf '%s\n' 'synthetic.mov -> IMG_20370325_213000_00.mov' > "$d/manifest"
TZ=America/New_York "$root/media-dater" "$d/media"
test -f "$d/media/IMG_20370325_213000_00.mov"
test ! -e "$d/media/synthetic.mov"
