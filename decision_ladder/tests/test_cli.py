from datetime import datetime, timedelta, timezone
import pytest
from helpers import feed


def test_build_without_snapshot_reports_recovery(dl, capsys):
    assert dl.main(["build", "--no-open"]) == 1
    assert "decision_ladder refresh" in capsys.readouterr().err


@pytest.mark.parametrize("args,age,expected", [
    ([], 1, False), ([], 25, True), (["refresh"], 1, True), (["build"], 25, False),
    (["--no-refresh"], 25, False), (["refresh", "--no-refresh"], 25, False),
])
def test_commands_choose_fetch_by_age(dl, tmp_path, args, age, expected):
    now = datetime(2026, 1, 3, tzinfo=timezone.utc)
    result = {"feed": feed(), "sha256": "synthetic"}
    dl.save_snapshot(dl.runtime_home(), result, now - timedelta(hours=age))
    calls = []
    def fetch():
        calls.append(True)
        return result
    output = tmp_path / "result.html"
    assert dl.main(args + ["--no-open", "--output", str(output)], now=now, fetch=fetch) == 0
    assert bool(calls) is expected
    assert output.exists()


def test_failed_fetch_falls_back_or_fails_without_snapshot(dl, capsys):
    now = datetime(2026, 1, 3, tzinfo=timezone.utc)
    def fail():
        raise dl.FetchError("synthetic outage")
    assert dl.main(["refresh", "--no-open"], now=now, fetch=fail) == 1
    dl.save_snapshot(dl.runtime_home(), {"feed": feed(), "sha256": "synthetic"}, now)
    assert dl.main(["refresh", "--no-open"], now=now, fetch=fail) == 0
    error = capsys.readouterr().err
    assert "synthetic outage" in error
    assert "snapshot" in error


def test_first_run_fetches_and_prints_summary(dl, capsys):
    now = datetime(2026, 1, 3, tzinfo=timezone.utc)
    assert dl.main(["--no-open"], now=now, fetch=lambda: {"feed": feed(), "sha256": "synthetic"}) == 0
    assert "Fetched 1 systems (1 ranked), revision synthetic." in capsys.readouterr().out
