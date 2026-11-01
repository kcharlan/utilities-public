#!/bin/bash
set -euo pipefail
script=$(cd "$(dirname "$0")/.." && pwd)/trim_last
d=$(mktemp -d "${TMPDIR:-/tmp}/audit-XXXXXX")
trap 'rm -r -- "${d:?}"' EXIT
for cmd in ffmpeg ffprobe perl shasum; do command -v "$cmd" >/dev/null; done
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
for kind in symlink directory; do
  mkdir "$kind"
  cp clip.mp4 "$kind/clip.mp4"
  if [[ $kind == directory ]]; then
    mkdir "$kind/clip_trim.mp4"
  else
    mkdir "$kind/target"
    ln -s target "$kind/clip_trim.mp4"
  fi
  cp clip.mp4 "$kind/clip_trim.mp4/clip_trim.mp4"
  before_first=$(shasum "$kind/clip.mp4" | cut -d' ' -f1)
  before_second=$(shasum "$kind/clip_trim.mp4/clip_trim.mp4" | cut -d' ' -f1)
  if "$script" -f 0.2 "$kind/clip.mp4" "$kind/clip_trim.mp4/clip_trim.mp4"; then
    echo "$kind destination accepted" >&2
    exit 1
  fi
  [[ $(shasum "$kind/clip.mp4" | cut -d' ' -f1) == "$before_first" ]] || exit 1
  [[ $(shasum "$kind/clip_trim.mp4/clip_trim.mp4" | cut -d' ' -f1) == "$before_second" ]] || exit 1
done
# A directory created after validation must not become an implicit destination.
mkdir race_bin
real_ffmpeg=$(command -v ffmpeg)
cat > race_bin/ffmpeg <<'SH'
#!/bin/bash
"$REAL_FFMPEG" "$@" || exit $?
mkdir "$RACE_DEST"
SH
chmod +x race_bin/ffmpeg
cp clip.mp4 race.mp4
if REAL_FFMPEG="$real_ffmpeg" RACE_DEST="$d/race_trim.mp4" PATH="$d/race_bin:$PATH" "$script" -f 1 race.mp4; then
  echo 'late directory destination accepted' >&2
  exit 1
fi
[[ -d race_trim.mp4 && ! -e race_trim.mp4/race_trim.mp4 ]] || exit 1
[[ $(shasum race.mp4 | cut -d' ' -f1) == "$hash" ]] || exit 1
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
