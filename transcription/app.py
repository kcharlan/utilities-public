# app.py
# Streamlit transcription app with:
# - Per-file atomic counter commits (only after success)
# - Wildcard path ingest with live preview via data grid (checkbox + basename + full path) and Clear
# - Sticky transcripts in session_state
# - Metrics + aligned reset buttons (session & cumulative) rendered at end for immediate updates
# - Cumulative reset confirmation that appears immediately; both resets force-refresh the UI
# - Shared private counter persistence in the Transcription runtime home
# - Whisper-only duration via whisper.audio.load_audio
# - Private temporary upload batches cleaned after processing
# - Robust against flipping input mode back/forth
# - Per-transcript "Copy to clipboard" (HTML) that targets only that transcript and is visible

import os
import time
import glob
import hashlib
import datetime as dt
from dataclasses import dataclass
from typing import List, Dict, Tuple

import streamlit as st
import pandas as pd
import html as _html
from streamlit.components.v1 import html as components_html
import transcription_state as counter_state

# ---------- PAGE CONFIG ----------
st.set_page_config(page_title="Transcription Console", layout="wide")

# ----------------------------
# Config & constants
# ----------------------------
APP_TITLE = "Transcription Console"

TIME_FMT = "%Y-%m-%d %H:%M:%S"

# ----------------------------
# Whisper-only duration support
# ----------------------------
import whisper
try:
    # Newer versions
    from whisper.audio import load_audio, SAMPLE_RATE
except Exception:
    # Older versions expose load_audio at top-level
    load_audio = whisper.load_audio  # type: ignore
    from whisper.audio import SAMPLE_RATE  # type: ignore

# ----------------------------
# Utilities
# ----------------------------
def humanize_seconds(total_seconds: float) -> str:
    s = int(round(total_seconds))
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def now_str() -> str:
    return dt.datetime.now().strftime(TIME_FMT)

def hash_file_identity(filepath: str) -> str:
    try:
        stat = os.stat(filepath)
        base = f"{os.path.basename(filepath)}|{stat.st_size}|{int(stat.st_mtime)}"
    except Exception:
        base = f"{os.path.basename(filepath)}|{time.time_ns()}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]

# ----------------------------
# Whisper-only duration
# ----------------------------
def read_audio_duration_seconds(filepath: str) -> float:
    """
    Duration via Whisper's own loader (ffmpeg under the hood), so it matches
    whatever Whisper can successfully transcribe. Raises on failure.
    """
    try:
        audio = load_audio(filepath)  # float32 mono at SAMPLE_RATE
        if audio is None or (hasattr(audio, "__len__") and len(audio) == 0):
            raise RuntimeError("Empty audio after load_audio().")
        dur = float(len(audio) / float(SAMPLE_RATE))
        if dur <= 0:
            raise RuntimeError("Computed non-positive duration.")
        return dur
    except Exception as e:
        raise RuntimeError(f"Whisper duration failed for {os.path.basename(filepath)}: {e}")

# ----------------------------
# Transcription abstraction
# ----------------------------
def transcribe_audio(filepath: str, model_name: str = "small") -> str:
    """
    Prefer local whisper; fallback to OpenAI API if OPENAI_API_KEY is set.
    """
    # Local whisper
    try:
        model = whisper.load_model(model_name)
        result = model.transcribe(filepath)
        text = (result.get("text") or "").strip()
        if not text:
            raise RuntimeError("Empty transcription text from local whisper.")
        return text
    except Exception as e_local:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(f"Local whisper failed and no OPENAI_API_KEY set. Error: {e_local}") from e_local

    # OpenAI API fallback
    try:
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        with open(filepath, "rb") as f:
            resp = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="text",
            )
        text = (resp or "").strip()
        if not text:
            raise RuntimeError("Empty transcription text from OpenAI API.")
        return text
    except Exception as e_api:
        raise RuntimeError(f"OpenAI API transcription failed: {e_api}") from e_api

# ----------------------------
# Data classes
# ----------------------------
@dataclass
class TranscriptEntry:
    key: str
    filename: str
    text: str
    duration_seconds: float
    timestamp: str

# ----------------------------
# Session state init
# ----------------------------
def ensure_session_state():
    if "transcripts" not in st.session_state:
        st.session_state.transcripts: Dict[str, TranscriptEntry] = {}
    if "current_session_seconds" not in st.session_state:
        st.session_state.current_session_seconds = 0.0
    if "last_delta_seconds" not in st.session_state:
        st.session_state.last_delta_seconds = 0.0
    if "counters_initialized" not in st.session_state:
        result = counter_state.read_counters()
        st.session_state.cumulative_total_seconds = result.counters.cumulative_seconds
        st.session_state.lifetime_total_seconds = result.counters.lifetime_seconds
        st.session_state.counter_warnings = result.warnings
        st.session_state.counters_initialized = True
    for warning in st.session_state.counter_warnings:
        st.warning(warning)
    if "last_wildcard_pattern" not in st.session_state:
        st.session_state.last_wildcard_pattern = ""
    if "preview_df" not in st.session_state:
        st.session_state.preview_df = pd.DataFrame(columns=["Include", "File", "Full Path"])
    if "confirm_reset_cum" not in st.session_state:
        st.session_state.confirm_reset_cum = False

# ----------------------------
# UI: Mode & Path (outside form so Enter won't submit)
# ----------------------------
def mode_and_path_controls() -> Tuple[str, str, pd.DataFrame]:
    st.subheader("Select Input")

    mode = st.radio(
        "Choose input method",
        options=["Upload files", "Path (wildcards)"],
        index=0,
        horizontal=True,
        key="input_mode",
        help="Upload smaller files or use a path pattern like ./audio/**/*.mp3 for large files."
    )

    wildcard = ""
    preview_df = st.session_state.preview_df

    if mode == "Path (wildcards)":
        c1, c2 = st.columns([3,1])
        with c1:
            wildcard = st.text_input(
                "Path pattern (supports wildcards)",
                value=st.session_state.get("last_wildcard_pattern", ""),
                placeholder="./audio/**/*.mp3   or   ~/Downloads/*.m4a   or   /full/path/file.m4a",
                help="Tips: ~ expands to your home dir. Exact filenames without wildcards are accepted."
            )
        with c2:
            if st.button("Clear", help="Clear the pattern and list"):
                wildcard = ""
                st.session_state.last_wildcard_pattern = ""
                preview_df = pd.DataFrame(columns=["Include", "File", "Full Path"])
                st.session_state.preview_df = preview_df

        # Live preview without submitting
        if wildcard.strip():
            try:
                expanded = os.path.expanduser(wildcard.strip())
                matches = sorted(glob.glob(expanded, recursive=True))
                if not matches and os.path.exists(expanded):
                    matches = [expanded]  # exact path
            except Exception as e:
                st.warning(f"Error evaluating pattern: {e}")
                matches = []
        else:
            matches = []

        if matches:
            # Build/refresh grid, preserving "Include" where possible
            old = st.session_state.preview_df
            old_map = {row["Full Path"]: bool(row["Include"]) for _, row in old.iterrows()} if not old.empty else {}
            rows = []
            for p in matches:
                rows.append({
                    "Include": old_map.get(p, True),
                    "File": os.path.basename(p),
                    "Full Path": p
                })
            preview_df = pd.DataFrame(rows, columns=["Include", "File", "Full Path"])
            st.session_state.preview_df = preview_df

            st.caption("Review files. Uncheck rows you do not want to process.")
            edited = st.data_editor(
                preview_df,
                use_container_width=True,
                num_rows="fixed",
                hide_index=True,
                column_config={
                    "Include": st.column_config.CheckboxColumn(required=True),
                    "File": st.column_config.TextColumn(),
                    "Full Path": st.column_config.TextColumn()
                },
                key="preview_editor"
            )
            # Keep the edited state
            st.session_state.preview_df = edited

    return mode, wildcard, st.session_state.preview_df

# ----------------------------
# UI: Form (model, allow_non_audio, uploader, submit)
# ----------------------------
def controls_form(mode: str, wildcard: str):
    """
    Returns: selected_paths, model_name, did_submit, upload_batch
    """
    selected_paths: List[str] = []
    upload_batch = None
    uploads = None
    did_submit = False

    with st.form("controls_form", clear_on_submit=False):
        colL, colR = st.columns([1,1])
        with colL:
            model_name = st.selectbox(
                "Whisper model (local)",
                options=["tiny", "base", "small", "medium", "large"],
                index=2,
                help="Used for local whisper. With OpenAI API we use whisper-1."
            )
        with colR:
            allow_non_audio = st.checkbox(
                "Allow non-audio file extensions",
                value=False,
                help="If checked, try transcribing any matched paths."
            )

        if mode == "Upload files":
            uploads = st.file_uploader(
                "Upload audio files",
                type=["mp3", "wav", "m4a", "flac", "ogg", "wma", "mp4", "aac"],
                accept_multiple_files=True
            )

        submitted = st.form_submit_button("Start Transcription", use_container_width=True)
        did_submit = bool(submitted)

    if submitted:
        if mode == "Upload files":
            if uploads:
                try:
                    for index, uf in enumerate(uploads):
                        suffix = os.path.splitext(uf.name)[1].lower()
                        if (suffix not in [".mp3", ".wav", ".m4a", ".flac", ".ogg", ".wma", ".mp4", ".aac"]) and not allow_non_audio:
                            st.warning(f"Skipped non-audio by extension: {uf.name}")
                            continue
                        if upload_batch is None:
                            upload_batch = counter_state.new_upload_batch()
                        selected_paths.append(str(counter_state.write_upload(upload_batch, index, uf.name, uf.getbuffer())))
                except OSError as error:
                    counter_state.discard_upload_batch(upload_batch)
                    upload_batch = None
                    selected_paths = []
                    st.error(f"Could not save uploads: {error}")
                except BaseException:
                    counter_state.discard_upload_batch(upload_batch)
                    raise
        else:
            # Use the curated grid selection
            st.session_state["last_wildcard_pattern"] = (wildcard or "").strip()
            df = st.session_state.preview_df
            if df is not None and not df.empty:
                chosen = df[df["Include"] == True]["Full Path"].tolist()  # noqa: E712
            else:
                chosen = []
            if not chosen:
                st.warning("No files selected. Check the grid to include files.")
            else:
                if not allow_non_audio:
                    chosen = [
                        p for p in chosen
                        if os.path.splitext(p)[1].lower() in
                        (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".wma", ".mp4", ".aac")
                    ]
                selected_paths = chosen

    return selected_paths, model_name, did_submit, upload_batch

# ----------------------------
# Processing loop with per-file commits
# ----------------------------
def process_files(filepaths: List[str], model_name: str) -> float:
    """
    Returns total seconds added in this batch (for delta display).
    """
    if not filepaths:
        return 0.0

    status = st.container()
    ok_count = 0
    fail_count = 0
    batch_added_seconds = 0.0

    with st.spinner("Transcribing..."):
        for idx, path in enumerate(filepaths, start=1):
            row = status.empty()
            base = os.path.basename(path)
            row.info(f"({idx}/{len(filepaths)}) Processing: **{base}**")

            try:
                duration = read_audio_duration_seconds(path)
                text = transcribe_audio(path, model_name=model_name)

                # Commit per-file AFTER success
                st.session_state.current_session_seconds += duration
                try:
                    counters = counter_state.add_duration(duration)
                    st.session_state.cumulative_total_seconds = counters.cumulative_seconds
                    st.session_state.lifetime_total_seconds = counters.lifetime_seconds
                except OSError as error:
                    st.error(f"Could not save counters: {error}")
                    st.session_state.cumulative_total_seconds += duration
                    st.session_state.lifetime_total_seconds += duration
                batch_added_seconds += duration

                # Add transcript (sticky)
                key = f"{hash_file_identity(path)}-{time.time_ns()}"
                st.session_state.transcripts[key] = TranscriptEntry(
                    key=key,
                    filename=base,
                    text=text,
                    duration_seconds=duration,
                    timestamp=now_str(),
                )
                ok_count += 1
                row.success(f"({idx}/{len(filepaths)}) ✅ {base} — added {humanize_seconds(duration)}")

            except Exception as e:
                fail_count += 1
                row.error(f"({idx}/{len(filepaths)}) ❌ {base} — {e}")

    if ok_count or fail_count:
        st.info(f"Completed. Success: {ok_count} | Failed: {fail_count} | Added: {humanize_seconds(batch_added_seconds)}")

    return batch_added_seconds

# ----------------------------
# UI: Transcripts list (with precise per-item Copy + instant Remove)
# ----------------------------
def render_transcripts():
    st.subheader("Transcripts")
    if not st.session_state.transcripts:
        st.caption("No transcripts yet.")
        return

    c1, _ = st.columns([1,1])
    with c1:
        if st.button("Clear all transcripts", type="secondary"):
            st.session_state.transcripts.clear()
            st.toast("Cleared transcripts.", icon="🧹")
            st.rerun()  # drop all expanders immediately

    # Show newest first
    for key, entry in list(st.session_state.transcripts.items())[::-1]:
        header = f"{entry.filename}  ·  {humanize_seconds(entry.duration_seconds)}  ·  {entry.timestamp}"
        with st.expander(header, expanded=False):
            ta_key = f"ta_{key}"
            st.text_area("Transcript", value=entry.text, key=ta_key, height=240)

            # Pull current text (includes user edits post-rerun)
            current_text = st.session_state.get(ta_key, entry.text)
            hidden_id = f"copy_{key}"

            # Hidden textarea + visible copy button (targets only this transcript)
            components_html(
                f"""
                <div style="display:flex; gap:8px; margin:6px 0;">
                  <textarea id="{hidden_id}" style="position:absolute; left:-10000px; top:-10000px;">{_html.escape(current_text)}</textarea>
                  <button id="btn_{key}" style="flex:1; padding:0.6rem; cursor:pointer;">
                    Copy to clipboard
                  </button>
                </div>
                <script>
                  (function(){{
                    const btn = document.getElementById('btn_{key}');
                    if (btn) {{
                      btn.addEventListener('click', function() {{
                        const t = document.getElementById('{hidden_id}');
                        if (!t) return;
                        navigator.clipboard.writeText(t.value).catch(function(){{
                          alert('Clipboard copy failed');
                        }});
                      }});
                    }}
                  }})();
                </script>
                """,
                height=80,  # ensure visibility
            )

            # Remove button
            if st.button("Remove", key=f"rm_{key}", use_container_width=True):
                st.session_state.transcripts.pop(key, None)
                st.toast(f"Removed {entry.filename}", icon="🗑️")
                st.rerun()  # immediately remove this block

# ----------------------------
# UI: Metrics + aligned reset buttons (with confirm for cumulative)
# ----------------------------
def render_metrics_and_resets():
    st.divider()

    # Metrics row
    col1, col2, col3 = st.columns(3)
    delta_str = None
    if st.session_state.last_delta_seconds and st.session_state.last_delta_seconds > 0:
        delta_str = f"+{humanize_seconds(st.session_state.last_delta_seconds)}"
    with col1:
        st.metric("Session Total", humanize_seconds(st.session_state.current_session_seconds), delta=delta_str)
    with col2:
        st.metric("Cumulative Total", humanize_seconds(st.session_state.cumulative_total_seconds))
    with col3:
        st.metric("Lifetime Total", humanize_seconds(st.session_state.lifetime_total_seconds))

    # Reset buttons row (aligned under the corresponding tiles)
    r1, r2, r3 = st.columns(3)
    with r1:
        if st.button("Reset session total", type="secondary", key="btn_reset_session"):
            st.session_state.current_session_seconds = 0.0
            st.session_state.last_delta_seconds = 0.0
            st.rerun()  # update tile immediately

    with r2:
        if not st.session_state.confirm_reset_cum:
            if st.button("Reset cumulative total", type="primary", key="btn_reset_cum_prompt"):
                st.session_state.confirm_reset_cum = True
                st.rerun()  # show confirmation UI immediately
        else:
            st.warning("Really reset cumulative total? This cannot be undone.")
            c_yes, c_no = st.columns([1,1])
            with c_yes:
                if st.button("Yes, reset cumulative", key="btn_reset_cum_yes"):
                    try:
                        counters = counter_state.reset_cumulative()
                    except OSError as error:
                        st.error(f"Could not reset counters: {error}")
                    else:
                        st.session_state.cumulative_total_seconds = counters.cumulative_seconds
                        st.session_state.lifetime_total_seconds = counters.lifetime_seconds
                        st.session_state.confirm_reset_cum = False
                        st.session_state.last_delta_seconds = 0.0
                        st.toast("Cumulative total reset.", icon="♻️")
                        st.rerun()
            with c_no:
                if st.button("No, keep it", key="btn_reset_cum_no"):
                    st.session_state.confirm_reset_cum = False
                    st.info("Cumulative total unchanged.")
                    st.rerun()

    with r3:
	    st.empty()

# ----------------------------
# Main
# ----------------------------
def main():
    ensure_session_state()

    # Mode + path input (non-submitting; Enter won't start)
    mode, wildcard, _preview_df = mode_and_path_controls()

    # Form with model, allow_non_audio, uploader, and submit
    selected_paths, model_name, did_submit, upload_batch = controls_form(mode, wildcard)

    # Process if submitted
    try:
        if selected_paths:
            batch_delta = process_files(selected_paths, model_name=model_name)
            st.session_state.last_delta_seconds = float(batch_delta)
        else:
            st.session_state.last_delta_seconds = 0.0
    finally:
        counter_state.discard_upload_batch(upload_batch)

    # Transcripts, then metrics + aligned resets (metrics last so clicks reflect immediately)
    render_transcripts()
    render_metrics_and_resets()

# Streamlit always runs this file as a script.
main()
