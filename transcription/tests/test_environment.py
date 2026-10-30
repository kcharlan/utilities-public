import importlib
import importlib.metadata
import os
import subprocess
import sys
import wave
from pathlib import Path

from tools.check_uv_headers import extract_pep723, normalize_distribution, parse_requirements_file

PROJECT_DIR = Path(__file__).resolve().parents[1]


def requirements():
    return extract_pep723((PROJECT_DIR / "transcription").read_text())["dependencies"]


def test_python_is_312():
    assert sys.version_info[:2] == (3, 12)


def test_direct_pins_are_installed():
    for requirement in requirements():
        name, version = requirement.split("==")
        assert importlib.metadata.version(name) == version


def test_header_pins_match_requirement_files():
    manifests = parse_requirements_file(PROJECT_DIR / "requirements.txt")
    manifests += parse_requirements_file(PROJECT_DIR / "requirements-optional.txt")
    assert sorted(requirements()) == sorted(manifests)


def test_dev_requirements_name_the_overlay():
    dev = {normalize_distribution(x) for x in parse_requirements_file(PROJECT_DIR / "requirements-dev.txt")}
    runtime = {normalize_distribution(x) for x in requirements()}
    assert dev - runtime == {"httpx", "pip", "pytest"}
    for name in dev - runtime:
        importlib.import_module(name)


def test_dependency_closure_is_consistent():
    subprocess.run([sys.executable, "-m", "pip", "check"], check=True)


def test_optional_packages_work_offline(tmp_path):
    import librosa
    path = tmp_path / "synthetic.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\0\0" * 800)
    samples, rate = librosa.load(path)
    assert len(samples) / rate > 0


def test_installed_openai_text_response(tmp_path, monkeypatch):
    import httpx
    import openai
    import app
    seen = []
    def handle(request):
        seen.append(request)
        assert request.url.path == "/v1/audio/transcriptions"
        assert b'name="model"\r\n\r\nwhisper-1' in request.content
        assert b'name="response_format"\r\n\r\ntext' in request.content
        assert b'name="file"; filename="synthetic.wav"' in request.content
        assert b'synthetic audio' in request.content
        return httpx.Response(200, text="synthetic transcription")
    transport = httpx.MockTransport(handle)
    http_client = httpx.Client(transport=transport)
    client = openai.OpenAI(api_key="SYNTHETIC-NOT-A-REAL-KEY", http_client=http_client)
    monkeypatch.setenv("OPENAI_API_KEY", "SYNTHETIC-NOT-A-REAL-KEY")
    monkeypatch.setattr(openai, "OpenAI", lambda **_: client)
    monkeypatch.setattr(app.whisper, "load_model", lambda _: (_ for _ in ()).throw(RuntimeError("synthetic failure")))
    path = tmp_path / "synthetic.wav"
    path.write_bytes(b"synthetic audio")
    try:
        assert app.transcribe_audio(str(path), "tiny") == "synthetic transcription"
        assert len(seen) == 1
    finally:
        client.close()
        http_client.close()
