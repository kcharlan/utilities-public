import json
from datetime import datetime, timedelta, timezone

import pytest

from helpers import model

NOW = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)
RATE = {"limit": 100, "remaining": 95, "reset": 1_800_000_000}
SECRET = "synthetic-secret-key-123"


def fetched(models=None):
    models = models if models is not None else [model("Alpha Test 1 (high)", 50, 1.0), model("Unscored One")]
    return {"models": models, "index_version": 5, "rate_limit": RATE}


class Fetch:
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result, self.error = result or fetched(), error

    def __call__(self, key):
        self.calls.append(key)
        if self.error:
            raise self.error
        return self.result


class Env:
    """Everything main needs, injected; records what happened."""

    def __init__(self, ml, monkeypatch):
        self.ml = ml
        self.fetch = Fetch()
        self.built = []
        self.opened = []
        monkeypatch.setattr(ml, "build_page", lambda home, output: self.built.append((home, output)))

    def run(self, *argv, now=NOW, get_key=None):
        return self.ml.main(list(argv), now=now, fetch=self.fetch,
                            get_key=get_key or (lambda config: SECRET), open_page=self.opened.append)

    def seed(self, age_hours, models=None):
        when = NOW - timedelta(hours=age_hours)
        home = self.ml.ensure_runtime_home(self.ml.runtime_home())
        return self.ml.save_snapshot(home, fetched(models), when)


@pytest.fixture
def env(ml, monkeypatch):
    return Env(ml, monkeypatch)


def test_cli_first_run_fetches(env, tmp_path):
    assert env.run() == 0
    assert env.fetch.calls == [SECRET]
    assert len(env.ml.load_snapshots(tmp_path / "ml-home")) == 1
    assert len(env.built) == 1


def test_cli_fresh_snapshot_skips_fetch(env):
    env.seed(1)
    assert env.run() == 0
    assert env.fetch.calls == [] and len(env.built) == 1


def test_cli_stale_snapshot_fetches(env):
    env.seed(13)
    assert env.run() == 0
    assert len(env.fetch.calls) == 1


def test_cli_max_age_from_config(env, tmp_path):
    home = env.ml.ensure_runtime_home(tmp_path / "ml-home")
    (home / "config.json").write_text(json.dumps({"max_age_hours": 1}))
    env.seed(2)
    assert env.run() == 0
    assert len(env.fetch.calls) == 1


def test_cli_future_last_checked_is_fresh(env):
    env.seed(-5)
    assert env.run() == 0 and env.fetch.calls == []


def test_cli_refresh_always_fetches(env):
    env.seed(0)
    assert env.run("refresh") == 0
    assert len(env.fetch.calls) == 1


def test_cli_build_never_fetches(env):
    env.seed(100)
    assert env.run("build") == 0
    assert env.fetch.calls == [] and len(env.built) == 1


def test_cli_no_refresh_flag(env):
    env.seed(100)
    assert env.run("--no-refresh") == 0
    assert env.fetch.calls == [] and len(env.built) == 1


def test_cli_build_without_snapshot_fails(env, capsys):
    assert env.run("build") == 1
    assert "no snapshot" in capsys.readouterr().err.lower()
    assert env.built == [] and env.fetch.calls == []


def test_cli_fetch_failure_with_snapshot_builds(env, capsys):
    env.seed(100)
    env.fetch.error = env.ml.FetchError("Artificial Analysis returned HTTP 500")
    assert env.run() == 0
    assert "Model Ladder: Artificial Analysis returned HTTP 500" in capsys.readouterr().err
    assert len(env.built) == 1


def test_cli_key_failure_with_snapshot_builds(env, capsys):
    env.seed(100)

    def no_key(config):
        raise env.ml.KeyUnavailable("No API key configured.")
    assert env.run(get_key=no_key) == 0
    assert "Model Ladder: No API key configured." in capsys.readouterr().err
    assert env.fetch.calls == [] and len(env.built) == 1


def test_cli_fetch_failure_without_snapshot(env, capsys):
    env.fetch.error = env.ml.FetchError("boom")
    assert env.run() == 1
    assert "Model Ladder: boom" in capsys.readouterr().err
    assert env.built == []


def test_cli_unreadable_snapshot(env, capsys):
    older = env.seed(30)
    newest = env.seed(20, models=[model("Alpha Test 1", 40, 1.0)])
    newest.write_bytes(newest.read_bytes()[:20])
    assert env.run() == 1
    err = capsys.readouterr().err
    assert str(newest) in err and "Traceback" not in err and err.startswith("Model Ladder: cannot read")
    assert older.exists() and newest.exists()
    assert env.fetch.calls == [] and env.built == []


def test_cli_prints_quota(env, capsys):
    assert env.run() == 0
    out = capsys.readouterr().out
    assert "Fetched 2 models (1 scored)." in out
    assert "95 of 100 requests left today; resets " in out
    assert datetime.fromtimestamp(RATE["reset"]).strftime("%H:%M") in out


def test_cli_quota_line_survives_missing_headers(env, capsys):
    env.fetch.result = {**fetched(), "rate_limit": {"limit": None, "remaining": None, "reset": None}}
    assert env.run() == 0
    assert "Fetched 2 models (1 scored)." in capsys.readouterr().out


def test_cli_prints_output_path_and_passes_it(env, tmp_path, capsys):
    env.seed(1)
    assert env.run() == 0
    home, output = env.built[0]
    assert output == tmp_path / "ml-home" / "model_ladder.html"
    assert str(output) in capsys.readouterr().out


def test_cli_output_option(env, tmp_path, capsys):
    env.seed(1)
    target = tmp_path / "out" / "page.html"
    assert env.run("--output", str(target)) == 0
    assert env.built[0][1] == target
    assert str(target) in capsys.readouterr().out


def test_cli_never_opens_under_testing(env):
    env.seed(1)
    assert env.run() == 0
    assert env.opened == []


def test_cli_opens_when_not_testing(env, monkeypatch, tmp_path):
    monkeypatch.setenv("UTILITIES_TESTING", "")
    env.seed(1)
    assert env.run() == 0
    assert env.opened == [(tmp_path / "ml-home" / "model_ladder.html").resolve().as_uri()]


def test_cli_no_open_flag(env, monkeypatch):
    monkeypatch.setenv("UTILITIES_TESTING", "")
    env.seed(1)
    assert env.run("--no-open") == 0
    assert env.opened == []


def test_cli_bad_config_is_one_line(env, tmp_path, capsys):
    home = env.ml.ensure_runtime_home(tmp_path / "ml-home")
    (home / "config.json").write_text(json.dumps({"max_age_hours": "soon"}))
    assert env.run() == 1
    err = capsys.readouterr().err
    assert err.startswith("Model Ladder: ") and "max_age_hours" in err and "Traceback" not in err
    assert env.fetch.calls == []


def test_cli_unsavable_snapshot_still_builds_from_old(env, monkeypatch, capsys):
    env.seed(100)

    def fail(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(env.ml, "save_snapshot", fail)
    assert env.run() == 0
    assert "Model Ladder: cannot save snapshot: disk full" in capsys.readouterr().err
    assert len(env.built) == 1


def test_cli_rejects_unknown_command(env):
    with pytest.raises(SystemExit) as info:
        env.run("explode")
    assert info.value.code == 2
