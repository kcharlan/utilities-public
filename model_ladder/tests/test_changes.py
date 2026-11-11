from helpers import model


def snap(models, version=5, fetched="2026-11-01T12:00:00+00:00"):
    return {"schema": 1, "fetched_at": fetched, "last_checked": fetched,
            "index_version": version, "rate_limit": {}, "models": models}


def test_diff_none_without_previous(ml):
    assert ml.diff_rows(None, snap([])) is None


def test_diff_added_removed_changed(ml):
    old = snap([model("Alpha Test 1 (high)", 50.04, 1.5), model("Beta Test 2", 30, 2.0),
                model("Gamma Test 3", 20, 1.0)])
    new = snap([model("Alpha Test 1 (high)", 51.26, 1.75), model("Gamma Test 3", 20, 1.0),
                model("Delta Test 4", 10, 0.5)], fetched="2026-11-02T12:00:00+00:00")
    diff = ml.diff_rows(old, new)
    assert diff["from"] == "2026-11-01T12:00:00+00:00" and diff["to"] == "2026-11-02T12:00:00+00:00"
    assert diff["version"] is None
    assert diff["added"] == ["Delta Test 4"] and diff["removed"] == ["Beta Test 2"]
    assert diff["changed"] == [{"slug": "alpha-test-1--high-", "name": "Alpha Test 1 (high)",
                                "index": [50.04, 51.26], "cost": [1.5, 1.75]}]


def test_diff_ignores_unscored_and_identical(ml):
    old = snap([model("Alpha Test 1", 50, 1.0), model("Unscored One")])
    new = snap([model("Alpha Test 1", 50, 1.0), model("Unscored One"), model("Unscored Two")])
    diff = ml.diff_rows(old, new)
    assert diff["added"] == diff["removed"] == diff["changed"] == []


def test_diff_cost_appearing_counts_as_change(ml):
    diff = ml.diff_rows(snap([model("Alpha Test 1", 50)]), snap([model("Alpha Test 1", 50, 1.0)]))
    assert diff["changed"][0]["cost"] == [None, 1.0]


def test_diff_version_change(ml):
    diff = ml.diff_rows(snap([], version=5), snap([], version=6))
    assert diff["version"] == [5, 6]
