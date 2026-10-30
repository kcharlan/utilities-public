# Transcription Console

A local, Whisper-powered transcription toolkit with two Streamlit interfaces. Both accept multiple audio files, transcribe them with a selectable local Whisper model, and track processed audio duration.

`app.py` is the primary interface. `transcribe.py` is an alternate interface for workflows that split transcripts on spoken divider words.

## Requirements

- [uv](https://docs.astral.sh/uv/) and Python 3.12 available to uv
- [FFmpeg](https://ffmpeg.org/) available on `PATH`
- Enough disk space to download and cache the selected Whisper model on first use

On macOS, install FFmpeg with:

```bash
brew install ffmpeg
```

## Setup

Run the launcher from this directory. uv installs the pinned dependencies on
first use; the [decision record](../docs/transcription_uv_decision.md) records
the measured cache footprint.

```bash
./transcription
```

### Optional OpenAI API fallback

Only `app.py` can fall back to the OpenAI transcription API when local Whisper fails. The launcher installs the client; enable the fallback by providing the key through the environment:

```bash
export OPENAI_API_KEY="your-key"
```

Do not store the key in this repository.

## Run the primary interface

The launcher preserves the caller's working directory:

```bash
./transcription app
```

Use `--port N` to select the starting port or `--no-browser` for headless operation:

```bash
./transcription app --port 8501 --no-browser
```

The primary interface supports:

- Uploading multiple `mp3`, `wav`, `m4a`, `flac`, `ogg`, `wma`, `mp4`, or `aac` files.
- Selecting local files with an exact path or recursive wildcard pattern.
- Reviewing wildcard matches in a grid and excluding individual files.
- Attempting other file extensions when **Allow non-audio file extensions** is enabled.
- Retaining completed transcripts during the current Streamlit session, with editable text, per-item copy and remove controls, and a clear-all action.
- Falling back to the OpenAI API when local transcription fails and `OPENAI_API_KEY` plus the `openai` package are available.
- Updating duration counters only after each file is transcribed successfully.

## Run the divider-word interface

From this directory:

```bash
./transcription divider
```

This interface supports:

- Uploading multiple `wav`, `mp3`, `m4a`, `ogg`, `flac`, or `aac` files.
- Selecting files with a path or wildcard pattern.
- Splitting editable transcript text on configurable divider words such as `cut` or `mark`.
- Using `librosa` for duration detection, with Whisper audio loading as the fallback.

This older interface records a file's detected duration before transcription finishes, so a failed transcription can still increase its counters. It does not use the OpenAI API fallback.

`requirements-optional.txt` pins both packages included in the launcher graph.

## Validation

Run the complete automated self-test with the owner-selected test overlay:

```bash
uv run --no-python-downloads --with pytest --with pip --with httpx --script transcription self-test
```

The self-test uses synthetic state and audio, and tests the installed OpenAI
client with an offline transport. Real-model acceptance requires a separate
model download and is described in the implementation plan.

## Counters and local state

Both interfaces use three counters:

- **Session**: duration processed in the current browser session or batch.
- **Cumulative**: resettable total persisted in `session_backup.json`.
- **Lifetime**: persistent total stored as a number in `transcription_odometer.txt`.

The two persistence files are local runtime state and are ignored by Git. `app.py` writes both files atomically and lets you reset the session and cumulative totals from the interface. The divider-word interface uses ordinary file writes and provides a cumulative reset.

`app.py` also accepts `CUMULATIVE_JSON_PATH` and `LIFETIME_TXT_PATH` environment variables to place these files elsewhere. `transcribe.py` always uses filenames relative to its current working directory.

Back up the files before deleting or replacing them if their history matters.

## Legacy wrappers

The old wrappers are transitional pending retirement. `run.sh`, `m4a-run.sh`, and `help.sh` pass obsolete command-line options and are not supported launch methods. Use the launcher above.

## Troubleshooting

- If Whisper cannot load an audio file, confirm that `ffmpeg` is installed and available on `PATH`.
- If local transcription is slow or runs out of memory, choose a smaller model in the interface.
- Until counter migration, isolate the working directory and override `app.py`'s counter paths when testing.
