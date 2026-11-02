"""
Comprehensive API tests for the jtree backend server.

Endpoint inventory (20 routes):
  GET  /              - Serve SPA HTML
  GET  /api/status    - File/editor status
  POST /api/open      - Open file by server path
  POST /api/open-content - Open JSON from raw content (browser upload)
  GET  /api/node      - Get node info at path
  GET  /api/children  - Get paginated children
  GET  /api/subtree   - Get subtree to a depth
  GET  /api/search    - Search keys/values
  PUT  /api/node      - Set value at path
  POST /api/node      - Add child to container
  DELETE /api/node    - Delete node at path
  POST /api/rename    - Rename key in object
  POST /api/save      - Save to original file
  POST /api/save-as   - Save to new path
  GET  /api/download  - Download full JSON
  POST /api/undo      - Undo last mutation
  POST /api/redo      - Redo last undo
  POST /api/move      - Reorder array element
  GET  /api/copy      - Deep-copy node value
  POST /api/paste     - Paste value into container

"""
import json
import os

import pytest

from conftest import jtree_mod
from tests.conftest import SAMPLE_DATA


@pytest.mark.parametrize("method, url, kwargs", [
    ("get", "/api/node", {}),
    ("get", "/api/children", {}),
    ("get", "/api/subtree", {}),
    ("get", "/api/search", {"params": {"q": "x"}}),
    ("put", "/api/node", {"params": {"path": json.dumps(["x"])}, "json": {"value": 1}}),
    ("post", "/api/node", {"params": {"path": json.dumps([])}, "json": {"key": "x"}}),
    ("delete", "/api/node", {"params": {"path": json.dumps(["x"])}}),
    ("post", "/api/rename", {"params": {"path": json.dumps(["x"])}, "json": {"newKey": "y"}}),
    ("post", "/api/save", {}),
    ("post", "/api/save-as", {"json": {"path": "/tmp/x.json"}}),
    ("get", "/api/download", {}),
    ("post", "/api/undo", {}),
    ("post", "/api/redo", {}),
    ("post", "/api/move", {"params": {"path": json.dumps([])}, "json": {"fromIndex": 0, "toIndex": 1}}),
    ("get", "/api/copy", {"params": {"path": json.dumps([])}}),
    ("post", "/api/paste", {"params": {"path": json.dumps([])}, "json": {"value": 1}}),
])
def test_no_file_returns_409(client, method, url, kwargs):
    assert getattr(client, method)(url, **kwargs).status_code == 409


# ============================================================================
# GET / — SPA HTML
# ============================================================================

class TestServeSPA:
    def test_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_contains_jtree_title_no_file(self, client):
        resp = client.get("/")
        assert "jtree" in resp.text

    def test_contains_filename_when_loaded(self, loaded_client):
        resp = loaded_client.get("/")
        assert "sample.json" in resp.text


# ============================================================================
# GET /api/status
# ============================================================================

class TestStatus:
    def test_no_file_loaded(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["loaded"] is False
        assert data["file"] is None
        assert data["dirty"] is False
        assert data["readonly"] is False
        assert data["canUndo"] is False
        assert data["canRedo"] is False

    def test_file_loaded(self, loaded_client):
        data = loaded_client.get("/api/status").json()
        assert data["loaded"] is True
        assert data["fileName"] == "sample.json"
        assert data["dirty"] is False
        assert data["readonly"] is False
        assert data["hasFilePath"] is True

    def test_readonly_status(self, readonly_client):
        data = readonly_client.get("/api/status").json()
        assert data["readonly"] is True
        assert data["loaded"] is True

    def test_dirty_after_mutation(self, loaded_client):
        loaded_client.put("/api/node", params={"path": json.dumps(["version"])}, json={"value": 99})
        data = loaded_client.get("/api/status").json()
        assert data["dirty"] is True
        assert data["canUndo"] is True


# ============================================================================
# POST /api/open
# ============================================================================

class TestOpen:
    @pytest.mark.parametrize("content, size_limit", [
        (b'{"name": "caf\xe9"}', None),
        (b'{"name":"123456"}', 16),
    ], ids=["undecodable", "oversized"])
    def test_open_rejects_undecodable_or_oversized_file(
        self, loaded_client, tmp_path, monkeypatch, content, size_limit
    ):
        candidate = tmp_path / "invalid.json"
        candidate.write_bytes(content)
        if size_limit is not None:
            monkeypatch.setattr(jtree_mod.JSONManager, "MAX_FILE_SIZE", size_limit)
        before_node = loaded_client.get("/api/node").json()
        before_file = loaded_client.get("/api/status").json()["file"]

        response = loaded_client.post("/api/open", json={"path": str(candidate)})

        assert response.status_code == 400
        assert loaded_client.get("/api/node").json() == before_node
        assert loaded_client.get("/api/status").json()["file"] == before_file

    def test_open_valid_file(self, client, sample_json_file):
        resp = client.post("/api/open", json={"path": sample_json_file})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["fileName"] == "sample.json"

    def test_open_nonexistent_file(self, client):
        resp = client.post("/api/open", json={"path": "/tmp/does_not_exist_jtree_test.json"})
        assert resp.status_code == 404

    def test_open_invalid_json(self, client, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{ not valid json !!!")
        resp = client.post("/api/open", json={"path": str(bad)})
        assert resp.status_code == 400
        assert "Invalid JSON" in resp.json()["detail"]

    def test_open_readonly(self, client, sample_json_file):
        resp = client.post("/api/open", json={"path": sample_json_file, "readonly": True})
        assert resp.status_code == 200
        status = client.get("/api/status").json()
        assert status["readonly"] is True

    def test_open_missing_path_field(self, client):
        resp = client.post("/api/open", json={})
        assert resp.status_code == 422  # Pydantic validation

    def test_open_empty_path(self, client):
        resp = client.post("/api/open", json={"path": ""})
        assert resp.status_code == 404  # file not found

    def test_open_replaces_previous(self, client, sample_json_file, tmp_path):
        """Opening a new file replaces the previous one."""
        other = tmp_path / "other.json"
        other.write_text('{"x": 1}')
        client.post("/api/open", json={"path": sample_json_file})
        client.post("/api/open", json={"path": str(other)})
        status = client.get("/api/status").json()
        assert status["fileName"] == "other.json"


# ============================================================================
# POST /api/open-content
# ============================================================================

class TestOpenContent:
    def test_open_valid_content(self, client):
        resp = client.post("/api/open-content", json={
            "content": '{"hello": "world"}',
            "fileName": "test.json",
        })
        assert resp.status_code == 200
        assert resp.json()["fileName"] == "test.json"
        # Verify status shows no file path (browser upload)
        status = client.get("/api/status").json()
        assert status["loaded"] is True
        assert status["hasFilePath"] is False

    def test_open_invalid_content(self, client):
        resp = client.post("/api/open-content", json={
            "content": "not json",
            "fileName": "bad.json",
        })
        assert resp.status_code == 400
        assert "Invalid JSON" in resp.json()["detail"]

    def test_open_content_missing_fields(self, client):
        resp = client.post("/api/open-content", json={"content": "{}"})
        assert resp.status_code == 422

    def test_open_array_content(self, client):
        resp = client.post("/api/open-content", json={
            "content": '[1, 2, 3]',
            "fileName": "arr.json",
        })
        assert resp.status_code == 200


# ============================================================================
# GET /api/node
# ============================================================================

class TestGetNode:
    def test_root_node(self, loaded_client):
        data = loaded_client.get("/api/node", params={"path": json.dumps([])}).json()
        assert data["type"] == "object"
        assert data["childCount"] == len(SAMPLE_DATA)
        assert data["path"] == []

    @pytest.mark.parametrize("key, node_type, value", [
        ("name", "string", "jtree"),
        ("version", "number", 1),
        ("flag", "boolean", False),
        ("nothing", "null", None),
    ])
    def test_leaf(self, loaded_client, key, node_type, value):
        data = loaded_client.get("/api/node", params={"path": json.dumps([key])}).json()
        assert data["type"] == node_type
        if node_type in ("boolean", "null"):
            assert data["value"] is value
        else:
            assert data["value"] == value

    def test_array_node(self, loaded_client):
        data = loaded_client.get("/api/node", params={"path": json.dumps(["tags"])}).json()
        assert data["type"] == "array"
        assert data["childCount"] == 3

    def test_nested_path(self, loaded_client):
        data = loaded_client.get("/api/node", params={"path": json.dumps(["nested","c","deep"])}).json()
        assert data["type"] == "boolean"
        assert data["value"] is True

    def test_array_index_path(self, loaded_client):
        data = loaded_client.get("/api/node", params={"path": json.dumps(["tags",1])}).json()
        assert data["type"] == "string"
        assert data["value"] == "viewer"

    def test_invalid_path_returns_404(self, loaded_client):
        resp = loaded_client.get("/api/node", params={"path": json.dumps(["nonexistent"])})
        assert resp.status_code == 404

    def test_invalid_array_index(self, loaded_client):
        resp = loaded_client.get("/api/node", params={"path": json.dumps(["tags",99])})
        assert resp.status_code == 404

    def test_traverse_into_scalar(self, loaded_client):
        resp = loaded_client.get("/api/node", params={"path": json.dumps(["name","x"])})
        assert resp.status_code == 404

    def test_empty_object_node(self, loaded_client):
        data = loaded_client.get("/api/node", params={"path": json.dumps(["empty_obj"])}).json()
        assert data["type"] == "object"
        assert data["childCount"] == 0

    def test_empty_array_node(self, loaded_client):
        data = loaded_client.get("/api/node", params={"path": json.dumps(["empty_arr"])}).json()
        assert data["type"] == "array"
        assert data["childCount"] == 0


# ============================================================================
# GET /api/children
# ============================================================================

class TestGetChildren:
    def test_root_children(self, loaded_client):
        data = loaded_client.get("/api/children", params={"path": json.dumps([])}).json()
        assert data["total"] == len(SAMPLE_DATA)
        assert len(data["children"]) == len(SAMPLE_DATA)
        assert data["hasMore"] is False
        containers = [child for child in data["children"] if child["type"] in ("object", "array")]
        leaves = [child for child in data["children"] if child["type"] not in ("object", "array")]
        assert len(containers) >= 3
        assert leaves
        assert all("childCount" in child for child in containers)

    def test_nested_children_identify_paths_and_types(self, loaded_client):
        for path, expected_path, expected_type in [
            ([], ["nested"], "object"),
            (["nested"], ["nested", "c"], "object"),
            (["nested", "c"], ["nested", "c", "deep"], "boolean"),
        ]:
            response = loaded_client.get("/api/children", params={
                "path": json.dumps(path), "offset": 0, "limit": 200,
            })
            assert response.status_code == 200
            matches = [child for child in response.json()["children"] if child["path"] == expected_path]
            assert len(matches) == 1
            assert matches[0]["type"] == expected_type

    def test_pagination_offset_limit(self, loaded_client):
        data = loaded_client.get("/api/children", params={"path": json.dumps([]), "offset": 0, "limit": 2}).json()
        assert len(data["children"]) == 2
        assert data["hasMore"] is True

    def test_array_children(self, loaded_client):
        data = loaded_client.get("/api/children", params={"path": json.dumps(["tags"])}).json()
        assert data["total"] == 3
        assert data["children"][0]["value"] == "json"
        assert data["children"][2]["value"] == "editor"

    def test_array_pagination(self, loaded_client):
        data = loaded_client.get("/api/children", params={"path": json.dumps(["nested","b"]), "offset": 1, "limit": 1}).json()
        assert len(data["children"]) == 1
        assert data["children"][0]["value"] == 20
        assert data["hasMore"] is True

    def test_scalar_has_no_children(self, loaded_client):
        data = loaded_client.get("/api/children", params={"path": json.dumps(["name"])}).json()
        assert data["total"] == 0
        assert data["children"] == []

    def test_invalid_path_returns_404(self, loaded_client):
        resp = loaded_client.get("/api/children", params={"path": json.dumps(["nope"])})
        assert resp.status_code == 404


# ============================================================================
# GET /api/subtree
# ============================================================================

class TestGetSubtree:
    def test_root_depth_1(self, loaded_client):
        data = loaded_client.get("/api/subtree", params={"path": json.dumps([]), "depth": 1}).json()
        assert data["type"] == "object"
        # depth=1 means immediate children have node info but no grandchildren expanded
        for child in data.get("children", []):
            assert "children" not in child or child.get("childCount", 0) == 0

    def test_root_depth_2(self, loaded_client):
        data = loaded_client.get("/api/subtree", params={"path": json.dumps([]), "depth": 2}).json()
        # nested object should have children expanded
        nested = [c for c in data["children"] if c["path"] == ["nested"]][0]
        assert "children" in nested
        assert len(nested["children"]) == 3

    def test_subtree_of_leaf(self, loaded_client):
        data = loaded_client.get("/api/subtree", params={"path": json.dumps(["name"])}).json()
        assert data["type"] == "string"
        assert "children" not in data

    def test_invalid_path(self, loaded_client):
        resp = loaded_client.get("/api/subtree", params={"path": json.dumps(["bogus"])})
        assert resp.status_code == 404


# ============================================================================
# GET /api/search
# ============================================================================

class TestSearch:
    def test_empty_query_returns_empty(self, loaded_client):
        data = loaded_client.get("/api/search", params={"q": ""}).json()
        assert data == []

    def test_search_key_match(self, loaded_client):
        data = loaded_client.get("/api/search", params={"q": "name", "type": "key"}).json()
        paths = [r["path"] for r in data]
        assert ["name"] in paths

    def test_search_value_match(self, loaded_client):
        data = loaded_client.get("/api/search", params={"q": "jtree", "type": "value"}).json()
        assert any(r["preview"] == "jtree" for r in data)

    def test_search_both_default(self, loaded_client):
        data = loaded_client.get("/api/search", params={"q": "deep"}).json()
        # Should find "deep" as a key
        assert len(data) >= 1

    def test_search_case_insensitive(self, loaded_client):
        data = loaded_client.get("/api/search", params={"q": "JTREE", "type": "value"}).json()
        assert any(r["preview"] == "jtree" for r in data)

    def test_search_limit(self, loaded_client):
        data = loaded_client.get("/api/search", params={"q": "e", "limit": 2}).json()
        assert len(data) <= 2

    def test_search_in_array_values(self, loaded_client):
        data = loaded_client.get("/api/search", params={"q": "viewer", "type": "value"}).json()
        assert any(r["preview"] == "viewer" for r in data)

    def test_search_numeric_value(self, loaded_client):
        data = loaded_client.get("/api/search", params={"q": "20", "type": "value"}).json()
        assert any("20" in r["preview"] for r in data)


# ============================================================================
# PUT /api/node — set value
# ============================================================================

class TestSetValue:
    def test_set_string(self, loaded_client):
        resp = loaded_client.put("/api/node", params={"path": json.dumps(["name"])}, json={"value": "new_name"})
        assert resp.status_code == 200
        node = loaded_client.get("/api/node", params={"path": json.dumps(["name"])}).json()
        assert node["value"] == "new_name"

    def test_set_number(self, loaded_client):
        loaded_client.put("/api/node", params={"path": json.dumps(["version"])}, json={"value": 42})
        node = loaded_client.get("/api/node", params={"path": json.dumps(["version"])}).json()
        assert node["value"] == 42

    def test_set_null(self, loaded_client):
        loaded_client.put("/api/node", params={"path": json.dumps(["name"])}, json={"value": None})
        node = loaded_client.get("/api/node", params={"path": json.dumps(["name"])}).json()
        assert node["type"] == "null"

    def test_set_complex_value(self, loaded_client):
        """Replace a scalar with an object."""
        loaded_client.put("/api/node", params={"path": json.dumps(["name"])}, json={"value": {"first": "j", "last": "t"}})
        node = loaded_client.get("/api/node", params={"path": json.dumps(["name"])}).json()
        assert node["type"] == "object"
        assert node["childCount"] == 2

    def test_set_root(self, loaded_client):
        loaded_client.put("/api/node", params={"path": json.dumps([])}, json={"value": [1, 2, 3]})
        node = loaded_client.get("/api/node", params={"path": json.dumps([])}).json()
        assert node["type"] == "array"
        assert node["childCount"] == 3

    def test_set_invalid_path(self, loaded_client):
        resp = loaded_client.put("/api/node", params={"path": json.dumps(["no","such","path"])}, json={"value": 1})
        assert resp.status_code == 404

    def test_set_readonly_returns_403(self, readonly_client):
        resp = readonly_client.put("/api/node", params={"path": json.dumps(["name"])}, json={"value": "x"})
        assert resp.status_code == 403

    def test_set_missing_body(self, loaded_client):
        resp = loaded_client.put("/api/node", params={"path": json.dumps(["name"])})
        assert resp.status_code == 422


# ============================================================================
# POST /api/node — add child
# ============================================================================

class TestAddChild:
    def test_add_to_object(self, loaded_client):
        resp = loaded_client.post("/api/node", params={"path": json.dumps([])}, json={"key": "newkey", "value": "hello"})
        assert resp.status_code == 200
        node = loaded_client.get("/api/node", params={"path": json.dumps(["newkey"])}).json()
        assert node["value"] == "hello"

    def test_add_to_array(self, loaded_client):
        resp = loaded_client.post("/api/node", params={"path": json.dumps(["tags"])}, json={"value": "new_tag"})
        assert resp.status_code == 200
        children = loaded_client.get("/api/children", params={"path": json.dumps(["tags"])}).json()
        assert children["total"] == 4

    @pytest.mark.parametrize("node_type, expected_value", [
        ("string", ""),
        ("object", None),
        ("array", None),
        ("number", 0),
        ("boolean", False),
        ("null", None),
    ])
    def test_add_default(self, loaded_client, node_type, expected_value):
        key = {"string": "def_str", "object": "def_obj", "array": "def_arr",
               "number": "def_num", "boolean": "def_bool", "null": "def_null"}[node_type]
        loaded_client.post("/api/node", params={"path": json.dumps([])}, json={"key": key, "type": node_type})
        node = loaded_client.get("/api/node", params={"path": json.dumps([key])}).json()
        assert node["type"] == node_type
        if node_type in ("boolean", "null"):
            assert node["value"] is expected_value
        elif node_type not in ("object", "array"):
            assert node["value"] == expected_value

    def test_add_duplicate_key_fails(self, loaded_client):
        resp = loaded_client.post("/api/node", params={"path": json.dumps([])}, json={"key": "name", "value": "dup"})
        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"]

    def test_add_to_scalar_fails(self, loaded_client):
        resp = loaded_client.post("/api/node", params={"path": json.dumps(["name"])}, json={"key": "x", "value": 1})
        assert resp.status_code == 400

    def test_add_to_object_missing_key_fails(self, loaded_client):
        resp = loaded_client.post("/api/node", params={"path": json.dumps([])}, json={"value": "orphan"})
        assert resp.status_code == 400

    def test_add_readonly_returns_403(self, readonly_client):
        resp = readonly_client.post("/api/node", params={"path": json.dumps([])}, json={"key": "x"})
        assert resp.status_code == 403


# ============================================================================
# DELETE /api/node
# ============================================================================

class TestDeleteNode:
    def test_delete_leaf(self, loaded_client):
        resp = loaded_client.delete("/api/node", params={"path": json.dumps(["name"])})
        assert resp.status_code == 200
        assert loaded_client.get("/api/node", params={"path": json.dumps(["name"])}).status_code == 404

    def test_delete_subtree(self, loaded_client):
        resp = loaded_client.delete("/api/node", params={"path": json.dumps(["nested"])})
        assert resp.status_code == 200
        assert loaded_client.get("/api/node", params={"path": json.dumps(["nested"])}).status_code == 404

    def test_delete_array_element(self, loaded_client):
        loaded_client.delete("/api/node", params={"path": json.dumps(["tags",1])})
        children = loaded_client.get("/api/children", params={"path": json.dumps(["tags"])}).json()
        assert children["total"] == 2
        # Element 0 should be "json", element 1 (was 2) should be "editor"
        assert children["children"][0]["value"] == "json"
        assert children["children"][1]["value"] == "editor"

    def test_delete_root_fails(self, loaded_client):
        resp = loaded_client.delete("/api/node", params={"path": json.dumps([])})
        assert resp.status_code == 400

    def test_delete_nonexistent_fails(self, loaded_client):
        resp = loaded_client.delete("/api/node", params={"path": json.dumps(["nope"])})
        assert resp.status_code == 400 or resp.status_code == 404

    def test_delete_readonly_returns_403(self, readonly_client):
        resp = readonly_client.delete("/api/node", params={"path": json.dumps(["name"])})
        assert resp.status_code == 403


# ============================================================================
# POST /api/rename
# ============================================================================

class TestRename:
    def test_rename_key(self, loaded_client):
        resp = loaded_client.post("/api/rename", params={"path": json.dumps(["name"])}, json={"newKey": "title"})
        assert resp.status_code == 200
        assert loaded_client.get("/api/node", params={"path": json.dumps(["title"])}).status_code == 200
        assert loaded_client.get("/api/node", params={"path": json.dumps(["name"])}).status_code == 404

    def test_rename_to_existing_key_fails(self, loaded_client):
        resp = loaded_client.post("/api/rename", params={"path": json.dumps(["name"])}, json={"newKey": "version"})
        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"]

    def test_rename_root_fails(self, loaded_client):
        resp = loaded_client.post("/api/rename", params={"path": json.dumps([])}, json={"newKey": "x"})
        assert resp.status_code == 400

    def test_rename_array_element_fails(self, loaded_client):
        resp = loaded_client.post("/api/rename", params={"path": json.dumps(["tags",0])}, json={"newKey": "x"})
        assert resp.status_code == 400

    def test_rename_readonly_returns_403(self, readonly_client):
        resp = readonly_client.post("/api/rename", params={"path": json.dumps(["name"])}, json={"newKey": "x"})
        assert resp.status_code == 403

    def test_rename_missing_body(self, loaded_client):
        resp = loaded_client.post("/api/rename", params={"path": json.dumps(["name"])})
        assert resp.status_code == 422

    def test_rename_preserves_order(self, loaded_client):
        """Renamed key should remain in the same position."""
        before = loaded_client.get("/api/children", params={"path": json.dumps([])}).json()
        before_paths = [c["path"] for c in before["children"]]
        loaded_client.post("/api/rename", params={"path": json.dumps(["name"])}, json={"newKey": "title"})
        after = loaded_client.get("/api/children", params={"path": json.dumps([])}).json()
        after_paths = [c["path"] for c in after["children"]]
        idx = before_paths.index(["name"])
        assert after_paths[idx] == ["title"]


# ============================================================================
# POST /api/save
# ============================================================================

class TestSave:
    def test_save_persists_changes(self, loaded_client, sample_json_file):
        loaded_client.put("/api/node", params={"path": json.dumps(["version"])}, json={"value": 999})
        resp = loaded_client.post("/api/save")
        assert resp.status_code == 200
        # Verify file on disk
        with open(sample_json_file) as f:
            disk_data = json.load(f)
        assert disk_data["version"] == 999

    def test_save_clears_dirty(self, loaded_client):
        loaded_client.put("/api/node", params={"path": json.dumps(["version"])}, json={"value": 999})
        loaded_client.post("/api/save")
        status = loaded_client.get("/api/status").json()
        assert status["dirty"] is False

    def test_save_readonly_returns_403(self, readonly_client):
        resp = readonly_client.post("/api/save")
        assert resp.status_code == 403

    def test_save_content_uploaded_no_path_returns_403(self, client):
        """A file opened via open-content has no path, save should fail."""
        client.post("/api/open-content", json={"content": '{"a":1}', "fileName": "test.json"})
        resp = client.post("/api/save")
        assert resp.status_code == 403


# ============================================================================
# POST /api/save-as
# ============================================================================

class TestSaveAs:
    def test_save_as_existing_file_without_force_changes_nothing(self, loaded_client, tmp_path):
        target = tmp_path / 'existing.json'
        original = b'{"keep": "synthetic"}\n'
        target.write_bytes(original)
        response = loaded_client.post('/api/save-as', json={'path': str(target)})
        assert response.status_code == 200
        assert response.json()['ok'] is False
        assert response.json()['exists'] is True
        assert target.read_bytes() == original

    def test_save_as_existing_file_with_force_overwrites(self, loaded_client, tmp_path):
        target = tmp_path / 'existing.json'
        target.write_bytes(b'{"keep": "synthetic"}\n')
        response = loaded_client.post('/api/save-as', json={'path': str(target), 'force': True})
        assert response.status_code == 200
        assert response.json()['ok'] is True
        with target.open() as f:
            assert json.load(f)['name'] == 'jtree'

    def test_save_as_adopts_path_for_uploaded_document(self, client, tmp_path):
        target = tmp_path / 'adopted.json'
        assert client.post('/api/open-content', json={'content': '{"a": 1}', 'fileName': 'synthetic.json'}).status_code == 200
        assert client.post('/api/save-as', json={'path': str(target)}).json()['ok'] is True
        assert client.put('/api/node', params={'path': json.dumps(['a'])}, json={'value': 2}).status_code == 200
        assert client.post('/api/save').status_code == 200
        assert json.loads(target.read_text()) == {'a': 2}
        status = client.get('/api/status').json()
        assert status['file'] == os.path.realpath(target)
        assert status['dirty'] is False

    def test_save_as_keeps_original_target_for_disk_file(self, loaded_client, sample_json_file, tmp_path):
        assert loaded_client.put('/api/node', params={'path': json.dumps(['version'])}, json={'value': 999}).status_code == 200
        assert loaded_client.post('/api/save-as', json={'path': str(tmp_path / 'copy.json')}).json()['ok'] is True
        status = loaded_client.get('/api/status').json()
        assert status['file'] == os.path.realpath(sample_json_file)
        assert status['dirty'] is True
        with open(sample_json_file) as f:
            assert json.load(f)['version'] == 1

    def test_save_as_new_path(self, loaded_client, tmp_path):
        target = str(tmp_path / "output.json")
        resp = loaded_client.post("/api/save-as", json={"path": target})
        assert resp.status_code == 200
        with open(target) as f:
            data = json.load(f)
        assert data["name"] == "jtree"

    def test_save_as_missing_path(self, loaded_client):
        resp = loaded_client.post("/api/save-as", json={})
        assert resp.status_code == 422

    def test_save_as_bad_directory(self, loaded_client):
        resp = loaded_client.post("/api/save-as", json={"path": "/nonexistent_dir_xyz/out.json"})
        assert resp.status_code == 500


# ============================================================================
# GET /api/download
# ============================================================================

class TestDownload:
    def test_download_returns_json(self, loaded_client):
        resp = loaded_client.get("/api/download")
        assert resp.status_code == 200
        assert "application/json" in resp.headers["content-type"]
        data = resp.json()
        assert data["name"] == "jtree"
        assert data["tags"] == ["json", "viewer", "editor"]

    def test_download_reflects_mutations(self, loaded_client):
        loaded_client.put("/api/node", params={"path": json.dumps(["version"])}, json={"value": 42})
        data = loaded_client.get("/api/download").json()
        assert data["version"] == 42


# ============================================================================
# POST /api/undo and POST /api/redo
# ============================================================================

class TestUndoRedo:
    def test_undo_nothing_returns_400(self, loaded_client):
        resp = loaded_client.post("/api/undo")
        assert resp.status_code == 400

    def test_redo_nothing_returns_400(self, loaded_client):
        resp = loaded_client.post("/api/redo")
        assert resp.status_code == 400

    def test_undo_set_value(self, loaded_client):
        loaded_client.put("/api/node", params={"path": json.dumps(["version"])}, json={"value": 99})
        loaded_client.post("/api/undo")
        node = loaded_client.get("/api/node", params={"path": json.dumps(["version"])}).json()
        assert node["value"] == 1

    def test_redo_set_value(self, loaded_client):
        loaded_client.put("/api/node", params={"path": json.dumps(["version"])}, json={"value": 99})
        loaded_client.post("/api/undo")
        loaded_client.post("/api/redo")
        node = loaded_client.get("/api/node", params={"path": json.dumps(["version"])}).json()
        assert node["value"] == 99

    def test_undo_add_child(self, loaded_client):
        loaded_client.post("/api/node", params={"path": json.dumps([])}, json={"key": "temp", "value": "x"})
        assert loaded_client.get("/api/node", params={"path": json.dumps(["temp"])}).status_code == 200
        loaded_client.post("/api/undo")
        assert loaded_client.get("/api/node", params={"path": json.dumps(["temp"])}).status_code == 404

    def test_undo_delete(self, loaded_client):
        loaded_client.delete("/api/node", params={"path": json.dumps(["name"])})
        assert loaded_client.get("/api/node", params={"path": json.dumps(["name"])}).status_code == 404
        loaded_client.post("/api/undo")
        node = loaded_client.get("/api/node", params={"path": json.dumps(["name"])}).json()
        assert node["value"] == "jtree"

    def test_undo_rename(self, loaded_client):
        loaded_client.post("/api/rename", params={"path": json.dumps(["name"])}, json={"newKey": "title"})
        loaded_client.post("/api/undo")
        assert loaded_client.get("/api/node", params={"path": json.dumps(["name"])}).status_code == 200
        assert loaded_client.get("/api/node", params={"path": json.dumps(["title"])}).status_code == 404

    def test_undo_redo_status_flags(self, loaded_client):
        """canUndo / canRedo should track stack state."""
        status = loaded_client.get("/api/status").json()
        assert status["canUndo"] is False
        assert status["canRedo"] is False

        loaded_client.put("/api/node", params={"path": json.dumps(["version"])}, json={"value": 99})
        status = loaded_client.get("/api/status").json()
        assert status["canUndo"] is True
        assert status["canRedo"] is False

        loaded_client.post("/api/undo")
        status = loaded_client.get("/api/status").json()
        assert status["canUndo"] is False
        assert status["canRedo"] is True

    def test_new_mutation_clears_redo(self, loaded_client):
        loaded_client.put("/api/node", params={"path": json.dumps(["version"])}, json={"value": 99})
        loaded_client.post("/api/undo")
        # New mutation should clear redo stack
        loaded_client.put("/api/node", params={"path": json.dumps(["version"])}, json={"value": 50})
        resp = loaded_client.post("/api/redo")
        assert resp.status_code == 400  # nothing to redo

    def test_multiple_undo(self, loaded_client):
        loaded_client.put("/api/node", params={"path": json.dumps(["version"])}, json={"value": 10})
        loaded_client.put("/api/node", params={"path": json.dumps(["version"])}, json={"value": 20})
        loaded_client.put("/api/node", params={"path": json.dumps(["version"])}, json={"value": 30})
        loaded_client.post("/api/undo")
        loaded_client.post("/api/undo")
        node = loaded_client.get("/api/node", params={"path": json.dumps(["version"])}).json()
        assert node["value"] == 10


# ============================================================================
# POST /api/move
# ============================================================================

class TestMove:
    def test_move_array_element(self, loaded_client):
        """Move tags[0] ('json') to position 2."""
        resp = loaded_client.post("/api/move", params={"path": json.dumps(["tags"])}, json={"fromIndex": 0, "toIndex": 2})
        assert resp.status_code == 200
        children = loaded_client.get("/api/children", params={"path": json.dumps(["tags"])}).json()
        values = [c["value"] for c in children["children"]]
        assert values == ["viewer", "editor", "json"]

    def test_move_same_position(self, loaded_client):
        """Move to same index should be a no-op."""
        resp = loaded_client.post("/api/move", params={"path": json.dumps(["tags"])}, json={"fromIndex": 1, "toIndex": 1})
        assert resp.status_code == 200

    def test_move_on_object_fails(self, loaded_client):
        resp = loaded_client.post("/api/move", params={"path": json.dumps([])}, json={"fromIndex": 0, "toIndex": 1})
        assert resp.status_code == 400

    def test_move_out_of_range(self, loaded_client):
        resp = loaded_client.post("/api/move", params={"path": json.dumps(["tags"])}, json={"fromIndex": 0, "toIndex": 99})
        assert resp.status_code == 400

    def test_move_negative_index(self, loaded_client):
        resp = loaded_client.post("/api/move", params={"path": json.dumps(["tags"])}, json={"fromIndex": -1, "toIndex": 0})
        assert resp.status_code == 400

    def test_move_readonly_returns_403(self, readonly_client):
        resp = readonly_client.post("/api/move", params={"path": json.dumps(["tags"])}, json={"fromIndex": 0, "toIndex": 1})
        assert resp.status_code == 403

    def test_move_missing_body(self, loaded_client):
        resp = loaded_client.post("/api/move", params={"path": json.dumps(["tags"])})
        assert resp.status_code == 422


# ============================================================================
# GET /api/copy
# ============================================================================

class TestCopy:
    def test_copy_leaf(self, loaded_client):
        data = loaded_client.get("/api/copy", params={"path": json.dumps(["name"])}).json()
        assert data["key"] == "name"
        assert data["value"] == "jtree"

    def test_copy_subtree(self, loaded_client):
        data = loaded_client.get("/api/copy", params={"path": json.dumps(["nested"])}).json()
        assert data["key"] == "nested"
        assert isinstance(data["value"], dict)
        assert data["value"]["a"] == 1

    def test_copy_root(self, loaded_client):
        data = loaded_client.get("/api/copy", params={"path": json.dumps([])}).json()
        assert data["key"] == "root"
        assert isinstance(data["value"], dict)

    def test_copy_array_element(self, loaded_client):
        data = loaded_client.get("/api/copy", params={"path": json.dumps(["tags",0])}).json()
        assert data["value"] == "json"

    def test_copy_invalid_path(self, loaded_client):
        resp = loaded_client.get("/api/copy", params={"path": json.dumps(["nope"])})
        assert resp.status_code == 404

# ============================================================================
# POST /api/paste
# ============================================================================

class TestPaste:
    def test_paste_into_object(self, loaded_client):
        resp = loaded_client.post("/api/paste", params={"path": json.dumps([])}, json={"key": "pasted_key", "value": "hello"})
        assert resp.status_code == 200
        assert resp.json()["key"] == "pasted_key"
        node = loaded_client.get("/api/node", params={"path": json.dumps(["pasted_key"])}).json()
        assert node["value"] == "hello"

    def test_paste_into_array(self, loaded_client):
        resp = loaded_client.post("/api/paste", params={"path": json.dumps(["tags"])}, json={"value": "pasted_tag"})
        assert resp.status_code == 200
        children = loaded_client.get("/api/children", params={"path": json.dumps(["tags"])}).json()
        assert children["total"] == 4

    def test_paste_auto_dedup_key(self, loaded_client):
        """Pasting with key='name' when 'name' exists should auto-rename."""
        resp = loaded_client.post("/api/paste", params={"path": json.dumps([])}, json={"key": "name", "value": "dup"})
        assert resp.status_code == 200
        key = resp.json()["key"]
        assert key.startswith("name_copy")
        node = loaded_client.get("/api/node", params={"path": json.dumps([key])}).json()
        assert node["value"] == "dup"

    def test_paste_default_key(self, loaded_client):
        """Pasting without key should default to 'pasted'."""
        resp = loaded_client.post("/api/paste", params={"path": json.dumps([])}, json={"value": "x"})
        assert resp.status_code == 200
        assert "pasted" in resp.json()["key"]

    def test_paste_into_scalar_fails(self, loaded_client):
        resp = loaded_client.post("/api/paste", params={"path": json.dumps(["name"])}, json={"value": 1})
        assert resp.status_code == 400

    def test_paste_complex_value(self, loaded_client):
        """Paste an entire subtree."""
        subtree = {"x": [1, 2], "y": {"z": True}}
        resp = loaded_client.post("/api/paste", params={"path": json.dumps([])}, json={"key": "complex", "value": subtree})
        assert resp.status_code == 200
        node = loaded_client.get("/api/node", params={"path": json.dumps(["complex"])}).json()
        assert node["type"] == "object"
        assert node["childCount"] == 2

    def test_paste_readonly_returns_403(self, readonly_client):
        resp = readonly_client.post("/api/paste", params={"path": json.dumps([])}, json={"key": "x", "value": 1})
        assert resp.status_code == 403


# ============================================================================
# Cross-cutting: malformed input / edge cases
# ============================================================================

class TestMalformedInput:
    def test_invalid_json_body(self, loaded_client):
        """Send malformed JSON to a POST endpoint."""
        resp = loaded_client.post(
            "/api/open",
            content="{ not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 422

    def test_wrong_content_type(self, loaded_client):
        """Send form data instead of JSON."""
        resp = loaded_client.post(
            "/api/open",
            content="path=/tmp/x.json",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 422

# ============================================================================
# Integration: copy-then-paste workflow
# ============================================================================

class TestCopyPasteWorkflow:
    def test_copy_and_paste_subtree(self, loaded_client):
        """Full copy → paste workflow: copy nested, paste into empty_obj."""
        copy_data = loaded_client.get("/api/copy", params={"path": json.dumps(["nested"])}).json()
        resp = loaded_client.post(
            "/api/paste",
            params={"path": json.dumps(["empty_obj"])},
            json={"key": copy_data["key"], "value": copy_data["value"]},
        )
        assert resp.status_code == 200
        # Verify the paste landed
        node = loaded_client.get("/api/node", params={"path": json.dumps(["empty_obj","nested"])}).json()
        assert node["type"] == "object"
        assert node["childCount"] == 3

    def test_copy_paste_then_undo(self, loaded_client):
        """Paste and then undo should remove the pasted node."""
        loaded_client.post("/api/paste", params={"path": json.dumps([])}, json={"key": "temp", "value": 42})
        assert loaded_client.get("/api/node", params={"path": json.dumps(["temp"])}).status_code == 200
        loaded_client.post("/api/undo")
        assert loaded_client.get("/api/node", params={"path": json.dumps(["temp"])}).status_code == 404


# ============================================================================
# Security and robustness regressions
# ============================================================================

class TestFilenameEscaping:
    """HTML special chars in filenames must be escaped in the SPA."""

    def test_html_chars_in_filename_are_escaped(self, client):
        """A filename containing HTML chars should be escaped in the page."""
        # Use open-content to set a display_name with HTML special chars
        # (avoids filesystem restrictions on < > in filenames)
        client.post("/api/open-content", json={
            "content": '{"a": 1}',
            "fileName": 'test<b>bold</b>.json',
        })
        resp = client.get("/")
        assert resp.status_code == 200
        # The literal <b> tag must NOT appear unescaped
        assert "<b>bold</b>" not in resp.text
        # The escaped form should be present
        assert "&lt;b&gt;" in resp.text

    def test_ampersand_in_filename_escaped(self, client, tmp_path):
        """A filename with & should be escaped to &amp; in HTML."""
        p = tmp_path / "a&b.json"
        p.write_text('{}')
        client.post("/api/open", json={"path": str(p)})
        resp = client.get("/")
        assert resp.status_code == 200
        # Raw & followed by 'b' should not appear unescaped in an HTML attribute context
        # Check the title tag specifically for proper escaping
        assert "a&amp;b.json" in resp.text


class TestServeSpaAfterContentUpload:
    """The SPA must work after content upload leaves file_path unset."""

    def test_spa_works_after_open_content(self, client):
        """GET / must not crash after loading JSON via browser upload."""
        client.post("/api/open-content", json={
            "content": '{"hello": "world"}',
            "fileName": "uploaded.json",
        })
        resp = client.get("/")
        assert resp.status_code == 200
        assert "uploaded.json" in resp.text


class TestSearchDepthGuard:
    """Deeply nested JSON must not blow the Python call stack."""

    def test_search_deeply_nested_json(self, client, tmp_path):
        """Search on a deeply nested file should not raise RecursionError."""
        import sys
        # Build a deeply nested dict that exceeds the recursion limit
        depth = sys.getrecursionlimit() + 100
        data = "leaf"
        for _ in range(depth):
            data = {"a": data}
        p = tmp_path / "deep.json"
        p.write_text(json.dumps(data))
        client.post("/api/open", json={"path": str(p)})
        # This should not crash with RecursionError — must return 200
        resp = client.get("/api/search", params={"q": "leaf"})
        assert resp.status_code == 200


class TestSaveAsPathValidation:
    """Save As must reject non-.json file extensions."""

    def test_save_as_rejects_non_json_extension(self, loaded_client, tmp_path):
        """Saving as a .txt file should be rejected."""
        target = str(tmp_path / "output.txt")
        resp = loaded_client.post("/api/save-as", json={"path": target})
        assert resp.status_code == 400
        assert ".json" in resp.json()["detail"]
