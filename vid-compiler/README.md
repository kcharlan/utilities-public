# Video Compiler

`video_compiler.py` creates a recap for each video matched by an input path or
glob. Each recap contains sampled clips followed by the requested segment from
the end of the source video. Multiple input files are processed concurrently.

## Requirements

- Python 3.12
- FFmpeg with the `h264_videotoolbox` encoder

The provided setup script recreates `vid-compiler/venv` and installs MoviePy,
NumPy, and tqdm. Run it from this directory:

```bash
./setup.sh
source venv/bin/activate
```

`setup.sh` deletes any existing `venv` directory before creating the new
environment. MoviePy obtains an FFmpeg binary through ImageIO automatically,
but that binary must provide the fixed `h264_videotoolbox` encoder used by this
script. To use Homebrew's FFmpeg build on macOS:

```bash
brew install ffmpeg
export FFMPEG_BINARY="$(brew --prefix)/bin/ffmpeg"
```

The codec choice makes the current script macOS-oriented. The command fails for
an FFmpeg build that does not provide the encoder.

## Usage

Run the command from `vid-compiler` with the virtual environment activated:

```bash
python video_compiler.py \
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
| `--sampling` | No | `even` | `even` for evenly spaced start times or `random` for randomly selected start times. |
| `--max_workers` | No | Executor default | Maximum number of concurrent worker processes. |
| `--verbose` | No | Off | Print sample ranges while processing. |

If the glob has no matches, the script prints `No matching files found.` and
exits without creating a video.

## Output

Each input file produces `<basename>_compilation.mp4` in the output directory.
The result is re-encoded with `h264_videotoolbox` video and AAC audio.

Input files from different directories that share the same base name map to the
same output path. Use separate runs or output directories to avoid collisions.

## Behavior and limitations

- A requested tail longer than the video is reduced to the video's duration.
- Sampling start times are chosen from the portion before the tail. If that
  portion is shorter than `--sample_length`, samples can overlap the appended
  tail; multiple even samples can also repeat the same start time.
- Clips are concatenated with MoviePy's `compose` method, which accommodates
  different clip sizes at the cost of additional processing.
- A processing error is printed for the affected input and the remaining files
  continue. The script does not currently return a failing exit status for
  those per-file errors.

Use `--sampling random` for different selections across runs. Reduce
`--max_workers` if concurrent FFmpeg processes exhaust system resources.
