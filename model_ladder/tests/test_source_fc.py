"""Invented FrontierCode feed and page contract; no provider requests."""
import copy
from datetime import datetime, timezone

import pytest

from test_fetch import Opener, Response, http_error

MAIN = {"new_score": 0.73456, "correct": 0.5, "cost": 1.25, "tokens": 32, "flagged_rate": 0.125}
FC_FIXTURE = {"data": {"Example Model": {key: {"main": dict(MAIN)} for key in
              ("max", "xhigh", "high", "medium", "low", "minimal", "none", "na")}},
              "harness": {"Example Model": "Example Harness"}, "efforts": {}}
FC_HTML = """<p>Jan 1, 2020</p><span>FrontierCode <span>2.1</span> Current</span>
<h2>Changelog</h2><b>Nov 4, 2026</b><span>Added Example Model</span><br><i>synthetic note</i>
<b>Oct 2, 2026</b><span>Older entry</span><script>hidden</script>"""


class HtmlResponse(Response):
    def __init__(self, html):
        self._body = html.encode()
        self.headers = {}


def test_fc_flattens_and_classifies(ml):
    feed = copy.deepcopy(FC_FIXTURE)
    feed["data"]["Example Model"]["na"]["main"].update(cost=0, tokens=0)
    records = ml.validate_frontiercode(feed)
    rows = ml.classify_frontiercode(records)
    assert [r["rung"] for r in rows] == [*ml.EFFORTS, ml.NON_REASONING, None]
    assert rows[0]["scores"] == {"score": 73.46}
    assert rows[0]["axes"] == {"cost": 1.25, "tokens": 32}
    assert rows[0]["extras"] == {"flagged": 0.125}
    assert rows[0]["maker"] == "Example Harness"
    assert rows[-1]["name"] == "Example Model"
    assert rows[-1]["slug"] == "Example Model|na"
    assert rows[-1]["axes"] == {"cost": None, "tokens": None}


@pytest.mark.parametrize("kind", ["missing", "empty", "string", "range", "nan", "negative", "effort", "bool", "missing_field"])
def test_fc_rejects(ml, kind):
    feed = copy.deepcopy(FC_FIXTURE)
    main = feed["data"]["Example Model"]["max"]["main"]
    if kind == "missing": del feed["data"]
    elif kind == "empty": feed["data"] = {}
    elif kind == "string": main["new_score"] = "0.5"
    elif kind == "range": main["new_score"] = 1.1
    elif kind == "nan": main["cost"] = float("nan")
    elif kind == "negative": main["tokens"] = -1
    elif kind == "effort": feed["data"]["Example Model"]["mystery"] = {"main": main}
    elif kind == "missing_field": del main["correct"]
    else: main["correct"] = True
    with pytest.raises(ml.FetchError, match="FrontierCode 2.0"):
        ml.validate_frontiercode(feed)


def test_page_text_separates_adjacent_elements(ml):
    assert ml.page_text("<b>A<span>B</span>C</b><br>D<script>bad</script><style>bad</style>") == "A B C D"


def test_fc_page_version_and_date(ml):
    result = ml.fetch_frontiercode(None, Opener([Response(FC_FIXTURE, {"ETag": '"example"'}), HtmlResponse(FC_HTML)]))
    assert result["current_version"] == "2.1"
    assert result["published"] == {"date": "2026-11-04", "note": "Added Example Model synthetic note"}
    assert result["etag"] == '"example"'


def test_fc_long_published_note_truncates_at_word_boundary(ml):
    note = "invented " * 30
    result = ml.fetch_frontiercode(None, Opener([Response(FC_FIXTURE), HtmlResponse("<h2>Changelog</h2><b>Nov 4, 2026</b><span>" + note + "</span>")]))
    published = result["published"]["note"]
    assert published == " ".join(["invented"] * 17) + "…"
    assert len(published) <= 160


def test_fc_sends_etag_and_handles_304(ml):
    opener = Opener([http_error(304), HtmlResponse(FC_HTML)])
    result = ml.fetch_frontiercode('"old"', opener)
    assert result == {"not_modified": True, "etag": '"old"', "published": {"date": "2026-11-04", "note": "Added Example Model synthetic note"}, "current_version": "2.1"}
    assert opener.requests[0].get_header("If-none-match") == '"old"'
    assert opener.timeouts == [30, 30]


@pytest.mark.parametrize("error", [http_error(500), RuntimeError("synthetic page failure")])
def test_fc_page_failure_is_tolerated(ml, error):
    result = ml.fetch_frontiercode(None, Opener([Response(FC_FIXTURE), error]))
    assert "published" not in result and "current_version" not in result
    assert result["models"]


def test_fc_not_modified_page_failure_omits_page_keys(ml):
    result = ml.fetch_frontiercode('"old"', Opener([http_error(304), http_error(500)]))
    assert result == {"not_modified": True, "etag": '"old"'}


@pytest.mark.parametrize("failure", ["decode", "parse"])
def test_fc_page_decode_or_parse_failure_omits_page_keys(ml, failure):
    page = HtmlResponse(FC_HTML if failure == "decode" else
                        "FrontierCode 2.1 Current Changelog Feb 30, 2026 invalid")
    if failure == "decode":
        page._body = b"\xff"
    result = ml.fetch_frontiercode(None, Opener([Response(FC_FIXTURE), page]))
    assert result["models"]
    assert "published" not in result and "current_version" not in result


def test_fc_page_without_changelog_gives_none(ml):
    result = ml.fetch_frontiercode(None, Opener([Response(FC_FIXTURE), HtmlResponse("No metadata")]))
    assert result["published"] is None and result["current_version"] is None


def test_fc_user_agent(ml):
    opener = Opener([Response(FC_FIXTURE), HtmlResponse(FC_HTML)])
    ml.fetch_frontiercode(None, opener)
    assert all(r.get_header("User-agent") == ml.USER_AGENT for r in opener.requests)


def test_fc_version_string_round_trip(ml, tmp_path):
    result = ml.fetch_frontiercode(None, Opener([Response(FC_FIXTURE), HtmlResponse(FC_HTML)]))
    path = ml.save_snapshot(tmp_path, result, datetime.now(timezone.utc), source="fc")
    saved = ml.read_snapshot(path, source="fc")
    assert saved["index_version"] == "2.0"
    payload = ml.build_payload({"fc": (saved, None)}, ml.DEFAULT_CONFIG)
    assert payload["sources"]["fc"]["version_label"] == "FrontierCode 2.0"
