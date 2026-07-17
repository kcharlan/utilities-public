# Video Compiler
Batch tool that samples highlight clips from long-form footage and appends a tail segment, producing shareable recaps in one pass. Relies on MoviePy with optional multiprocessing.

## Environment

```bash
./setup.sh
source venv/bin/activate
```

`moviepy` pulls in `ffmpeg` wrappers, but you still need FFmpeg installed on your system (Homebrew: `brew install ffmpeg`).

## Usage

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

Arguments:

- `--input` – Single file path or glob pattern (`"*.mp4"`). Each match is processed independently.
- `--output_dir` – Folder for compiled clips (created if missing).
- `--samples` – Number of samples to grab from the first portion of the video.
- `--sample_length` – Duration (seconds) of each sample clip.
- `--tail_length` – Seconds from the end of the video to append verbatim.
- `--sampling` – `even` (linspace across the eligible segment) or `random`.
- `--max_workers` – Parallel workers for ProcessPoolExecutor; default uses all cores.
- `--verbose` – Print sample ranges while processing.

## Output

Each input file produces `<basename>_compilation.mp4` in the output directory. Encoding uses `h264_videotoolbox` on Apple Silicon with AAC audio for fast hardware-assisted exports.

## Implementation Notes

- `sample_start_times` avoids exceeding the tail segment by constraining the sampling range.
- Videos shorter than the requested tail length automatically shrink the tail to fit.
- Errors within a worker process are surfaced on stdout; the main thread keeps the progress bar moving via `tqdm`.

## Tips

- Use `--sampling random` when you want varied highlight reels from the same source footage.
- Reduce `--max_workers` if you hit system resource limits (MoviePy spawns FFmpeg subprocesses under the hood).
- Concatenated clips use `method="compose"` to handle mismatched resolutions; resize upstream for faster exports.

