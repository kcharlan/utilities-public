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

# Exercise the EXIT cleanup with a pathname that cannot safely be embedded in shell code.
mkdir "$d/bin" "$d/quote ' tmp" "$d/input"
: > "$d/input/synthetic.jpg"
cat > "$d/bin/exiftool" <<'SH'
#!/bin/bash
while [ "$#" -gt 0 ]; do
    if [ "$1" = -@ ]; then printf '%s\n' "$2" > "$ARGFILE_RECORD"; break; fi
    shift
done
exit "${EXIF_EXIT:-0}"
SH
chmod 755 "$d/bin/exiftool"
for expected in 0 7; do
    rc=0
    ARGFILE_RECORD="$d/argfile-record" EXIF_EXIT="$expected" TMPDIR="$d/quote ' tmp" PATH="$d/bin:$PATH" \
        "$root/media-dater" "$d/input" > "$d/synthetic-output" 2>&1 || rc=$?
    [ "$rc" -eq "$expected" ] || { echo "FAIL: expected exit $expected, got $rc"; exit 1; }
    argfile=$(cat "$d/argfile-record")
    [ ! -e "$argfile" ] && [ ! -L "$argfile" ] || { echo 'FAIL: argfile remains'; exit 1; }
done
