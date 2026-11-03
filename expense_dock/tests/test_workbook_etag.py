import io
from pathlib import Path
import sys

import httpx
import pytest
from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.testkit import load_launcher


def setup_graph(monkeypatch, tmp_path, conflicts=0, missing_etag=False):
    monkeypatch.setenv("EXPENSE_DOCK_HOME", str(tmp_path / "home"))
    module = load_launcher(Path(__file__).resolve().parents[1] / "expense_dock")
    wb = Workbook()
    wb.active.title = "Expense Log"
    wb.active.append(module.EXPECTED_HEADERS)
    buffer = io.BytesIO()
    wb.save(buffer)
    state = {"content": buffer.getvalue(), "version": 1, "puts": [], "gets": 0}

    def transport(request):
        path = request.url.path
        if request.method == "GET" and path.endswith("/content"):
            state["gets"] += 1
            return httpx.Response(200, content=state["content"])
        if request.method == "GET" and path.endswith("/items/workbook"):
            data = {} if missing_etag else {"eTag": f'"v{state["version"]}"'}
            return httpx.Response(200, json=data)
        if request.method == "PUT" and path.endswith("/content"):
            state["puts"].append(request.headers.get("If-Match"))
            if len(state["puts"]) <= conflicts:
                # Simulate another writer adding a row between download and upload.
                current = load_workbook(io.BytesIO(state["content"]))
                current["Expense Log"].append([state["version"], None, "SYNTHETIC OTHER"])
                changed = io.BytesIO()
                current.save(changed)
                state["content"] = changed.getvalue()
                state["version"] += 1
                return httpx.Response(412, json={"error": {"message": "conflict"}})
            state["content"] = request.content
            return httpx.Response(200, json={"id": "workbook"})
        raise AssertionError(f"Unexpected request: {request.method} {path}")

    def init(client, token):
        client.access_token = token
        client.client = httpx.Client(transport=httpx.MockTransport(transport))

    monkeypatch.setattr(module.GraphClient, "__init__", init)
    monkeypatch.setattr(module, "get_access_token", lambda config: "SYNTHETIC")
    monkeypatch.setattr(module, "resolve_root_and_workbook", lambda *args: ({"id": "root"}, {"id": "workbook"}, "drive"))
    submission = dict(date="2030-01-02", vendor="SYNTHETIC", amount=10, category="SYNTHETIC",
                      business_purpose="SYNTHETIC", paid_by="SYNTHETIC", payment_method="SYNTHETIC",
                      reimbursable="Yes", reimbursement_status="SYNTHETIC", notes="SYNTHETIC")
    module.ensure_runtime_dirs()
    pending = module.save_pending_operation(submission, "synthetic.pdf", "https://example.test/receipt", "receipt", "test")
    return module, state, pending


@pytest.mark.parametrize("conflicts", [0, 1, 3])
def test_retry_refetches_and_reapplies_after_conflict(monkeypatch, tmp_path, conflicts):
    module, state, pending = setup_graph(monkeypatch, tmp_path, conflicts)
    result = module.retry_pending_operation({"worksheet_name": "Expense Log"}, pending["id"])
    assert result["ok"]
    assert result["receipt_filename"] == "synthetic.pdf"
    assert state["puts"] == [f'"v{n}"' for n in range(1, conflicts + 2)]
    assert state["gets"] == conflicts + 1
    sheet = load_workbook(io.BytesIO(state["content"]))["Expense Log"]
    assert [sheet.cell(n, 3).value for n in range(2, conflicts + 3)] == ["SYNTHETIC OTHER"] * conflicts + ["SYNTHETIC"]
    assert sheet.cell(conflicts + 2, 12).value == "synthetic.pdf"
    assert not Path(module.pending_path(pending["id"])).exists()


@pytest.mark.parametrize("missing_etag", [False, True])
def test_failure_retains_pending_and_never_writes_without_etag(monkeypatch, tmp_path, missing_etag):
    module, state, pending = setup_graph(monkeypatch, tmp_path, conflicts=4, missing_etag=missing_etag)
    result = module.retry_pending_operation({"worksheet_name": "Expense Log"}, pending["id"])
    assert not result["ok"]
    assert len(state["puts"]) == (0 if missing_etag else 4)
    assert Path(module.pending_path(pending["id"])).exists()


def test_new_submission_queues_after_exhausted_conflicts(monkeypatch, tmp_path):
    module, state, pending = setup_graph(monkeypatch, tmp_path, conflicts=4)
    submission = module.load_pending_operation(pending["id"])["submission"]
    monkeypatch.setattr(module.GraphClient, "ensure_folder", lambda *args: ({"id": "folder"}, False))
    monkeypatch.setattr(module.GraphClient, "upload_file", lambda *args: ({"id": "receipt"}, True))
    monkeypatch.setattr(module.GraphClient, "create_view_link", lambda *args: "https://example.test/new")
    result = module.process_submission({"worksheet_name": "Expense Log"}, submission, b"SYNTHETIC", "synthetic.pdf", "application/pdf")
    assert not result["ok"]
    assert len(state["puts"]) == 4
    assert Path(module.pending_path(result["pending"]["id"])).exists()
