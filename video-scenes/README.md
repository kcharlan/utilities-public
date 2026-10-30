# Video Scene Detection Cheatsheet

This directory contains a small launcher for
[PySceneDetect](https://www.scenedetect.com/) and a few common commands for
detecting cuts, splitting videos, and exporting scene previews.

## Requirements

- [uv](https://docs.astral.sh/uv/) (`brew install uv`).
- `ffmpeg` must be available on `PATH` to use `split-video`.

## Setup

Run the launcher from this directory. uv resolves Python 3.12 and the exact
dependency releases tracked in [requirements.txt](requirements.txt) on first
run. OpenCV is declared directly because PySceneDetect no longer publishes an
`opencv` extra.

```bash
cd video-scenes
./video-scenes --help
```

## Common Commands

```bash
# Detect cuts with the default detector and write one clip per scene.
./video-scenes -i video.mp4 split-video

# Save three representative frames per detected scene.
./video-scenes -i video.mp4 save-images

# Analyze from 10 seconds onward, then split the detected scenes.
./video-scenes -i video.mp4 time --start 10s split-video

# Use perceptual hash detection with a custom threshold.
./video-scenes -i video.mp4 detect-hash -t 0.16 split-video
```

## Tips

- Put global options before commands. For example, use
  `./video-scenes -i video.mp4 --output ./stills save-images`.
- Add `--min-scene-len 2.0` before the detector or output commands to merge cuts
  that would create shorter scenes.
- Use `detect-content` or `detect-adaptive` for fast cuts,
  `detect-threshold` for fades, and `detect-hash` for perceptual hash
  comparisons.
- Use `time --start`, `--end`, or `--duration` to restrict the analyzed range.
- Run `./video-scenes --help` for the global options, or
  `./video-scenes help <command>` for command-specific options.

## Validation

Run `./video-scenes --help` as the dependency smoke check after an
update. Also run a synthetic scene-detection check, keeping the fixture and
results outside the checkout:

```bash
S=$(mktemp -d "${TMPDIR:-/tmp}/vs-check.XXXXXX")
ffmpeg -v error -f lavfi -i testsrc=size=320x240:rate=25:duration=3 \
  -f lavfi -i color=c=red:size=320x240:rate=25:duration=3 \
  -filter_complex '[0:v][1:v]concat=n=2:v=1[v]' -map '[v]' \
  -pix_fmt yuv420p "$S/cut.mp4"
./video-scenes -i "$S/cut.mp4" -o "$S/scenes" detect-content list-scenes
```

Acceptance: the scene CSV contains exactly two 75-frame scenes spanning
0–3 and 3–6 seconds, with the cut at `00:00:03.000` (the second scene starts
at frame 76). For dependency updates, retain the baseline scene CSV before
changing the graph and require identical scene boundaries afterward;
processing-time logs are not the comparison criterion.

See the [PySceneDetect CLI reference](https://www.scenedetect.com/docs/latest/cli.html)
for complete command and detector documentation.
