import os
from pathlib import Path

import pytest
import transcription_state as state
from streamlit.testing.v1 import AppTest

PROJECT_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def model_cache(monkeypatch):
    directory = Path(os.environ["TRANSCRIPTION_ACCEPTANCE_DIR"])
    monkeypatch.setenv("XDG_CACHE_HOME", str(directory / "cache"))
    return directory


def test_tiny_model_word_timings(model_cache):
    import whisper

    model = whisper.load_model("tiny")
    result = model.transcribe(str(model_cache / "synthetic.wav"), word_timestamps=True, fp16=False)
    assert result["text"].strip()
    words = [word for segment in result["segments"] for word in segment.get("words", [])]
    assert words
    previous = 0
    for word in words:
        assert previous <= word["start"] <= word["end"]
        previous = word["end"]
    assert (model_cache / "cache" / "whisper" / "tiny.pt").is_file()


def assert_positive_counters():
    counters = state.read_counters().counters
    assert counters.cumulative_seconds > 0
    assert counters.lifetime_seconds > 0


def test_app_end_to_end_with_tiny(model_cache):
    at = AppTest.from_file(str(PROJECT_DIR / "app.py"), default_timeout=300).run()
    at.radio[0].set_value("Path (wildcards)").run()
    at.text_input[0].set_value(str(model_cache / "synthetic.wav")).run()
    at.selectbox[0].set_value("tiny")
    next(item for item in at.button if item.label == "Start Transcription").click().run(timeout=300)
    assert not at.exception and not at.error
    assert any(item.value.strip() for item in at.text_area)
    assert_positive_counters()


def test_divider_end_to_end_with_m4a(model_cache):
    at = AppTest.from_file(str(PROJECT_DIR / "transcribe.py"), default_timeout=300).run()
    at.checkbox[0].check().run()
    next(item for item in at.text_input if item.label == "File Path or Wildcard Pattern").set_value(str(model_cache / "synthetic.m4a")).run()
    at.selectbox[0].set_value("tiny")
    next(item for item in at.button if item.label == "🎯 Start Transcription").click().run(timeout=300)
    assert not at.exception and not at.error
    assert any(item.value.strip() for item in at.text_area)
    assert all("[ERROR]" not in item.value for item in at.text_area)
    assert_positive_counters()
