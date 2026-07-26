# Video Scene Detection Cheatsheet

This directory contains a small helper for installing
[PySceneDetect](https://www.scenedetect.com/) and a few common commands for
detecting cuts, splitting videos, and exporting scene previews.

## Requirements

- `python3.12` must be available on `PATH`.
- `ffmpeg` must be available on `PATH` to use `split-video`.

## Setup

Run the setup script from this directory:

```bash
cd video-scenes
./setup.sh
source venv/bin/activate
```

The script deletes and recreates `video-scenes/venv`, then installs PySceneDetect,
OpenCV, and the CLI dependencies into it. Do not keep anything important in that
directory.

## Common Commands

```bash
# Detect cuts with the default detector and write one clip per scene.
scenedetect -i video.mp4 split-video

# Save three representative frames per detected scene.
scenedetect -i video.mp4 save-images

# Analyze from 10 seconds onward, then split the detected scenes.
scenedetect -i video.mp4 time --start 10s split-video

# Use perceptual hash detection with a custom threshold.
scenedetect -i video.mp4 detect-hash -t 0.16 split-video
```

## Tips

- Put global options before commands. For example, use
  `scenedetect -i video.mp4 --output ./stills save-images`.
- Add `--min-scene-len 2.0` before the detector or output commands to merge cuts
  that would create shorter scenes.
- Use `detect-content` or `detect-adaptive` for fast cuts,
  `detect-threshold` for fades, and `detect-hash` for perceptual hash
  comparisons.
- Use `time --start`, `--end`, or `--duration` to restrict the analyzed range.
- Run `scenedetect --help` for the global options, or
  `scenedetect help <command>` for command-specific options.

See the [PySceneDetect CLI reference](https://www.scenedetect.com/docs/latest/cli.html)
for complete command and detector documentation.
