import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("rollup_snapshots.py")


def load_rollup_module():
    spec = importlib.util.spec_from_file_location("rollup_snapshots_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_rollup_snapshot_prefers_daily_totals(tmp_path):
    module = load_rollup_module()
    snapshot = tmp_path / "snapshot_1777174200000.json"
    snapshot.write_text(
        json.dumps(
            {
                "totals": {"chat.openai.com": 5, "gemini.google.com": 4},
                "daily_totals": {
                    "2026-04-25": {"chat.openai.com": 2},
                    "2026-04-26": {"chat.openai.com": 3, "gemini.google.com": 4},
                },
            }
        )
    )

    assert module._rollup_snapshot(snapshot, cutoff_hour=8) == {
        "2026-04-25": {"chat.openai.com": 2},
        "2026-04-26": {"chat.openai.com": 3, "gemini.google.com": 4},
    }


def test_rollup_snapshot_supports_legacy_totals(tmp_path):
    module = load_rollup_module()
    snapshot = tmp_path / "snapshot_1777174200000.json"
    snapshot.write_text(json.dumps({"totals": {"chat.openai.com": 5}}))

    assert module._rollup_snapshot(snapshot, cutoff_hour=8) == {
        "2026-04-25": {"chat.openai.com": 5}
    }
