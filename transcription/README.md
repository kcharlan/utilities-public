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

From the repository root, run the complete automated Self-test with the
owner-selected overlay. It checks the pinned launcher graph, dependency
closure, installed API surfaces, and synthetic input and state behavior:

```bash
uv run --no-python-downloads --with pytest --with pip --with httpx --script transcription/transcription self-test
```

Optional pytest options such as `-k counter` still select from this project's
tests, regardless of the caller's working directory. Explicit pytest paths or
node IDs select those targets instead and resolve relative to the caller.

The installed OpenAI client is tested with an offline transport. For release,
run this **Release invocation** from the repository root. The named tests
exercise both launcher shebangs and record the full environment for audit;
the trap removes the evidence even if a check fails.

```bash
(
  set -eu
  S=$(mktemp -d "${TMPDIR:-/tmp}/transcription-acceptance.XXXXXX")
  trap 'rm -r -- "$S"' EXIT
  TRANSCRIPTION_ACCEPTANCE_DIR="$S" uv run --no-python-downloads --with pytest --with pip --with httpx --script transcription/transcription self-test transcription/tests/acceptance/release_checks.py
  uvx --no-python-downloads pip-audit --strict --no-deps --disable-pip -r "$S/freeze.txt"
)
```

Real-model acceptance is also required before release, after the owner
authorizes downloading Whisper's `tiny` model. Insert the following commands
and the named Self-test before the closing parenthesis of Release invocation:

```bash
say -o "$S/synthetic.aiff" 'This is a synthetic transcription acceptance test.'
ffmpeg -nostdin -y -i "$S/synthetic.aiff" -ac 1 -ar 16000 "$S/synthetic.wav"
afconvert -f m4af -d aac "$S/synthetic.aiff" "$S/synthetic.m4a"
TRANSCRIPTION_ACCEPTANCE_DIR="$S" uv run --no-python-downloads --with pytest --with pip --with httpx --script transcription/transcription self-test transcription/tests/acceptance/real_model.py
```

The model test isolates Whisper's cache inside the same temporary directory;
uv's cache is unchanged. It exercises word timings and both interfaces with
synthetic audio. A missing authorization or failed check leaves the release
gate unmet.

## Counters and local state

Both interfaces use three counters:

- **Session**: duration processed in the current browser session or batch.
- **Cumulative**: resettable total persisted in `session_backup.json`.
- **Lifetime**: persistent total stored as a number in `transcription_odometer.txt`.

Both interfaces share `~/.transcription/` (mode 0700), or the nonempty `TRANSCRIPTION_HOME` override. The nonempty `CUMULATIVE_JSON_PATH` and `LIFETIME_TXT_PATH` overrides select individual files. Tildes expand and relative paths are relative to the caller's working directory. Files and the home lock have mode 0600; existing outside parent permissions are left alone.

Each file is published atomically under `counters.lock`; the pair is not a single atomic transaction. Reads and updates hold the same per-home lock. Never share an override file between different runtime homes because their locks are independent. Invalid values are preserved as `.unreadable-*` files, named in a persistent interface warning, and read as zero. Inspect and reconcile preserved files before restoring their totals.

## Manual counter migration

Stop both interfaces first. The authoritative legacy files are in `~/transcription`. Run the following from the intended caller directory with the same environment overrides as the launcher. It reports absent sources and existing destinations, including dangling symlinks, as skipped; it never overwrites them.

```bash
set -eu
expand_path() {
  case "$1" in
    '~') printf '%s\n' "$HOME" ;;
    '~/'*) printf '%s/%s\n' "$HOME" "${1#\~/}" ;;
    '~'*)
      rest=${1#\~}; user=${rest%%/*}; suffix=${rest#"$user"}
      if [[ ! $user =~ ^[a-zA-Z0-9_.-]+$ ]]; then
        printf 'Invalid user in path: %s\n' "$1" >&2; return 1
      fi
      eval "expanded=~$user"
      if [ "$expanded" = "~$user" ]; then
        printf 'Unknown user in path: %s\n' "$1" >&2; return 1
      fi
      printf '%s%s\n' "$expanded" "$suffix" ;;
    *) printf '%s\n' "$1" ;;
  esac
}
home=$(expand_path "${TRANSCRIPTION_HOME:-$HOME/.transcription}")
cumulative=$(expand_path "${CUMULATIVE_JSON_PATH:-$home/session_backup.json}")
lifetime=$(expand_path "${LIFETIME_TXT_PATH:-$home/transcription_odometer.txt}")
mkdir -p "$home"
chmod 700 "$home"
copy_counter() {
  source=$1 destination=$2
  if [ ! -f "$source" ]; then printf 'Skipped absent source: %s\n' "$source"; return; fi
  if [ -e "$destination" ] || [ -L "$destination" ]; then printf 'Skipped existing destination: %s\n' "$destination"; return; fi
  parent=$(dirname "$destination")
  mkdir -p "$parent"
  temp=$(mktemp "$parent/.counter-migration.XXXXXX")
  if ! chmod 600 "$temp" || ! cat "$source" > "$temp"; then rm -f "$temp"; return 1; fi
  if ln "$temp" "$destination" 2>/dev/null; then
    printf 'Copied: %s\n' "$destination"
  elif [ -e "$destination" ] || [ -L "$destination" ]; then
    printf 'Skipped existing destination: %s\n' "$destination"
  else
    rm -f "$temp"
    printf 'Could not publish destination: %s\n' "$destination" >&2
    return 1
  fi
  rm -f "$temp"
}
copy_counter "$HOME/transcription/session_backup.json" "$cumulative"
copy_counter "$HOME/transcription/transcription_odometer.txt" "$lifetime"
```

For a retry or rollback, compare and reconcile legacy and runtime totals yourself before choosing which values to retain. A skipped destination may contain accumulated work; do not delete it merely to retry migration.

## Legacy wrappers

The old wrappers are transitional pending retirement. `run.sh`, `m4a-run.sh`, and `help.sh` pass obsolete command-line options and are not supported launch methods. Use the launcher above.

## Troubleshooting

- If Whisper cannot load an audio file, confirm that `ffmpeg` is installed and available on `PATH`.
- If local transcription is slow or runs out of memory, choose a smaller model in the interface.
- Check runtime-home permissions and override paths if counters cannot be saved.

## Input handling

Relative paths and wildcard patterns resolve from the launcher's caller directory.
Path inputs remain in place after processing. The selected local model is used for
transcription. Uploads are written only after Start into a private temporary batch,
with indexed names to distinguish duplicates, and removed after processing or an
error. If saving an upload fails, prior results remain available and you can retry.
A forcibly killed process can leave its upload directory in the OS temporary directory.
