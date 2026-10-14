"""Measurement tools must reject public checkouts before loading scan code."""

from pathlib import Path
import runpy
import shutil
import subprocess
import sys

import pytest


PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def public_checkouts(tmp_path):
    primary = tmp_path / "synthetic-primary"
    linked = tmp_path / "synthetic-linked"
    sibling = tmp_path / "synthetic-sibling with space\nand newline"
    subprocess.run(["git", "init", "-q", str(primary)], check=True)
    launcher = primary / "storage_monitor" / "storage_monitor"
    launcher.parent.mkdir()
    launcher.write_text("# Synthetic historical launcher; never executed.\n")
    subprocess.run(["git", "add", "storage_monitor/storage_monitor"], cwd=primary, check=True)
    subprocess.run([
        "git", "-c", "user.name=Synthetic Test", "-c", "user.email=synthetic@example.invalid",
        "commit", "--allow-empty", "-qm", "Synthetic fixture",
    ], cwd=primary, check=True)
    for checkout in (linked, sibling):
        subprocess.run(["git", "worktree", "add", "--detach", "-q", str(checkout)],
                       cwd=primary, check=True)
    # Run the real entry points from a linked layout, without substituting their
    # repository discovery. Copy only test tool source, never runtime state.
    sources = ["tests/perf/measure_scan.py", "tests/parity/compare_walkers.py",
               "tests/destination_guard.py"]
    for source in sources:
        target = linked / "storage_monitor" / source
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT / source, target)
    (linked / "tools").mkdir()
    shutil.copyfile(PROJECT.parent / "tools/testkit.py", linked / "tools/testkit.py")
    return primary, linked, sibling


def tool_main(monkeypatch, linked, tool, runtime, output):
    script = linked / "storage_monitor" / "tests" / tool
    namespace = runpy.run_path(str(script))
    main = namespace["main"]

    def stop_before_loading(*args, **kwargs):
        raise RuntimeError("launcher loading reached")

    monkeypatch.setitem(main.__globals__, "load_launcher", stop_before_loading)
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(runtime))
    arguments = (["--runtime-home", str(runtime), "--runs", "1"]
                 if tool.startswith("perf/") else
                 ["--baseline-ref", "HEAD", "--root", str(linked)])
    monkeypatch.setattr(sys, "argv", [str(script), *arguments, "--output", str(output)])
    monkeypatch.chdir(linked)
    return main


@pytest.mark.parametrize("tool,destination", [
    ("perf/measure_scan.py", "runtime"),
    ("perf/measure_scan.py", "output"),
    ("parity/compare_walkers.py", "output"),
])
@pytest.mark.parametrize("checkout_index", [0, 1, 2], ids=["primary", "current", "sibling"])
@pytest.mark.parametrize("symlink", [False, True], ids=["direct", "symlink"])
def test_rejects_checkout_before_loading_or_writing(
    monkeypatch, tmp_path, public_checkouts, capsys, tool, destination, checkout_index, symlink,
):
    checkout = public_checkouts[checkout_index]
    if symlink:
        alias = tmp_path / "synthetic-alias"
        alias.symlink_to(checkout, target_is_directory=True)
        checkout = alias
    runtime = tmp_path / "synthetic-runtime"
    output = tmp_path / "synthetic-output.json"
    if destination == "runtime":
        runtime = checkout / "synthetic-runtime"
    else:
        output = checkout / "synthetic-output.json"
    main = tool_main(monkeypatch, public_checkouts[1], tool, runtime, output)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "outside" in capsys.readouterr().err
    assert not runtime.exists()
    assert not output.exists()


@pytest.mark.parametrize("tool", ["perf/measure_scan.py", "parity/compare_walkers.py"])
def test_accepts_external_destinations(monkeypatch, tmp_path, public_checkouts, tool):
    main = tool_main(monkeypatch, public_checkouts[1], tool,
                     tmp_path / "synthetic-runtime", tmp_path / "synthetic-output.json")
    with pytest.raises(RuntimeError, match="launcher loading reached"):
        main()


@pytest.mark.parametrize("tool", ["perf/measure_scan.py", "parity/compare_walkers.py"])
def test_standalone_help(tool, tmp_path):
    result = subprocess.run([sys.executable, str(PROJECT / "tests" / tool), "--help"],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "--output" in result.stdout


@pytest.mark.parametrize("tool", ["perf/measure_scan.py", "parity/compare_walkers.py"])
def test_refuses_destinations_when_checkout_inventory_unavailable(
    monkeypatch, tmp_path, public_checkouts, capsys, tool,
):
    runtime = tmp_path / "synthetic-runtime"
    output = tmp_path / "synthetic-output.json"
    main = tool_main(monkeypatch, public_checkouts[1], tool, runtime, output)
    monkeypatch.setitem(main.__globals__, "REPOSITORY_ROOT", tmp_path)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "cannot establish public checkouts" in capsys.readouterr().err
    assert not runtime.exists()
    assert not output.exists()


@pytest.mark.parametrize("tool,destination", [
    ("perf/measure_scan.py", "runtime"),
    ("perf/measure_scan.py", "output"),
    ("parity/compare_walkers.py", "output"),
])
@pytest.mark.parametrize("redirect", ["GIT_DIR", "GIT_COMMON_DIR", "all"])
def test_inherited_git_context_cannot_hide_primary_checkout(
    monkeypatch, tmp_path, public_checkouts, capsys, tool, destination, redirect,
):
    foreign = tmp_path / "synthetic-unrelated"
    subprocess.run(["git", "init", "-q", str(foreign)], check=True)
    runtime = tmp_path / "synthetic-runtime"
    output = tmp_path / "synthetic-output.json"
    if destination == "runtime":
        runtime = public_checkouts[0] / "synthetic-runtime"
    else:
        output = public_checkouts[0] / "synthetic-output.json"
    main = tool_main(monkeypatch, public_checkouts[1], tool, runtime, output)
    for name, value in {"GIT_DIR": foreign / ".git", "GIT_COMMON_DIR": foreign / ".git",
                        "GIT_WORK_TREE": foreign}.items():
        if redirect == "all" or redirect == name:
            monkeypatch.setenv(name, str(value))
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "outside" in capsys.readouterr().err
    assert not runtime.exists()
    assert not output.exists()
