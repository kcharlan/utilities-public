# Video Scene Detection Cheatsheet
Notes and helpers for running `PySceneDetect` on long-form footage. Useful for quickly splitting a video into individual scenes or exporting representative frames.

## Environment

```bash
./setup.sh
source venv/bin/activate
```

`setup.sh` installs `scenedetect[opencv]` plus the OpenCV wheel and dependencies required for the command-line interface.

## Common Commands

```bash
# Split input video at sharp content cuts (default content detector)
scenedetect -i video.mp4 split-video

# Save keyframes from each detected scene into the current directory
scenedetect -i video.mp4 save-images

# Skip the first 10 seconds before detecting scenes
scenedetect -i video.mp4 time -s 10s split-video

# Use perceptual hash-based detection with a custom threshold
scenedetect -i video.mp4 detect-hash -t 0.16 split-video
```

See `quick-start.txt` for the raw command references captured while experimenting.

## Tips

- Add `--min-scene-len 2s` (or similar) to prevent over-fragmenting short clips.
- Combine detectors: `detect-content` (default) works well for hard cuts, while `detect-threshold` or `detect-hash` catch lighting changes or fades.
- When saving images, append `--output /path/to/stills` to keep your working directory tidy.
- Use the `time` subcommand to trim or window the video before running additional detectors—everything after `time` is treated as a nested command.
