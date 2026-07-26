# Apple Health Workout Extractor

Utilities for turning an Apple Health export (`export.xml`) into structured CSV datasets covering workouts, heart-rate detail, and incidental exercise bouts.

## What You Get

- `workout_summary.csv` – One row per recorded workout with start/end timestamps, duration, source name, heart-rate aggregates, steps, distance, and active-calorie totals.
- `workout_heart_rate_detail.csv` – Heart-rate samples whose timestamps fall within each workout window, keyed by the generated workout ID.
- `exercise_bouts.csv` – Contiguous Apple Exercise Time records grouped into bouts and annotated with average heart rate, steps, active calories, distance, and an overlapping-workout label (`Workout` or `Incidental`).

## Files

- `extract_workout_stats.py` – Parses workouts and health records from the export, writes summary and heart-rate detail CSVs.
- `exercise_bouts.py` – Groups Apple Exercise Time minutes into bouts, labels them against workouts, and writes a bouts CSV.
- `setup.sh` – Creates a `venv/` and installs dependencies (`pandas` and `tqdm`).
- `run.sh` – Runs `extract_workout_stats.py` from the project virtual environment. It works beside the project or as a standalone copy using local project-path configuration.
- `project-dir.example` – Conspicuously synthetic example of the one-line local path configuration. It is documentation only.

## Setup

Run the setup script from this directory. It requires `python3` and network access for the initial dependency installation.

```bash
./setup.sh
```

This creates `venv/` and installs `pandas` and `tqdm`. The provided commands call `venv/bin/python` directly, so activation is optional. To run the Python scripts by name during an interactive session, activate it with `source venv/bin/activate`.

## Portable Wrapper

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

1. In the Apple Health app, use **Export All Health Data** to create a ZIP archive.
2. Extract `export.xml` from the archive and place it in this project directory.

The scripts use fixed input and output filenames and do not provide command-line options for changing them. Existing output CSVs are overwritten.

## Typical Workflow

1. **Generate workout summaries and heart-rate detail**

   ```bash
   ./run.sh
   ```

   - Scans every `<Workout>` entry to build a baseline table.
   - Scans the XML again for all heart-rate, step, walking/running-distance, and active-energy records, then selects records whose start timestamps fall within each workout window.
   - Writes `workout_summary.csv` and `workout_heart_rate_detail.csv`.

2. **Build incidental exercise bouts**

   ```bash
   venv/bin/python exercise_bouts.py
   ```

   - Consumes `workout_summary.csv` to label bouts that overlap an official workout.
   - Groups contiguous Apple Exercise Time records within 90 seconds into a single bout.
   - Aggregates complementary metrics (heart rate, steps, calories, distance) and writes `exercise_bouts.csv`.

## Data Interpretation and Limitations

- Both scripts parse with `iterparse` and clear XML elements, but they retain the selected health records in Python lists or DataFrames. Memory use therefore grows with the number of relevant records in the export.
- `exercise_bouts.py` counts input lines to estimate progress, while its parser advances by XML events. Treat the progress percentage as approximate.
- Record values are summed as exported. `extract_workout_stats.py` divides walking/running distance totals by 1,000 before writing `distance_km`; `exercise_bouts.py` writes the summed exported values under the same heading without conversion. Check the `unit` attributes in your export before interpreting distance values.
- `extract_workout_stats.py` strips timezone offsets from workout and record timestamps. `exercise_bouts.py` parses the export timestamps with their offsets, then interprets summary timestamps as `US/Eastern`. Exports recorded in another timezone may be labelled incorrectly.
- If workouts overlap, the same health record can be included in more than one workout. Exercise bouts use the first overlapping workout found in `workout_summary.csv`.
- Expect multi-minute runtimes for multi-year exports.

## Troubleshooting

- Run `./run.sh --check` to validate the wrapper path and virtual environment. This check does not validate `export.xml`.
- `extract_workout_stats.py` lets the XML parser open `export.xml`; malformed XML or an unreadable file stops processing.
- `exercise_bouts.py` opens `export.xml` as UTF-8 with invalid bytes ignored, but malformed XML still stops processing.
- If the export contains no Apple Exercise Time records, `exercise_bouts.py` raises `ValueError: No Apple Exercise Time records found!`.
