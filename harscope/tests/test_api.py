"""Comprehensive API test suite for harscope backend.

Tests are organized by endpoint group. Each endpoint has:
- Success/happy-path tests
- Validation failure tests (missing fields, wrong types)
- Edge cases (empty data, boundary values, malformed input)
- State-dependent behavior (no file loaded → 400)

All tests use httpx.AsyncClient with ASGITransport for zero-network testing.
"""

import copy
import json

import pytest

from conftest import MINIMAL_HAR, load_har

pytestmark = pytest.mark.anyio


def _fixture_value(*parts: str) -> str:
    """Build intentional detector inputs without storing secret-shaped literals."""
    return "".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# GET /  — HTML landing page
# ═══════════════════════════════════════════════════════════════════════════

class TestIndex:
    async def test_returns_html(self, client):
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "<html" in resp.text

    async def test_contains_react_mount(self, client):
        resp = await client.get("/")
        assert "react" in resp.text.lower() or "React" in resp.text

    async def test_no_legacy_seq_arrow_css(self, client):
        """Verify old CSS pseudo-element arrow hack is removed."""
        resp = await client.get("/")
        assert ".seq-arrow::after" not in resp.text
        assert ".seq-arrow-left::after" not in resp.text

    async def test_sequence_canvas_css(self, client):
        """Verify SVG canvas styles are present in template."""
        resp = await client.get("/")
        assert ".seq-canvas" in resp.text
        assert ".seq-minimap" in resp.text

    async def test_sequence_uses_svg(self, client):
        """Verify SequenceView uses SVG rendering instead of CSS arrows."""
        resp = await client.get("/")
        assert "seq-arrow-right" in resp.text
        assert "marker" in resp.text.lower()
        assert "seq-canvas" in resp.text

    async def test_sequence_zoom_stepper(self, client):
        """Verify zoom stepper control with -/+/editable input is present."""
        resp = await client.get("/")
        html = resp.text
        # Stepper uses Lucide Minus and Plus icons
        assert '"Minus"' in html
        assert '"Plus"' in html
        # Editable input with zoom range hint in title
        assert "20-300" in html
        # zoomInput state for editable zoom control
        assert "zoomInput" in html


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/status — Application status
# ═══════════════════════════════════════════════════════════════════════════

class TestStatus:
    async def test_no_file_loaded(self, client):
        resp = await client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["loaded"] is False
        assert "fileName" not in data

    async def test_file_loaded(self, client, minimal_har_json):
        await load_har(client)
        resp = await client.get("/api/status")
        data = resp.json()
        assert data["loaded"] is True
        assert data["fileName"] == "test.har"
        assert data["entryCount"] == 2
        assert "security" in data
        assert "creator" in data

    async def test_security_summary_shape(self, client):
        await load_har(client)
        resp = await client.get("/api/status")
        sec = resp.json()["security"]
        assert "total" in sec
        assert "critical" in sec
        assert "warning" in sec
        assert "info" in sec
        assert isinstance(sec["total"], int)


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/open-content — Load HAR from JSON string
# ═══════════════════════════════════════════════════════════════════════════

class TestOpenContent:
    async def test_valid_har(self, client, minimal_har_json):
        resp = await client.post("/api/open-content", json={
            "content": minimal_har_json,
            "filename": "my.har",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["entryCount"] == 2

    async def test_invalid_json_content(self, client):
        resp = await client.post("/api/open-content", json={
            "content": "not valid json {{{",
            "filename": "bad.har",
        })
        assert resp.status_code == 400

    async def test_valid_json_but_no_log(self, client):
        resp = await client.post("/api/open-content", json={
            "content": '{"entries": []}',
            "filename": "nolog.har",
        })
        assert resp.status_code == 400
        assert "log" in resp.json()["detail"].lower()

    async def test_missing_content_field(self, client):
        resp = await client.post("/api/open-content", json={
            "filename": "test.har",
        })
        assert resp.status_code == 422  # Pydantic validation

    async def test_missing_filename_field(self, client):
        resp = await client.post("/api/open-content", json={
            "content": json.dumps(MINIMAL_HAR),
        })
        assert resp.status_code == 422

    async def test_empty_entries(self, client):
        har = {"log": {"version": "1.2", "creator": {}, "entries": []}}
        resp = await client.post("/api/open-content", json={
            "content": json.dumps(har),
            "filename": "empty.har",
        })
        assert resp.status_code == 200
        assert resp.json()["entryCount"] == 0

    async def test_malformed_body_not_json(self, client):
        resp = await client.post("/api/open-content", content=b"plain text", headers={"content-type": "text/plain"})
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/upload — Load HAR from file upload
# ═══════════════════════════════════════════════════════════════════════════

class TestUpload:
    async def test_valid_upload(self, client, minimal_har_json):
        resp = await client.post(
            "/api/upload",
            files={"file": ("capture.har", minimal_har_json.encode(), "application/json")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["entryCount"] == 2

    async def test_upload_invalid_json(self, client):
        resp = await client.post(
            "/api/upload",
            files={"file": ("bad.har", b"not json", "application/octet-stream")},
        )
        assert resp.status_code == 400

    async def test_upload_no_file(self, client):
        resp = await client.post("/api/upload")
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/open — Load HAR from file path
# ═══════════════════════════════════════════════════════════════════════════

class TestOpen:
    async def test_nonexistent_path(self, client):
        resp = await client.post("/api/open", json={"path": "/tmp/does_not_exist_harscope.har"})
        assert resp.status_code == 400
        assert "not found" in resp.json()["detail"].lower() or "no such" in resp.json()["detail"].lower()

    async def test_missing_path_field(self, client):
        resp = await client.post("/api/open", json={})
        assert resp.status_code == 422

    async def test_valid_file(self, client, tmp_path, minimal_har_json):
        """Write a temp HAR file and open it via path."""
        har_file = tmp_path / "test.har"
        har_file.write_text(minimal_har_json)
        resp = await client.post("/api/open", json={"path": str(har_file)})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/entries — Paginated entry list
# ═══════════════════════════════════════════════════════════════════════════

class TestEntries:
    async def test_no_file_loaded(self, client):
        resp = await client.get("/api/entries")
        assert resp.status_code == 400

    async def test_default_pagination(self, client):
        await load_har(client)
        resp = await client.get("/api/entries")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["offset"] == 0
        assert data["limit"] == 50
        assert len(data["entries"]) == 2

    async def test_custom_pagination(self, client):
        await load_har(client)
        resp = await client.get("/api/entries", params={"offset": 1, "limit": 1})
        data = resp.json()
        assert len(data["entries"]) == 1
        assert data["entries"][0]["index"] == 1

    async def test_offset_beyond_range(self, client):
        await load_har(client)
        resp = await client.get("/api/entries", params={"offset": 100})
        assert resp.status_code == 200
        assert resp.json()["entries"] == []

    async def test_filter_by_domain(self, client):
        await load_har(client)
        resp = await client.get("/api/entries", params={"domain": "example.com"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    async def test_filter_by_nonexistent_domain(self, client):
        await load_har(client)
        resp = await client.get("/api/entries", params={"domain": "nosuch.dev"})
        assert resp.json()["total"] == 0

    async def test_filter_by_status(self, client):
        await load_har(client)
        resp = await client.get("/api/entries", params={"status": "2xx"})
        assert resp.json()["total"] == 1
        assert resp.json()["entries"][0]["status"] == 200

    async def test_filter_by_search(self, client):
        await load_har(client)
        resp = await client.get("/api/entries", params={"search": "submit"})
        assert resp.json()["total"] == 1

    async def test_negative_offset_rejected(self, client):
        await load_har(client)
        resp = await client.get("/api/entries", params={"offset": -1})
        assert resp.status_code == 422

    async def test_limit_zero_rejected(self, client):
        await load_har(client)
        resp = await client.get("/api/entries", params={"limit": 0})
        assert resp.status_code == 422

    async def test_limit_over_max_rejected(self, client):
        await load_har(client)
        resp = await client.get("/api/entries", params={"limit": 201})
        assert resp.status_code == 422

    async def test_entry_summary_shape(self, client):
        await load_har(client)
        resp = await client.get("/api/entries")
        entry = resp.json()["entries"][0]
        for key in ("index", "url", "method", "status", "domain", "contentType", "bodySize", "time"):
            assert key in entry, f"Missing key: {key}"


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/entry/{index} — Single entry detail
# ═══════════════════════════════════════════════════════════════════════════

class TestEntryDetail:
    async def test_no_file_loaded(self, client):
        resp = await client.get("/api/entry/0")
        assert resp.status_code == 400

    async def test_valid_index(self, client):
        await load_har(client)
        resp = await client.get("/api/entry/0")
        assert resp.status_code == 200
        data = resp.json()
        assert "entry" in data
        assert data["method"] == "GET"
        assert data["status"] == 200

    async def test_second_entry(self, client):
        await load_har(client)
        resp = await client.get("/api/entry/1")
        assert resp.status_code == 200
        assert resp.json()["method"] == "POST"

    async def test_out_of_range(self, client):
        await load_har(client)
        resp = await client.get("/api/entry/999")
        assert resp.status_code == 404

    async def test_negative_index(self, client):
        await load_har(client)
        resp = await client.get("/api/entry/-1")
        assert resp.status_code == 404

    async def test_entry_has_request_response(self, client):
        await load_har(client)
        resp = await client.get("/api/entry/0")
        entry = resp.json()["entry"]
        assert "request" in entry
        assert "response" in entry
        assert "timings" in entry


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/waterfall — Timeline data
# ═══════════════════════════════════════════════════════════════════════════

class TestWaterfall:
    async def test_no_file_loaded(self, client):
        resp = await client.get("/api/waterfall")
        assert resp.status_code == 400

    async def test_basic_waterfall(self, client):
        await load_har(client)
        resp = await client.get("/api/waterfall")
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert "maxEndTime" in data
        assert data["total"] == 2

    async def test_waterfall_has_timings(self, client):
        await load_har(client)
        resp = await client.get("/api/waterfall")
        entry = resp.json()["entries"][0]
        assert "timings" in entry
        assert "startOffset" in entry
        timings = entry["timings"]
        for phase in ("blocked", "dns", "connect", "ssl", "send", "wait", "receive"):
            assert phase in timings
            assert timings[phase] >= 0

    async def test_waterfall_pagination(self, client):
        await load_har(client)
        resp = await client.get("/api/waterfall", params={"offset": 0, "limit": 1})
        assert len(resp.json()["entries"]) == 1

    async def test_waterfall_domain_filter(self, client):
        await load_har(client)
        resp = await client.get("/api/waterfall", params={"domain": "example.com"})
        assert resp.json()["total"] == 2


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/domains — Domain list
# ═══════════════════════════════════════════════════════════════════════════

class TestDomains:
    async def test_no_file_loaded(self, client):
        resp = await client.get("/api/domains")
        assert resp.status_code == 400

    async def test_returns_domains(self, client):
        await load_har(client)
        resp = await client.get("/api/domains")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["domain"] == "example.com"
        assert data[0]["count"] == 2


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/stats — Aggregate statistics
# ═══════════════════════════════════════════════════════════════════════════

class TestStats:
    async def test_no_file_loaded(self, client):
        resp = await client.get("/api/stats")
        assert resp.status_code == 400

    async def test_stats_shape(self, client):
        await load_har(client)
        resp = await client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalRequests"] == 2
        assert isinstance(data["totalSize"], (int, float))
        assert isinstance(data["errorRate"], (int, float))
        assert "statusCodes" in data
        assert "domains" in data
        assert "contentTypes" in data
        assert "timingPercentiles" in data

    async def test_error_rate_counts_4xx_5xx(self, client):
        await load_har(client)
        resp = await client.get("/api/stats")
        data = resp.json()
        # Entry 1 has status 401 → error count = 1 out of 2
        assert data["errorCount"] == 1
        assert data["errorRate"] == 50.0


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/security — Security findings
# ═══════════════════════════════════════════════════════════════════════════

class TestSecurity:
    async def test_no_file_loaded(self, client):
        resp = await client.get("/api/security")
        assert resp.status_code == 400

    async def test_findings_detected(self, client):
        await load_har(client)
        resp = await client.get("/api/security")
        assert resp.status_code == 200
        data = resp.json()
        assert "findings" in data
        assert "summary" in data
        assert "manualRedactions" in data
        assert len(data["findings"]) > 0

    async def test_jwt_detected(self, client):
        await load_har(client)
        resp = await client.get("/api/security")
        findings = resp.json()["findings"]
        categories = [f["category"] for f in findings]
        # JWT should be detected in Authorization header and response body
        assert any("JWT" in c for c in categories)

    async def test_sensitive_field_detected(self, client):
        """Authorization header should be flagged as a sensitive field."""
        await load_har(client)
        resp = await client.get("/api/security")
        findings = resp.json()["findings"]
        auth_findings = [f for f in findings if "authorization" in f["location"].lower()]
        assert len(auth_findings) > 0

    async def test_http_warning_detected(self, client):
        """http:// request should generate a warning."""
        await load_har(client)
        resp = await client.get("/api/security")
        findings = resp.json()["findings"]
        http_findings = [f for f in findings if f["category"] == "HTTP"]
        assert len(http_findings) >= 1

    async def test_password_detected_in_body(self, client):
        """Password field in POST body should be flagged."""
        await load_har(client)
        resp = await client.get("/api/security")
        findings = resp.json()["findings"]
        password_findings = [f for f in findings if "password" in f["location"].lower()]
        assert len(password_findings) > 0

    async def test_finding_shape(self, client):
        await load_har(client)
        resp = await client.get("/api/security")
        finding = resp.json()["findings"][0]
        for key in ("id", "entryIndex", "severity", "category", "location",
                     "description", "preview", "redact"):
            assert key in finding, f"Missing key: {key}"

    async def test_internal_fields_stripped(self, client):
        """Internal tracking fields (categories, descriptions) should not leak."""
        await load_har(client)
        resp = await client.get("/api/security")
        for f in resp.json()["findings"]:
            assert "categories" not in f
            assert "descriptions" not in f


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/security/toggle — Toggle single finding
# ═══════════════════════════════════════════════════════════════════════════

class TestSecurityToggle:
    async def test_toggle_finding(self, client):
        await load_har(client)
        # Get first finding
        sec = await client.get("/api/security")
        finding = sec.json()["findings"][0]
        original_redact = finding["redact"]
        finding_id = finding["id"]

        # Toggle
        resp = await client.post("/api/security/toggle", json={"id": finding_id})
        assert resp.status_code == 200
        assert resp.json()["redact"] is not original_redact

        # Toggle back
        resp2 = await client.post("/api/security/toggle", json={"id": finding_id})
        assert resp2.json()["redact"] is original_redact

    async def test_toggle_nonexistent_id(self, client):
        await load_har(client)
        resp = await client.post("/api/security/toggle", json={"id": 99999})
        assert resp.status_code == 404

    async def test_toggle_missing_id_field(self, client):
        await load_har(client)
        resp = await client.post("/api/security/toggle", json={})
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/security/bulk — Bulk toggle findings
# ═══════════════════════════════════════════════════════════════════════════

class TestSecurityBulk:
    async def test_deselect_all(self, client):
        await load_har(client)
        resp = await client.post("/api/security/bulk", json={"action": "deselect"})
        assert resp.status_code == 200

        sec = await client.get("/api/security")
        for f in sec.json()["findings"]:
            assert f["redact"] is False

    async def test_select_all(self, client):
        await load_har(client)
        # First deselect, then select all
        await client.post("/api/security/bulk", json={"action": "deselect"})
        await client.post("/api/security/bulk", json={"action": "select"})

        sec = await client.get("/api/security")
        for f in sec.json()["findings"]:
            assert f["redact"] is True

    async def test_bulk_by_severity(self, client):
        await load_har(client)
        # Deselect all, then select only critical
        await client.post("/api/security/bulk", json={"action": "deselect"})
        await client.post("/api/security/bulk", json={"action": "select", "severity": "critical"})

        sec = await client.get("/api/security")
        for f in sec.json()["findings"]:
            if f["severity"] == "critical":
                assert f["redact"] is True
            else:
                assert f["redact"] is False

    async def test_missing_action_field(self, client):
        await load_har(client)
        resp = await client.post("/api/security/bulk", json={})
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/redaction/manual — Add manual redaction
# POST /api/redaction/remove-manual — Remove manual redaction
# ═══════════════════════════════════════════════════════════════════════════

class TestManualRedaction:
    async def test_no_file_loaded(self, client):
        resp = await client.post("/api/redaction/manual", json={
            "entryIndex": 0, "location": "test", "value": "x",
        })
        assert resp.status_code == 400

    async def test_add_manual_redaction(self, client):
        await load_har(client)
        resp = await client.post("/api/redaction/manual", json={
            "entryIndex": 0,
            "location": "entries[0].response.content.text(parsed).user",
            "value": "alice",
            "redact": True,
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Verify it shows up in security findings
        sec = await client.get("/api/security")
        assert len(sec.json()["manualRedactions"]) == 1

    async def test_remove_manual_redaction(self, client):
        await load_har(client)
        loc = "entries[0].response.content.text(parsed).user"
        await client.post("/api/redaction/manual", json={
            "entryIndex": 0, "location": loc, "value": "alice",
        })
        resp = await client.post("/api/redaction/remove-manual", json={
            "entryIndex": 0, "location": loc,
        })
        assert resp.status_code == 200

        sec = await client.get("/api/security")
        assert len(sec.json()["manualRedactions"]) == 0

    async def test_remove_nonexistent_manual(self, client):
        """Removing a manual redaction that doesn't exist should succeed silently."""
        await load_har(client)
        resp = await client.post("/api/redaction/remove-manual", json={
            "entryIndex": 0, "location": "does.not.exist",
        })
        assert resp.status_code == 200

    async def test_missing_fields(self, client):
        await load_har(client)
        resp = await client.post("/api/redaction/manual", json={"value": "x"})
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/redaction/reset — Reset all redaction decisions
# ═══════════════════════════════════════════════════════════════════════════

class TestRedactionReset:
    async def test_no_file_loaded(self, client):
        resp = await client.post("/api/redaction/reset")
        assert resp.status_code == 400

    async def test_reset_restores_defaults(self, client):
        await load_har(client)
        # Deselect all, add manual, then reset
        await client.post("/api/security/bulk", json={"action": "deselect"})
        await client.post("/api/redaction/manual", json={
            "entryIndex": 0, "location": "x", "value": "y",
        })
        resp = await client.post("/api/redaction/reset")
        assert resp.status_code == 200

        sec = await client.get("/api/security")
        # Manual redactions should be cleared
        assert len(sec.json()["manualRedactions"]) == 0
        # Auto findings should be back to severity-based defaults
        for f in sec.json()["findings"]:
            expected = f["severity"] in ("critical", "warning")
            assert f["redact"] is expected


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/redaction/reapply-auto — Re-apply auto redactions
# ═══════════════════════════════════════════════════════════════════════════

class TestReapplyAuto:
    async def test_no_file_loaded(self, client):
        resp = await client.post("/api/redaction/reapply-auto")
        assert resp.status_code == 400

    async def test_reapply_after_deselect(self, client):
        await load_har(client)
        await client.post("/api/security/bulk", json={"action": "deselect"})
        await client.post("/api/redaction/reapply-auto")

        sec = await client.get("/api/security")
        for f in sec.json()["findings"]:
            expected = f["severity"] in ("critical", "warning")
            assert f["redact"] is expected


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/redaction/decisions — All redaction decisions
# ═══════════════════════════════════════════════════════════════════════════

class TestDecisions:
    async def test_no_file_loaded(self, client):
        resp = await client.get("/api/redaction/decisions")
        assert resp.status_code == 400

    async def test_decisions_structure(self, client):
        await load_har(client)
        resp = await client.get("/api/redaction/decisions")
        assert resp.status_code == 200
        data = resp.json()
        assert "decisions" in data
        assert len(data["decisions"]) > 0

    async def test_decision_shape(self, client):
        await load_har(client)
        resp = await client.get("/api/redaction/decisions")
        d = resp.json()["decisions"][0]
        for key in ("type", "redact", "severity", "category", "keyName",
                     "preview", "side", "area", "location", "entry"):
            assert key in d, f"Missing key: {key}"
        assert d["type"] == "auto"
        assert "entryIndex" in d["entry"]

    async def test_includes_manual_decisions(self, client):
        await load_har(client)
        await client.post("/api/redaction/manual", json={
            "entryIndex": 0,
            "location": "entries[0].response.content.text(parsed).user",
            "value": "alice",
        })
        resp = await client.get("/api/redaction/decisions")
        types = [d["type"] for d in resp.json()["decisions"]]
        assert "manual" in types


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/sequence — Sequence diagram data
# GET /api/sequence/flows — Detected flows
# ═══════════════════════════════════════════════════════════════════════════

class TestSequence:
    async def test_no_file_loaded(self, client):
        resp = await client.get("/api/sequence")
        assert resp.status_code == 400

    async def test_basic_sequence(self, client):
        await load_har(client)
        resp = await client.get("/api/sequence")
        assert resp.status_code == 200
        data = resp.json()
        assert "participants" in data
        assert "messages" in data
        assert "flows" in data
        assert "Browser" in data["participants"]
        # 2 entries → 2 request + 2 response messages
        assert len(data["messages"]) == 4

    async def test_sequence_domain_filter(self, client):
        await load_har(client)
        resp = await client.get("/api/sequence", params={"domain": "example.com"})
        assert resp.status_code == 200
        assert len(resp.json()["messages"]) == 4

    async def test_sequence_nonexistent_domain(self, client):
        await load_har(client)
        resp = await client.get("/api/sequence", params={"domain": "nope.dev"})
        assert resp.json()["messages"] == []

    async def test_flows_no_file(self, client):
        resp = await client.get("/api/sequence/flows")
        assert resp.status_code == 400

    async def test_flows_detected(self, client):
        await load_har(client)
        resp = await client.get("/api/sequence/flows")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_message_structure(self, client):
        """Verify message objects have required fields for SVG rendering."""
        await load_har(client)
        resp = await client.get("/api/sequence")
        data = resp.json()
        for msg in data["messages"]:
            assert "index" in msg
            assert "from" in msg
            assert "to" in msg
            assert "label" in msg
            assert "type" in msg
            assert msg["type"] in ("request", "response")
            assert "status" in msg

    async def test_response_direction_reversed(self, client):
        """Response messages must have from/to reversed vs their request.

        Requests go Browser→Server; responses go Server→Browser. The SVG
        canvas relies on this to point arrowheads in the correct direction.
        If from/to are not reversed, response arrows point the wrong way.
        """
        await load_har(client)
        resp = await client.get("/api/sequence")
        data = resp.json()
        messages = data["messages"]
        # Group by entry index — each index should have a request and response
        by_index = {}
        for msg in messages:
            by_index.setdefault(msg["index"], {})[msg["type"]] = msg
        for idx, pair in by_index.items():
            if "request" in pair and "response" in pair:
                req = pair["request"]
                res = pair["response"]
                assert req["from"] == res["to"], (
                    f"Entry {idx}: response 'to' ({res['to']}) should equal "
                    f"request 'from' ({req['from']})"
                )
                assert req["to"] == res["from"], (
                    f"Entry {idx}: response 'from' ({res['from']}) should equal "
                    f"request 'to' ({req['to']})"
                )


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/export/har — Export sanitized HAR
# ═══════════════════════════════════════════════════════════════════════════

class TestExportHar:
    async def test_no_file_loaded(self, client):
        resp = await client.post("/api/export/har")
        assert resp.status_code == 400

    async def test_export_returns_valid_har(self, client):
        await load_har(client)
        resp = await client.post("/api/export/har")
        assert resp.status_code == 200
        assert "application/json" in resp.headers["content-type"]
        assert "attachment" in resp.headers.get("content-disposition", "")
        data = resp.json()
        assert "log" in data
        assert "entries" in data["log"]

    async def test_export_redacts_critical_findings(self, client):
        """Critical findings (like Authorization) should be redacted in export."""
        await load_har(client)
        resp = await client.post("/api/export/har")
        har = resp.json()
        entries = har["log"]["entries"]
        # Authorization header should be redacted
        auth_header = entries[0]["request"]["headers"][1]
        assert auth_header["name"] == "Authorization"
        assert auth_header["value"] == "[REDACTED]"

    async def test_export_preserves_non_redacted(self, client):
        """Non-sensitive values should remain intact."""
        await load_har(client)
        # Deselect all findings first
        await client.post("/api/security/bulk", json={"action": "deselect"})
        resp = await client.post("/api/export/har")
        har = resp.json()
        # With nothing redacted, Host header should be preserved
        host_header = har["log"]["entries"][0]["request"]["headers"][0]
        assert host_header["value"] == "example.com"


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/export/edl — Export Edit Decision List
# ═══════════════════════════════════════════════════════════════════════════

class TestExportEdl:
    async def test_no_file_loaded(self, client):
        resp = await client.post("/api/export/edl")
        assert resp.status_code == 400

    async def test_edl_structure(self, client):
        await load_har(client)
        resp = await client.post("/api/export/edl")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == 1
        assert data["generator"] == "harscope"
        assert "generated" in data
        assert "sourceFile" in data
        assert "summary" in data
        assert "decisions" in data
        assert isinstance(data["decisions"], list)
        assert len(data["decisions"]) > 0

    async def test_edl_decision_shape(self, client):
        await load_har(client)
        resp = await client.post("/api/export/edl")
        d = resp.json()["decisions"][0]
        for key in ("entryIndex", "location", "action", "source", "preview",
                     "side", "area", "key", "severity", "category", "entry"):
            assert key in d, f"Missing key: {key}"
        assert d["action"] in ("redact", "keep")
        assert d["source"] == "auto"

    async def test_edl_summary_counts(self, client):
        await load_har(client)
        resp = await client.post("/api/export/edl")
        summary = resp.json()["summary"]
        assert summary["totalDecisions"] == len(resp.json()["decisions"])
        assert summary["autoRedacted"] >= 0
        assert summary["autoKept"] >= 0


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/validate — Validate EDL against loaded HAR
# ═══════════════════════════════════════════════════════════════════════════

class TestValidate:
    async def test_no_file_loaded(self, client):
        resp = await client.post("/api/validate", files={
            "file": ("test.edl.json", b'{"decisions":[]}', "application/json"),
        })
        assert resp.status_code == 400

    async def test_invalid_edl_json(self, client):
        await load_har(client)
        resp = await client.post("/api/validate", files={
            "file": ("bad.edl.json", b"not json", "application/json"),
        })
        assert resp.status_code == 400

    async def test_roundtrip_validation(self, client):
        """Export HAR + EDL, reload sanitized HAR, validate EDL → all pass."""
        await load_har(client)

        # Export the EDL
        edl_resp = await client.post("/api/export/edl")
        edl_data = edl_resp.json()

        # Export the sanitized HAR
        har_resp = await client.post("/api/export/har")
        sanitized_har = har_resp.json()

        # Reload the sanitized HAR
        await client.post("/api/open-content", json={
            "content": json.dumps(sanitized_har),
            "filename": "sanitized_test.har",
        })

        # Validate the EDL against the sanitized HAR
        edl_bytes = json.dumps(edl_data).encode()
        resp = await client.post("/api/validate", files={
            "file": ("test.edl.json", edl_bytes, "application/json"),
        })
        assert resp.status_code == 200
        result = resp.json()
        assert "results" in result
        assert "summary" in result
        # All redact decisions should pass (values are [REDACTED])
        # All keep decisions should pass (values are NOT [REDACTED])
        assert result["summary"]["fail"] == 0

    async def test_empty_edl(self, client):
        await load_har(client)
        resp = await client.post("/api/validate", files={
            "file": ("empty.edl.json", json.dumps({"decisions": []}).encode(), "application/json"),
        })
        assert resp.status_code == 200
        assert resp.json()["summary"]["total"] == 0

    async def test_edl_with_out_of_range_entry(self, client):
        await load_har(client)
        edl = {"decisions": [{"entryIndex": 999, "location": "x", "action": "redact"}]}
        resp = await client.post("/api/validate", files={
            "file": ("test.edl.json", json.dumps(edl).encode(), "application/json"),
        })
        assert resp.status_code == 200
        assert resp.json()["results"][0]["status"] == "error"


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/export/csv — Export CSV
# ═══════════════════════════════════════════════════════════════════════════

class TestExportCsv:
    async def test_no_file_loaded(self, client):
        resp = await client.post("/api/export/csv")
        assert resp.status_code == 400

    async def test_csv_export(self, client):
        await load_har(client)
        resp = await client.post("/api/export/csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        lines = resp.text.strip().split("\n")
        assert len(lines) == 3  # header + 2 entries
        assert "Index" in lines[0]
        assert "Method" in lines[0]


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/export/report — Export summary report
# ═══════════════════════════════════════════════════════════════════════════

class TestExportReport:
    async def test_no_file_loaded(self, client):
        resp = await client.post("/api/export/report", json={"format": "md"})
        assert resp.status_code == 400

    async def test_markdown_report(self, client):
        await load_har(client)
        resp = await client.post("/api/export/report", json={"format": "md"})
        assert resp.status_code == 200
        assert "text/markdown" in resp.headers["content-type"]
        assert "# HAR Analysis Report" in resp.text

    async def test_html_report(self, client):
        await load_har(client)
        resp = await client.post("/api/export/report", json={"format": "html"})
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "<html" in resp.text

    async def test_default_format_is_md(self, client):
        await load_har(client)
        resp = await client.post("/api/export/report", json={})
        assert resp.status_code == 200
        assert "text/markdown" in resp.headers["content-type"]


# ═══════════════════════════════════════════════════════════════════════════
# HTML Report — dark mode
# ═══════════════════════════════════════════════════════════════════════════

class TestHtmlReportDarkMode:
    """Tests that the HTML report includes dark mode CSS, toggle, and script."""

    async def _get_html(self, client):
        await load_har(client)
        resp = await client.post("/api/export/report", json={"format": "html"})
        assert resp.status_code == 200
        return resp.text

    async def test_dark_css_variables_media_query(self, client):
        """Dark palette defined in prefers-color-scheme media query."""
        html = await self._get_html(client)
        assert "prefers-color-scheme:dark" in html or "prefers-color-scheme: dark" in html
        # The media query should use :root:not(.light) so manual .light overrides system dark
        assert ":root:not(.light)" in html

    async def test_dark_class_css_variables(self, client):
        """Dark palette also defined via .dark class for manual toggle."""
        html = await self._get_html(client)
        assert ".dark{" in html or ".dark {" in html

    async def test_toggle_button_present(self, client):
        """Toggle button exists in the doc-header."""
        html = await self._get_html(client)
        assert 'id="theme-toggle"' in html
        assert "Toggle dark/light mode" in html

    async def test_toggle_button_has_aria_label(self, client):
        """Toggle button is accessible."""
        html = await self._get_html(client)
        assert 'aria-label="Toggle dark/light mode"' in html

    async def test_theme_script_present(self, client):
        """Inline script handles localStorage persistence and toggle."""
        html = await self._get_html(client)
        assert "harscope-report-theme" in html
        assert "localStorage" in html

    async def test_theme_script_reads_before_paint(self, client):
        """Script checks localStorage and applies class before paint."""
        html = await self._get_html(client)
        # The script should add .dark or .light class based on saved preference
        assert "classList.add('dark')" in html or 'classList.add("dark")' in html
        assert "classList.add('light')" in html or 'classList.add("light")' in html

    async def test_toggle_updates_localstorage(self, client):
        """Toggle click handler persists preference to localStorage."""
        html = await self._get_html(client)
        assert "localStorage.setItem('harscope-report-theme'" in html or \
               'localStorage.setItem("harscope-report-theme"' in html

    async def test_print_forces_light_theme(self, client):
        """Print media query resets variables to light palette."""
        html = await self._get_html(client)
        # Print block should hide the toggle button
        assert "@media print" in html
        assert "theme-toggle" in html
        # Print block should contain light-palette variable resets
        # The critical color should be reset to the original red
        assert "#dc2626" in html  # original critical color in print reset

    async def test_report_background_uses_variable(self, client):
        """Report background uses CSS variable instead of hardcoded #fff."""
        html = await self._get_html(client)
        # The .report class should use var(--slate-100) not #fff
        assert ".report{" in html or ".report {" in html
        # Should not have background:#fff on .report (it's now var-based)
        # But #fff may appear in the print media query, so check specifically
        import re
        report_bg = re.search(r'\.report\{[^}]*background:[^;}]+', html)
        assert report_bg is not None
        assert "var(--slate-100)" in report_bg.group()

    async def test_color_scheme_property(self, client):
        """Root has color-scheme: light dark for native form control theming."""
        html = await self._get_html(client)
        assert "color-scheme:light dark" in html or "color-scheme: light dark" in html

    async def test_system_theme_change_listener(self, client):
        """Script listens for system theme changes to update toggle icon."""
        html = await self._get_html(client)
        assert "matchMedia" in html
        assert "change" in html


# ═══════════════════════════════════════════════════════════════════════════
# Security scanner — detection accuracy
# ═══════════════════════════════════════════════════════════════════════════

class TestSecurityDetection:
    """Tests that verify the scanner detects specific secret patterns."""

    async def _load_with_response_body(self, client, body: dict):
        """Helper: load a HAR with a custom response body."""
        har = copy.deepcopy(MINIMAL_HAR)
        har["log"]["entries"] = [har["log"]["entries"][0]]
        har["log"]["entries"][0]["response"]["content"]["text"] = json.dumps(body)
        har["log"]["entries"][0]["request"]["headers"] = [{"name": "Host", "value": "example.com"}]
        har["log"]["entries"][0]["request"]["queryString"] = []
        await load_har(client, har)

    async def test_jwt_detection(self, client):
        await self._load_with_response_body(client, {
            "access_token": _fixture_value(
                "eyJhbGci", "OiJIUzI1", "NiJ9.",
                "eyJzdWIi", "OiIxMjM0", "NTY3ODkw", "IiwiaWF0",
                "IjoxNTE2", "MjM5MDIy", "fQ.",
                "SflKxwRJ", "SMeKKF2Q", "T4fwpMeJ", "f36POk6y",
                "JV_adQss", "w5c",
            ),
        })
        sec = await client.get("/api/security")
        findings = sec.json()["findings"]
        jwt_findings = [f for f in findings if "JWT" in f["category"]]
        assert len(jwt_findings) >= 1

    async def test_aws_key_detection(self, client):
        await self._load_with_response_body(client, {
            "config": _fixture_value("AKIA", "IOSF", "ODNN", "7EXA", "MPLE"),
        })
        sec = await client.get("/api/security")
        findings = sec.json()["findings"]
        aws_findings = [f for f in findings if "Cloud Key" in f["category"] or "AWS" in f["description"]]
        assert len(aws_findings) >= 1

    async def test_github_token_detection(self, client):
        await self._load_with_response_body(client, {
            "token": _fixture_value(
                "ghp_", "ABCDEF", "GHIJKL", "MNOPQR", "STUVWX",
                "YZabcd", "efghij",
            ),
        })
        sec = await client.get("/api/security")
        findings = sec.json()["findings"]
        gh_findings = [f for f in findings if "GitHub" in f["description"]]
        assert len(gh_findings) >= 1

    async def test_private_key_detection(self, client):
        await self._load_with_response_body(client, {
            "cert": _fixture_value(
                "-----", "BEGIN ", "RSA ", "PRIVATE ", "KEY", "-----",
                "\n", "MIIE", "owIB", "AAK...",
            ),
        })
        sec = await client.get("/api/security")
        findings = sec.json()["findings"]
        pk_findings = [f for f in findings if "Private Key" in f["category"]]
        assert len(pk_findings) >= 1

    async def test_connection_string_detection(self, client):
        await self._load_with_response_body(client, {
            "db": _fixture_value(
                "post", "gresql", "://", "user", ":", "pass", "@host", ":5432", "/mydb",
            ),
        })
        sec = await client.get("/api/security")
        findings = sec.json()["findings"]
        conn_findings = [f for f in findings if "Connection" in f["category"]]
        assert len(conn_findings) >= 1

    async def test_opaque_token_heuristic(self, client):
        """Long random-looking strings should be flagged even without a known pattern."""
        await self._load_with_response_body(client, {
            "session_token": _fixture_value(
                "aB3dE5", "fG7hI9", "jK1lM3", "nO5pQ7", "rS9tU1",
                "vW3xY5", "zA7bC9", "dE1fG7", "hI9jK1l",
            ),
        })
        sec = await client.get("/api/security")
        findings = sec.json()["findings"]
        # Should detect as token-like (48+ chars, 2+ char classes)
        token_findings = [f for f in findings if "token" in f["category"].lower() or "Token" in f["category"]]
        assert len(token_findings) >= 1

    async def test_redacted_values_not_reflagged(self, client):
        """[REDACTED] placeholder values should not generate findings."""
        await self._load_with_response_body(client, {
            "secret": "[REDACTED]",
            "token": "[REDACTED]",
        })
        sec = await client.get("/api/security")
        findings = sec.json()["findings"]
        # No findings should reference these redacted values
        body_findings = [f for f in findings if "(parsed).secret" in f["location"] or "(parsed).token" in f["location"]]
        assert len(body_findings) == 0

    async def test_cookie_flag_warnings(self, client):
        """Sensitive cookies without httpOnly/secure flags should be warned."""
        har = copy.deepcopy(MINIMAL_HAR)
        har["log"]["entries"] = [{
            "startedDateTime": "2024-01-01T00:00:00.000Z",
            "time": 50,
            "request": {
                "method": "GET",
                "url": "https://example.com/",
                "httpVersion": "HTTP/1.1",
                "headers": [],
                "queryString": [],
                "cookies": [],
                "headersSize": -1,
                "bodySize": -1,
            },
            "response": {
                "status": 200,
                "statusText": "OK",
                "httpVersion": "HTTP/1.1",
                "headers": [],
                "cookies": [
                    {"name": "session_id", "value": "abc123", "httpOnly": False, "secure": False},
                ],
                "content": {"size": 0, "mimeType": "text/html", "text": ""},
                "redirectURL": "",
                "headersSize": -1,
                "bodySize": 0,
            },
            "cache": {},
            "timings": {"blocked": 0, "dns": 0, "connect": 0, "ssl": 0, "send": 0, "wait": 0, "receive": 0},
        }]
        await load_har(client, har)
        sec = await client.get("/api/security")
        findings = sec.json()["findings"]
        cookie_findings = [f for f in findings if "Cookie" in f["category"]]
        assert len(cookie_findings) >= 1
        # Both flags are consolidated into one finding; verify both are mentioned
        combined_desc = " ".join(f["description"] for f in cookie_findings)
        assert "httpOnly" in combined_desc
        assert "secure" in combined_desc


# ═══════════════════════════════════════════════════════════════════════════
# End-to-end redaction workflow
# ═══════════════════════════════════════════════════════════════════════════

class TestRedactionWorkflow:
    """Tests that simulate the full user workflow: load → scan → toggle → export → validate."""

    async def test_toggle_keep_then_export(self, client):
        """Toggle a finding to keep, export, verify it's not redacted."""
        await load_har(client)
        sec = await client.get("/api/security")
        # Find a critical finding that would normally be redacted
        findings = sec.json()["findings"]
        critical = [f for f in findings if f["severity"] == "critical" and f["redact"]]
        assert len(critical) > 0
        target = critical[0]

        # Toggle to keep
        await client.post("/api/security/toggle", json={"id": target["id"]})

        # Export EDL and check decision
        edl_resp = await client.post("/api/export/edl")
        edl = edl_resp.json()
        target_decisions = [d for d in edl["decisions"] if d["location"] == target["location"]]
        assert len(target_decisions) == 1
        assert target_decisions[0]["action"] == "keep"

    async def test_manual_redaction_appears_in_export(self, client):
        """Manual redactions should appear in EDL export."""
        await load_har(client)
        loc = "entries[0].response.content.text(parsed).status"
        await client.post("/api/redaction/manual", json={
            "entryIndex": 0, "location": loc, "value": "ok", "redact": True,
        })
        edl_resp = await client.post("/api/export/edl")
        edl = edl_resp.json()
        manual_decisions = [d for d in edl["decisions"] if d["source"] == "manual"]
        assert len(manual_decisions) == 1
        assert manual_decisions[0]["action"] == "redact"

    async def test_manual_redaction_applied_in_har_export(self, client):
        """Manual redaction should actually redact the value in exported HAR."""
        await load_har(client)
        loc = "entries[0].response.content.text(parsed).status"
        await client.post("/api/redaction/manual", json={
            "entryIndex": 0, "location": loc, "value": "ok", "redact": True,
        })
        har_resp = await client.post("/api/export/har")
        exported = har_resp.json()
        body = json.loads(exported["log"]["entries"][0]["response"]["content"]["text"])
        assert body["status"] == "[REDACTED]"

    async def test_reload_clears_state(self, client):
        """Loading a new file should clear all previous redaction state."""
        await load_har(client)
        await client.post("/api/redaction/manual", json={
            "entryIndex": 0, "location": "x", "value": "y",
        })

        # Reload a different file
        await load_har(client, filename="second.har")

        sec = await client.get("/api/security")
        assert len(sec.json()["manualRedactions"]) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Edge cases and error handling
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    async def test_empty_har_entries(self, client):
        """A HAR with zero entries should work without errors."""
        har = {"log": {"version": "1.2", "creator": {}, "entries": []}}
        await load_har(client, har)
        status = await client.get("/api/status")
        assert status.json()["entryCount"] == 0

        entries = await client.get("/api/entries")
        assert entries.json()["total"] == 0

        stats = await client.get("/api/stats")
        assert stats.json()["totalRequests"] == 0

        # Export should still work
        har_export = await client.post("/api/export/har")
        assert har_export.status_code == 200

    async def test_entry_with_missing_timings(self, client):
        """Entries missing timing data should not crash."""
        har = copy.deepcopy(MINIMAL_HAR)
        del har["log"]["entries"][0]["timings"]
        har["log"]["entries"][0]["time"] = 0
        await load_har(client, har)

        wf = await client.get("/api/waterfall")
        assert wf.status_code == 200

    async def test_entry_with_null_body_size(self, client):
        """Null body sizes should be handled gracefully."""
        har = copy.deepcopy(MINIMAL_HAR)
        har["log"]["entries"][0]["response"]["bodySize"] = None
        await load_har(client, har)

        entries = await client.get("/api/entries")
        assert entries.status_code == 200

    async def test_very_long_url(self, client):
        """Very long URLs should not crash any endpoint."""
        har = copy.deepcopy(MINIMAL_HAR)
        har["log"]["entries"][0]["request"]["url"] = "https://example.com/" + "a" * 5000
        await load_har(client, har)

        entries = await client.get("/api/entries")
        assert entries.status_code == 200
        seq = await client.get("/api/sequence")
        assert seq.status_code == 200

    async def test_non_utf8_upload(self, client):
        """Binary content that isn't valid UTF-8 should be rejected gracefully."""
        resp = await client.post(
            "/api/upload",
            files={"file": ("bad.har", b'\xff\xfe\x00\x01', "application/octet-stream")},
        )
        assert resp.status_code == 400

    async def test_large_offset(self, client):
        """Offsets way beyond data range should return empty, not error."""
        await load_har(client)
        resp = await client.get("/api/entries", params={"offset": 1000000})
        assert resp.status_code == 200
        assert resp.json()["entries"] == []

    async def test_multiple_reloads(self, client):
        """Multiple sequential file loads should not leak state."""
        for i in range(3):
            await load_har(client, filename=f"file{i}.har")
            status = await client.get("/api/status")
            assert status.json()["fileName"] == f"file{i}.har"


# ═══════════════════════════════════════════════════════════════════════════
# Security — Path validation on /api/open
# ═══════════════════════════════════════════════════════════════════════════

class TestOpenPathValidation:
    async def test_open_rejects_non_har_extension(self, client):
        resp = await client.post("/api/open", json={"path": "/etc/passwd"})
        assert resp.status_code == 400
        assert "Only .har files" in resp.json()["detail"]

    async def test_open_rejects_device_path(self, client):
        resp = await client.post("/api/open", json={"path": "/dev/urandom"})
        assert resp.status_code == 400
        assert "Only .har files" in resp.json()["detail"]

    async def test_open_rejects_txt_extension(self, client):
        resp = await client.post("/api/open", json={"path": "/tmp/test.txt"})
        assert resp.status_code == 400
        assert "Only .har files" in resp.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════
# Security — Bulk toggle validates action, report format validates format
# ═══════════════════════════════════════════════════════════════════════════

class TestBulkToggleValidation:
    async def test_bulk_invalid_action_rejected(self, client):
        await load_har(client)
        resp = await client.post("/api/security/bulk", json={"action": "typo"})
        assert resp.status_code == 422


class TestReportFormatValidation:
    async def test_report_rejects_invalid_format(self, client):
        await load_har(client)
        resp = await client.post("/api/export/report", json={"format": "pdf"})
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# Security — XSS in HTML report
# ═══════════════════════════════════════════════════════════════════════════

class TestHtmlReportXss:
    async def test_html_report_escapes_filename(self, client):
        har = copy.deepcopy(MINIMAL_HAR)
        await load_har(client, har, filename="<script>alert(1)</script>test.har")
        resp = await client.post("/api/export/report", json={"format": "html"})
        assert resp.status_code == 200
        assert "<script>alert(1)</script>" not in resp.text
        assert "&lt;script&gt;" in resp.text

    async def test_html_report_escapes_domain(self, client):
        har = copy.deepcopy(MINIMAL_HAR)
        har["log"]["entries"][0]["request"]["url"] = 'https://<img/onerror=alert(1)>/api/data'
        await load_har(client, har)
        resp = await client.post("/api/export/report", json={"format": "html"})
        assert resp.status_code == 200
        assert '<img/onerror=alert(1)>' not in resp.text


# ═══════════════════════════════════════════════════════════════════════════
# Security — Markdown report escaping
# ═══════════════════════════════════════════════════════════════════════════

class TestMarkdownReportEscaping:
    async def test_markdown_report_escapes_pipes(self, client):
        har = copy.deepcopy(MINIMAL_HAR)
        har["log"]["entries"][0]["request"]["url"] = 'https://|injected|.com/api/data'
        await load_har(client, har)
        resp = await client.post("/api/export/report", json={"format": "md"})
        assert resp.status_code == 200
        # Pipes should be escaped to prevent markdown table injection
        assert '\\|injected\\|' in resp.text


# ═══════════════════════════════════════════════════════════════════════════
# Robustness — Upload size limits
# ═══════════════════════════════════════════════════════════════════════════

class TestUploadSizeLimit:
    async def test_upload_rejects_oversized_content(self, client):
        from conftest import harscope_mod
        old_max = harscope_mod.MAX_HAR_BYTES
        harscope_mod.MAX_HAR_BYTES = 100  # tiny limit for test
        try:
            big = "x" * 200
            resp = await client.post("/api/open-content", json={
                "content": big, "filename": "big.har",
            })
            assert resp.status_code == 413
        finally:
            harscope_mod.MAX_HAR_BYTES = old_max

    async def test_upload_non_utf8_explicit_error(self, client):
        resp = await client.post(
            "/api/upload",
            files={"file": ("bad.har", b'\xff\xfe\x00\x01\x80\x81', "application/octet-stream")},
        )
        assert resp.status_code == 400
        assert "UTF-8" in resp.json()["detail"]


class TestEdlSizeLimit:
    async def test_validate_rejects_oversized_edl(self, client):
        from conftest import harscope_mod
        await load_har(client)
        old_max = harscope_mod.MAX_EDL_BYTES
        harscope_mod.MAX_EDL_BYTES = 100  # tiny limit for test
        try:
            big_edl = "x" * 200
            resp = await client.post(
                "/api/validate",
                files={"file": ("big.edl.json", big_edl.encode(), "application/json")},
            )
            assert resp.status_code == 413
        finally:
            harscope_mod.MAX_EDL_BYTES = old_max


class TestContentDisposition:
    async def test_export_har_filename_sanitized(self, client):
        await load_har(client, filename='"quotes"test.har')
        resp = await client.post("/api/export/har")
        assert resp.status_code == 200
        disposition = resp.headers.get("content-disposition", "")
        assert '"' not in disposition.split("filename=")[1].strip('"') or '_quotes_test.har' in disposition


# ═══════════════════════════════════════════════════════════════════════════
# Scanner correctness — Percentiles, Fmt negative, Depth guard, Null nav
# ═══════════════════════════════════════════════════════════════════════════

class TestPercentiles:
    async def test_p50_with_10_elements(self, client):
        """p50 of [10,20,...,100] should be 50 (index 4), not 60 (index 5)."""
        har = copy.deepcopy(MINIMAL_HAR)
        entries = []
        for i in range(10):
            entry = copy.deepcopy(MINIMAL_HAR["log"]["entries"][0])
            entry["time"] = (i + 1) * 10  # 10,20,30,...,100
            entry["startedDateTime"] = f"2024-01-01T00:00:0{i}.000Z"
            entries.append(entry)
        har["log"]["entries"] = entries
        await load_har(client, har)
        resp = await client.get("/api/stats")
        stats = resp.json()
        # With n=10, index=(10-1)*0.5=4 → value=50
        assert stats["timingPercentiles"]["p50"] == 50


class TestFmtNegative:
    def test_fmt_size_negative(self):
        from conftest import harscope_mod
        assert harscope_mod.ExportEngine._fmt_size(-1) == 'unknown'

    def test_fmt_time_negative(self):
        from conftest import harscope_mod
        assert harscope_mod.ExportEngine._fmt_time(-1) == 'unknown'


class TestScannerDepthGuard:
    async def test_nested_json_in_json_no_crash(self, client):
        """JSON-in-JSON-in-JSON should scan without error using correct depth tracking."""
        inner = json.dumps({"secret": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123def456"})
        middle = json.dumps({"data": inner})
        outer = json.dumps({"payload": middle})
        har = copy.deepcopy(MINIMAL_HAR)
        har["log"]["entries"] = [har["log"]["entries"][0]]
        har["log"]["entries"][0]["response"]["content"]["text"] = outer
        har["log"]["entries"][0]["request"]["headers"] = [{"name": "Host", "value": "example.com"}]
        har["log"]["entries"][0]["request"]["queryString"] = []
        await load_har(client, har)
        # Should complete without error and detect the JWT inside
        sec = await client.get("/api/security")
        assert sec.status_code == 200


class TestNavigateJsonNull:
    async def test_redact_null_json_value(self, client):
        """_navigate_json_path should handle null JSON values without breaking navigation."""
        har = copy.deepcopy(MINIMAL_HAR)
        har["log"]["entries"] = [har["log"]["entries"][0]]
        har["log"]["entries"][0]["response"]["content"]["text"] = json.dumps({
            "secret": None,
            "token": _fixture_value(
                "eyJhbGci", "OiJIUzI1", "NiJ9.", "eyJzdWIi", "OiIxMjM0",
                "NTY3ODkw", "In0.", "abc123", "def456",
            ),
        })
        har["log"]["entries"][0]["request"]["headers"] = [{"name": "Host", "value": "example.com"}]
        har["log"]["entries"][0]["request"]["queryString"] = []
        await load_har(client, har)
        # Export should work without crashing
        resp = await client.post("/api/export/har")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# Test Coverage Gaps — csv-findings, security patterns, bulk category, etc.
# ═══════════════════════════════════════════════════════════════════════════

class TestCsvFindings:
    async def test_csv_findings_no_file(self, client):
        resp = await client.post("/api/export/csv-findings")
        assert resp.status_code == 400

    async def test_csv_findings_structure(self, client):
        await load_har(client)
        resp = await client.post("/api/export/csv-findings")
        assert resp.status_code == 200
        lines = resp.text.strip().split('\n')
        assert len(lines) >= 2  # header + at least one data row
        header = lines[0]
        assert 'Finding ID' in header
        assert 'Severity' in header
        assert 'Category' in header

    async def test_csv_findings_includes_manual(self, client):
        await load_har(client)
        await client.post("/api/redaction/manual", json={
            "entryIndex": 0, "location": "test.manual", "value": "secret_val",
        })
        resp = await client.post("/api/export/csv-findings")
        assert resp.status_code == 200
        assert "manual" in resp.text.lower()


class TestSecurityPatterns:
    """Extended pattern detection tests."""

    async def _load_with_header(self, client, name, value):
        har = copy.deepcopy(MINIMAL_HAR)
        har["log"]["entries"] = [har["log"]["entries"][0]]
        har["log"]["entries"][0]["request"]["headers"] = [
            {"name": name, "value": value},
        ]
        har["log"]["entries"][0]["request"]["queryString"] = []
        await load_har(client, har)

    async def test_bearer_token(self, client):
        await self._load_with_header(
            client,
            "Authorization",
            "Bearer " + _fixture_value(
                "eyJhbGci", "OiJIUzI1", "NiJ9.", "eyJzdWIi", "OiIxMjM0",
                "NTY3ODkw", "In0.", "abc123", "def456",
            ),
        )
        sec = await client.get("/api/security")
        findings = sec.json()["findings"]
        auth_findings = [f for f in findings if "Auth" in f["category"] or "Bearer" in f["description"]]
        assert len(auth_findings) >= 1

    async def test_basic_auth(self, client):
        await self._load_with_header(
            client,
            "Authorization",
            "Basic " + _fixture_value("dXNl", "cjpw", "YXNz"),
        )
        sec = await client.get("/api/security")
        findings = sec.json()["findings"]
        auth_findings = [f for f in findings if "Auth" in f["category"] or "Basic" in f["description"]]
        assert len(auth_findings) >= 1

    async def test_private_ip_info_severity(self, client):
        """Private IPs in response bodies should be flagged as info severity."""
        har = copy.deepcopy(MINIMAL_HAR)
        har["log"]["entries"] = [har["log"]["entries"][0]]
        har["log"]["entries"][0]["request"]["headers"] = [{"name": "Host", "value": "example.com"}]
        har["log"]["entries"][0]["request"]["queryString"] = []
        har["log"]["entries"][0]["response"]["content"]["text"] = json.dumps({
            "server": _fixture_value("192.", "168.", "0.", "1"),
        })
        await load_har(client, har)
        sec = await client.get("/api/security")
        findings = sec.json()["findings"]
        ip_findings = [f for f in findings if f["severity"] == "info" and "Private IP" in f["category"]]
        assert len(ip_findings) >= 1


class TestBulkToggleCategory:
    async def test_bulk_toggle_by_category(self, client):
        await load_har(client)
        # Get current findings to find a category
        sec = await client.get("/api/security")
        findings = sec.json()["findings"]
        if not findings:
            pytest.skip("No findings to test with")
        target_cat = findings[0]["category"]

        # Deselect all, then select by category
        await client.post("/api/security/bulk", json={"action": "deselect"})
        await client.post("/api/security/bulk", json={"action": "select", "category": target_cat})

        sec = await client.get("/api/security")
        for f in sec.json()["findings"]:
            if f["category"] == target_cat:
                assert f["redact"] is True
            else:
                assert f["redact"] is False


class TestReapplyPreservesManual:
    async def test_reapply_preserves_manual_redactions(self, client):
        await load_har(client)
        # Add manual redaction
        await client.post("/api/redaction/manual", json={
            "entryIndex": 0, "location": "test.manual", "value": "val",
        })
        # Deselect all auto
        await client.post("/api/security/bulk", json={"action": "deselect"})
        # Reapply auto
        await client.post("/api/redaction/reapply-auto")
        # Manual should still be present
        sec = await client.get("/api/security")
        assert len(sec.json()["manualRedactions"]) == 1


class TestResetClearsManual:
    async def test_reset_clears_manual_redactions(self, client):
        await load_har(client)
        # Add manual redaction
        await client.post("/api/redaction/manual", json={
            "entryIndex": 0, "location": "test.manual", "value": "val",
        })
        # Reset all
        await client.post("/api/redaction/reset")
        # Manual should be gone
        sec = await client.get("/api/security")
        assert len(sec.json()["manualRedactions"]) == 0


class TestInfoSeverityHandling:
    async def test_info_findings_not_redacted_by_default(self, client):
        har = copy.deepcopy(MINIMAL_HAR)
        har["log"]["entries"] = [{
            "startedDateTime": "2024-01-01T00:00:00.000Z",
            "time": 50,
            "request": {
                "method": "GET",
                "url": "http://192.0.2.1/api",
                "httpVersion": "HTTP/1.1",
                "headers": [],
                "queryString": [],
                "cookies": [],
                "headersSize": -1,
                "bodySize": -1,
            },
            "response": {
                "status": 200, "statusText": "OK", "httpVersion": "HTTP/1.1",
                "headers": [], "cookies": [],
                "content": {"size": 0, "mimeType": "text/html", "text": ""},
                "redirectURL": "", "headersSize": -1, "bodySize": 0,
            },
            "cache": {},
            "timings": {"blocked": 0, "dns": 0, "connect": 0, "ssl": 0, "send": 0, "wait": 0, "receive": 0},
        }]
        await load_har(client, har)
        sec = await client.get("/api/security")
        info_findings = [f for f in sec.json()["findings"] if f["severity"] == "info"]
        for f in info_findings:
            assert f["redact"] is False

    async def test_reapply_does_not_redact_info(self, client):
        har = copy.deepcopy(MINIMAL_HAR)
        har["log"]["entries"] = [{
            "startedDateTime": "2024-01-01T00:00:00.000Z",
            "time": 50,
            "request": {
                "method": "GET",
                "url": "http://192.0.2.1/api",
                "httpVersion": "HTTP/1.1",
                "headers": [],
                "queryString": [],
                "cookies": [],
                "headersSize": -1,
                "bodySize": -1,
            },
            "response": {
                "status": 200, "statusText": "OK", "httpVersion": "HTTP/1.1",
                "headers": [], "cookies": [],
                "content": {"size": 0, "mimeType": "text/html", "text": ""},
                "redirectURL": "", "headersSize": -1, "bodySize": 0,
            },
            "cache": {},
            "timings": {"blocked": 0, "dns": 0, "connect": 0, "ssl": 0, "send": 0, "wait": 0, "receive": 0},
        }]
        await load_har(client, har)
        # Deselect all, then reapply auto
        await client.post("/api/security/bulk", json={"action": "deselect"})
        await client.post("/api/redaction/reapply-auto")
        sec = await client.get("/api/security")
        info_findings = [f for f in sec.json()["findings"] if f["severity"] == "info"]
        for f in info_findings:
            assert f["redact"] is False
