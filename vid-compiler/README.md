# Video Compiler

`video_compiler.py` creates a recap for each video matched by an input path or
glob. Each recap contains sampled clips followed by the requested segment from
the end of the source video. Multiple input files are processed concurrently.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- Python 3.12 or newer, selected by uv from the launcher's inline metadata
- System `ffmpeg` and `ffprobe` commands on `PATH`
- An FFmpeg build with the `h264_videotoolbox` encoder

The launcher has no third-party Python runtime packages. On macOS, Homebrew's
FFmpeg build provides the required command-line tools and encoder:

```bash
brew install ffmpeg
ffmpeg -hide_banner -encoders | grep h264_videotoolbox
```

The fixed hardware encoder makes the tool macOS-oriented. Processing fails
with an actionable per-file message when FFmpeg, ffprobe, readable media, or
the required encoder is unavailable.

## Usage

Run the command directly through uv. No setup script or activated virtual
environment is required:

```bash
uv run --script video_compiler.py \
  --input "*.mp4" \
  --output_dir zz-comps \
  --samples 5 \
  --sample_length 8 \
  --tail_length 90 \
  --sampling even \
  --max_workers 8
```

Keep glob patterns quoted so the script, rather than the shell, expands them.

| Argument | Required | Default | Description |
| --- | --- | --- | --- |
| `--input` | Yes | — | One file path or a glob pattern. Each match is processed independently. |
| `--output_dir` | No | `outputs` | Output directory, created when necessary. Relative paths are resolved from the current working directory. |
| `--samples` | No | `10` | Requested number of sample clips. |
| `--sample_length` | No | `10` | Length of each sample clip, in seconds. |
| `--tail_length` | No | `90` | Length of the final segment, in seconds. |
| `--sampling` | No | `even` | `even` for evenly spaced start times or `random` for distinct selections from a 1,000-point grid. |
| `--max_workers` | No | Executor default | Maximum number of concurrent FFmpeg worker processes. |
| `--verbose` | No | Off | Print accepted sample ranges while processing. |

If the glob has no matches, the script prints `No matching files found.` and
exits with status zero without creating a video.

## Output

Each input file produces `<basename>_compilation.mp4` in the output directory.
FFmpeg constructs one trim/concatenation graph, resets timestamps on every
leg, and re-encodes video with `h264_videotoolbox`. Inputs with audio receive
an AAC output stream; video-only inputs remain video-only.

Renders use a unique temporary `.mp4` beside the final path. A successful
render atomically replaces the final path; a failure removes only its own
partial and leaves an existing final untouched.

Input files from different directories that share the same base name still map
to the same final output path. Their temporary files cannot collide, but the
last successful worker to replace the final path wins. Use separate runs or
output directories when that final-path collision is undesirable.

## Behavior and limitations

- A requested tail longer than the video is reduced to the video's duration.
- Sampling start times are chosen from the portion before the tail. If an
  accepted sample overlaps the tail boundary, it retains the full requested
  sample length before the tail is appended. Multiple even samples can repeat
  the same start time.
- Random sampling is without replacement and caps a request at the available
  1,000-point grid.
- A processing error is printed with the affected input and the remaining
  files continue. Missing matches, per-file failures, and unexpected worker
  exceptions retain the historical overall zero exit status.

Use `--sampling random` for different selections across runs. Reduce
`--max_workers` if concurrent FFmpeg processes exhaust system resources.

## Development and validation

Tests use an isolated project environment; `requirements-dev.txt` contains
pytest only:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
uv run --script video_compiler.py --help
```

For a render smoke, create conspicuously synthetic sources with FFmpeg's
`testsrc` or `color` and `sine` generators. Validate both an audio/video input
and a video-only input. Probe the outputs with `ffprobe` and confirm their
duration and stream codecs: H.264 video for both, AAC only for the source with
audio. Inspect boundary frames when changing sampling or graph construction to
confirm the samples remain ordered and the tail is last, and confirm no
`*.partial*.mp4` files remain.
