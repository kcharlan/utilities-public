import csv
import io
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tools.testkit import load_launcher
from fake_graph import FakeGraph
from test_input_safety import payload


CONFIG = {"worksheet_name": "Expense Log"}
RECEIPT = b"SYNTHETIC RECEIPT CONTENT"


def setup_submission(monkeypatch, tmp_path, failure=None):
    monkeypatch.setenv("EXPENSE_DOCK_HOME", str(tmp_path / "home"))
    module = load_launcher(Path(__file__).resolve().parents[1] / "expense_dock")
    module.ensure_runtime_dirs()
    graph = FakeGraph(module.EXPECTED_HEADERS, workbook_failure=failure)
    graph.install(module, monkeypatch)
    return module, graph, module.parse_submission(payload())


def submit(module, submission):
    return module.process_submission(CONFIG, submission, RECEIPT, "synthetic.pdf", "application/pdf")


def puts(graph):
    return [url for method, url, _, _ in graph.requests if method == "PUT"]


def test_resubmitting_same_receipt_logs_once(monkeypatch, tmp_path):
    module, graph, submission = setup_submission(monkeypatch, tmp_path)
    # Force a second list page and a competing folder creator through the real client.
    graph.add_item("root", "SYNTHETIC UNRELATED", "folder")
    graph.conflict_folder_once = True
    first = submit(module, submission)
    second = submit(module, submission)
    assert (first["ok"], first["uploaded"], first["duplicate"], first["row_number"]) == (True, True, False, 2)
    assert (second["ok"], second["duplicate"], second["uploaded"], second["row_number"], second["expense_id"]) == (True, True, False, 2, 1)
    assert sum(":/content" in url for url in puts(graph)) == 1
    assert sum(url.endswith("/workbook/content") for url in puts(graph)) == 1
    assert graph.sheet().max_row == 2
    assert graph.sheet().cell(2, 3).value == "SYNTHETIC"
    assert graph.sheet().cell(2, 12).value == first["receipt_filename"]
    assert any("example.invalid/page?" in url for _, url, _, _ in graph.requests)


def test_retry_after_lost_workbook_response_reports_duplicate(monkeypatch, tmp_path):
    module, graph, submission = setup_submission(monkeypatch, tmp_path, "after")
    failed = submit(module, submission)
    assert failed["ok"] is False
    pending_id = failed["pending"]["id"]
    pending_path = Path(module.pending_path(pending_id))
    assert pending_path.is_file()
    result = module.retry_pending_operation(CONFIG, pending_id)
    assert (result["ok"], result["duplicate"], result["row_number"], result["expense_id"]) == (True, True, 2, 1)
    assert not pending_path.exists()
    assert graph.sheet().max_row == 2
    assert sum(url.endswith("/workbook/content") for url in puts(graph)) == 1


def test_large_receipt_session_is_reused_on_resubmission(monkeypatch, tmp_path):
    module, graph, submission = setup_submission(monkeypatch, tmp_path)
    content = b"SYNTHETIC" * 500_000
    first = module.process_submission(CONFIG, submission, content, "synthetic.pdf", "application/pdf")
    second = module.process_submission(CONFIG, submission, content, "synthetic.pdf", "application/pdf")
    assert (first["ok"], first["uploaded"], first["duplicate"]) == (True, True, False)
    assert (second["ok"], second["uploaded"], second["duplicate"], second["row_number"]) == (True, False, True, 2)
    assert list(graph.files.values()) == [content]
    assert sum(url.startswith("https://upload.example.invalid/") for url in puts(graph)) == 2
    assert sum(url.endswith("/workbook/content") for url in puts(graph)) == 1
    assert graph.sheet().max_row == 2


def test_pasted_csv_fallback_row_is_recognized_on_retry(monkeypatch, tmp_path):
    module, graph, submission = setup_submission(monkeypatch, tmp_path, "before")
    failed = submit(module, submission)
    assert failed["ok"] is False
    pending_id = failed["pending"]["id"]
    pending_path = Path(module.pending_path(pending_id))
    assert pending_path.is_file()
    header, row = list(csv.reader(io.StringIO(failed["fallback_csv"])))
    assert header == module.EXPECTED_HEADERS
    graph.paste_row(row)
    result = module.retry_pending_operation(CONFIG, pending_id)
    assert (result["ok"], result["duplicate"], result["row_number"]) == (True, True, 2)
    assert not pending_path.exists()
    assert graph.sheet().max_row == 2
    assert sum(url.endswith("/workbook/content") for url in puts(graph)) == 1
