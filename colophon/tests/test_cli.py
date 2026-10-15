import json
import ctypes
import os
import stat
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from helpers import SESSION, REQUEST, extract_payload, row, usage
from browser_errors import guard_browser_errors

UUID = "00000000-0000-4000-8000-00000000c0de"

def test_claude_resumed_usage_buckets_and_provider_isolation(native):
    native.session()
    assert native.build("--no-claude").returncode == 0
    before = native.payload()
    codex_before = before["sessions"][0]
    assert codex_before["buckets"][0][:8] == [1963728, "gpt-5", "standard", 120, 20, 0, 30, 5]
    source = native.claude_session(directory=native.home / ".claude/projects/a")
    lines = source.read_text().splitlines()
    assistant = json.loads(lines[-1])
    assistant["requestId"] = "synthetic-request-kite"
    assistant["message"]["id"] = "synthetic-message-kite"
    assistant["message"]["model"] = "synthetic-claude-model"
    assistant["message"]["usage"] = {
        "input_tokens": 17, "cache_read_input_tokens": 13,
        "cache_creation_input_tokens": 11, "output_tokens": 7,
        "cache_creation": {"ephemeral_1h_input_tokens": 5},
        "output_tokens_details": {"thinking_tokens": 3}, "speed": "fast",
    }
    source.write_text(lines[0] + "\n" + json.dumps(assistant, separators=(",", ":")) + "\n")
    copy = native.home / ".claude/projects/b/synthetic-claude.jsonl"
    copy.parent.mkdir(parents=True)
    copy.write_bytes(source.read_bytes())
    result = native.build()
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    sessions = {s["provider"]: s for s in payload["sessions"]}
    claude = sessions["claude"]
    assert claude["own_usage"]["input"] == 41, payload["diagnostics"]["claude_rows_dropped"]
    assert claude["own_usage"]["cached_input"] == 13
    assert claude["own_usage"]["cache_write"] == 11
    assert claude["own_usage"]["output"] == 7
    assert claude["own_usage"]["reasoning"] == 3
    assert claude["own_usage"]["cost_usd"] is None
    assert claude["buckets"][0][2] == "fast"
    assert claude["buckets"][0][3:8] == [41, 13, 11, 7, 3]
    assert claude["buckets"][0][9] == "claude"
    assert sessions["codex"]["own_usage"] == codex_before["own_usage"]
    assert [b[:9] for b in sessions["codex"]["buckets"]] == [b[:9] for b in codex_before["buckets"]]
    assert all(b[9] == "codex" for b in sessions["codex"]["buckets"])
    assert payload["meta"]["costs"] == before["meta"]["costs"]
    assert payload["diagnostics"]["claude_duplicate_responses"] == {"key_count": 1, "row_count": 1}
    assert "colophon: codex:" in result.stdout
    assert "colophon: claude:" in result.stdout

def test_claude_usage_does_not_depend_on_codex_ledger(native):
    native.session()
    native.claude_session(rows=[{
        "type": "assistant", "timestamp": "2001-01-01T00:00:00Z",
        "message": {"model": "synthetic-claude-model", "usage": {
            "input_tokens": 19, "output_tokens": 23}},
    }])
    source = native.home / ".claude/projects/synthetic-kite/synthetic-claude.jsonl"
    source.write_text(json.dumps(json.loads(source.read_text()), separators=(",", ":")) + "\n")
    native.runtime.mkdir()
    (native.runtime / "price-history.json").write_text("synthetic-invalid-ledger")
    result = native.build()
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    assert not payload["meta"]["costs"]["available"]
    assert not payload["meta"]["sources"]["codex"]["costs"]["available"]
    assert payload["meta"]["sources"]["claude"]["costs"] == {"available": True, "reason": None}
    claude, = [s for s in payload["sessions"] if s["provider"] == "claude"]
    assert claude["own_usage"]["input"] == 19
    assert claude["own_usage"]["output"] == 23
    assert claude["own_usage"]["unpriced_tokens"] == 42
    assert claude["own_usage"]["cost_usd"] is None
    lines = result.stdout.splitlines()
    assert any(line.startswith("colophon: claude:") and "42 tokens" in line and "costs unavailable" in line for line in lines)

def test_claude_session_without_codex(native):
    native.codex.rmdir()
    native.claude_session()
    result = native.build()
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    assert payload["schema"] == 1
    session, = payload["sessions"]
    assert session["id"] == "synthetic-claude"
    assert session["provider"] == "claude"
    assert session["title"] == "Invent a synthetic Claude kite"
    assert session["cwd"] == "/synthetic/claude-kite"
    assert session["branch"] == "synthetic-branch"
    assert session["workspace"] in payload["workspaces"]
    assert session["turns"][0]["status"] == "completed"
    assert session["turns"][0]["requests"][0]["kind"] == "text"
    assert "no_session_meta" not in session["flags"]
    assert payload["meta"]["sources"]["codex"]["status"] == "absent"
    assert payload["meta"]["sources"]["claude"]["status"] == "ok"
    assert payload["meta"]["counts"] == {"logs": 0, "parsed": 0, "cached": 0, "sessions": 0, "subagents": 0, "orphans": 0}
    assert session["resume_config_dir"] == str(native.home / ".claude")
    assert not (native.runtime / "cache-native").exists()

def test_claude_disabled_and_mixed(native):
    native.session()
    assert native.build("--no-claude").returncode == 0
    baseline = native.payload()["meta"]["counts"]
    native.claude_session()
    assert native.build().returncode == 0
    assert {s["provider"] for s in native.payload()["sessions"]} == {"codex", "claude"}
    # The baseline was warm on disk; only parse-cache hit counters change.
    baseline.update(parsed=0, cached=1)
    assert native.payload()["meta"]["counts"] == baseline
    assert native.payload()["meta"]["sources"]["claude"]["logs"] == 1
    result = native.build("--no-claude")
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    assert [s["provider"] for s in payload["sessions"]] == ["codex"]
    assert payload["meta"]["sources"]["claude"]["status"] == "disabled"

def test_claude_history_establishes_presence_read_only(native):
    native.codex.rmdir()
    config = native.home / ".claude"
    config.mkdir()
    history = config / "history.jsonl"
    history.write_text(json.dumps({"sessionId": "synthetic-history", "display": "Synthetic remembered kite", "timestamp": 1767355200000, "project": "/synthetic/history"}) + "\n")
    before = history.read_bytes()
    result = native.build()
    assert result.returncode == 0, result.stderr
    assert native.payload()["meta"]["sources"]["claude"]["status"] == "ok"
    assert history.read_bytes() == before

def test_no_sources_reports_checked_paths_without_runtime(native):
    native.codex.rmdir()
    result = native.build()
    assert result.returncode == 1
    assert str(native.codex) in result.stderr
    assert str(native.home / ".claude/projects") in result.stderr
    assert str(native.home / ".claude/history.jsonl") in result.stderr
    assert not native.runtime.exists()

@pytest.mark.parametrize("relative", [
    ".claude/projects/synthetic-project",
    ".config/claude/projects/synthetic-project",
    "Library/Application Support/Claude/local-agent-mode-sessions/synthetic-account/synthetic-org/synthetic-session/local_agent/.claude/projects/synthetic-project",
    "Library/Application Support/Claude/claude-code-sessions/synthetic-account/synthetic-org/.claude/projects/synthetic-project",
    ".claude-swap-backup/sessions/1-synthetic/projects/synthetic-project",
])
def test_claude_each_search_root(native, relative):
    native.codex.rmdir()
    source = native.claude_session(directory=native.home / relative)
    before = source.read_bytes()
    result = native.build()
    assert result.returncode == 0, result.stderr
    assert [s["id"] for s in native.payload()["sessions"]] == ["synthetic-claude"]
    assert source.read_bytes() == before
    assert native.payload()["meta"]["sources"]["claude"]["logs"] == 1

def test_claude_symlink_roots_deduplicate_without_nested_descent(native):
    native.codex.rmdir()
    primary = native.home / ".config/claude"
    native.claude_session(directory=primary / "projects/synthetic-project")
    (native.home / ".claude").symlink_to(primary, target_is_directory=True)
    swap = native.home / ".claude-swap-backup/sessions"
    swap.mkdir(parents=True)
    (swap / "1-synthetic").symlink_to(primary, target_is_directory=True)
    nested = native.root / "synthetic-outside"
    native.claude_session("synthetic-excluded", directory=nested)
    (primary / "projects/synthetic-linked").symlink_to(nested, target_is_directory=True)
    native.claude_session("synthetic-hidden", directory=primary / "projects/.synthetic-hidden")
    result = native.build()
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    assert [s["id"] for s in payload["sessions"]] == ["synthetic-claude"]
    assert payload["meta"]["sources"]["claude"]["logs"] == 1
    assert payload["meta"]["sources"]["claude"]["roots"].count(str(primary / "projects")) == 1
    assert payload["sessions"][0]["resume_config_dir"] == str(primary)

def test_claude_explicit_home_matches_environment_selection(native):
    custom = native.root / "synthetic-custom-config"
    native.claude_session(directory=custom / "projects/synthetic-project")
    native.claude_session("synthetic-default-excluded")
    native.claude_session("synthetic-xdg-excluded", directory=native.home / ".config/claude/projects/synthetic-project")
    result = native.build("--claude-home", str(custom))
    assert result.returncode == 0, result.stderr
    explicit = native.payload()
    native.env["CLAUDE_CONFIG_DIR"] = str(custom)
    result = native.build()
    assert result.returncode == 0, result.stderr
    environment = native.payload()
    assert explicit["meta"]["sources"]["claude"] == environment["meta"]["sources"]["claude"]
    assert [s["id"] for s in environment["sessions"]] == ["synthetic-claude"]
    assert environment["sessions"][0]["resume_config_dir"] == str(custom)

def test_claude_xdg_default_and_same_stem_provenance_uses_ascending_config(native):
    native.claude_session(directory=native.home / ".config/claude/projects/synthetic-project")
    assert native.build().returncode == 0
    xdg_config = str(native.home / ".config/claude")
    assert native.payload()["sessions"][0]["resume_config_dir"] == xdg_config
    native.claude_session()
    assert native.build().returncode == 0
    assert len(native.payload()["sessions"]) == 1
    # .claude sorts before .config/claude despite XDG discovery occurring first.
    assert native.payload()["sessions"][0]["resume_config_dir"] == str(native.home / ".claude")

def test_claude_custom_config_is_not_assigned_to_swap_desktop_or_subagents(native):
    custom = native.root / "synthetic-custom-config"
    native.claude_session(directory=custom / "projects/synthetic-project")
    native.claude_session("synthetic-swap", directory=native.home / ".claude-swap-backup/sessions/1-synthetic/projects/synthetic-project")
    native.claude_session("agent-synthetic-child", directory=custom / "projects/synthetic-project/synthetic-claude/subagents")
    result = native.build("--claude-home", str(custom))
    assert result.returncode == 0, result.stderr
    rows = {s["id"]: s for s in native.payload()["sessions"]}
    assert rows["synthetic-claude"]["resume_config_dir"] == str(custom)
    assert rows["synthetic-swap"]["resume_config_dir"] is None
    assert rows["synthetic-claude/agent-synthetic-child"]["resume_config_dir"] is None
    native.claude_session("synthetic-desktop", directory=native.home / "Library/Application Support/Claude/claude-code-sessions/a/.claude/projects/synthetic-project")
    result = native.build()
    assert result.returncode == 0, result.stderr
    assert next(s for s in native.payload()["sessions"] if s["id"] == "synthetic-desktop")["resume_config_dir"] is None

@pytest.mark.parametrize("relative", [
    "Library/Application Support/Claude/local-agent-mode-sessions/a/.claude/projects",
    ".claude-swap-backup/sessions/1-synthetic/projects",
])
def test_claude_unreadable_locator_and_swap_projects_are_diagnostic(native, relative):
    blocked = native.home / relative
    native.claude_session(directory=blocked / "synthetic-project")
    blocked.chmod(0)
    try:
        result = native.build()
        assert result.returncode == 0, result.stderr
        assert native.payload()["sessions"] == []
        assert {p["path"] for p in native.payload()["diagnostics"]["skipped_files"]} == {str(blocked)}
    finally:
        blocked.chmod(0o700)

def test_claude_desktop_override_and_locator_depth(native):
    desktop = native.root / "synthetic-desktop"
    base = desktop / "local-agent-mode-sessions"
    native.claude_session(directory=base / "a/b/c/d/.claude/projects/synthetic-project")
    native.claude_session("synthetic-too-deep", directory=base / "a/b/c/d/e/.claude/projects/synthetic-project")
    native.claude_session("synthetic-build-excluded", directory=base / "build/.claude/projects/synthetic-project")
    result = native.build("--claude-desktop-dir", str(desktop))
    assert result.returncode == 0, result.stderr
    assert [s["id"] for s in native.payload()["sessions"]] == ["synthetic-claude"]

def test_claude_same_stem_foreign_ids_and_codex_collision(native):
    native.session()
    native.claude_session("synthetic-shared", directory=native.home / ".claude/projects/a")
    native.claude_session("synthetic-shared", directory=native.home / ".claude/projects/b")
    native.claude_session(SESSION)
    result = native.build()
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    assert sorted(s["id"] for s in payload["sessions"]) == [SESSION, "synthetic-shared"]
    assert next(s for s in payload["sessions"] if s["id"] == SESSION)["provider"] == "codex"
    assert payload["diagnostics"]["claude_session_id_collisions"] == [SESSION]

def test_claude_collision_preserves_codex_filename_fallback_identity(native):
    rows = [r for r in native.session_rows() if r["type"] != "session_meta"]
    native.write_session(rows, name=f"rollout-2026-01-02T12-00-00-{UUID}.jsonl")
    native.claude_session(UUID)
    result = native.build()
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    assert [(s["id"], s["provider"]) for s in payload["sessions"]] == [(UUID, "codex")]
    assert payload["diagnostics"]["claude_session_id_collisions"] == [UUID]

@pytest.mark.parametrize("rebuild", [False, True])
@pytest.mark.parametrize("cache_state", ["populated", "incompatible", "recovery"])
def test_absent_codex_preserves_cache_bytes_names_and_modes(native, rebuild, cache_state):
    native.session()
    result = native.build()
    assert result.returncode == 0, result.stderr
    installed = native.runtime / "cache-native"
    if cache_state == "incompatible":
        (installed / "FORMAT").write_bytes(b"synthetic-incompatible-format\n")
    if cache_state == "recovery":
        backup = native.runtime / "cache-native.old-424242"
        shutil.copytree(installed, backup)
        stage = native.runtime / "cache-native.rebuild-424242"
        stage.mkdir(mode=0o700)
        (stage / "synthetic-recovery-residue").write_bytes(b"Synthetic recovery residue\n")
        (stage / "synthetic-recovery-residue").chmod(0o600)
    def snapshot():
        roots = [p for p in native.runtime.iterdir() if "cache-native" in p.name]
        paths = [p for root in roots for p in [root, *root.rglob("*")]]
        return {str(p.relative_to(native.runtime)): (mode(p), None if p.is_dir() else p.read_bytes()) for p in paths}
    before = snapshot()
    shutil.rmtree(native.codex)
    native.claude_session()
    result = native.build(*(["--rebuild"] if rebuild else []))
    assert result.returncode == 0, result.stderr
    assert snapshot() == before
    assert native.payload()["meta"]["sources"]["codex"]["status"] == "absent"

@pytest.mark.parametrize("entry", [
    {"sessionId": "", "display": "synthetic", "timestamp": 1767355200000, "project": "/synthetic"},
    {"sessionId": "synthetic", "display": 1, "timestamp": 1767355200000, "project": "/synthetic"},
    {"sessionId": "synthetic", "display": "synthetic", "timestamp": 1.5, "project": "/synthetic"},
    {"sessionId": "synthetic", "display": "synthetic", "timestamp": True, "project": "/synthetic"},
    {"sessionId": "synthetic", "display": "synthetic", "timestamp": 1767355200000, "project": None},
])
def test_unusable_claude_history_does_not_establish_presence(native, entry):
    native.codex.rmdir()
    config = native.home / ".claude"
    config.mkdir()
    (config / "history.jsonl").write_text(json.dumps(entry) + "\n")
    result = native.build()
    assert result.returncode == 1
    assert not native.runtime.exists()

def test_claude_readable_empty_directory_is_present(native):
    native.codex.rmdir()
    (native.home / ".claude/projects").mkdir(parents=True)
    result = native.build()
    assert result.returncode == 0, result.stderr
    assert native.payload()["sessions"] == []
    assert native.payload()["meta"]["sources"]["claude"]["status"] == "ok"

def test_claude_diagnostics_keep_codex_unknown_types_separate(native):
    source = native.claude_session()
    with source.open("a") as stream:
        stream.write("synthetic malformed line\n")
        stream.write(json.dumps({"type": "synthetic-future-kind"}) + "\n")
    history = native.home / ".claude/history.jsonl"
    history.write_text(json.dumps({"sessionId": "synthetic-missing-fields"}) + "\n")
    result = native.build()
    assert result.returncode == 0, result.stderr
    diagnostics = native.payload()["diagnostics"]
    assert diagnostics["malformed_lines"]["total"] == 2
    assert {p["path"] for p in diagnostics["malformed_lines"]["files"]} == {str(source), str(history)}
    assert diagnostics["claude_unknown_record_types"] == {"synthetic-future-kind": 1}
    assert diagnostics["unknown_record_types"] == {}
    assert "malformed_lines=2" in result.stderr
    assert "claude_unknown_record_types=1" in result.stderr

def test_claude_config_relative_literal_and_explicit_precedence(native):
    config = native.root / "synthetic-literal-config"
    native.claude_session(directory=config / "projects/synthetic-project")
    native.env["CLAUDE_CONFIG_DIR"] = "synthetic-absent-env"
    relative = os.path.relpath(config, Path(__file__).resolve().parents[1])
    result = native.build("--claude-home", relative)
    assert result.returncode == 0, result.stderr
    assert [s["id"] for s in native.payload()["sessions"]] == ["synthetic-claude"]
    native.env["CLAUDE_CONFIG_DIR"] = relative
    assert native.build().returncode == 0
    assert [s["id"] for s in native.payload()["sessions"]] == ["synthetic-claude"]

def test_claude_config_tilde_is_literal_and_empty_uses_defaults(native):
    native.claude_session()
    native.env["CLAUDE_CONFIG_DIR"] = "~/.claude"
    result = native.build()
    assert result.returncode == 0, result.stderr
    assert native.payload()["sessions"] == []
    assert native.payload()["meta"]["sources"]["claude"]["status"] == "absent"
    native.env["CLAUDE_CONFIG_DIR"] = ""
    result = native.build()
    assert result.returncode == 0, result.stderr
    assert [s["id"] for s in native.payload()["sessions"]] == ["synthetic-claude"]
def test_claude_disabled_only_source_creates_no_runtime(native):
    native.codex.rmdir()
    native.claude_session()
    result = native.build("--no-claude")
    assert result.returncode == 1
    assert "--no-claude" in result.stderr
    assert not native.runtime.exists()

def test_claude_desktop_search_root_symlink_and_nested_symlink_skip(native):
    container = native.root / "synthetic-desktop-container"
    native.claude_session(directory=container / "a/.claude/projects/synthetic-project")
    excluded = native.root / "synthetic-desktop-excluded"
    native.claude_session("synthetic-excluded", directory=excluded / ".claude/projects/synthetic-project")
    (container / "synthetic-nested-link").symlink_to(excluded, target_is_directory=True)
    nested_config = container / "b"
    nested_config.mkdir()
    (nested_config / ".claude").symlink_to(excluded / ".claude", target_is_directory=True)
    desktop = native.home / "Library/Application Support/Claude"
    desktop.mkdir(parents=True)
    (desktop / "claude-code-sessions").symlink_to(container, target_is_directory=True)
    result = native.build()
    assert result.returncode == 0, result.stderr
    assert [s["id"] for s in native.payload()["sessions"]] == ["synthetic-claude"]

def test_claude_unreadable_descendant_is_diagnostic(native):
    native.claude_session()
    blocked = native.home / ".claude/projects/synthetic-unreadable"
    native.claude_session("synthetic-unreadable", directory=blocked)
    blocked.chmod(0)
    try:
        result = native.build()
        assert result.returncode == 0, result.stderr
        assert [s["id"] for s in native.payload()["sessions"]] == ["synthetic-claude"]
        assert {p["path"] for p in native.payload()["diagnostics"]["skipped_files"]} == {str(blocked)}
    finally:
        blocked.chmod(0o700)

@pytest.mark.parametrize("archived", [False, True])
def test_zstd_log_counts_like_plain_across_cold_warm_rebuild(native, archived):
    source = native.write_zstd_session(native.session_rows(), archived=archived)
    before = source.read_bytes()
    for args, count in [((), "1 parsed, 0 cached"), ((), "0 parsed, 1 cached"), (("--rebuild",), "1 parsed, 0 cached")]:
        result = native.build(*args)
        assert result.returncode == 0, result.stderr
        assert count in result.stdout
        payload = native.payload()
        session = assert_session(payload)
        assert session["archived"] is archived
        assert session["log_path"].endswith(".jsonl.zst")
        assert session["own_usage"]["input"] == 120 and session["own_usage"]["output"] == 30
        assert payload["diagnostics"]["skipped_files"] == []
        assert source.read_bytes() == before
        private_runtime(native)

def test_plain_and_zstd_copies_of_one_log_count_once(native):
    native.session()
    native.write_zstd_session(native.session_rows(), name="rollout-synthetic.jsonl.zst")
    result = native.build()
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    assert payload["meta"]["counts"]["logs"] == 1
    assert assert_session(payload)["log_path"].endswith("rollout-synthetic.jsonl")

def test_truncated_and_corrupt_zstd_logs_are_skipped_not_fatal(native):
    native.session()
    good = native.write_zstd_session(native.session_rows(), name="rollout-cut.jsonl.zst")
    good.write_bytes(good.read_bytes()[:-3])
    (good.parent / "rollout-junk.jsonl.zst").write_bytes(b"synthetic junk, not zstd\n")
    result = native.build()
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    assert_session(payload)
    skipped = payload["diagnostics"]["skipped_files"]
    assert sorted(p["path"].rsplit("/", 1)[1] for p in skipped) == ["rollout-cut.jsonl.zst", "rollout-junk.jsonl.zst"]
    assert all(p["reason"] == "unreadable" for p in skipped)
    assert "skipped_files" in result.stderr

def test_zstd_log_with_large_declared_window_decodes(native):
    native.write_zstd_session(native.session_rows(), window_log=28)
    result = native.build()
    assert result.returncode == 0, result.stderr
    assert_session(native.payload())

@pytest.mark.parametrize("suffix", [".jsonl", ".jsonl.zst"])
def test_log_without_session_meta_takes_filename_uuid(native, suffix):
    rows = [r for r in native.session_rows() if r["type"] != "session_meta"]
    name = f"rollout-2026-01-02T12-00-00-{UUID}{suffix}"
    if suffix == ".jsonl":
        native.write_session(rows, name=name)
    else:
        native.write_zstd_session(rows, name=name)
    result = native.build()
    assert result.returncode == 0, result.stderr
    assert [s["id"] for s in native.payload()["sessions"]] == [UUID]

def mode(path):
    return stat.S_IMODE(path.stat().st_mode)

def private_runtime(native):
    assert mode(native.runtime) == 0o700
    for path in native.runtime.rglob("*"):
        assert mode(path) == (0o700 if path.is_dir() else 0o600), path

def test_help_and_version_create_no_runtime(native):
    help_result = native.invoke("--help")
    assert help_result.returncode == 0
    for text in ("--offline", "--codex-home", "cache-native/", "COLOPHON_HOME"):
        assert text in help_result.stdout
    for text in ("make test", "make sanitize", "make tsan", "make check-assets", "make check-sort"):
        assert text in help_result.stdout
    assert "parity and performance tools" not in help_result.stdout
    assert "private/" not in help_result.stdout
    version = native.invoke("--version")
    assert version.returncode == 0
    assert version.stdout == "colophon 0.1.0\n"
    assert not native.runtime.exists()

def test_sandbox_allows_active_reads_and_scratch_only_writes(tmp_path):
    project = Path(__file__).resolve().parents[1]
    binary = Path(os.environ["COLOPHON_BIN"])
    assert (project / "src/cli/args.c").read_bytes()
    assert binary.read_bytes()
    scratch = tmp_path / "synthetic-scratch.txt"
    scratch.write_text("Synthetic sandbox fixture")
    assert scratch.read_text() == "Synthetic sandbox fixture"

    # Evaluate nonexistent children: no real runtime/source reads or writes.
    check = ctypes.CDLL(None).sandbox_check
    check.restype = ctypes.c_int
    # sandbox_check is variadic; only its three fixed arguments belong here
    # (Apple Silicon passes variadic arguments differently).
    check.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    def denied(path):
        result = check(os.getpid(), b"file-write-create", 1, os.fsencode(path))
        assert result >= 0, "sandbox policy evaluation failed"
        return result != 0
    assert not denied(tmp_path)
    assert denied(project)
    assert denied(project / "synthetic-sandbox-nonexistent-child/canary")
    real_home = Path(os.environ["COLOPHON_TEST_REAL_HOME"])
    for target in (".codex", ".colophon", "Library/Scripts", ".local/bin", "bin",
                   "Downloads/colophon-native", "Downloads/colophon-c-experiment"):
        assert denied(real_home / target), target
        assert denied(real_home / target / "synthetic-sandbox-nonexistent-child/canary"), target


def test_sandbox_source_write_denied():
    # The wrapper also runs this under an allowlisted scratch PROJECT_DIR,
    # independently testing the explicit source deny and its mutation control.
    project = Path(os.environ.get("COLOPHON_TEST_SOURCE_PROBE", Path(__file__).resolve().parents[1]))
    check = ctypes.CDLL(None).sandbox_check
    check.restype = ctypes.c_int
    check.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    result = check(os.getpid(), b"file-write-create", 1, os.fsencode(project))
    assert result >= 0, "sandbox policy evaluation failed"
    assert result != 0, "PROJECT_DIR write protection missing"

def test_sandbox_claude_paths_denied():
    check = ctypes.CDLL(None).sandbox_check
    check.restype = ctypes.c_int
    check.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    home = Path(os.environ["COLOPHON_TEST_REAL_HOME"])
    selected = os.environ.get("COLOPHON_TEST_POLICY_TARGET")
    targets = [selected] if selected else [".claude", ".config/claude", "Library/Application Support/Claude", ".claude-swap-backup"]
    for target in targets:
        for operation in (b"file-read-data", b"file-write-create"):
            for path in (home / target, home / target / "synthetic-nonexistent-child"):
                result = check(os.getpid(), operation, 1, os.fsencode(path))
                assert result >= 0, "sandbox policy evaluation failed"
                assert result != 0, f"Claude source protection missing: {target} {operation!r}"

@pytest.mark.parametrize("args,diagnostic", [
    (["--not-synthetic-option"], "unrecognized arguments"),
    (["--output"], "expected one argument"),
    (["--offline", "--refresh-prices"], "cannot be combined"),
    (["--re"], "ambiguous option"),
    (["--no"], "--no-open, --no-claude"),
    (["--claude"], "--claude-home, --claude-desktop-dir"),
])
def test_invalid_options_exit_two(native, args, diagnostic):
    result = native.invoke(*args)
    assert result.returncode == 2
    assert diagnostic in result.stderr
    assert "usage: colophon" in result.stderr
    assert not native.runtime.exists()

def test_missing_codex_home_exit_one(native):
    result = native.invoke("--codex-home", str(native.root / "absent"), "--offline", "--no-open")
    assert result.returncode == 1
    assert "colophon:" in result.stderr and "Codex" in result.stderr
    assert not native.page.exists()

def test_empty_offline_home_creates_private_page(native):
    result = native.build()
    assert result.returncode == 0, result.stderr
    assert "0 sessions" in result.stdout and "0 parsed, 0 cached" in result.stdout
    payload = native.payload()
    assert payload["schema"] == 1
    assert payload["sessions"] == []
    private_runtime(native)

def assert_session(payload):
    assert payload["schema"] == 1
    assert len(payload["sessions"]) == 1
    session = payload["sessions"][0]
    assert session["id"] == SESSION
    assert len(session["turns"]) == 1
    turn = session["turns"][0]
    assert turn["id"] == "synthetic-turn"
    assert turn["status"] == "completed"
    assert len(turn["requests"]) == 1
    assert turn["requests"][0]["text"] == REQUEST
    assert turn["requests"][0]["kind"] == "text"
    assert turn["requests"][0]["images"] == 0
    assert turn["final_answer"] == {"text": "Synthetic kite complete", "voice": False}
    return session

def test_nonempty_cold_warm_and_rebuild_preserve_session_usage(native):
    source = native.session()
    before = source.read_bytes()
    sessions = []
    for args, count in [((), "1 parsed, 0 cached"), ((), "0 parsed, 1 cached"), (("--rebuild",), "1 parsed, 0 cached")]:
        result = native.build(*args)
        assert result.returncode == 0, result.stderr
        assert count in result.stdout
        payload = native.payload()
        assert payload["meta"]["counts"] == {"logs": 1, "parsed": int("1 parsed" in count), "cached": int("1 cached" in count), "sessions": 1, "subagents": 0, "orphans": 0}
        sessions.append(assert_session(payload))
        assert source.read_bytes() == before
        private_runtime(native)
    assert sessions[0] == sessions[1] == sessions[2]
    usage = sessions[0]["own_usage"]
    assert usage["input"] == 120
    assert usage["cached_input"] == 20
    assert usage["output"] == 30
    assert usage["reasoning"] == 5

@pytest.mark.parametrize("status,diagnostic", [(0, "unstable sort is forbidden"), (1, ""), (2, "stable-sort search failed (status 2)")])
def test_build_sort_guard_preserves_search_status(tmp_path, status, diagnostic):
    project = Path(__file__).resolve().parents[1]
    rg = tmp_path / "rg"
    rg.write_text(f"#!/bin/sh\nexit {status}\n")
    rg.chmod(0o700)
    env = os.environ.copy()
    env["PATH"] = str(tmp_path) + os.pathsep + env["PATH"]
    result = subprocess.run(["make", "check-sort"], cwd=project, env=env, text=True, capture_output=True)
    assert (result.returncode == 0) == (status == 1)
    assert diagnostic in result.stderr

def test_browser_error_guard_fails_on_console_and_page_errors():
    class Page:
        def __init__(self):
            self.listeners = {}
        def on(self, event, listener):
            self.listeners[event] = listener
        def remove_listener(self, event, listener):
            assert self.listeners.pop(event) is listener
    page = Page()
    with pytest.raises(AssertionError, match="synthetic page error"):
        with guard_browser_errors(page):
            page.listeners["pageerror"]("synthetic page error")
    assert not page.listeners
    class Message:
        type = "error"
        text = "synthetic console error"
    with pytest.raises(AssertionError, match="synthetic console error"):
        with guard_browser_errors(page):
            page.listeners["console"](Message())
    assert not page.listeners

def test_output_override_and_existing_ledger_are_preserved(native):
    source = native.session()
    original = source.read_bytes()
    native.runtime.mkdir(mode=0o700)
    ledger = native.runtime / "price-history.json"
    content = b'{"schema":1,"entries":[{"model":"synthetic-ledger-model","effective_from":null,"per_million":{"input":1,"output":2,"cached_input":0.5,"cache_write":1},"source":"synthetic","note":"invented preservation sentinel"}]}\n'
    ledger.write_bytes(content)
    ledger.chmod(0o600)
    output = native.root / "synthetic-output.html"
    result = native.build("--output", str(output))
    assert result.returncode == 0, result.stderr
    assert_session(native.payload(output))
    assert mode(output) == 0o600
    assert not native.page.exists()
    assert ledger.read_bytes() == content
    assert source.read_bytes() == original
    private_runtime(native)

def test_loopback_catalog_fetch_uses_only_synthetic_endpoint(native):
    calls = []
    catalog = {"openai": {"models": {"synthetic-kite-model": {"id": "synthetic-kite-model", "name": "Synthetic Kite", "cost": {"input": 1, "output": 2}}}}}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            body = json.dumps(catalog).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        native.env["COLOPHON_PRICING_URL"] = f"http://127.0.0.1:{server.server_port}/synthetic-catalog.json"
        result = native.build("--refresh-prices", offline=False)
        assert result.returncode == 0, result.stderr
        assert calls == ["/synthetic-catalog.json"]
        assert native.payload()["meta"]["catalog"]["source_host"] == "127.0.0.1"
        assert native.payload()["meta"]["catalog"]["status"] == "fetched"
        assert "synthetic-kite-model" in (native.runtime / "pricing-cache.json").read_text()
        private_runtime(native)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

@pytest.mark.parametrize("html", ["<html></html>", '<script id="colophon-data">[]</script>', '<script id="colophon-data">broken</script>', '<script id="colophon-data">{}</script><script id="colophon-data">{}</script>'])
def test_payload_helper_rejects_corruption(html):
    with pytest.raises(ValueError):
        extract_payload(html)

def test_local_asset_checker_rejects_corruption_and_missing_asset(tmp_path):
    project = Path(__file__).resolve().parents[1]
    assets = tmp_path / "assets"
    assets.mkdir()
    for path in (project / "assets").iterdir():
        (assets / path.name).write_bytes(path.read_bytes())
    command = ["perl", str(project / "tools/check_assets.pl"), str(assets)]
    assert subprocess.run(command, capture_output=True).returncode == 0
    asset = assets / "page.js"
    original = asset.read_bytes()
    asset.write_bytes(original + b"synthetic corruption")
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode != 0 and "digest mismatch: page.js" in result.stderr
    asset.write_bytes(original)
    asset.unlink()
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode != 0 and "page.js" in result.stderr
    asset.write_bytes(original)
    assert subprocess.run(command, capture_output=True).returncode == 0

def test_long_context_threshold_prices_250k_request_at_standard_rates(native):
    turn = "synthetic-long-turn"
    native.write_session([
        row("session_meta", {"id": SESSION, "cwd": "/synthetic/kite", "source": "cli"}, 0),
        row("turn_context", {"model": "gpt-6.1-sol", "turn_id": turn}, 1),
        row("event_msg", {"type": "task_started", "turn_id": turn}, 1),
        row("event_msg", {"type": "token_count", "turn_id": turn, "info": {
            "last_token_usage": usage(250_000, 0, 1_000), "total_token_usage": usage(250_000, 0, 1_000)}}, 3),
    ])
    result = native.build()
    assert result.returncode == 0, result.stderr
    cost = native.payload()["sessions"][0]["own_usage"]["cost_usd"]
    # 250,000 × $2/M + 1,000 × $10/M; the 200K threshold would give 1.015.
    assert cost == pytest.approx(0.51)

def test_thread_settings_priority_applies_fast_multiplier(native):
    turn = "synthetic-fast-turn"
    native.write_session([
        row("session_meta", {"id": SESSION, "cwd": "/synthetic/kite", "source": "cli"}, 0),
        row("turn_context", {"model": "gpt-6-astra", "turn_id": turn}, 1),
        row("event_msg", {"type": "thread_settings_applied", "thread_settings": {"service_tier": "priority"}}, 1),
        row("event_msg", {"type": "task_started", "turn_id": turn}, 2),
        row("event_msg", {"type": "token_count", "turn_id": turn, "info": {
            "last_token_usage": usage(1_000, 0, 100), "total_token_usage": usage(1_000, 0, 100)}}, 3),
    ])
    result = native.build()
    assert result.returncode == 0, result.stderr
    session = native.payload()["sessions"][0]
    # Standard cost is 0.015; the curated Astra priority multiplier is 2.
    assert session["own_usage"]["cost_usd"] == pytest.approx(0.03)
    assert any(bucket[2] == "priority" for bucket in session["buckets"])

def test_ledger_mirror_counts_once_and_snapshot_only_request_counts(native):
    turn = "synthetic-ledger-turn"
    native.write_session([
        row("session_meta", {"id": SESSION, "session_id": SESSION, "cwd": "/synthetic/kite", "source": "cli"}, 0),
        row("turn_context", {"model": "gpt-5", "turn_id": turn}, 1),
        row("event_msg", {"type": "task_started", "turn_id": turn}, 1),
        row("token_usage_record", {"thread_id": SESSION, "session_id": SESSION, "response_id": "synthetic-response-1",
            "turn_id": turn, "usage": usage(100, 40, 10), "thread_token_usage": usage(100, 40, 10)}, 3),
        row("event_msg", {"type": "token_count", "info": {"last_token_usage": usage(100, 40, 10),
            "total_token_usage": usage(100, 40, 10)}}, 3, ".200"),
        row("event_msg", {"type": "token_count", "info": {"last_token_usage": usage(50, 0, 5),
            "total_token_usage": usage(150, 40, 15)}}, 9),
    ])
    result = native.build()
    assert result.returncode == 0, result.stderr
    own = native.payload()["sessions"][0]["own_usage"]
    assert (own["input"], own["cached_input"], own["output"]) == (150, 40, 15)

def test_ledger_mirror_earlier_near_owns_before_later_exact(native):
    turn = "synthetic-chronological-turn"
    native.write_session([
        row("session_meta", {"id": SESSION, "session_id": SESSION, "cwd": "/synthetic/kite", "source": "cli"}, 0),
        row("event_msg", {"type": "task_started", "turn_id": turn}, 1),
        row("token_usage_record", {"thread_id": SESSION, "session_id": SESSION,
            "response_id": "synthetic-chronological-response", "turn_id": turn,
            "usage": usage(100, 0, 10), "thread_token_usage": usage(100, 0, 10)}, 2),
        row("event_msg", {"type": "token_count", "info": {"last_token_usage": usage(100, 0, 10)}}, 3),
        row("event_msg", {"type": "token_count", "info": {"last_token_usage": usage(100, 0, 10)}}, 2),
    ])
    result = native.build()
    assert result.returncode == 0, result.stderr
    own = native.payload()["sessions"][0]["own_usage"]
    assert (own["input"], own["cached_input"], own["output"]) == (100, 0, 10)
