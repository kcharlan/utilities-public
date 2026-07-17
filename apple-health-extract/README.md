# Apple Health Workout Extractor
Utilities for turning an Apple Health export (`export.xml`) into structured CSV datasets covering workouts, heart-rate detail, and incidental exercise bouts.

## What You Get

- `workout_summary.csv` – One row per recorded workout with start/end timestamps, duration, device, heart-rate aggregates, steps, distance, and calorie totals.
- `workout_heart_rate_detail.csv` – Timestamped heart-rate samples keyed to the workout that produced them.
- `exercise_bouts.csv` – Groups of non-workout Apple Exercise Time minutes, annotated with average heart rate, steps, calories, and overlapping workout labels (Workout vs Incidental).

## Files

- `extract_workout_stats.py` – Parses workouts and health records from the export, writes summary and heart-rate detail CSVs.
- `exercise_bouts.py` – Groups Apple Exercise Time minutes into bouts, labels them against workouts, and writes a bouts CSV.
- `setup.sh` – Creates a `venv/` and installs dependencies (`pandas` and `tqdm`).
- `run.sh` – Portable wrapper that works beside the project or as a standalone copy using local project-path configuration.
- `project-dir.example` – Conspicuously synthetic example of the one-line local path configuration. It is documentation only.

## Environment

1. Run `./setup.sh` to create a `venv/` and install dependencies (`pandas` and `tqdm`).
2. Activate the virtual environment: `source venv/bin/activate`.

## Portable wrapper

When `run.sh` remains in this project directory, it finds the project beside itself:

```bash
./run.sh --check
./run.sh
```

To copy the wrapper elsewhere, including `~/Library/Scripts`, create its private local configuration while your shell is in this project directory:

```bash
mkdir -p "$HOME/.apple-health-extract"
chmod 700 "$HOME/.apple-health-extract"
printf '%s\n' "$(pwd -P)" > "$HOME/.apple-health-extract/project-dir"
chmod 600 "$HOME/.apple-health-extract/project-dir"
cp run.sh "$HOME/Library/Scripts/apple-health-extract"
chmod 755 "$HOME/Library/Scripts/apple-health-extract"
"$HOME/Library/Scripts/apple-health-extract" --check
```

The `project-dir` file contains exactly one absolute path. The wrapper reads it as plain text and never sources or evaluates it. `APPLE_HEALTH_EXTRACT_PROJECT_DIR` may override the configured path, and `APPLE_HEALTH_EXTRACT_HOME` may override the runtime directory for controlled use or tests.

If a standalone copy has no configuration, its first processing or `--check` invocation creates an empty `~/.apple-health-extract/project-dir`, prints an actionable error, and stops without running the extractor. Fill that file locally and retry. The wrapper does not inspect or migrate any legacy machine-specific path.

## Required Inputs

1. From the Health app, export your data (Profile Icon → Export All Health Data) which produces a ZIP file.
2. Extract `export.xml` and place it in this directory.

## Typical Workflow

1. **Generate workout summaries and heart-rate detail**
   ```bash
   ./run.sh
   ```
   - Scans every `<Workout>` entry to build a baseline table.
   - Streams the XML once more to capture heart rate, steps, distance, and active calories for the workout window.
   - Writes `workout_summary.csv` and `workout_heart_rate_detail.csv`.

2. **Build incidental exercise bouts**
   ```bash
   venv/bin/python exercise_bouts.py
   ```
   - Consumes `workout_summary.csv` to label bouts that overlap an official workout.
   - Groups contiguous Apple Exercise Time records within 90 seconds into a single bout.
   - Aggregates complementary metrics (heart rate, steps, calories, distance) and writes `exercise_bouts.csv`.

## Performance Notes

- `extract_workout_stats.py` streams the XML via `iterparse` and clears elements immediately to keep memory stable even for multi-gigabyte exports.
- `exercise_bouts.py` pre-counts the XML lines to show a progress bar sized correctly for large files.
- Expect multi-minute runtimes for multi-year exports; run from SSD storage when possible.

## Troubleshooting

- Ensure `export.xml` is UTF-8 encoded. The scripts open the file in text mode with `errors="ignore"` to survive odd characters, but a corrupt XML file will still fail.
- If you have only a small subset of data, confirm that the export actually contains Apple Exercise Time records—otherwise `exercise_bouts.py` raises a descriptive error.
