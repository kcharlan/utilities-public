#!/bin/bash
set -euo pipefail
script=$(cd "$(dirname "$0")/.." && pwd)/trim_last
d=$(mktemp -d "${TMPDIR:-/tmp}/audit-XXXXXX")
trap 'rm -r -- "${d:?}"' EXIT
for cmd in ffmpeg ffprobe shasum; do command -v "$cmd" >/dev/null; done
ffmpeg -v error -f lavfi -i color=c=black:s=16x16:d=1 -c:v libx264 "$d/clip.mp4"
hash=$(shasum "$d/clip.mp4" | cut -d' ' -f1)
cd "$d"
if "$script" -s '' -f 1 clip.mp4; then echo 'same file accepted' >&2; exit 1; fi
[[ $(shasum clip.mp4 | cut -d' ' -f1) == "$hash" ]]
ln -s clip.mp4 clip_trim.mp4
if "$script" -f 1 ./clip.mp4; then echo 'symlink accepted' >&2; exit 1; fi
[[ $(shasum clip.mp4 | cut -d' ' -f1) == "$hash" ]]
rm -- clip_trim.mp4
ln clip.mp4 clip_trim.mp4
if "$script" -f 1 clip.mp4; then echo 'hard link accepted' >&2; exit 1; fi
[[ $(shasum clip.mp4 | cut -d' ' -f1) == "$hash" ]]
rm -- clip_trim.mp4
cp clip.mp4 clip_trim.mp4
if "$script" -f 1 clip.mp4 clip_trim.mp4; then echo 'another input accepted as output' >&2; exit 1; fi
[[ $(shasum clip_trim.mp4 | cut -d' ' -f1) == "$hash" ]]
rm -- clip_trim.mp4 clip_trim_trim.mp4
if "$script" 1 missing.mp4; then echo 'missing input accepted' >&2; exit 1; fi
printf 'invalid media\n' > bad.mp4
if "$script" 1 bad.mp4; then echo 'invalid input accepted' >&2; exit 1; fi
[[ ! -e bad_trim.mp4 ]]
cp clip.mp4 unsupported.foo
printf 'existing output' > unsupported_trim.foo
if "$script" -f 1 unsupported.foo; then echo 'encoding failure accepted' >&2; exit 1; fi
[[ $(cat unsupported_trim.foo) == 'existing output' ]]
"$script" 1 clip.mp4
[[ -s clip_trim.mp4 ]]
