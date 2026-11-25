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
    assert diff["changed"] == [{"id": "id-alpha-test-1--high-", "name": "Alpha Test 1 (high)",
                                "scores": {key: [50.04, 51.26] if key == "intelligence" else [None, None]
                                           for key, *_ in ml.INDEXES}, "axes": {"cost": [1.5, 1.75]}, "extras": {}}]


def test_domain_changes_and_disappearing_score(ml):
    old = snap([model("Example", 50, scores={"finance": 10})])
    for value in (11, None):
        new = snap([model("Example", 50, scores={"finance": value})])
        assert ml.diff_rows(old, new)["changed"][0]["scores"]["finance"] == [10, value]


def test_diff_ignores_unscored_and_identical(ml):
    old = snap([model("Alpha Test 1", 50, 1.0), model("Unscored One")])
    new = snap([model("Alpha Test 1", 50, 1.0), model("Unscored One"), model("Unscored Two")])
    diff = ml.diff_rows(old, new)
    assert diff["added"] == diff["removed"] == diff["changed"] == []


def test_diff_cost_appearing_counts_as_change(ml):
    diff = ml.diff_rows(snap([model("Alpha Test 1", 50)]), snap([model("Alpha Test 1", 50, 1.0)]))
    assert diff["changed"][0]["axes"]["cost"] == [None, 1.0]


def test_maxima_only_change(ml, tmp_path):
    old = {**snap([]), "index_maxima": {"intelligence": 100}}
    new = {**snap([]), "index_maxima": {"intelligence": 120}}
    diff = ml.diff_rows(old, new)
    assert diff["maxima"] == {"intelligence": [100, 120]}
    assert ml._shows_a_change(diff)
    path = tmp_path / "old.json.gz"
    ml._write_snapshot(path, old)
    assert ml._last_real_change([path], new) == old
    entry = ml.build_payload({"aa": (new, old)}, {"max_age_hours": 12})["sources"]["aa"]
    assert entry["changes"]["maxima"] == {"intelligence": [100, 120]}
    assert entry["indexes"][0]["max"] == 120


def test_displayed_extras_only_change(ml, monkeypatch, tmp_path):
    spec = {**ml.SOURCE_SPECS["aa"], "extras": [{"key": "grade", "label": "Grade", "kind": "text", "path": "extras.grade"},
                                               {"key": "tested", "label": "Tested", "kind": "text", "path": "extras.tested"},
                                               {"key": "framework", "label": "Framework", "kind": "number", "path": "scores.framework"}],
            "classify": lambda models: models}
    monkeypatch.setitem(ml.SOURCE_SPECS, "aicd", spec)
    base = {"id": "synthetic", "name": "Synthetic", "scores": {"intelligence": 5}, "axes": {"cost": 1}, "extras": {"grade": "A"}}
    old = snap([base])
    new = snap([{**base, "extras": {"grade": "B"}}], fetched="2026-11-02T12:00:00+00:00")
    diff = ml.diff_rows(old, new, "aicd")
    assert diff["changed"][0]["extras"] == {"extras.grade": ["A", "B"]}
    assert ml._shows_a_change(diff)
    older = tmp_path / "old.json.gz"
    ml._write_snapshot(older, old)
    assert ml._last_real_change([older], new, "aicd") == old
    payload = ml.build_payload({"aicd": (new, old)}, {"max_age_hours": 12})
    assert payload["sources"]["aicd"]["changes"] == diff
    tested_only = {**old, "models": [{**base, "extras": {"grade": "A", "tested": "synthetic"}}]}
    assert not ml._shows_a_change(ml.diff_rows(old, tested_only, "aicd"))
    score_extra = {**old, "models": [{**base, "scores": {"intelligence": 5, "framework": 7}}]}
    assert ml.diff_rows(old, score_extra, "aicd")["changed"][0]["extras"] == {"scores.framework": [None, 7]}


def test_diff_version_change(ml):
    diff = ml.diff_rows(snap([], version=5), snap([], version=6))
    assert diff["version"] == [5, 6]


def test_diff_follows_id_when_a_new_version_takes_the_slug(ml):
    old = snap([model("Alpha Test 1", 50, 1.0, slug="alpha-test-1", model_id="id-first")])
    new = snap([model("Alpha Test 1 0101", 50, 1.0, slug="alpha-test-1-0101", model_id="id-first"),
                model("Alpha Test 1", 60, 2.0, slug="alpha-test-1", model_id="id-second")])
    diff = ml.diff_rows(old, new)
    assert diff["added"] == ["Alpha Test 1"]
    assert diff["removed"] == [] and diff["changed"] == []


def test_diff_reports_a_change_across_a_slug_rename(ml):
    old = snap([model("Beta Test 2", 30, 2.0, slug="beta-test-2-0101", model_id="id-beta")])
    new = snap([model("Beta Test 2", 31, 2.0, slug="beta-test-2", model_id="id-beta")])
    diff = ml.diff_rows(old, new)
    assert diff["added"] == [] and diff["removed"] == []
    assert [(item["id"], item["scores"]["intelligence"]) for item in diff["changed"]] == [("id-beta", [30, 31])]


def test_slug_only_change_keeps_the_last_real_change(ml, tmp_path):
    item = model("Gamma Test 3", 20, 1.0, slug="gamma-test-3", model_id="id-gamma")
    older = snap([model("Gamma Test 3", 19, 1.0, slug="gamma-test-3", model_id="id-gamma")])
    previous = snap([item], fetched="2026-11-02T12:00:00+00:00")
    current = snap([{**item, "slug": "gamma-test-3-0101"}], fetched="2026-11-03T12:00:00+00:00")
    previous_path = tmp_path / "previous.json.gz"
    older_path = tmp_path / "older.json.gz"
    ml._write_snapshot(previous_path, previous)
    ml._write_snapshot(older_path, older)
    assert ml._last_real_change([previous_path, older_path], current) == older


def test_name_only_change_is_omitted(ml):
    item = model("Invented Name", 50, 1)
    old = snap([item])
    new = snap([{**item, "name": "Invented Renamed"}], fetched="2026-11-02T12:00:00+00:00")
    assert not ml._shows_a_change(ml.diff_rows(old, new))
