import argparse
import os
import glob
import numpy as np
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor, as_completed

from moviepy.video.io.VideoFileClip import VideoFileClip
from moviepy import concatenate_videoclips

def sample_start_times(total_duration, tail_length, sample_length, num_samples, method):
    sampling_range = max(0, total_duration - tail_length)
    max_start = max(0, sampling_range - sample_length)
    if method == 'even':
        if num_samples <= 1:
            return [0]
        return np.linspace(0, max_start, num_samples)
    elif method == 'random':
        if max_start <= 0 or num_samples == 0:
            return []
        possible = np.linspace(0, max_start, 1000)
        if num_samples > len(possible):
            num_samples = len(possible)
        starts = np.sort(np.random.choice(possible, num_samples, replace=False))
        return starts
    else:
        raise ValueError("sampling method must be 'even' or 'random'.")

def process_video(input_path, output_path, num_samples, sample_length, tail_length, sampling_method, verbose=False):
    try:
        video = VideoFileClip(input_path)
        duration = video.duration

        if tail_length > duration:
            tail_length = duration

        # Tail: last N seconds
        tail_clip = video.subclipped(max(0, duration - tail_length), duration)

        # Clips from first part
        starts = sample_start_times(duration, tail_length, sample_length, num_samples, sampling_method)
        clips = []
        for idx, start in enumerate(starts):
            end = min(start + sample_length, duration - tail_length)
            if end > start:
                clips.append(video.subclipped(start, start + sample_length))
                if verbose:
                    print(f"Sample {idx+1}: {start:.2f}s to {start + sample_length:.2f}s")
        # Add tail
        clips.append(tail_clip)

        # Concatenate
        compilation = concatenate_videoclips(clips, method="compose")
        # Apple Silicon hardware acceleration: h264_videotoolbox
        compilation.write_videofile(output_path, codec="h264_videotoolbox", audio_codec="aac")
    except Exception as e:
        print(f"Failed to process {input_path}: {e}")

def batch_args(f, args):
    base = os.path.splitext(os.path.basename(f))[0]
    out = os.path.join(args.output_dir, f"{base}_compilation.mp4")
    return (f, out, args.samples, args.sample_length, args.tail_length, args.sampling, args.verbose)

def main():
    parser = argparse.ArgumentParser(description="Compile a video from samples and a tail segment.")
    parser.add_argument("--input", required=True, help="Input file or wildcard pattern (e.g., '*.mp4')")
    parser.add_argument("--output_dir", default="outputs", help="Directory to save output files")
    parser.add_argument("--samples", type=int, default=10, help="Number of samples")
    parser.add_argument("--sample_length", type=float, default=10, help="Sample clip length (seconds)")
    parser.add_argument("--tail_length", type=float, default=90, help="Tail segment length (seconds)")
    parser.add_argument("--sampling", choices=["even", "random"], default="even", help="Sampling method")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--max_workers", type=int, default=None, help="Number of parallel workers (default: all cores)")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    files = glob.glob(args.input)
    if not files:
        print("No matching files found.")
        return

    # Multicore batch processing
    with ProcessPoolExecutor(max_workers=args.max_workers) as executor:
        futures = [
            executor.submit(process_video, *batch_args(f, args))
            for f in files
        ]
        for _ in tqdm(as_completed(futures), total=len(futures), desc="Processing videos"):
            pass  # Progress bar only; errors print inside process_video

if __name__ == "__main__":
    main()
