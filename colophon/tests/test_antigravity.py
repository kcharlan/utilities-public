"""Invented Antigravity databases: never use an installed session store."""
import sqlite3
import json
import ctypes
import os
import stat
import subprocess
from pathlib import Path
import pytest
from helpers import proto_field

ID = "00000000-0000-4000-8000-000000000001"
SCHEMA = """CREATE TABLE trajectory_meta(trajectory_id TEXT,cascade_id TEXT,trajectory_type INTEGER,source INTEGER);
CREATE TABLE trajectory_metadata_blob(id INTEGER,data BLOB);
CREATE TABLE steps(idx INTEGER,step_type INTEGER,status INTEGER,metadata BLOB,step_payload BLOB,step_format INTEGER);
CREATE TABLE gen_metadata(idx INTEGER,data BLOB);
"""

def database(native, surface="antigravity", identity=ID):
    path = native.home / ".gemini" / surface / "conversations" / (identity + ".db")
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO trajectory_meta VALUES (?,?,1,1)", (identity, identity))
    return path

def cached_pricing(native, unknown=True, model="gemini-pro-default-high"):
    """Invented cached rates through the real offline catalog/DB path."""
    path = database(native)
    catalog = {"openai": {"models": {}}, "google": {"models": {"gemini-3.1-pro-preview": {
        "id": "gemini-3.1-pro-preview", "cost": {"input": 11, "output": 17,
        "context_over_200k": {"input":23},
        "tiers": [{"tier": {"type": "context", "size": 41}, "input": 23}]}}}}}
    native.runtime.mkdir(exist_ok=True)
    (native.runtime / "pricing-cache.json").write_text(json.dumps({
        "schema": 1, "url": native.env["COLOPHON_PRICING_URL"], "etag": "synthetic-cached",
        "fetched_at_ms": 1, "catalog": catalog}))
    prompt = proto_field(19, proto_field(2, b"Synthetic priced Antigravity request"))
    metadata = proto_field(1, proto_field(1, 1767355200)) + proto_field(8, proto_field(1, 1767355202))
    usage = b"".join(proto_field(k, v) for k,v in [(2,42),(5,3),(4,5),(3,7),(9,2),(10,5)])
    chat = proto_field(4, usage) + proto_field(19, model)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO steps VALUES(0,14,3,?,?,0)", (metadata,prompt))
        db.execute("INSERT INTO gen_metadata VALUES(0,?)", (proto_field(1,chat)+proto_field(2,0),))
        if unknown:
            chat = proto_field(4,proto_field(2,2)+proto_field(3,3))+proto_field(19,"synthetic-unpriced-high")
            db.execute("INSERT INTO gen_metadata VALUES(1,?)", (proto_field(1,chat)+proto_field(2,0),))
    return path

def test_antigravity_cached_pricing(native):
    cached_pricing(native)
    result = native.build("--no-claude", "--no-opencode")
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    row, = payload["sessions"]
    assert row["own_usage"]["input"] == 52
    assert row["own_usage"]["output"] == 10
    assert row["own_usage"]["cached_input"] == 3
    assert row["own_usage"]["cache_write"] == 5
    assert row["own_usage"]["reasoning"] == 2
    assert row["own_usage"]["unpriced_tokens"] == 5
    assert row["own_usage"]["cost_usd"] is None
    priced = next(b for b in row["buckets"] if b[1] == "gemini-3.1-pro-preview")
    assert priced[8] == pytest.approx(.001173)
    assert payload["meta"]["sources"]["antigravity"]["costs"] == {"available":True,"reason":None}
    assert "antigravity:bundled/synthetic-unpriced" in json.dumps(payload["diagnostics"])

@pytest.mark.parametrize("model", ["gemini-3.1-pro-high-thinking", "gemini-3.1-pro-low-thinking",
    "gemini-3.1-pro-high-tiered", "gemini-3.1-pro-low-tiered",
    "gemini-3.1-pro-high-low", "gemini-3.1-pro-low-low"])
def test_antigravity_cached_pricing_effort_alias_after_routing(native, model):
    cached_pricing(native, unknown=False, model=model)
    result = native.build("--no-claude", "--no-opencode")
    assert result.returncode == 0, result.stderr
    row, = native.payload()["sessions"]
    assert row["own_usage"]["unpriced_tokens"] == 0
    assert row["own_usage"]["cost_usd"] == pytest.approx(.001173)
    assert row["buckets"][0][1] == "gemini-3.1-pro-preview"

@pytest.mark.parametrize("key", ["synthetic-opaque-key", 7, None])
def test_antigravity_trajectory_key_types_preserve_workspace_creation_and_parent(native, key):
    child_id = "00000000-0000-4000-8000-000000000002"
    parent_path = database(native)
    child_path = database(native, identity=child_id)
    workspace = proto_field(1,"file:///SYNTHETIC-NONEXISTENT-KEY-WORKSPACE") + proto_field(2,"file:///SYNTHETIC-NONEXISTENT-KEY-GIT-ROOT")
    trajectory = proto_field(1,workspace) + proto_field(2,proto_field(1,1767355200)) + proto_field(5,ID)
    with sqlite3.connect(child_path) as db:
        # The column is deliberately affinity-free: preserve actual SQLite
        # TEXT/INTEGER/NULL states rather than having SQLite coerce the fixture.
        db.executescript("DROP TABLE trajectory_metadata_blob; CREATE TABLE trajectory_metadata_blob(id,data BLOB)")
        db.execute("INSERT INTO trajectory_metadata_blob VALUES (?,?)", (key,trajectory))
    assert parent_path.exists()
    result = native.build("--no-claude", "--no-opencode")
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    parent, = payload["sessions"]
    child = payload["subagents"][child_id]
    assert parent["id"] == ID
    assert parent["children"] == [child_id]
    assert child["parent_id"] == ID
    assert child["cwd"] == "/SYNTHETIC-NONEXISTENT-KEY-WORKSPACE"
    assert child["git_root"] == "/SYNTHETIC-NONEXISTENT-KEY-GIT-ROOT"
    assert child["start_ms"] == 1767355200000
    assert payload["diagnostics"]["antigravity_malformed_rows"] == 0

@pytest.mark.parametrize("timestamp", [b"\x80", proto_field(1,b"Synthetic wrong wire")])
def test_antigravity_malformed_chat_start_timestamp_isolates_generator(native, timestamp):
    path = database(native)
    bad_chat = proto_field(4,proto_field(2,5)) + proto_field(9,proto_field(4,timestamp))
    valid_chat = proto_field(4,proto_field(2,7)) + proto_field(9,proto_field(4,proto_field(1,1767355200)))
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO trajectory_metadata_blob VALUES(1,?)", (proto_field(2,proto_field(1,1767355200)),))
        db.executemany("INSERT INTO gen_metadata VALUES(?,?)", [(1,proto_field(1,bad_chat)),(2,proto_field(1,valid_chat))])
    result = native.build("--no-claude","--no-opencode")
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    row, = payload["sessions"]
    assert payload["diagnostics"]["antigravity_malformed_blobs"] == 1
    assert payload["diagnostics"]["antigravity_unknown_clocks"] == 0
    assert row["own_usage"]["input"] == 7
    assert len(row["buckets"]) == 1
    assert row["buckets"][0][0] == 1963728
    assert row["buckets"][0][3] == 7

@pytest.mark.parametrize("created, bucket", [(proto_field(4,b""),0),
    (proto_field(4,proto_field(1,0)+proto_field(2,0)),0),
    (proto_field(4,proto_field(1,1767355200))+proto_field(4,proto_field(2,500000000)),1963728)])
def test_antigravity_chat_start_empty_default_and_split_clocks(native, created, bucket):
    path = database(native)
    chat = proto_field(4,proto_field(2,5)) + proto_field(9,created)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO gen_metadata VALUES(1,?)", (proto_field(1,chat),))
    result = native.build("--no-claude","--no-opencode")
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    row, = payload["sessions"]
    assert payload["diagnostics"]["antigravity_malformed_blobs"] == 0
    assert payload["diagnostics"]["antigravity_unknown_clocks"] == 0
    assert row["own_usage"]["input"] == 5
    assert row["buckets"][0][0] == bucket

def test_antigravity_corpus_acceptance(native):
    native.codex.rmdir()
    path = database(native)
    result = native.build("--no-claude", "--no-opencode")
    assert result.returncode == 0, result.stderr
    source = native.payload()["meta"]["sources"]["antigravity"]
    assert source["status"] == "ok"
    assert source["databases"][0]["path"] == str(path)
    assert source["databases"][0]["accepted_sessions"] == 1
    assert source["databases"][0]["surface"] == "app"
    rows = native.payload()["sessions"]
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == ID
    assert row["provider"] == "antigravity"
    assert row["antigravity_surface"] == "app"
    assert row["turns"] == []
    assert row["capabilities"] == {"copy_session_id": True, "copy_log_path": False,
                                   "open_in_codex": False, "continue_in_cli": False}
    assert native.build().returncode == 0
    assert native.payload()["sessions"][0]["turns"] == []
    assert "antigravity: 1 sessions" in result.stdout
    assert "1 databases (1 parsed" in result.stdout
    assert native.runtime.stat().st_mode & 0o777 == 0o700

def source(native):
    return native.payload()["meta"]["sources"]["antigravity"]

@pytest.mark.parametrize("disabled", [False, True])
def test_antigravity_absent_disabled_never_initializes_runtime(native, disabled):
    native.codex.rmdir()
    args = ["--no-claude", "--no-opencode"]
    if disabled:
        database(native)
        args += ["--no-antigravity", "--antigravity-home", "~synthetic-invalid-user/no-source"]
    result = native.build(*args)
    assert result.returncode == 1
    assert "no readable sources" in result.stderr
    assert "Antigravity" in result.stderr
    assert not native.runtime.exists()

def test_antigravity_mixed_disabled_and_environment_names_only(native):
    native.session()
    database(native)
    for name in ("ANTIGRAVITY_GEMINI_DIR", "ANTIGRAVITY_APP_DATA_DIR", "JETSKI_APP_DATA_DIR"):
        native.env[name] = "SYNTHETIC-PRIVATE-ENVIRONMENT-CANARY"
    result = native.build()
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    assert source(native)["sessions"] == 1
    assert len(payload["sessions"]) == 2
    assert source(native)["ignored_environment"] == ["ANTIGRAVITY_GEMINI_DIR", "ANTIGRAVITY_APP_DATA_DIR", "JETSKI_APP_DATA_DIR"]
    assert "use --antigravity-home PATH" in result.stderr
    assert "SYNTHETIC-PRIVATE-ENVIRONMENT-CANARY" not in native.page.read_text() + result.stdout + result.stderr
    assert native.build("--no-antigravity").returncode == 0
    assert source(native)["status"] == "disabled"
    assert source(native)["databases"] == []
    assert native.payload()["sessions"] == [row for row in payload["sessions"] if row["provider"] != "antigravity"]


@pytest.mark.parametrize('surface,label', [('antigravity','app'), ('antigravity-cli','cli'), ('antigravity-ide','ide')])
@pytest.mark.parametrize('archive', ['annotation', 'summary', 'default-false'])
def test_antigravity_corpus_archive_projection_and_summary(native, surface, label, archive):
    path = database(native, surface)
    annotations = path.parent.parent / 'annotations'
    annotations.mkdir()
    if archive != 'summary':
        (annotations / (ID + '.pbtxt')).write_text('title: "Synthetic annotation"' + (' archived: true' if archive == 'annotation' else ''))
    with sqlite3.connect(path.parent.parent / 'conversation_summaries.db') as db:
        db.execute('CREATE TABLE conversation_summaries(conversation_id TEXT, title TEXT, raw_summary BLOB)')
        db.execute('INSERT INTO conversation_summaries VALUES(?,?,?)', (ID, 'Synthetic summary', proto_field(15, proto_field(4, 1))))
    metadata = proto_field(1, proto_field(1, 1767355200))
    prompt = proto_field(19, proto_field(2, 'Synthetic corpus prompt'))
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO steps VALUES(0,14,3,?,?,0)', (metadata, prompt))
    result = native.build('--no-claude', '--no-opencode')
    assert result.returncode == 0, result.stderr
    row, = native.payload()['sessions']
    assert row['antigravity_surface'] == label
    assert row['title_full'] == ('Synthetic summary' if archive == 'summary' else 'Synthetic annotation')
    assert row['title_source'] == 'antigravity_title'
    assert row['archived'] == (archive != 'default-false')
    assert row['archive_reason'] == ('session' if archive != 'default-false' else None)
    assert len(row['turns']) == 1
    assert row['turns'][0]['end_ms'] is None
    assert source(native)['sessions'] == 1
    assert source(native)['subagents'] == 0
    assert 'antigravity: 1 sessions · 0 subagents' in result.stdout
    assert native.build('--no-claude', '--no-opencode', '--rebuild').returncode == 0
    assert native.payload()['sessions'] == [row]

@pytest.mark.parametrize("args,reason", [
    (["--antigravity-home"], "expected one argument"),
    (["--no-antigravity=true"], "ignored explicit argument"),
    (["--no"], "--no-open, --no-claude, --no-opencode, --no-antigravity"),
    (["--no-op"], "--no-open, --no-opencode"),
    (["--o"], "--offline, --output, --opencode-db"),
])
def test_antigravity_options_preserve_unique_prefix_parser(native, args, reason):
    result = native.invoke(*args)
    assert result.returncode == 2
    assert reason in result.stderr
    assert not native.runtime.exists()

def test_antigravity_help_and_expanded_relative_home(native):
    result = native.invoke("--help")
    assert result.returncode == 0
    assert 'Codex, Claude Code, OpenCode and Antigravity sessions' in result.stdout
    for value in ("--antigravity-home", "--no-antigravity", "ANTIGRAVITY_GEMINI_DIR", "ANTIGRAVITY_APP_DATA_DIR", "JETSKI_APP_DATA_DIR"):
        assert value in result.stdout
    database(native)
    for root in ("~/.gemini/./", os.path.relpath(native.home / ".gemini", Path.cwd())):
        result = native.build("--antigravity-home", root)
        assert result.returncode == 0, result.stderr
        assert source(native)["sessions"] == 1

def test_antigravity_surface_precedence_legacy_distinct_ids_and_failed_sibling(native):
    app = database(native)
    cli = database(native, "antigravity-cli")
    other = database(native, "antigravity-ide", ID[:-1] + "2")
    for path in (app, cli, other):
        (path.parent / (ID[:-1] + "3.pb")).write_bytes(b"SYNTHETIC-ENCRYPTED-NEVER-DECODE")
        (path.parent / (ID + ".pb")).write_bytes(b"SYNTHETIC-SIBLING-NEVER-DECODE")
    bad = app.parent / (ID[:-1] + "4.db")
    bad.write_bytes(b"SYNTHETIC-BROKEN-SQLITE")
    (app.parent / "synthetic-not-a-uuid.db").write_bytes(b"NEVER-OPEN")
    result = native.build()
    assert result.returncode == 0, result.stderr
    data = source(native)
    assert data["sessions"] == 2
    assert data["legacy_encrypted"] == 1
    assert [d["surface"] for d in data["databases"]] == ["app", "app", "cli", "ide"]
    assert [d["accepted_sessions"] for d in data["databases"]] == [1, 0, 0, 1]
    assert native.payload()["diagnostics"]["antigravity_duplicate_sessions"] == 1
    assert len(native.payload()["diagnostics"]["antigravity_unreadable_databases"]) == 1

@pytest.mark.parametrize("fault,status", [("schema", "unsupported"), ("bytes", "unreadable")])
def test_antigravity_error_only_source_initializes_diagnostics(native, fault, status):
    native.codex.rmdir()
    path = database(native)
    if fault == "schema":
        with sqlite3.connect(path) as db:
            db.execute("DROP TABLE gen_metadata")
    else:
        path.write_bytes(b"SYNTHETIC-NOT-A-DATABASE")
    result = native.build("--no-claude", "--no-opencode")
    assert result.returncode == 0, result.stderr
    assert source(native)["status"] == status
    assert source(native)["sessions"] == 0
    assert status in result.stdout

def test_antigravity_same_surface_archive_default_and_malformed_fallback(native):
    path = database(native)
    annotation = path.parent.parent / "annotations" / (ID + ".pbtxt")
    annotation.parent.mkdir()
    summary = path.parent.parent / "conversation_summaries.db"
    with sqlite3.connect(summary) as db:
        db.execute("CREATE TABLE conversation_summaries(conversation_id,title,raw_summary)")
        db.execute("INSERT INTO conversation_summaries VALUES (?,?,?)", (ID, "Synthetic summary", proto_field(15, proto_field(4, 1))))
    annotation.write_text('title: "Synthetic title"')
    assert native.build().returncode == 0
    assert source(native)["archived"] == 0
    assert native.payload()["diagnostics"]["antigravity_archive_disagreements"] == 1
    annotation.write_text('unknown { text: "quoted }"')
    assert native.build().returncode == 0
    assert source(native)["archived"] == 1
    assert native.payload()["diagnostics"]["antigravity_annotation_errors"] == 1

@pytest.mark.parametrize("wal", [False, True])
def test_antigravity_source_database_wal_and_annotation_unchanged(native, wal):
    path = database(native)
    writer = sqlite3.connect(path)
    if wal:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO steps VALUES(1,1,1,?,?,0)", (b"", b""))
        writer.commit()
    annotation = path.parent.parent / "annotations" / (ID + ".pbtxt")
    annotation.parent.mkdir()
    annotation.write_text('archived: true')
    paths = [path, annotation] + ([Path(str(path) + "-wal")] if wal else [])
    before = {p: (p.read_bytes(), stat.S_IMODE(p.stat().st_mode)) for p in paths}
    try:
        result = native.build()
        assert result.returncode == 0, result.stderr
        assert source(native)["databases"][0]["accepted_steps"] == int(wal)
        assert {p: (p.read_bytes(), stat.S_IMODE(p.stat().st_mode)) for p in paths} == before
    finally:
        writer.close()

def test_antigravity_privacy_contract_never_serializes_unrelated_or_hidden_text(native):
    path = database(native)
    canary = "SYNTHETIC-PRIVATE-CONTENT-NEVER-RENDER"
    for name in ("settings.json", "credentials.json", "oauth_creds.json"):
        (native.home / ".gemini" / name).write_text(canary)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE synthetic_credentials(secret)")
        db.execute("INSERT INTO synthetic_credentials VALUES (?)", (canary,))
        db.execute("INSERT INTO gen_metadata VALUES(1,?)", (proto_field(1, proto_field(1, canary)),))
        db.execute("INSERT INTO steps VALUES(1,1,1,?,?,0)", (b"", proto_field(20, proto_field(3, canary) + proto_field(16, canary))))
    result = native.build()
    assert result.returncode == 0, result.stderr
    assert canary not in result.stdout + result.stderr
    for artifact in native.runtime.rglob("*"):
        if artifact.is_file():
            assert canary.encode() not in artifact.read_bytes()

def test_antigravity_no_database_size_cap_and_no_summary_only_sessions(native):
    path = database(native)
    with sqlite3.connect(path) as db:
        # Large unrelated table must never become a reader cap or selected data.
        db.execute("CREATE TABLE synthetic_unrelated(data)")
        db.execute("INSERT INTO synthetic_unrelated VALUES(zeroblob(70000000))")
    assert native.build().returncode == 0
    assert source(native)["sessions"] == 1
    path.unlink()
    with sqlite3.connect(path.parent.parent / "conversation_summaries.db") as db:
        db.execute("CREATE TABLE conversation_summaries(conversation_id,title)")
        db.execute("INSERT INTO conversation_summaries VALUES(?,?)", (ID, "Synthetic index only"))
    assert native.build().returncode == 0
    assert source(native)["status"] == "absent"
    assert source(native)["sessions"] == 0

def test_antigravity_symlink_database_annotation_and_sidecar_excluded(native):
    path = database(native)
    outside = native.root / "synthetic-outside.db"
    path.rename(outside)
    path.symlink_to(outside)
    assert native.build().returncode == 0
    assert source(native)["sessions"] == 0
    assert "symlink" in source(native)["databases"][0]["reason"]
    path.unlink()
    outside.rename(path)
    sidecar = Path(str(path) + "-wal")
    target = native.root / "synthetic-sidecar"
    target.write_bytes(b"SYNTHETIC-DO-NOT-OPEN")
    sidecar.symlink_to(target)
    assert native.build().returncode == 0
    assert source(native)["sessions"] == 0
    assert "sidecar symlink" in source(native)["databases"][0]["reason"]

def test_sandbox_antigravity_paths_denied():
    check = ctypes.CDLL(None).sandbox_check
    check.restype = ctypes.c_int
    check.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    home = Path(os.environ["COLOPHON_TEST_REAL_HOME"])
    for operation in (b"file-read-data", b"file-write-create"):
        for path in (home / ".gemini", home / ".gemini/synthetic-nonexistent-child"):
            result = check(os.getpid(), operation, 1, os.fsencode(path))
            assert result >= 0, "sandbox policy evaluation failed"
            assert result != 0, "Antigravity source protection missing"

def test_antigravity_annotation_nul_escape_is_malformed_and_falls_back(native):
    path = database(native)
    annotation = path.parent.parent / "annotations" / (ID + ".pbtxt")
    annotation.parent.mkdir()
    annotation.write_bytes(b'title: "Synthetic\\\x00" archived: true')
    result = native.build()
    assert result.returncode == 0, result.stderr
    assert source(native)["archived"] == 0
    assert native.payload()["diagnostics"]["antigravity_annotation_errors"] == 1

@pytest.mark.parametrize("rebuild", [False, True])
def test_antigravity_only_leaves_unopened_codex_cache_unchanged(native, rebuild):
    database(native)
    native.codex.rmdir()
    cache = native.runtime / "cache-native"
    cache.mkdir(parents=True)
    canary = cache / "SYNTHETIC-CACHE-CANARY"
    canary.write_text("Synthetic unopened cache")
    canary.chmod(0o640)
    before = canary.read_bytes(), stat.S_IMODE(canary.stat().st_mode)
    result = native.build("--no-claude", "--no-opencode", *(["--rebuild"] if rebuild else []))
    assert result.returncode == 0, result.stderr
    assert (canary.read_bytes(), stat.S_IMODE(canary.stat().st_mode)) == before
    assert [p.name for p in cache.iterdir()] == [canary.name]

def test_antigravity_locked_database_preserves_good_sibling(native):
    first = database(native)
    other = database(native, identity=ID[:-1] + "2")
    writer = sqlite3.connect(other)
    writer.execute("BEGIN EXCLUSIVE")
    try:
        result = native.build()
        assert result.returncode == 0, result.stderr
        data = source(native)
        assert data["sessions"] == 1
        assert data["databases"][0]["path"] == str(first)
        assert data["databases"][1]["status"] == "unreadable"
    finally:
        writer.rollback()
        writer.close()

def test_antigravity_annotation_and_root_symlink_excluded(native):
    path = database(native)
    target = native.root / "synthetic-annotation.pbtxt"
    target.write_text("archived: true")
    annotation = path.parent.parent / "annotations" / (ID + ".pbtxt")
    annotation.parent.mkdir()
    annotation.symlink_to(target)
    assert native.build().returncode == 0
    assert source(native)["archived"] == 0
    assert native.payload()["diagnostics"]["antigravity_annotation_errors"] == 1
    root = native.home / ".gemini"
    moved = native.root / "synthetic-outside-root"
    root.rename(moved)
    root.symlink_to(moved)
    assert native.build().returncode == 0
    assert source(native)["sessions"] == 0
    assert source(native)["status"] == "unreadable"

def test_antigravity_filename_identity_and_summary_joins_use_exact_case(native):
    lower = "00000000-0000-4000-8000-000000000abc"
    upper = lower.upper()
    app = database(native, identity=lower)
    cli = database(native, "antigravity-cli", identity=upper)
    for path in (app, cli):
        with sqlite3.connect(path.parent.parent / "conversation_summaries.db") as db:
            db.execute("CREATE TABLE conversation_summaries(conversation_id COLLATE NOCASE,title,raw_summary)")
            db.execute("INSERT INTO conversation_summaries VALUES(?,?,?)", (lower, "Synthetic exact-case summary", proto_field(15, proto_field(4, 1))))
    result = native.build()
    assert result.returncode == 0, result.stderr
    assert source(native)["sessions"] == 2
    assert source(native)["archived"] == 1
    assert native.payload()["diagnostics"]["antigravity_duplicate_sessions"] == 0

def test_antigravity_summary_fifo_is_diagnosed_without_opening(native):
    path = database(native)
    summary = path.parent.parent / "conversation_summaries.db"
    os.mkfifo(summary)
    result = subprocess.run([str(native.binary), "--codex-home", str(native.codex),
                             "--offline", "--no-open"], env=native.env,
                            text=True, capture_output=True, timeout=2)
    assert result.returncode == 0, result.stderr
    assert source(native)["sessions"] == 1
    diagnostic, = native.payload()["diagnostics"]["antigravity_source_diagnostics"]
    assert diagnostic["context"] == "conversation_summaries"
    assert "regular file" in diagnostic["reason"]

@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
@pytest.mark.parametrize("kind", ["fifo", "directory"])
@pytest.mark.parametrize("summary", [False, True])
def test_antigravity_nonregular_sidecar_rejected_before_sqlite_open(native, suffix, kind, summary):
    path = database(native)
    good = database(native, identity=ID[:-1] + "2")
    if summary:
        path = path.parent.parent / "conversation_summaries.db"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE conversation_summaries(conversation_id,title)")
    sidecar = Path(str(path) + suffix)
    if kind == "fifo":
        os.mkfifo(sidecar)
    else:
        sidecar.mkdir()
    result = subprocess.run([str(native.binary), "--codex-home", str(native.codex),
                             "--offline", "--no-open"], env=native.env,
                            text=True, capture_output=True, timeout=2)
    assert result.returncode == 0, result.stderr
    data = source(native)
    assert data["databases"][1]["path"] == str(good)
    assert data["databases"][1]["accepted_sessions"] == 1
    if summary:
        assert data["sessions"] == 2
        diagnostics = native.payload()["diagnostics"]["antigravity_source_diagnostics"]
        assert len(diagnostics) == 2
        assert all(d["context"] == "conversation_summaries" and "sidecar is not a regular file" in d["reason"] for d in diagnostics)
    else:
        assert data["sessions"] == 1
        assert data["databases"][0]["status"] == "unreadable"
        assert "sidecar is not a regular file" in data["databases"][0]["reason"]

@pytest.mark.parametrize("later,archived", [(proto_field(1, "Synthetic"), 1), (proto_field(4, 0), 0), (b"", 1)])
def test_antigravity_summary_singular_annotations_merge(native, later, archived):
    path = database(native)
    with sqlite3.connect(path.parent.parent / "conversation_summaries.db") as db:
        db.execute("CREATE TABLE conversation_summaries(conversation_id,title,raw_summary)")
        db.execute("INSERT INTO conversation_summaries VALUES (?,?,?)", (ID, "Synthetic merged summary", proto_field(15, proto_field(4, 1)) + proto_field(15, later)))
    result = native.build()
    assert result.returncode == 0, result.stderr
    assert source(native)["archived"] == archived
    assert native.payload()["diagnostics"]["antigravity_source_diagnostics"] == []
    annotation = path.parent.parent / "annotations" / (ID + ".pbtxt")
    annotation.parent.mkdir()
    annotation.write_text("archived: false")
    assert native.build().returncode == 0
    assert source(native)["archived"] == 0
    assert native.payload()["diagnostics"]["antigravity_archive_disagreements"] == archived

@pytest.mark.parametrize("bad", ["synthetic-enum", 1.5, b"SYNTHETIC-ENUM"])
def test_antigravity_malformed_optional_enum_keeps_indexed_step(native, bad):
    path = database(native)
    metadata = proto_field(9, proto_field(2, 9))
    payload = proto_field(19, proto_field(1, "Synthetic request"))
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO steps VALUES (1,?,NULL,?,?,0)", (bad, metadata, payload))
        db.execute("INSERT INTO steps VALUES (?,1,1,?,?,0)", (bad, metadata, payload))
    result = native.build()
    assert result.returncode == 0, result.stderr
    assert source(native)["databases"][0]["accepted_steps"] == 1
    assert native.payload()["diagnostics"]["antigravity_malformed_rows"] == 2
