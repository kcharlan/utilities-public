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

`setup.sh` deletes and recreates `venv/`, then installs the exact
`openai-whisper`, `streamlit`, and directly imported `pandas` releases tracked
in `requirements.txt`.

### Optional OpenAI API fallback

Only `app.py` can fall back to the OpenAI transcription API when local Whisper fails. To enable that fallback, install the OpenAI client in the project virtual environment and provide the key through the environment:

```bash
venv/bin/python -m pip install -r requirements-optional.txt
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

`requirements-optional.txt` pins both optional packages. Neither is installed
by `setup.sh`; install the optional file only when those features are needed.

## Validation

Validate the core graph and, separately, a fresh environment containing both
requirements files. Use Python 3.12 and keep acceptance audio, logs, model cache,
and counters outside the checkout. For [counter isolation](#counters-and-local-state),
run from a fresh scratch directory and set both counter environment variables;
the working directory also isolates `transcribe.py`'s counters.

From this project directory, retain its absolute path before entering scratch:

```bash
PROJECT="$PWD"
S=$(mktemp -d "${TMPDIR:-/tmp}/transcription-acceptance.XXXXXX")
cd "$S"
export CUMULATIVE_JSON_PATH="$S/session_backup.json"
export LIFETIME_TXT_PATH="$S/transcription_odometer.txt"
"$PROJECT/venv/bin/python" -c 'import pandas, streamlit, whisper; print(pandas.__version__, streamlit.__version__, whisper.__version__)'
```

Save this AppTest harness as `apptest_acceptance.py` in the scratch directory:

```python
import sys
from streamlit.testing.v1 import AppTest
for script in sys.argv[1:]:
    at = AppTest.from_file(script, default_timeout=120).run()
    assert not at.exception, f"{script}: {at.exception}"
```

Run it against both scripts:

```bash
"$PROJECT/venv/bin/python" "$S/apptest_acceptance.py" "$PROJECT/app.py" "$PROJECT/transcribe.py"
```

Smoke-run each entrypoint through the project interpreter, one at a time:

```bash
"$PROJECT/venv/bin/python" -m streamlit run "$PROJECT/app.py" --server.headless true --server.address 127.0.0.1 --server.port 8501
"$PROJECT/venv/bin/python" -m streamlit run "$PROJECT/transcribe.py" --server.headless true --server.address 127.0.0.1 --server.port 8501
```

For each server, require HTTP 200 from `/` and `/_stcore/health` (body `ok`),
then terminate it cleanly. Choose an available port when 8501 is occupied.
Repeat AppTest and smoke checks with each graph's interpreter.

On macOS, generate conspicuously synthetic speech and convert it to mono audio:

```bash
say -o "$S/synthetic.aiff" 'This is a synthetic transcription acceptance test.'
ffmpeg -nostdin -y -i "$S/synthetic.aiff" -ac 1 -ar 16000 "$S/synthetic.wav"
```

With the core graph, load Whisper's `tiny` model with `download_root` pointing
inside scratch (the first run downloads the model), transcribe the WAV using
`word_timestamps=True` and `fp16=False`, and assert nonempty text and nonempty
segment word timings with nonnegative, ordered start/end times. With the optional
graph, assert positive duration from `librosa.load` and verify the OpenAI client
surface without sending a request:

```python
from openai import OpenAI
with OpenAI(api_key="SYNTHETIC-NOT-A-REAL-KEY") as client:
    assert callable(client.audio.transcriptions.create)
```

Finally run `pip check`, retain `pip freeze`, and audit the core and optional
freezes separately, using each validated environment's interpreter:

```bash
"$PROJECT/venv/bin/python" -m pip check
"$PROJECT/venv/bin/python" -m pip freeze > "$S/freeze.txt"
uvx --no-python-downloads pip-audit --strict --no-deps --disable-pip -r "$S/freeze.txt"
```

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
