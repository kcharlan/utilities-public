# trim_last

`trim_last` creates a new video containing the final requested number of seconds from each input file. By default it re-encodes video with H.264 and audio with AAC for accurate cuts. `--copy` performs a faster stream copy when keyframe-level precision is acceptable.

Requirements: `zsh`, `ffmpeg`, and `ffprobe`.

```bash
trim_last 90 recording.mp4
trim_last --copy -s _tail 30 *.mov
```

The input is never overwritten. Existing outputs are skipped unless `--force` is supplied.
