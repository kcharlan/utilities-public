"""OpenCode public CLI integration using invented rows in scratch homes only."""
import ctypes
import json
import os
import sqlite3
import stat
from pathlib import Path

import pytest

SCHEMA = Path(__file__).parent / "fixtures/opencode/schema_v2.sql"
SESSION = "synthetic-opencode-kite"
CLOCK = 1767355200000


def database(native, name="opencode.db", *, session=SESSION, cost=.25, tokens=10, messages=True, parent=None, archived=None, project_archived=None):
    path = native.home / ".local/share/opencode" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA.read_text())
        db.execute("INSERT INTO migration VALUES (?,?)", ("20261010180456_project_time_archived", CLOCK))
        db.execute("INSERT INTO project VALUES (?,?,?,?,?)", ("synthetic-project", "/synthetic/opencode", CLOCK, CLOCK, project_archived))
        db.execute("INSERT INTO session_v2 (id,project_id,parent_id,directory,title,version,cost,tokens_input,time_created,time_updated,time_archived) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (session, "synthetic-project", parent, "/synthetic/opencode", "Synthetic OpenCode kite", "synthetic-version", cost, tokens, CLOCK, CLOCK + 3000, archived))
        if messages:
            message(db, session, "user", 1, {"text": "Invent a synthetic OpenCode kite"})
            message(db, session, "assistant", 2, {"content": [{"type": "text", "text": "Synthetic kite done"}], "model": {"id": "synthetic-model", "providerID": "synthetic-provider"}, "tokens": {"input": tokens, "output": 0}, "cost": cost, "finish": "stop"})
    return path


def message(db, session, kind, seq, fields):
    identity = f"synthetic-{session}-{seq}"
    data = {"id": identity, "type": kind, "time": {"created": CLOCK + seq * 1000, "completed": CLOCK + seq * 1000 + 100}, **fields}
    db.execute("INSERT INTO session_message VALUES (?,?,?,?,?,?,?)", (identity, session, kind, seq, CLOCK + seq * 1000, CLOCK + seq * 1000, json.dumps(data)))


def source(payload):
    return payload["meta"]["sources"]["opencode"]


def test_opencode_only_build_counts_cost_actions_and_private_runtime(native):
    path = database(native)
    native.codex.rmdir()
    result = native.build("--no-claude")
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    row, = payload["sessions"]
    assert row["provider"] == "opencode"
    assert row["opencode_database"] == str(path)
    assert row["capabilities"] == {"copy_session_id": True, "copy_log_path": False, "open_in_codex": False, "continue_in_cli": False}
    assert row["own_usage"]["input"] == 10
    assert row["own_usage"]["cost_usd"] == .25
    assert source(payload)["status"] == "ok"
    assert source(payload)["sessions"] == 1
    assert source(payload)["requests"] == 1
    assert source(payload)["cached"] == 0
    assert source(payload)["costs"] == {"available": True, "reason": None}
    assert "opencode: 1 sessions" in result.stdout and "$0.25 est." in result.stdout
    assert stat.S_IMODE(native.runtime.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == (0o700 if p.is_dir() else 0o600) for p in native.runtime.rglob("*"))


@pytest.mark.parametrize("option", ["--opencode-db", "--no-opencode"])
def test_opencode_help_documents_flags_and_environment(native, option):
    result = native.invoke("--help")
    assert option in result.stdout
    assert "OPENCODE_DB" in result.stdout and "XDG_DATA_HOME" in result.stdout
    assert not native.runtime.exists()


@pytest.mark.parametrize("args,reason", [
    (["--opencode-db"], "expected one argument"),
    (["--opencode-db=:memory:"], "file"),
    (["--no-opencode=true"], "ignored explicit argument"),
    (["--no"], "--no-open, --no-claude, --no-opencode"),
    (["--no-op"], "--no-open, --no-opencode"),
    (["--o"], "--offline, --output, --opencode-db"),
])
def test_opencode_invalid_options_and_ambiguity(native, args, reason):
    result = native.invoke(*args)
    assert result.returncode == 2
    assert reason in result.stderr
    assert not native.runtime.exists()


def test_opencode_disabled_and_absent_never_create_runtime(native):
    native.codex.rmdir()
    (native.home / ".local/share/opencode").mkdir(parents=True)
    result = native.build("--no-claude")
    assert result.returncode == 1
    assert "OpenCode" in result.stderr and "opencode.db" in result.stderr
    assert not native.runtime.exists()
    database(native)
    result = native.build("--no-claude", "--no-opencode")
    assert result.returncode == 1
    assert not native.runtime.exists()


def test_opencode_mixed_and_disabled_preserve_other_provider_rows(native):
    native.session()
    native.claude_session()
    assert native.build("--no-opencode").returncode == 0
    before = native.payload()
    database(native)
    assert native.build().returncode == 0
    after = native.payload()
    assert [r for r in after["sessions"] if r["provider"] != "opencode"] == before["sessions"]
    assert source(before)["status"] == "disabled"
    assert len(after["sessions"]) == len(before["sessions"]) + 1


def test_opencode_discovery_primary_sorted_deduplicated_preview_and_narrow_glob(native):
    primary = database(native, "opencode-z.db")
    other = database(native, "opencode-a.db", session="synthetic-other")
    default = database(native)
    preview = database(native, "opencode-next.db", session="synthetic-preview")
    database(native, "unrelated.db", session="synthetic-unrelated")
    native.env["OPENCODE_DB"] = "./opencode-z.db"
    result = native.build()
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    entries = source(payload)["databases"]
    assert [d["path"] for d in entries] == [str(primary), str(other), str(preview), str(default)]
    assert len({d["path"] for d in entries}) == 4
    assert entries[0]["primary"] is True
    assert next(d for d in entries if d["path"] == str(preview))["status"] == "skipped"
    assert {r["id"] for r in payload["sessions"]} == {SESSION, "synthetic-other"}
    assert next(r for r in payload["sessions"] if r["id"] == SESSION)["opencode_database"] == str(primary)
    duplicates = payload["diagnostics"]["opencode_duplicate_sessions"]
    assert len(duplicates) == 1 and duplicates[0]["database"] == str(default)
    assert "opencode_duplicate_sessions=1" in result.stderr
    assert "skipped" in result.stderr and "opencode-next.db" in result.stderr


def test_opencode_explicit_file_selects_only_expanded_path_and_preview_skips(native):
    chosen = database(native)
    database(native, "opencode-a.db", session="synthetic-other")
    native.env.update(OPENCODE_DB="synthetic-ignored.db", XDG_DATA_HOME="synthetic-ignored")
    result = native.build("--opencode-db", "~/.local/share/opencode/./opencode.db")
    assert result.returncode == 0, result.stderr
    assert [d["path"] for d in source(native.payload())["databases"]] == [str(chosen)]
    preview = database(native, "opencode-next.db")
    native.codex.rmdir()
    result = native.build("--no-claude", "--opencode-db", str(preview))
    assert result.returncode == 1


@pytest.mark.parametrize("override", [":memory:", ""])
def test_opencode_environment_primary_suppression_and_invalid_empty(native, override):
    database(native)
    native.env["OPENCODE_DB"] = override
    native.codex.rmdir()
    result = native.build("--no-claude")
    if override == ":memory:":
        assert result.returncode == 1 and not native.runtime.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert source(native.payload())["status"] == "ok"
        assert len(native.payload()["diagnostics"]["opencode_unreadable_databases"]) == 1


def test_opencode_relative_xdg_and_primary_resolve_against_correct_directories(native):
    path = database(native)
    project = Path(__file__).resolve().parents[1]
    native.env["XDG_DATA_HOME"] = os.path.relpath(path.parent.parent, project)
    native.env["OPENCODE_DB"] = "./opencode.db"
    assert native.build().returncode == 0
    assert source(native.payload())["data_dir"] == str(path.parent)
    assert source(native.payload())["databases"][0]["path"] == str(path)
    assert native.build("--opencode-db", os.path.relpath(path, project)).returncode == 0
    assert source(native.payload())["databases"][0]["path"] == str(path)


@pytest.mark.parametrize("fault,expected", [("schema", "unsupported"), ("unreadable", "unreadable")])
def test_opencode_diagnostic_only_source_builds(native, fault, expected):
    path = database(native)
    if fault == "schema":
        with sqlite3.connect(path) as db:
            db.execute("DROP TABLE session_message")
    else:
        path.write_text("Synthetic invalid SQLite bytes")
    native.codex.rmdir()
    result = native.build("--no-claude")
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    assert source(payload)["status"] == expected
    key = "opencode_schema_errors" if fault == "schema" else "opencode_unreadable_databases"
    assert payload["diagnostics"][key][0]["path"] == str(path)
    assert payload["diagnostics"][key][0]["reason"]
    assert key + "=1" in result.stderr
    assert expected in result.stdout


def test_opencode_partial_failure_and_newer_schema_details_remain_visible(native):
    good = database(native)
    bad = database(native, "opencode-bad.db", session="synthetic-bad")
    bad.write_text("Synthetic broken database")
    with sqlite3.connect(good) as db:
        db.execute("INSERT INTO migration VALUES (?,?)", ("99999999999999_synthetic_future", CLOCK))
    result = native.build()
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    assert source(payload)["status"] == "ok"
    assert len(payload["sessions"]) == 1
    assert payload["diagnostics"]["opencode_untested_schema"] == [{"path": str(good), "latest_migration": "99999999999999_synthetic_future"}]
    assert "opencode_unreadable_databases=1" in result.stderr
    assert "opencode_untested_schema=1" in result.stderr
    assert "opencode-bad.db" in result.stderr


@pytest.mark.parametrize("session_archive,project_archive,reason", [(CLOCK, CLOCK, "session"), (None, CLOCK, "project"), (CLOCK, None, "session")])
def test_opencode_archive_reason_precedence(native, session_archive, project_archive, reason):
    database(native, archived=session_archive, project_archived=project_archive)
    assert native.build().returncode == 0
    payload = native.payload()
    row, = payload["sessions"]
    assert row["archived"] is True and row["archive_reason"] == reason
    assert source(payload)["archived"] == 1
    assert row["capabilities"]["continue_in_cli"] is False


def test_opencode_credentials_never_enter_page_or_runtime(native):
    path = database(native)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE credential (value TEXT)")
        db.execute("INSERT INTO credential VALUES ('SYNTHETIC_CREDENTIAL_CANARY_NEVER_REAL')")
        db.execute("INSERT INTO kv VALUES ('synthetic-private-setting','SYNTHETIC_KV_CANARY_NEVER_REAL',0,0)")
    assert native.build().returncode == 0
    for file in native.runtime.rglob("*"):
        if file.is_file():
            assert b"SYNTHETIC_CREDENTIAL_CANARY_NEVER_REAL" not in file.read_bytes()
            assert b"SYNTHETIC_KV_CANARY_NEVER_REAL" not in file.read_bytes()


@pytest.mark.parametrize("wal", [False, True])
def test_opencode_source_database_and_wal_unchanged(native, wal):
    path = database(native)
    with sqlite3.connect(path) as db:
        if wal:
            assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
            db.execute("UPDATE session_v2 SET title='Synthetic WAL title'")
            db.commit()
        files = [path] + ([Path(str(path) + "-wal")] if wal else [])
        before = {p: p.read_bytes() for p in files}
        result = native.build()
        assert result.returncode == 0, result.stderr
        assert len(native.payload()["sessions"]) == 1
        assert {p: p.read_bytes() for p in files} == before


def test_opencode_locked_source_preserves_working_provider(native):
    path = database(native)
    native.claude_session()
    with sqlite3.connect(path) as db:
        db.execute("BEGIN EXCLUSIVE")
        result = native.build()
        assert result.returncode == 0, result.stderr
        assert source(native.payload())["status"] == "unreadable"
        assert {r["provider"] for r in native.payload()["sessions"]} == {"claude"}


@pytest.mark.parametrize("rebuild", [False, True])
def test_opencode_only_never_opens_codex_cache(native, rebuild):
    database(native)
    native.codex.rmdir()
    cache = native.runtime / "cache-native"
    cache.mkdir(parents=True)
    canary = cache / "SYNTHETIC-CACHE-CANARY"
    canary.write_text("Synthetic unopened cache")
    canary.chmod(0o640)
    before = canary.read_bytes(), stat.S_IMODE(canary.stat().st_mode)
    result = native.build(*(["--rebuild"] if rebuild else []))
    assert result.returncode == 0, result.stderr
    assert (canary.read_bytes(), stat.S_IMODE(canary.stat().st_mode)) == before
    assert [p.name for p in cache.iterdir()] == [canary.name]


def test_opencode_cross_session_cost_overflow_is_unavailable_finite_cli(native):
    database(native, cost=1.2e308)
    database(native, "opencode-other.db", session="synthetic-other", cost=1.2e308)
    result = native.build()
    assert result.returncode == 0, result.stderr
    line, = [line for line in result.stdout.splitlines() if line.startswith("colophon: opencode:")]
    assert "costs unavailable" in line
    assert "inf" not in line.lower() and "nan" not in line.lower()
    assert all(r["own_usage"]["cost_usd"] == 1.2e308 for r in native.payload()["sessions"])


def test_sandbox_opencode_paths_denied():
    check = ctypes.CDLL(None).sandbox_check
    check.restype = ctypes.c_int
    check.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    home = Path(os.environ["COLOPHON_TEST_REAL_HOME"])
    selected = os.environ.get("COLOPHON_TEST_POLICY_TARGET")
    targets = [selected] if selected else [".local/share/opencode", ".local/state/opencode", ".config/opencode", ".cache/opencode", "Library/Application Support/ai.opencode.desktop"]
    for target in targets:
        for operation in (b"file-read-data", b"file-write-create"):
            for path in (home / target, home / target / "synthetic-nonexistent-child"):
                result = check(os.getpid(), operation, 1, os.fsencode(path))
                assert result >= 0, "sandbox policy evaluation failed"
                assert result != 0, f"OpenCode source protection missing: {target} {operation!r}"


def test_opencode_contextual_diagnostics_count_maps_residuals_and_missing_cost(native):
    path = database(native, tokens=30, cost=.5)
    with sqlite3.connect(path) as db:
        # Known request remains ten tokens; rollup retains removed usage.
        value = json.loads(db.execute("SELECT data FROM session_message WHERE type='assistant'").fetchone()[0])
        value.update(tokens={"input": 10, "output": 0}, cost=.25)
        value["content"].append({"type": "synthetic-future-part"})
        db.execute("UPDATE session_message SET data=? WHERE type='assistant'", (json.dumps(value),))
        message(db, SESSION, "synthetic-future-message", 3, {})
        message(db, SESSION, "assistant", 4, {"content": [], "cost": .1})
        message(db, SESSION, "assistant", 5, {"content": [], "tokens": {"input": -1, "output": 0}})
        db.execute("INSERT INTO session_message VALUES ('synthetic-malformed',?,'user',6,0,0,'{')", (SESSION,))
    result = native.build()
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    d = payload["diagnostics"]
    assert d["opencode_unknown_message_types"] == {"synthetic-future-message": 1}
    assert d["opencode_unknown_content_types"] == {"synthetic-future-part": 1}
    assert d["opencode_requests_without_usage"] == {"opencode/unattributed": 2}
    assert d["opencode_malformed_messages"] == 1
    assert d["opencode_cost_without_tokens"] == 1
    assert len(d["opencode_invalid_numbers"]) == 1
    assert d["opencode_invalid_numbers"][0]["session"] == SESSION
    assert d["opencode_invalid_numbers"][0]["database"] == str(path)
    residual = d["opencode_rollup_residuals"][SESSION]
    assert residual["input"] == 20
    assert residual["cost"] == pytest.approx(.15)
    assert residual["date"] == CLOCK and residual["date_basis"] == "session_start"
    assert source(payload)["requests"] == 3
    assert source(payload)["requests_without_usage"] == 2
    assert source(payload)["residual_sessions"] == 1
    for key, count in [("opencode_unknown_message_types", 1), ("opencode_unknown_content_types", 1), ("opencode_requests_without_usage", 2), ("opencode_malformed_messages", 1), ("opencode_cost_without_tokens", 1), ("opencode_rollup_residuals", 1), ("opencode_invalid_numbers", 1)]:
        assert f"{key}={count}" in result.stderr


def test_opencode_shortfalls_and_aggregate_invalid_contexts(native):
    path = database(native, tokens=2, cost=.1)
    with sqlite3.connect(path) as db:
        value = json.loads(db.execute("SELECT data FROM session_message WHERE type='assistant'").fetchone()[0])
        value.update(tokens={"input": 10, "output": 3}, cost=.25)
        db.execute("UPDATE session_message SET data=? WHERE type='assistant'", (json.dumps(value),))
    result = native.build()
    assert result.returncode == 0, result.stderr
    d = native.payload()["diagnostics"]
    shortfall, = d["opencode_rollup_shortfalls"]
    assert shortfall["session"] == SESSION and shortfall["database"] == str(path)
    assert shortfall["input"] == 8 and shortfall["output"] == 3
    assert shortfall["cost"] == pytest.approx(.15) and shortfall["reason"]
    assert "opencode_rollup_shortfalls=1" in result.stderr
    with sqlite3.connect(path) as db:
        value["cost"] = 1.2e308
        db.execute("UPDATE session_message SET data=? WHERE type='assistant'", (json.dumps(value),))
        message(db, SESSION, "assistant", 3, {**value, "cost": 1.2e308})
    result = native.build()
    assert result.returncode == 0, result.stderr
    assert any(d["reason"] == "message cost sum overflow" and d["session"] == SESSION for d in native.payload()["diagnostics"]["opencode_invalid_numbers"])
    assert native.payload()["sessions"][0]["own_usage"]["cost_usd"] is None


def test_opencode_collisions_are_excluded_from_display_and_usage_counters(native):
    native.claude_session(name=SESSION)
    path = database(native)
    result = native.build()
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    assert {r["provider"] for r in payload["sessions"]} == {"claude"}
    assert source(payload)["sessions"] == source(payload)["requests"] == 0
    collision, = payload["diagnostics"]["opencode_session_id_collisions"]
    assert collision["session"] == SESSION and collision["database"] == str(path) and collision["reason"]
    assert "opencode_session_id_collisions=1" in result.stderr
    assert "opencode: 0 sessions" in result.stdout


def test_opencode_orphans_and_inherited_messages_keep_context_and_accepted_counts(native):
    path = database(native, parent="synthetic-missing-parent")
    fork = database(native, "opencode-fork.db", session="synthetic-fork")
    with sqlite3.connect(fork) as db:
        db.execute("UPDATE session_v2 SET fork_session_id=?,time_created=?", (SESSION, CLOCK + 10000))
    result = native.build()
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    orphan, = payload["diagnostics"]["opencode_orphaned_subagents"]
    assert orphan["session"] == SESSION and orphan["database"] == str(path) and orphan["reason"]
    assert payload["diagnostics"]["opencode_inherited_messages"] == 1
    assert source(payload)["sessions"] == 1 and source(payload)["subagents"] == 1
    assert source(payload)["requests"] == 1
    assert "opencode_inherited_messages=1" in result.stderr
    assert "opencode: 1 sessions · 1 subagents" in result.stdout


def test_opencode_missing_unit_cost_stays_unpriced_with_available_engine(native):
    path = database(native)
    with sqlite3.connect(path) as db:
        value = json.loads(db.execute("SELECT data FROM session_message WHERE type='assistant'").fetchone()[0])
        del value["cost"]
        db.execute("UPDATE session_message SET data=? WHERE type='assistant'", (json.dumps(value),))
        db.execute("UPDATE session_v2 SET cost=0")
    result = native.build()
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    assert source(payload)["costs"] == {"available": True, "reason": None}
    assert payload["sessions"][0]["own_usage"]["cost_usd"] is None
    assert "costs unavailable" in next(line for line in result.stdout.splitlines() if line.startswith("colophon: opencode:"))


def test_opencode_removed_messages_and_deleted_sessions_are_reread_without_cache(native):
    path = database(native)
    assert native.build().returncode == 0
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM session_message WHERE type='assistant'")
    assert native.build().returncode == 0
    payload = native.payload()
    assert source(payload)["requests"] == 0
    assert source(payload)["residual_sessions"] == 1
    assert payload["sessions"][0]["own_usage"]["input"] == 10
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM session_v2")
    assert native.build("--rebuild").returncode == 0
    assert native.payload()["sessions"] == []


def test_opencode_discovery_directory_error_is_present_and_sanitizes_cli_lines(native):
    location = native.home / "synthetic-data\nline"
    location.write_text("Synthetic regular file where a directory was expected")
    native.env["XDG_DATA_HOME"] = str(location)
    native.codex.rmdir()
    result = native.build("--no-claude")
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    assert source(payload)["status"] == "unreadable"
    assert payload["diagnostics"]["opencode_unreadable_databases"]
    assert all(line.startswith("colophon:") for line in result.stderr.splitlines())


def test_opencode_disabled_never_reads_invalid_override(native):
    native.env.update(OPENCODE_DB="", XDG_DATA_HOME="/synthetic/nonexistent-data")
    assert native.build("--no-opencode").returncode == 0
    payload = native.payload()
    assert source(payload)["status"] == "disabled"
    assert source(payload)["databases"] == []
    assert payload["diagnostics"]["opencode_unreadable_databases"] == []


def test_opencode_memory_primary_still_reads_regular_siblings(native):
    database(native)
    sibling = database(native, "opencode-.db", session="synthetic-sibling")
    (sibling.parent / "opencode-directory.db").mkdir()
    native.env["OPENCODE_DB"] = ":memory:"
    native.codex.rmdir()
    result = native.build("--no-claude")
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    assert [r["id"] for r in payload["sessions"]] == ["synthetic-sibling"]
    assert [d["path"] for d in source(payload)["databases"]] == [str(sibling)]


def test_opencode_missing_explicit_file_is_absent_and_never_created(native):
    missing = native.home / "synthetic-missing.db"
    result = native.build("--opencode-db=" + str(missing))
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    assert source(payload)["status"] == "absent"
    assert source(payload)["databases"][0]["status"] == "absent"
    assert not missing.exists()
    assert payload["meta"]["version"] == "0.4.0"


def test_opencode_status_prefers_structural_rejection_over_unreadable(native):
    path = database(native)
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE session_message")
    bad = database(native, "opencode-bad.db", session="synthetic-bad")
    bad.write_text("Synthetic unreadable database")
    assert native.build().returncode == 0
    payload = native.payload()
    assert source(payload)["status"] == "unsupported"
    assert len(payload["diagnostics"]["opencode_schema_errors"]) == 1
    assert len(payload["diagnostics"]["opencode_unreadable_databases"]) == 1
