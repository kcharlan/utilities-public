# Transcription Console

A local, Whisper-powered transcription toolkit with two Streamlit interfaces. Both accept multiple audio files, transcribe them with a selectable local Whisper model, and track processed audio duration.

`app.py` is the primary interface. `transcribe.py` is an alternate interface for workflows that split transcripts on spoken divider words.

## Requirements

- Python 3.12, as expected by `setup.sh`
- [FFmpeg](https://ffmpeg.org/) available on `PATH`
- Enough disk space to download and cache the selected Whisper model on first use

On macOS, install FFmpeg with:

```bash
brew install ffmpeg
```

## Setup

Run these commands from this directory:

```bash
./setup.sh
source venv/bin/activate
```

`setup.sh` deletes and recreates `venv/`, then installs `openai-whisper` and `streamlit`.

### Optional OpenAI API fallback

Only `app.py` can fall back to the OpenAI transcription API when local Whisper fails. To enable that fallback, install the OpenAI client in the project virtual environment and provide the key through the environment:

```bash
venv/bin/pip install openai
export OPENAI_API_KEY="your-key"
```

Do not store the key in this repository.

## Run the primary interface

The wrapper changes to the project directory before launching, so its local counter files are stored in the expected location:

```bash
./ui.sh
```

The equivalent manual command is:

```bash
source venv/bin/activate
streamlit run app.py
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
source venv/bin/activate
streamlit run transcribe.py
```

This interface supports:

- Uploading multiple `wav`, `mp3`, `m4a`, `ogg`, `flac`, or `aac` files.
- Selecting files with a path or wildcard pattern.
- Splitting editable transcript text on configurable divider words such as `cut` or `mark`.
- Using `librosa` for duration detection when it is separately installed, with Whisper audio loading as the built-in fallback.

This older interface records a file's detected duration before transcription finishes, so a failed transcription can still increase its counters. It does not use the OpenAI API fallback.

## Counters and local state

Both interfaces use three counters:

- **Session**: duration processed in the current browser session or batch.
- **Cumulative**: resettable total persisted in `session_backup.json`.
- **Lifetime**: persistent total stored as a number in `transcription_odometer.txt`.

The two persistence files are local runtime state and are ignored by Git. `app.py` writes both files atomically and lets you reset the session and cumulative totals from the interface. The divider-word interface uses ordinary file writes and provides a cumulative reset.

`app.py` also accepts `CUMULATIVE_JSON_PATH` and `LIFETIME_TXT_PATH` environment variables to place these files elsewhere. `transcribe.py` always uses filenames relative to its current working directory.

Back up the files before deleting or replacing them if their history matters.

## Legacy wrappers

`run.sh`, `m4a-run.sh`, and `help.sh` pass obsolete command-line options to `transcribe.py`. The current `transcribe.py` is a Streamlit app and does not implement those options, so these wrappers are not supported launch methods. Use one of the Streamlit commands above.

## Troubleshooting

- If Whisper cannot load an audio file, confirm that `ffmpeg` is installed and available on `PATH`.
- If local transcription is slow or runs out of memory, choose a smaller model in the interface.
- Run manual Streamlit commands from this directory unless you intentionally override `app.py`'s counter paths.
