import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_graph import FakeGraph
from tools.testkit import load_launcher


@pytest.fixture
def client_and_graph(monkeypatch, tmp_path):
    monkeypatch.setenv("EXPENSE_DOCK_HOME", str(tmp_path / "home"))
    module = load_launcher(Path(__file__).resolve().parents[1] / "expense_dock")
    graph = FakeGraph(module.EXPECTED_HEADERS)
    graph.install(module, monkeypatch)
    with module.GraphClient("SYNTHETIC TOKEN") as client:
        yield client, graph


def test_large_receipt_uses_contiguous_upload_session(client_and_graph):
    client, graph = client_and_graph
    content = (b"SYNTHETIC PATTERN" * 400_000)[:5_242_880]
    item, created = client.upload_file("drive", "root", "synthetic.pdf", content, "application/pdf")

    sessions = [r for r in graph.requests if r[0] == "POST" and r[1].endswith(":/createUploadSession")]
    assert len(sessions) == 1
    assert json.loads(sessions[0][3])["item"]["@microsoft.graph.conflictBehavior"] == "fail"
    chunks = [r for r in graph.requests if r[1].startswith("https://upload.example.invalid/")]
    assert [r[0] for r in chunks] == ["PUT", "PUT"]
    assert [r[2]["content-range"] for r in chunks] == [
        "bytes 0-3276799/5242880", "bytes 3276800-5242879/5242880"
    ]
    assert all("authorization" not in r[2] for r in chunks)
    assert b"".join(r[3] for r in chunks) == content
    assert len(graph.children["root"]) == 1
    expected_item = graph.items[graph.children["root"][0]]
    assert (item, created) == (expected_item, True)
    assert graph.files[("root", "synthetic.pdf")] == content


def test_child_lookup_follows_next_link_case_insensitively(client_and_graph):
    client, graph = client_and_graph
    graph.add_item("root", "SYNTHETIC OTHER", "file")
    expected = graph.add_item("root", "RECEIPT.PDF", "file")
    assert client.find_child_by_name("drive", "root", "receipt.pdf") == expected
    urls = [url for method, url, _, _ in graph.requests if method == "GET"]
    assert len(urls) == 2
    assert "/children?" in urls[0]
    assert urls[1] == "https://example.invalid/page?parent=root&offset=1"


def test_folder_create_conflict_returns_existing_folder(client_and_graph):
    client, graph = client_and_graph
    graph.conflict_folder_once = True
    folder, created = client.ensure_folder("drive", "root", "SYNTHETIC FOLDER")
    assert (folder, created) == (graph.items[folder["id"]], False)
    assert folder["name"] == "SYNTHETIC FOLDER" and "folder" in folder
    assert [method for method, _, _, _ in graph.requests] == ["GET", "POST", "GET"]
