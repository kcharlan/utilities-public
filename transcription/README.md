# Transcription Console
Whisper-powered transcription toolkit with two Streamlit UIs. Tracks session, cumulative, and lifetime durations, supports wildcard ingestion, and preserves counter files across sessions.

## Components

- `app.py` – Primary Streamlit console (“Transcription Console”). Features sticky transcripts, upload or wildcard ingestion with a data-grid file picker, per-transcript clipboard buttons, and resettable session/cumulative/lifetime counters. Uses atomic file writes for counter persistence and falls back to the OpenAI API when local Whisper fails.
- `transcribe.py` – Secondary Streamlit app (“Whisper Transcriber”). Styled interface with drag-and-drop upload or wildcard path input, configurable divider words that split transcripts into sections, and the same three-tier time counters. Uses `librosa` for duration when available, falling back to Whisper’s audio loader.
- `run.sh`, `m4a-run.sh`, `help.sh` – Legacy shell wrappers that invoke `transcribe.py` with `--file` and `--model` flags. These were written for an earlier CLI version of `transcribe.py` and may not function correctly with the current Streamlit-based implementation.
- `ui.sh` – Launches `app.py` from the project root.
- `session_backup.json` – Persists the cumulative counter (`{“cumulative_seconds”: <float>}`).
- `transcription_odometer.txt` – Persists the lifetime counter (plain-text float).
- `setup.sh` – Recreates a Python 3.12 venv and installs `openai-whisper` and `streamlit`. The optional OpenAI API fallback also requires the `openai` package.

## Environment

```bash
./setup.sh
source venv/bin/activate
```

FFmpeg must be installed on your system (`brew install ffmpeg` on macOS). If you plan to use the OpenAI API fallback in `app.py`, export `OPENAI_API_KEY`.

For that optional fallback, install the client into the project venv:

```bash
venv/bin/pip install openai
```

## Launching the Streamlit UI

```bash
streamlit run app.py
# or
./ui.sh
```

### app.py Highlights

- Drag-and-drop uploader or wildcard input box for local media files (`mp3`, `wav`, `m4a`, `flac`, `ogg`, `wma`, `mp4`, `aac`).
- Wildcard paths expand with live preview in an editable data grid where individual files can be unchecked.
- Option to allow non-audio file extensions for experimental formats.
- Session, cumulative, and lifetime counters update per-file (only after successful transcription) and persist atomically.
- Per-transcript “Copy to clipboard” buttons and inline text editing.
- Resilient error handling around Whisper loading — falls back to OpenAI API if `OPENAI_API_KEY` is set.

### transcribe.py Highlights

- Styled drag-and-drop uploader with optional wildcard/path input (collapsed by default).
- Configurable divider words (`cut`, `mark`, etc.) that split transcripts into sections.
- Raw transcript text areas are editable; a “Process Text” button applies divider splitting.
- Same three-tier time counters (session, cumulative, lifetime) persisted to the shared counter files.

## Customization

- Adjust default model size in the model selector of either app (both default to `small` in `app.py`, `large` in `transcribe.py`).
- Modify `process_text_with_dividers` in `transcribe.py` to add Markdown headings or timestamps between sections.

## Troubleshooting

- Ensure FFmpeg is installed and on your `PATH` if Whisper complains about audio loading.
- Large models (e.g., `large`) require several GB of VRAM; switch to `small` or `medium` on constrained GPUs/CPUs.
- Delete `session_backup.json`/`transcription_odometer.txt` if you want to reset counters — back them up first if the history matters.
