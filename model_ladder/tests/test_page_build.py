"""Page build: payload, rendering, escaping and file modes. Synthetic data only."""
import json
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from helpers import RATE, ladder_models, model, snapshot

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT.parent))
from tools.testkit import (  # noqa: E402
    assert_frontend_vendor_current,
    assert_launcher_compiles_cleanly,
    assert_offline_page_source,
    run_launcher,
)

LAUNCHER = PROJECT / "model_ladder"
CONFIG = {"op_item": "", "op_vault": "", "op_field": "credential", "max_age_hours": 12}
NOW = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)
PAYLOAD_OPEN = '<script type="application/json" id="payload">'


def payload_of(html: str) -> dict:
    start = html.index(PAYLOAD_OPEN) + len(PAYLOAD_OPEN)
    return json.loads(html[start:html.index("</script>", start)])


def seed(ml, models, when=NOW, version=5):
    home = ml.ensure_runtime_home(ml.runtime_home())
    return ml.save_snapshot(home, {"models": models, "index_version": version, "rate_limit": RATE}, when)


def test_payload_keys_and_types(ml):
    snap = snapshot(ladder_models())
    payload = ml.build_payload({"aa": (snap, None)}, CONFIG)
    assert set(payload) == {"schema", "app", "rung_order", "default_source", "sources"}
    assert payload["schema"] == 3
    assert set(payload["sources"]) == {"aa", "aicd", "fc"}
    assert not payload["sources"]["aicd"]["available"]
    assert payload["app"] == {"name": "Model Ladder", "version": ml.VERSION}
    assert payload["rung_order"] == list(ml.RUNG_ORDER)
    aa = payload["sources"]["aa"]
    assert aa["fetched_at"] == snap["fetched_at"] and aa["last_checked"] == snap["last_checked"]
    assert aa["max_age_hours"] == 12 and aa["version"] == 5
    assert aa["rate_limit"] == RATE and aa["rows"] == ml.classify(snap["models"])
    assert aa["changes"] is None
    json.dumps(payload)


def test_status_reaches_payload(ml):
    data = ml.build_payload({}, CONFIG, {"fc": {"last_attempt": "synthetic", "error": "failed"}})
    assert data["sources"]["fc"]["last_attempt"] == "synthetic"
    assert data["sources"]["fc"]["error"] == "failed"


def test_unavailable_source_entry_is_complete(ml):
    data = ml.build_payload({}, CONFIG)
    for key in ml.SOURCE_KEYS:
        entry = data["sources"][key]
        assert not entry["available"] and entry["rows"] == [] and entry["changes"] is None
        assert entry["version"] is None and entry["version_label"] == "" and entry["notice"] is None
        assert entry["rate_limit"] == {"limit": None, "remaining": None, "reset": None}
    assert data["sources"]["aa"]["axes"] == ml.SOURCE_SPECS["aa"]["axes"]


def test_build_page_isolates_unreadable_source(ml, tmp_path, capsys):
    seed(ml, ladder_models())
    broken = ml.snapshot_dir(ml.runtime_home(), "fc") / "20261101T120000Z.json.gz"
    broken.write_bytes(b"synthetic invalid")
    output = tmp_path / "page.html"
    ml.build_page(ml.runtime_home(), output)
    payload = payload_of(output.read_text())
    assert payload["sources"]["aa"]["available"]
    assert not payload["sources"]["fc"]["available"]
    assert str(broken) in payload["sources"]["fc"]["error"]
    assert str(broken) in capsys.readouterr().err


def test_payload_includes_empty_default_and_scored_domain(ml):
    payload = ml.build_payload({"aa": (snapshot([model("Example", scores={"finance": 42})]), None)}, CONFIG)
    assert [(i["key"], i["count"]) for i in payload["sources"]["aa"]["indexes"]] == [("intelligence", 0), ("finance", 1)]


def test_payload_changes_with_previous(ml):
    old = snapshot([model("Alpha Test 1 (High)", 40.0, 1.0)], when="2026-11-01T00:00:00+00:00", version=4)
    new = snapshot(ladder_models())
    assert ml.build_payload({"aa": (new, old)}, CONFIG)["sources"]["aa"]["changes"] == ml.diff_rows(old, new)


def test_render_is_offline_and_complete(ml):
    html = ml.render_page(ml.build_payload({"aa": (snapshot(ladder_models()), None)}, CONFIG)).decode("utf-8")
    assert_offline_page_source(html)
    assert html.startswith("<!DOCTYPE html>")
    assert "{{" not in html and "<!-- frontend-vendor -->" not in html
    assert html.count(PAYLOAD_OPEN) == 1
    assert f"<script>{ml.LADDER_MATH_JS}</script>" in html
    assert f"<script>{ml.APP_JS}</script>" in html
    assert html.index(ml.LADDER_MATH_JS) < html.index(ml.APP_JS)
    assert ml.PAGE_CSS in html
    assert payload_of(html)["sources"]["aa"]["rows"] == ml.classify(ladder_models())


def test_vendor_region_current_and_launcher_compiles():
    assert_frontend_vendor_current(LAUNCHER)
    assert_launcher_compiles_cleanly(LAUNCHER)


def test_markup_in_a_name_appears_only_escaped(ml):
    name = "X</script><b> (High)"
    data = ml.render_page(ml.build_payload({"aa": (snapshot([model(name, 30.0, 1.0)]), None)}, CONFIG))
    assert b"X</script>" not in data and b"</script><b>" not in data
    assert b"X\\u003c/script>\\u003cb>" in data
    assert payload_of(data.decode("utf-8"))["sources"]["aa"]["rows"][0]["name"] == name


@pytest.mark.parametrize("asset", ["PAGE_CSS", "LADDER_MATH_JS", "APP_JS"])
def test_render_rejects_a_closing_script_tag_in_an_asset(ml, monkeypatch, asset):
    monkeypatch.setattr(ml, asset, getattr(ml, asset) + "\n/* </SCRIPT > */\n")
    with pytest.raises(ValueError, match=asset):
        ml.render_page(ml.build_payload({"aa": (snapshot(ladder_models()), None)}, CONFIG))


def test_build_page_uses_newest_two_snapshots(ml, tmp_path):
    seed(ml, [model("Alpha Test 1 (High)", 40.0, 1.0)], when=datetime(2026, 11, 1, tzinfo=timezone.utc), version=4)
    seed(ml, ladder_models())
    home = ml.runtime_home()
    out = tmp_path / "page.html"
    ml.build_page(home, out)
    payload = payload_of(out.read_text(encoding="utf-8"))["sources"]["aa"]
    assert payload["fetched_at"] == NOW.isoformat()
    assert payload["changes"]["version"] == [4, 5]
    assert "Beta Test 1 (High)" in payload["changes"]["added"]


def test_build_page_with_unreadable_previous_still_builds(ml, tmp_path, capsys):
    older = seed(ml, [model("Alpha Test 1 (High)", 40.0, 1.0)], when=datetime(2026, 11, 1, tzinfo=timezone.utc))
    seed(ml, ladder_models())
    older.write_bytes(b"not gzip")
    out = tmp_path / "page.html"
    ml.build_page(ml.runtime_home(), out)
    assert payload_of(out.read_text(encoding="utf-8"))["sources"]["aa"]["changes"] is None
    err = capsys.readouterr().err
    assert str(older) in err and "Traceback" not in err


def test_page_contains_no_key_or_item_name(ml, tmp_path):
    home = ml.ensure_runtime_home(ml.runtime_home())
    (home / "config.json").write_text(json.dumps({**CONFIG, "op_item": "synthetic-op-item-name",
                                                  "op_vault": "synthetic-op-vault"}))
    seed(ml, ladder_models())
    result = run_launcher(LAUNCHER, "build", "--no-open",
                          env_overrides={"MODEL_LADDER_AA_KEY": "synthetic-secret-key-456"})
    assert result.returncode == 0, result.stderr
    page = (home / "model_ladder.html").read_text(encoding="utf-8")
    for secret in ("synthetic-secret-key-456", "synthetic-op-item-name", "synthetic-op-vault", "x-api-key"):
        assert secret not in page


def test_cli_writes_private_pages(ml, tmp_path):
    seed(ml, ladder_models())
    home = ml.runtime_home()
    result = run_launcher(LAUNCHER, "build", "--no-open")
    assert result.returncode == 0, result.stderr
    default = home / "model_ladder.html"
    assert str(default) in result.stdout
    assert stat.S_IMODE(default.stat().st_mode) == 0o600
    assert stat.S_IMODE(home.stat().st_mode) == 0o700

    target = tmp_path / "elsewhere" / "page.html"
    target.parent.mkdir()
    target.write_text("old")
    target.chmod(0o644)
    result = run_launcher(LAUNCHER, "build", "--no-open", "--output", str(target))
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert payload_of(target.read_text(encoding="utf-8"))["app"]["name"] == "Model Ladder"
    assert [p.name for p in target.parent.iterdir()] == ["page.html"]


def gamma_free():
    return [m for m in ladder_models() if m["name"] != "Gamma Test 1"]


def with_unused_field_change(field="performance"):
    models = ladder_models()
    models[0][field] = {"synthetic_value": 1}
    return models


def test_build_page_keeps_last_real_change_visible(ml, tmp_path):
    """A refetch that differs only in unused fields must not hide the last real change."""
    seed(ml, gamma_free(), when=datetime(2026, 11, 1, tzinfo=timezone.utc))
    seed(ml, ladder_models(), when=datetime(2026, 11, 3, tzinfo=timezone.utc))
    seed(ml, with_unused_field_change())
    assert len(ml.load_snapshots(ml.runtime_home())) == 3
    out = tmp_path / "page.html"
    ml.build_page(ml.runtime_home(), out)
    changes = payload_of(out.read_text(encoding="utf-8"))["sources"]["aa"]["changes"]
    assert changes["added"] == ["Gamma Test 1"]
    assert changes["from"] == "2026-11-01T00:00:00+00:00"
    assert changes["to"] == NOW.isoformat()


def test_build_page_without_any_real_change_has_no_changes(ml, tmp_path):
    seed(ml, ladder_models(), when=datetime(2026, 11, 1, tzinfo=timezone.utc))
    seed(ml, with_unused_field_change("pricing"))
    out = tmp_path / "page.html"
    ml.build_page(ml.runtime_home(), out)
    assert payload_of(out.read_text(encoding="utf-8"))["sources"]["aa"]["changes"] is None


def test_build_page_skips_unreadable_snapshot_while_walking_back(ml, tmp_path, capsys):
    seed(ml, gamma_free(), when=datetime(2026, 11, 1, tzinfo=timezone.utc))
    broken = seed(ml, ladder_models(), when=datetime(2026, 11, 3, tzinfo=timezone.utc))
    seed(ml, with_unused_field_change())
    broken.write_bytes(b"not gzip")
    out = tmp_path / "page.html"
    ml.build_page(ml.runtime_home(), out)
    assert payload_of(out.read_text(encoding="utf-8"))["sources"]["aa"]["changes"]["added"] == ["Gamma Test 1"]
    err = capsys.readouterr().err
    assert str(broken) in err and err.count("\n") == 1 and "Traceback" not in err
