import os
import socket
import subprocess
import sys
import types
from pathlib import Path

import pytest
from tools.testkit import assert_launcher_help, load_launcher
PROJECT_DIR = Path(__file__).resolve().parents[1]
LAUNCHER = PROJECT_DIR / "transcription"


@pytest.fixture
def launcher():
    return load_launcher(LAUNCHER)


def run_fake(monkeypatch, launcher, args):
    calls = []
    cli = types.ModuleType("streamlit.web.cli")
    cli.main = lambda: calls.append((sys.argv[:], os.getcwd())) or 0
    web = types.ModuleType("streamlit.web")
    web.cli = cli
    streamlit = types.ModuleType("streamlit")
    streamlit.web = web
    for name, module in (("streamlit", streamlit), ("streamlit.web", web), ("streamlit.web.cli", cli)):
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(sys, "argv", [str(LAUNCHER), *args])
    assert launcher.main() == 0
    assert len(calls) == 1
    return calls[0]


@pytest.mark.parametrize("mode,script", [(None, "app.py"), ("divider", "transcribe.py")])
def test_mode_selects_script(monkeypatch, launcher, mode, script):
    caller_cwd = os.getcwd()
    argv, cwd = run_fake(monkeypatch, launcher, [mode] if mode else [])
    assert argv[:3] == ["streamlit", "run", str(PROJECT_DIR / script)]
    assert cwd == caller_cwd


def test_streamlit_argv_binds_loopback(launcher):
    argv = launcher.build_streamlit_argv(PROJECT_DIR / "app.py", 8501, True)
    for option, value in (("--server.address", "127.0.0.1"), ("--server.port", "8501"),
                          ("--server.headless", "true"), ("--server.showEmailPrompt", "false"),
                          ("--browser.gatherUsageStats", "false")):
        i = argv.index(option)
        assert argv[i + 1] == value


def test_no_browser_sets_headless(monkeypatch, launcher):
    argv, _ = run_fake(monkeypatch, launcher, ["--no-browser"])
    assert argv[argv.index("--server.headless") + 1] == "true"


def test_busy_port_moves_and_warns(monkeypatch, launcher, capsys):
    for port in range(25000, 45000):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                with socket.socket() as next_sock:
                    next_sock.bind(("127.0.0.1", port + 1))
            except OSError:
                continue
            argv, _ = run_fake(monkeypatch, launcher, ["--port", str(port)])
            break
    else:
        pytest.fail("no adjacent ports available")
    used = int(argv[argv.index("--server.port") + 1])
    assert used == port + 1
    warning = capsys.readouterr().err
    assert str(port) in warning and str(used) in warning


def test_missing_ffmpeg_warns_and_continues(monkeypatch, launcher, capsys):
    monkeypatch.setattr(launcher.shutil, "which", lambda _: None)
    run_fake(monkeypatch, launcher, [])
    assert "ffmpeg" in capsys.readouterr().err.lower()


def test_missing_script_exits_with_message(monkeypatch, launcher, tmp_path, capsys):
    monkeypatch.setattr(launcher, "PROJECT_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", [str(LAUNCHER)])
    assert launcher.main() == 2
    assert "app.py" in capsys.readouterr().err


def test_help_does_not_import_streamlit():
    assert_launcher_help(LAUNCHER)
    code = "import runpy,sys; path=sys.argv[1]; sys.argv=[path, '--help']; " \
           "\ntry: runpy.run_path(path, run_name='__main__')\nexcept SystemExit: pass\n" \
           "assert 'streamlit' not in sys.modules"
    subprocess.run([sys.executable, "-c", code, str(LAUNCHER)], check=True, capture_output=True)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.parametrize("mode", ["app", "divider"])
def test_server_starts_and_stops(mode, tmp_path, server_cycle):
    port = free_port()
    server_cycle([sys.executable, str(LAUNCHER), mode, "--no-browser", "--port", str(port)],
                 tmp_path, os.environ.copy())


def test_symlinked_launcher_finds_scripts(tmp_path, server_cycle):
    directory = tmp_path / "with space"
    directory.mkdir()
    link = directory / "launcher"
    link.symlink_to(LAUNCHER)
    port = free_port()
    server_cycle([sys.executable, str(link), "--no-browser", "--port", str(port)],
                 tmp_path, os.environ.copy())
