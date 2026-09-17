#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Create sampled video recaps with the system FFmpeg tools."""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import random
import subprocess
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    has_audio: bool


@dataclass(frozen=True)
class Segment:
    start: float
    duration: float


class MediaProcessingError(RuntimeError):
    """An expected input, probe, or render failure."""


def probe_media(path: Path) -> MediaInfo:
    """Return duration and audio presence reported by the system ffprobe."""
    command = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", os.fspath(path),
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, check=False, shell=False
        )
    except FileNotFoundError as exc:
        raise MediaProcessingError(
            "ffprobe was not found on PATH; install FFmpeg and try again"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "ffprobe could not read the media"
        raise MediaProcessingError(detail)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise MediaProcessingError("ffprobe returned invalid JSON") from exc
    try:
        duration = float(payload["format"]["duration"])
        streams = payload["streams"]
    except (KeyError, TypeError, ValueError) as exc:
        raise MediaProcessingError(
            "ffprobe output did not contain valid media metadata"
        ) from exc
    if not math.isfinite(duration) or duration <= 0:
        raise MediaProcessingError("media must have a finite positive duration")
    if not isinstance(streams, list):
        raise MediaProcessingError("ffprobe output did not contain a stream list")
    return MediaInfo(
        duration=duration,
        has_audio=any(
            isinstance(stream, dict) and stream.get("codec_type") == "audio"
            for stream in streams
        ),
    )


def sample_start_times(
    total_duration: float,
    tail_length: float,
    sample_length: float,
    num_samples: int,
    method: str,
    rng: random.Random | None = None,
) -> list[float]:
    """Choose sample starts while preserving the legacy sampling matrix."""
    sampling_range = max(0.0, total_duration - tail_length)
    max_start = max(0.0, sampling_range - sample_length)
    if method == "even":
        if num_samples <= 1:
            return [0.0]
        step = max_start / (num_samples - 1)
        return [0.0] + [
            step * index for index in range(1, num_samples - 1)
        ] + [max_start]
    if method == "random":
        if max_start <= 0 or num_samples == 0:
            return []
        sample_count = min(num_samples, 1_000)
        generator = rng if rng is not None else random
        indices = sorted(generator.sample(range(1_000), sample_count))
        return [index * max_start / 999 for index in indices]
    raise ValueError("sampling method must be 'even' or 'random'.")


def build_segments(
    total_duration: float,
    tail_length: float,
    sample_length: float,
    num_samples: int,
    method: str,
    rng: random.Random | None = None,
) -> list[Segment]:
    """Build eligible samples followed by the clamped tail segment."""
    tail_length = min(tail_length, total_duration)
    starts = sample_start_times(
        total_duration, tail_length, sample_length, num_samples, method, rng
    )
    segments: list[Segment] = []
    for start in starts:
        end = min(start + sample_length, total_duration - tail_length)
        if end > start:
            # Preserve the legacy behavior: eligibility uses the clamped end,
            # but an accepted sample retains its full requested duration.
            segments.append(Segment(start, sample_length))
    segments.append(Segment(max(0.0, total_duration - tail_length), tail_length))
    return segments


def _ffmpeg_number(value: float) -> str:
    return format(value, ".15g")


def build_filter_graph(
    segments: Sequence[Segment], has_audio: bool
) -> tuple[str, list[str]]:
    """Build one ordered trim/reset/concat graph and its output map labels."""
    if not segments:
        raise ValueError("at least one segment is required")
    filters: list[str] = []
    concat_inputs: list[str] = []
    for index, segment in enumerate(segments):
        start = _ffmpeg_number(segment.start)
        duration = _ffmpeg_number(segment.duration)
        filters.append(
            f"[0:v]trim=start={start}:duration={duration},"
            f"setpts=PTS-STARTPTS[v{index}]"
        )
        concat_inputs.append(f"[v{index}]")
        if has_audio:
            filters.append(
                f"[0:a]atrim=start={start}:duration={duration},"
                f"asetpts=PTS-STARTPTS[a{index}]"
            )
            concat_inputs.append(f"[a{index}]")
    audio_count = 1 if has_audio else 0
    outputs = ["[v]"] + (["[a]"] if has_audio else [])
    filters.append(
        "".join(concat_inputs)
        + f"concat=n={len(segments)}:v=1:a={audio_count}"
        + "".join(outputs)
    )
    return ";".join(filters), outputs


def _temporary_output_path(output_path: Path) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.stem}.partial.",
        suffix=output_path.suffix,
        dir=output_path.parent,
    )
    os.close(descriptor)
    return Path(temporary_name)


def process_video(
    input_path: str | Path,
    output_path: str | Path,
    num_samples: int,
    sample_length: float,
    tail_length: float,
    sampling_method: str,
    verbose: bool = False,
) -> bool:
    """Render one recap atomically, returning whether FFmpeg succeeded."""
    source = Path(input_path)
    final = Path(output_path)
    temporary: Path | None = None
    try:
        info = probe_media(source)
        segments = build_segments(
            info.duration, tail_length, sample_length, num_samples, sampling_method
        )
        if verbose:
            for index, segment in enumerate(segments[:-1], start=1):
                print(
                    f"Sample {index}: {segment.start:.2f}s to "
                    f"{segment.start + segment.duration:.2f}s"
                )
        filter_graph, output_maps = build_filter_graph(segments, info.has_audio)
        final.parent.mkdir(parents=True, exist_ok=True)
        temporary = _temporary_output_path(final)
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i",
            os.fspath(source), "-filter_complex", filter_graph,
        ]
        for label in output_maps:
            command.extend(["-map", label])
        command.extend(["-c:v", "h264_videotoolbox"])
        if info.has_audio:
            command.extend(["-c:a", "aac"])
        command.append(os.fspath(temporary))
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, check=False, shell=False
            )
        except FileNotFoundError as exc:
            raise MediaProcessingError(
                "ffmpeg was not found on PATH; install FFmpeg and try again"
            ) from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "ffmpeg render failed"
            raise MediaProcessingError(detail)
        os.replace(temporary, final)
        temporary = None
        return True
    except (MediaProcessingError, OSError, ValueError) as exc:
        print(f"Failed to process {source}: {exc}")
        return False
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def batch_args(path: str, args: argparse.Namespace) -> tuple[object, ...]:
    base = Path(path).stem
    output = Path(args.output_dir) / f"{base}_compilation.mp4"
    return (
        path, output, args.samples, args.sample_length, args.tail_length,
        args.sampling, args.verbose,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compile a video from samples and a tail segment."
    )
    parser.add_argument(
        "--input", required=True, help="Input file or wildcard pattern (e.g., '*.mp4')"
    )
    parser.add_argument(
        "--output_dir", default="outputs", help="Directory to save output files"
    )
    parser.add_argument("--samples", type=int, default=10, help="Number of samples")
    parser.add_argument(
        "--sample_length", type=float, default=10, help="Sample clip length (seconds)"
    )
    parser.add_argument(
        "--tail_length", type=float, default=90, help="Tail segment length (seconds)"
    )
    parser.add_argument(
        "--sampling", choices=["even", "random"], default="even", help="Sampling method"
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument(
        "--max_workers", type=int, default=None,
        help="Number of parallel workers (default: all cores)",
    )
    args = parser.parse_args(argv)

    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    files = glob.glob(args.input)
    if not files:
        print("No matching files found.")
        return 0

    with ProcessPoolExecutor(max_workers=args.max_workers) as executor:
        future_inputs = {
            executor.submit(process_video, *batch_args(path, args)): path for path in files
        }
        total = len(future_inputs)
        for completed_count, future in enumerate(as_completed(future_inputs), start=1):
            path = future_inputs[future]
            try:
                succeeded = future.result()
            except Exception as exc:
                print(f"Failed to process {path}: unexpected worker error: {exc}")
                succeeded = False
            status = "completed" if succeeded else "failed"
            print(f"Processing videos: {completed_count}/{total} ({status}: {path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
