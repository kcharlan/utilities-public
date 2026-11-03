import sqlite3

import pytest

from model_sentinel import cli
from model_sentinel.storage import Store
from tests.test_cli import _write_config_files


@pytest.mark.parametrize("bad_catalog", [
    [{"id": "duplicate"}, {"id": "duplicate"}],
    [{"id": "overflow", "context_length": float("inf")}],
    [{"name": "Synthetic model without id"}],
    [],
])
def test_failed_catalog_preserves_baseline_and_scans_next_provider(
    tmp_path, monkeypatch, bad_catalog
):
    home = _write_config_files(tmp_path)
    providers = home / "providers.env"
    original = providers.read_text()
    providers.write_text(original + original.replace("OPENROUTER", "SECOND"))
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(home))
    monkeypatch.setenv("OPENROUTER_AI_CREDS", "synthetic")
    monkeypatch.setenv("SECOND_AI_CREDS", "synthetic")
    monkeypatch.setattr(cli, "fetch_raw_models", lambda *args: [{"id": "original"}])
    assert cli.main(["scan", "--save"]) == 0
    store = Store(home / "model_sentinel.db")
    before = store.get_latest_saved_baseline("openrouter")
    assert before is not None

    def fetch(provider, *args):
        return bad_catalog if provider.provider_id == "openrouter" else [{"id": "new"}]

    monkeypatch.setattr(cli, "fetch_raw_models", fetch)
    cli.main(["scan", "--save"])
    assert store.get_latest_saved_baseline("openrouter").scrape_id == before.scrape_id
    assert set(store.load_saved_models(before.scrape_id)) == {"original"}
    other = store.get_latest_saved_baseline("second")
    assert set(store.load_saved_models(other.scrape_id)) == {"new"}
    with sqlite3.connect(home / "model_sentinel.db") as connection:
        assert connection.execute(
            "SELECT status FROM scrapes WHERE provider_id = ? ORDER BY scrape_id DESC LIMIT 1",
            ("openrouter",),
        ).fetchone() == ("error",)


def test_failed_change_history_write_rolls_back_saved_snapshot(tmp_path, monkeypatch):
    home = _write_config_files(tmp_path)
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(home))
    monkeypatch.setenv("OPENROUTER_AI_CREDS", "synthetic")
    monkeypatch.setattr(cli, "fetch_raw_models", lambda *args: [{"id": "original"}])
    assert cli.main(["scan", "--save"]) == 0
    store = Store(home / "model_sentinel.db")
    before = store.get_latest_saved_baseline("openrouter")
    with sqlite3.connect(home / "model_sentinel.db") as connection:
        connection.execute("""CREATE TRIGGER reject_changes BEFORE INSERT ON field_changes
                              BEGIN SELECT RAISE(ABORT, 'synthetic history failure'); END""")
    monkeypatch.setattr(cli, "fetch_raw_models", lambda *args: [{"id": "new"}])
    cli.main(["scan", "--save"])
    assert store.get_latest_saved_baseline("openrouter").scrape_id == before.scrape_id
