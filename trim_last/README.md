# trim_last

`trim_last` creates a new video containing the final requested number of seconds
from each input file. If a video is shorter than the requested duration, the
whole video is retained.

By default, video is re-encoded as H.264 and audio as AAC for an accurate cut.
Subtitle streams are copied, data streams are omitted, and container metadata is
preserved. Use `--copy` to copy all streams without re-encoding when speed is
more important than frame-accurate trimming; the start of a copied segment is
limited by the available keyframes.

## Requirements

- `zsh`
- `ffmpeg`
- `ffprobe` (normally installed with `ffmpeg`)

The script is executable in place:

```bash
./trim_last 90 recording.mp4
./trim_last --copy -s _tail 30 *.mov
```

If the script is installed somewhere on `PATH`, omit the leading `./`.

## Usage

```text
trim_last [-s suffix] [-f] [--copy] seconds video_file [...]
```

Options must appear before the duration and input files:

- `-s`, `--suffix`: text appended to the input name before its extension
  (default: `_trim`)
- `-f`, `--force`: overwrite an existing output
- `--copy`: copy streams instead of re-encoding them
- `-h`, `--help`: show command help

For example, `recording.mp4` produces `recording_trim.mp4` by default. Outputs
are written beside their inputs, and input files are never overwritten. The
script skips an input if it is missing, its duration cannot be read, or its
output already exists without `--force`; it continues processing any remaining
inputs.
