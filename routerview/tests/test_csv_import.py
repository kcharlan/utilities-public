import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import ASGISyncClient, load_launcher


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "routerview"


def load_module(monkeypatch, runtime_home: Path):
    monkeypatch.setenv("ROUTERVIEW_HOME", str(runtime_home))
    return load_launcher(SCRIPT_PATH)


def build_client(module, tmp_path: Path):
    db_path = tmp_path / "routerview.db"
    module.init_database(str(db_path))
    module._db_path = str(db_path)

    return ASGISyncClient(module.app), db_path


def test_csv_import_reimport_counts_duplicates_as_skipped(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path / "runtime_home")
    client, db_path = build_client(module, tmp_path)
    csv_text = """generation_id,created_at,model_permaslug,provider_name,api_key_name,app_name,tokens_prompt,tokens_completion,tokens_reasoning,tokens_cached,cost_total,cost_cache,cost_web_search,cost_file_processing,generation_time_ms,finish_reason_normalized,streamed,cancelled,num_search_results,user,time_to_first_token_ms
gen-a,2026-04-13T10:00:00Z,openai/gpt-4o-mini,OpenAI,Primary,Test App,10,20,3,1,0.12,0.01,0.00,0.00,123,stop,true,false,0,user-1,50
gen-b,2026-04-13T11:00:00Z,anthropic/claude-3.7-sonnet,Anthropic,Primary,Test App,15,25,4,2,0.34,0.02,0.00,0.00,234,stop,false,false,1,user-2,80
"""

    first = client.post(
        "/api/import/csv",
        files={"file": ("openrouter_activity.csv", csv_text, "text/csv")},
    )
    assert first.status_code == 200
    assert first.json() == {"status": "ok", "inserted": 2, "skipped": 0}

    second = client.post(
        "/api/import/csv",
        files={"file": ("openrouter_activity.csv", csv_text, "text/csv")},
    )
    assert second.status_code == 200
    assert second.json() == {"status": "ok", "inserted": 0, "skipped": 2}

    conn = sqlite3.connect(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM generations").fetchone()[0]
    finally:
        conn.close()
    assert total == 2


_BASE_CSV_COLUMNS = (
    "generation_id,created_at,model_permaslug,provider_name,api_key_name,app_name,"
    "tokens_prompt,tokens_completion,tokens_reasoning,tokens_cached,cost_total,"
    "cost_cache,cost_web_search,cost_file_processing,generation_time_ms,"
    "finish_reason_normalized,streamed,cancelled,num_search_results,user,"
    "time_to_first_token_ms"
)


def _csv(row: str) -> str:
    return _BASE_CSV_COLUMNS + "\n" + row + "\n"


def test_csv_import_parses_naive_created_at_as_utc(monkeypatch, tmp_path):
    """OpenRouter exports naive timestamps in UTC. The server must store them
    verbatim as UTC, regardless of where the client lives."""
    module = load_module(monkeypatch, tmp_path / "runtime_home")
    client, db_path = build_client(module, tmp_path)
    # gen-1776081900 decodes to 2026-04-13 12:05:00 UTC; match the CSV string.
    row = "gen-1776081900-aaa,2026-04-13 12:05:00,openai/gpt-5.4-mini,OpenAI,Primary,App,10,20,3,1,0.12,0.01,0,0,123,stop,true,false,0,u,50"

    r = client.post("/api/import/csv",
        files={"file": ("openrouter_activity.csv", _csv(row), "text/csv")})
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "inserted": 1, "skipped": 0}

    conn = sqlite3.connect(db_path)
    try:
        created_at, created_date, created_hour = conn.execute(
            "SELECT created_at, created_date, created_hour FROM generations WHERE id='gen-1776081900-aaa'"
        ).fetchone()
    finally:
        conn.close()
    assert created_at.startswith("2026-04-13T12:05:00")
    assert created_at.endswith("+00:00")
    assert created_date == "2026-04-13"
    assert created_hour == 12


def test_csv_import_recovers_utc_from_gen_id_epoch_when_timestamp_diverges(monkeypatch, tmp_path):
    """If the CSV timestamp is shifted from the embedded gen-ID epoch (e.g. an
    export bug or legacy local-time export), the server must recover UTC from
    the gen-ID."""
    module = load_module(monkeypatch, tmp_path / "runtime_home")
    client, db_path = build_client(module, tmp_path)
    # gen-1776081900 → 2026-04-13 12:05:00 UTC. Feed a CSV value shifted +4h.
    row = "gen-1776081900-bbb,2026-04-13 16:05:00,openai/gpt-5.4-mini,OpenAI,Primary,App,10,20,3,1,0.12,0.01,0,0,123,stop,true,false,0,u,50"

    r = client.post("/api/import/csv",
        files={"file": ("openrouter_activity.csv", _csv(row), "text/csv")})
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "inserted": 1, "skipped": 0}

    conn = sqlite3.connect(db_path)
    try:
        created_at, created_hour = conn.execute(
            "SELECT created_at, created_hour FROM generations WHERE id='gen-1776081900-bbb'"
        ).fetchone()
    finally:
        conn.close()
    assert created_at.startswith("2026-04-13T12:05:00")
    assert created_hour == 12


def test_csv_import_honors_explicit_timezone_offset(monkeypatch, tmp_path):
    """An explicit offset/Z in the CSV value wins over everything else."""
    module = load_module(monkeypatch, tmp_path / "runtime_home")
    client, db_path = build_client(module, tmp_path)
    row = "gen-explicit,2026-04-13T14:00:00-04:00,openai/gpt-5.4-mini,OpenAI,Primary,App,10,20,3,1,0.12,0.01,0,0,123,stop,true,false,0,u,50"

    r = client.post("/api/import/csv",
        files={"file": ("openrouter_activity.csv", _csv(row), "text/csv")})
    assert r.status_code == 200

    conn = sqlite3.connect(db_path)
    try:
        created_at, created_hour = conn.execute(
            "SELECT created_at, created_hour FROM generations WHERE id='gen-explicit'"
        ).fetchone()
    finally:
        conn.close()
    assert created_at.startswith("2026-04-13T18:00:00")
    assert created_hour == 18


def test_rebuild_timestamps_corrects_offset_rows(monkeypatch, tmp_path):
    """Admin endpoint must rewrite stored created_at from the gen-ID epoch and
    leave rows whose IDs carry no recoverable epoch untouched."""
    module = load_module(monkeypatch, tmp_path / "runtime_home")
    client, db_path = build_client(module, tmp_path)

    # Pre-seed three rows directly: one shifted +4h, one already correct,
    # one with an ID that carries no epoch (should be left alone).
    ingested = "2026-04-13T18:00:00+00:00"
    conn = sqlite3.connect(db_path)
    try:
        # gen-1776081900 → 2026-04-13 12:05:00 UTC
        conn.execute(
            "INSERT INTO generations (id, created_at, created_date, created_hour, "
            "model, model_short, ingested_at) VALUES (?,?,?,?,?,?,?)",
            ("gen-1776081900-shift", "2026-04-13T16:05:00.123000+00:00",
             "2026-04-13", 16, "openai/gpt-5.4-mini", "gpt-5.4-mini", ingested),
        )
        conn.execute(
            "INSERT INTO generations (id, created_at, created_date, created_hour, "
            "model, model_short, ingested_at) VALUES (?,?,?,?,?,?,?)",
            ("gen-1776081900-ok", "2026-04-13T12:05:00.789000+00:00",
             "2026-04-13", 12, "openai/gpt-5.4-mini", "gpt-5.4-mini", ingested),
        )
        conn.execute(
            "INSERT INTO generations (id, created_at, created_date, created_hour, "
            "model, model_short, ingested_at) VALUES (?,?,?,?,?,?,?)",
            ("legacy-id-without-epoch", "2026-04-13T09:00:00+00:00",
             "2026-04-13", 9, "openai/gpt-5.4-mini", "gpt-5.4-mini", ingested),
        )
        conn.commit()
    finally:
        conn.close()

    r = client.post("/api/admin/rebuild-timestamps?confirm=true")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["scanned"] == 3
    assert body["updated"] == 1
    assert body["skipped_no_epoch"] == 1
    assert Path(body["backup_path"]).exists()

    conn = sqlite3.connect(db_path)
    try:
        shifted = conn.execute(
            "SELECT created_at, created_date, created_hour FROM generations WHERE id='gen-1776081900-shift'"
        ).fetchone()
        already_ok = conn.execute(
            "SELECT created_at FROM generations WHERE id='gen-1776081900-ok'"
        ).fetchone()
        legacy = conn.execute(
            "SELECT created_at FROM generations WHERE id='legacy-id-without-epoch'"
        ).fetchone()
    finally:
        conn.close()

    assert shifted[0].startswith("2026-04-13T12:05:00")
    assert shifted[0].endswith("+00:00")
    assert shifted[1] == "2026-04-13"
    assert shifted[2] == 12
    # Sub-second precision from the original row is preserved.
    assert ".123" in shifted[0]
    assert already_ok[0] == "2026-04-13T12:05:00.789000+00:00"
    assert legacy[0] == "2026-04-13T09:00:00+00:00"


def test_rebuild_timestamps_requires_confirm(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path / "runtime_home")
    client, _ = build_client(module, tmp_path)
    r = client.post("/api/admin/rebuild-timestamps")
    assert r.status_code == 400
    assert "confirm=true" in r.json().get("error", "")
