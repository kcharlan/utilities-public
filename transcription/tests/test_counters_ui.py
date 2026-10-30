from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import transcription_state as state

PROJECT = Path(__file__).resolve().parents[1]


def launch(interface):
    return AppTest.from_file(str(PROJECT / ("app.py" if interface == "app" else "transcribe.py")), default_timeout=120).run()


def button(at, label):
    return next(item for item in at.button if item.label == label)


def reset(at, interface):
    if interface == "app":
        button(at, "Reset cumulative total").click().run()
        button(at, "Yes, reset cumulative").click().run()
    else:
        button(at, "🔄 Reset Cumulative").click().run()


@pytest.mark.parametrize("interface", ["app", "divider"])
def test_reset_from_each_interface(interface, stub_whisper):
    state.add_duration(42)
    at = launch(interface)
    reset(at, interface)
    assert not at.exception
    assert state.read_counters().counters == state.Counters(0, 42)


@pytest.mark.parametrize("interface", ["app", "divider"])
def test_reset_failure_keeps_totals_and_transcripts(interface, stub_whisper, monkeypatch):
    state.add_duration(42)
    at = launch(interface)
    if interface == "app":
        at.session_state["transcripts"] = {"synthetic": __import__("types").SimpleNamespace(filename="sample.wav", duration_seconds=1, timestamp="now", text="synthetic transcript")}
    else:
        at.session_state["raw_texts"] = ["synthetic transcript"]
        at.session_state["processed_texts"] = [""]
        at.session_state["file_names"] = ["sample.wav"]
    original = state.reset_cumulative
    def fail():
        raise OSError("synthetic failure")
    monkeypatch.setattr(state, "reset_cumulative", fail)
    reset(at, interface)
    assert not at.exception
    assert any("synthetic failure" in error.value for error in at.error)
    assert not any("reset" in message.value.lower() for message in at.success)
    assert any("synthetic transcript" in area.value for area in at.text_area)
    assert state.read_counters().counters == state.Counters(42, 42)
    monkeypatch.setattr(state, "reset_cumulative", original)
    if interface == "app":
        button(at, "Yes, reset cumulative").click().run()
    else:
        button(at, "🔄 Reset Cumulative").click().run()
    assert state.read_counters().counters == state.Counters(0, 42)


@pytest.mark.parametrize("interface", ["app", "divider"])
def test_read_warning_is_shown(interface, stub_whisper):
    state.runtime_home().mkdir()
    state.cumulative_path().write_text("invalid")
    at = launch(interface)
    saved, = state.runtime_home().glob("session_backup.json.unreadable-*")
    assert any(str(saved) in warning.value for warning in at.warning)
    at.run()
    assert any(str(saved) in warning.value for warning in at.warning)


def process(at, interface, path):
    if interface == "app":
        at.radio[0].set_value("Path (wildcards)").run()
        at.text_input[0].set_value(str(path)).run()
        button(at, "Start Transcription").click().run()
    else:
        at.checkbox[0].check().run()
        next(item for item in at.text_input if item.label == "File Path or Wildcard Pattern").set_value(str(path)).run()
        button(at, "🎯 Start Transcription").click().run()


def test_interfaces_share_counters(tmp_path, stub_whisper):
    path = tmp_path / "sample.wav"
    path.write_bytes(b"synthetic")
    at = launch("app")
    process(at, "app", path)
    assert not at.exception
    assert state.read_counters().counters == state.Counters(3.5, 3.5)
    divider = launch("divider")
    assert "00:00:03" in " ".join(item.value for item in divider.markdown)
    reset(divider, "divider")
    fresh = launch("app")
    assert next(metric.value for metric in fresh.metric if metric.label == "Cumulative Total") == "00:00:00"
    assert state.read_counters().counters == state.Counters(0, 3.5)


@pytest.mark.parametrize("interface", ["app", "divider"])
def test_counter_failure_keeps_transcript(interface, tmp_path, stub_whisper, monkeypatch):
    path = tmp_path / "sample.wav"
    path.write_bytes(b"synthetic")
    state.runtime_home().write_text("synthetic")
    if interface == "divider":
        import librosa
        monkeypatch.setattr(librosa, "load", lambda *args, **kwargs: ([0] * 7, 2))
    at = launch(interface)
    process(at, interface, path)
    assert not at.exception
    assert at.error
    assert any("synthetic transcript" in area.value for area in at.text_area)


def test_divider_failed_transcription_counts_detected_duration(tmp_path, stub_whisper, monkeypatch):
    import librosa
    import whisper
    monkeypatch.setattr(librosa, "load", lambda *args, **kwargs: ([0] * 7, 2))
    class Model:
        def transcribe(self, path):
            raise RuntimeError("synthetic failure")
    monkeypatch.setattr(whisper, "load_model", lambda name: Model())
    path = tmp_path / "sample.wav"
    path.write_bytes(b"synthetic")
    at = launch("divider")
    process(at, "divider", path)
    assert not at.exception
    assert state.read_counters().counters == state.Counters(3.5, 3.5)
    assert any("synthetic failure" in area.value for area in at.text_area)
