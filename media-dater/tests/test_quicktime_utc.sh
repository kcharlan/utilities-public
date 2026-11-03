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
TZ=America/New_York "$root/media-dater" "$d/media"
test -f "$d/media/IMG_20370325_213000_00.mov"
test ! -e "$d/media/synthetic.mov"
rerun=$(TZ=America/New_York "$root/media-dater" "$d/media")
[[ "$rerun" == 'No files need renaming. (Skipped: 1)' ]] || { echo 'FAIL: media-dater/tests/test_quicktime_utc.sh:17' >&2; exit 1; }
test -f "$d/media/IMG_20370325_213000_00.mov"

# A same-second collision must preserve the existing file and every input byte.
mkdir "$d/collision"
for color in red white blue; do
    ffmpeg -loglevel error -f lavfi -i "color=c=$color:s=16x16:d=1" -c:v mpeg4 "$d/collision/$color.mov"
    TZ=UTC exiftool -overwrite_original '-QuickTime:CreateDate=2037:03:26 01:30:00' "$d/collision/$color.mov" >/dev/null
done
mv "$d/collision/red.mov" "$d/collision/IMG_20370325_213000_00.mov"
cp "$d/collision/IMG_20370325_213000_00.mov" "$d/red-reference.mov"
before_hashes=$(shasum "$d/collision/"*.mov | awk '{print $1}' | sort)
if [ "$(printf '%s\n' "$before_hashes" | sort -u | wc -l | tr -d ' ')" -ne 3 ]; then
    echo 'FAIL: collision inputs must have distinct hashes' >&2
    exit 1
fi
TZ=America/New_York "$root/media-dater" "$d/collision"
shopt -s nullglob
collision_files=("$d/collision/IMG_20370325_213000_"*.mov)
shopt -u nullglob
if [ "${#collision_files[@]}" -ne 3 ]; then
    printf 'FAIL: expected 3 collision files, got %s\n' "${#collision_files[@]}" >&2
    exit 1
fi
if ! cmp -s "$d/red-reference.mov" "$d/collision/IMG_20370325_213000_00.mov"; then
    echo 'FAIL: existing red clip changed' >&2
    exit 1
fi
after_hashes=$(shasum "$d/collision/"*.mov | awk '{print $1}' | sort)
if [ "$before_hashes" != "$after_hashes" ]; then
    echo 'FAIL: collision input hashes changed' >&2
    exit 1
fi

# A regex metacharacter in the selected prefix must remain literal.
mkdir "$d/prefix"
: > "$d/prefix/SYN+_20370325_213000_00.mov"
prefix_output=$("$root/media-dater" --dry-run -p 'SYN+_' "$d/prefix")
[[ "$prefix_output" == 'No files need renaming. (Skipped: 1)' ]] || {
    printf 'FAIL: literal prefix: %s\n' "$prefix_output" >&2
    exit 1
}

# Discovery excludes hidden files by default and respects extension and depth filters.
mkdir -p "$d/discovery/sub"
: > "$d/discovery/a.jpg"
: > "$d/discovery/b.mov"
: > "$d/discovery/.hidden.jpg"
: > "$d/discovery/sub/c.jpg"
discovery=$("$root/media-dater" --dry-run "$d/discovery")
[[ "$discovery" == *'Found 2 files to rename.'* ]] || { echo 'FAIL: media-dater/tests/test_quicktime_utc.sh:67' >&2; exit 1; }
discovery=$("$root/media-dater" --dry-run --ext jpg "$d/discovery")
[[ "$discovery" == *'Found 1 files to rename.'* && "$discovery" == *"$d/discovery/a.jpg"* ]] || { printf 'FAIL: jpg discovery: %s\n' "$discovery" >&2; exit 1; }
discovery=$("$root/media-dater" --dry-run --recursive --ext jpg "$d/discovery")
[[ "$discovery" == *'Found 2 files to rename.'* && "$discovery" == *"$d/discovery/a.jpg"* && "$discovery" == *"$d/discovery/sub/c.jpg"* ]] || { printf 'FAIL: recursive jpg discovery: %s\n' "$discovery" >&2; exit 1; }

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
