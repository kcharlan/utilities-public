from helpers import model


def test_effort_and_tags(ml):
    r = ml.split_name("Alpha Test 1 (Max, Some Tag)")
    assert (r["family"], r["rung"], r["tags"], r["problem"]) == ("Alpha Test 1", "max", ["Some Tag"], None)


def test_effort_case_insensitive(ml):
    assert ml.split_name("Alpha Test 1 (XHIGH)")["rung"] == "xhigh"


def test_non_reasoning_is_lowest_rung(ml):
    r = ml.split_name("Alpha Test 1 (Non-reasoning)")
    assert r["rung"] == "non-reasoning" and r["tags"] == []


def test_reasoning_is_only_a_tag(ml):
    r = ml.split_name("Alpha Test 1 (Reasoning)")
    assert r["rung"] is None and r["tags"] == ["Reasoning"]


def test_no_parentheses(ml):
    r = ml.split_name("Alpha Test 1")
    assert (r["family"], r["rung"], r["tags"]) == ("Alpha Test 1", None, [])


def test_group_not_at_end(ml):
    r = ml.split_name("Alpha (x) Test")
    assert (r["family"], r["rung"], r["problem"]) == ("Alpha (x) Test", None, None)


def test_two_groups_unclassified(ml):
    r = ml.split_name("Alpha (Beta) Test (High)")
    assert (r["family"], r["rung"], r["problem"]) == ("Alpha (Beta) Test (High)", None, "more than one group")


def test_two_efforts_unclassified(ml):
    r = ml.split_name("Alpha Test 1 (High, Low)")
    assert (r["family"], r["rung"], r["problem"]) == ("Alpha Test 1 (High, Low)", None, "two effort words")


def test_classify_skips_unscored(ml):
    rows = ml.classify([model("Alpha Test 1 (High)", index=50), model("Alpha Test 2", index=None)])
    assert len(rows) == 1 and rows[0]["name"] == "Alpha Test 1 (High)"


def test_classify_row_shape(ml):
    (row,) = ml.classify([model("Alpha Test 1 (High, Tag)", index=50, cost=2.5, total=9.0, release="2026-02-03", slug="s1")])
    assert row == {
        "slug": "s1", "name": "Alpha Test 1 (High, Tag)", "maker": "Example Lab", "family": "Alpha Test 1",
        "family_key": '["Example Lab", "Alpha Test 1"]', "rung": "high", "tags": ["Tag"], "index": 50,
        "cost": 2.5, "total_cost": 9.0, "release_date": "2026-02-03", "problem": None,
    }


def test_cost_zero_and_null_are_none(ml):
    rows = ml.classify([model("A", 1, cost=0), model("B", 1, cost=None), model("C", 1, cost=1.5)])
    assert [r["cost"] for r in rows] == [None, None, 1.5]


def test_duplicate_rung_unclassified(ml):
    rows = ml.classify([model("Alpha Test 1 (High)", 1), model("Alpha Test 1 (High, Tag)", 2)])
    for row in rows:
        assert row["rung"] is None and row["family"] == row["name"] and row["problem"] == "duplicate rung"
        assert row["family_key"] == f'["Example Lab", "{row["name"]}"]'


def test_same_family_different_makers_do_not_collide(ml):
    rows = ml.classify([model("Alpha Test 1 (High)", 1), model("Alpha Test 1 (High)", 2, maker="Sample Works", slug="x")])
    assert [r["rung"] for r in rows] == ["high", "high"]
    assert rows[0]["family_key"] != rows[1]["family_key"]


def test_two_rungless_rows_are_not_duplicates(ml):
    rows = ml.classify([model("Alpha Test 1 (Reasoning)", 1), model("Alpha Test 1 (Tag)", 2)])
    assert [r["problem"] for r in rows] == [None, None]


def test_pipe_and_markup_in_names(ml):
    rows = ml.classify([model("C<b> (High)", 1, maker="A|B"), model("B|C<b> (High)", 2, maker="A", slug="y")])
    assert rows[0]["family_key"] != rows[1]["family_key"]
    assert [r["family"] for r in rows] == ["C<b>", "B|C<b>"]
