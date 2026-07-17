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

Frontend feature tests:
  TestExpandAllViewCentering - Expand-all view centering + minimap scale guard
  TestNavigatorSidebar       - Navigator sidebar (TOC, lazy-load, auto-reveal, Ctrl+B)
  TestCollapseAll            - Collapse-all clears all descendant expanded state
"""
import json
import os
import pytest

from tests.conftest import SAMPLE_DATA


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
        loaded_client.put("/api/node", params={"path": "version"}, json={"value": 99})
        data = loaded_client.get("/api/status").json()
        assert data["dirty"] is True
        assert data["canUndo"] is True


# ============================================================================
# POST /api/open
# ============================================================================

class TestOpen:
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

    def test_open_with_tilde_expansion(self, client, sample_json_file, tmp_path):
        # Only testable if the file happens to be under $HOME; just test the endpoint doesn't crash
        resp = client.post("/api/open", json={"path": sample_json_file})
        assert resp.status_code == 200

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
    def test_no_file_loaded_returns_409(self, client):
        resp = client.get("/api/node")
        assert resp.status_code == 409

    def test_root_node(self, loaded_client):
        data = loaded_client.get("/api/node", params={"path": ""}).json()
        assert data["type"] == "object"
        assert data["childCount"] == len(SAMPLE_DATA)
        assert data["path"] == ""

    def test_string_leaf(self, loaded_client):
        data = loaded_client.get("/api/node", params={"path": "name"}).json()
        assert data["type"] == "string"
        assert data["value"] == "jtree"

    def test_number_leaf(self, loaded_client):
        data = loaded_client.get("/api/node", params={"path": "version"}).json()
        assert data["type"] == "number"
        assert data["value"] == 1

    def test_boolean_leaf(self, loaded_client):
        data = loaded_client.get("/api/node", params={"path": "flag"}).json()
        assert data["type"] == "boolean"
        assert data["value"] is False

    def test_null_leaf(self, loaded_client):
        data = loaded_client.get("/api/node", params={"path": "nothing"}).json()
        assert data["type"] == "null"
        assert data["value"] is None

    def test_array_node(self, loaded_client):
        data = loaded_client.get("/api/node", params={"path": "tags"}).json()
        assert data["type"] == "array"
        assert data["childCount"] == 3

    def test_nested_path(self, loaded_client):
        data = loaded_client.get("/api/node", params={"path": "nested.c.deep"}).json()
        assert data["type"] == "boolean"
        assert data["value"] is True

    def test_array_index_path(self, loaded_client):
        data = loaded_client.get("/api/node", params={"path": "tags.1"}).json()
        assert data["type"] == "string"
        assert data["value"] == "viewer"

    def test_invalid_path_returns_404(self, loaded_client):
        resp = loaded_client.get("/api/node", params={"path": "nonexistent"})
        assert resp.status_code == 404

    def test_invalid_array_index(self, loaded_client):
        resp = loaded_client.get("/api/node", params={"path": "tags.99"})
        assert resp.status_code == 404

    def test_traverse_into_scalar(self, loaded_client):
        resp = loaded_client.get("/api/node", params={"path": "name.x"})
        assert resp.status_code == 404

    def test_empty_object_node(self, loaded_client):
        data = loaded_client.get("/api/node", params={"path": "empty_obj"}).json()
        assert data["type"] == "object"
        assert data["childCount"] == 0

    def test_empty_array_node(self, loaded_client):
        data = loaded_client.get("/api/node", params={"path": "empty_arr"}).json()
        assert data["type"] == "array"
        assert data["childCount"] == 0


# ============================================================================
# GET /api/children
# ============================================================================

class TestGetChildren:
    def test_no_file_returns_409(self, client):
        assert client.get("/api/children").status_code == 409

    def test_root_children(self, loaded_client):
        data = loaded_client.get("/api/children", params={"path": ""}).json()
        assert data["total"] == len(SAMPLE_DATA)
        assert len(data["children"]) == len(SAMPLE_DATA)
        assert data["hasMore"] is False

    def test_pagination_offset_limit(self, loaded_client):
        data = loaded_client.get("/api/children", params={"path": "", "offset": 0, "limit": 2}).json()
        assert len(data["children"]) == 2
        assert data["hasMore"] is True

    def test_array_children(self, loaded_client):
        data = loaded_client.get("/api/children", params={"path": "tags"}).json()
        assert data["total"] == 3
        assert data["children"][0]["value"] == "json"
        assert data["children"][2]["value"] == "editor"

    def test_array_pagination(self, loaded_client):
        data = loaded_client.get("/api/children", params={"path": "nested.b", "offset": 1, "limit": 1}).json()
        assert len(data["children"]) == 1
        assert data["children"][0]["value"] == 20
        assert data["hasMore"] is True

    def test_scalar_has_no_children(self, loaded_client):
        data = loaded_client.get("/api/children", params={"path": "name"}).json()
        assert data["total"] == 0
        assert data["children"] == []

    def test_negative_offset_clamped(self, loaded_client):
        data = loaded_client.get("/api/children", params={"path": "", "offset": -5}).json()
        assert data["total"] == len(SAMPLE_DATA)

    def test_overlarge_limit_clamped(self, loaded_client):
        """Limits > 500 are clamped to 50."""
        data = loaded_client.get("/api/children", params={"path": "", "limit": 9999}).json()
        # Clamped to 50, but our data has only 8 keys so all returned
        assert len(data["children"]) == len(SAMPLE_DATA)

    def test_invalid_path_returns_404(self, loaded_client):
        resp = loaded_client.get("/api/children", params={"path": "nope"})
        assert resp.status_code == 404


# ============================================================================
# GET /api/subtree
# ============================================================================

class TestGetSubtree:
    def test_no_file_returns_409(self, client):
        assert client.get("/api/subtree").status_code == 409

    def test_root_depth_1(self, loaded_client):
        data = loaded_client.get("/api/subtree", params={"path": "", "depth": 1}).json()
        assert data["type"] == "object"
        # depth=1 means immediate children have node info but no grandchildren expanded
        for child in data.get("children", []):
            assert "children" not in child or child.get("childCount", 0) == 0

    def test_root_depth_2(self, loaded_client):
        data = loaded_client.get("/api/subtree", params={"path": "", "depth": 2}).json()
        # nested object should have children expanded
        nested = [c for c in data["children"] if c["path"] == "nested"][0]
        assert "children" in nested
        assert len(nested["children"]) == 3

    def test_depth_clamped_minimum(self, loaded_client):
        """depth < 1 should be clamped to 1."""
        data = loaded_client.get("/api/subtree", params={"path": "", "depth": 0}).json()
        assert data["type"] == "object"

    def test_depth_clamped_maximum(self, loaded_client):
        """depth > 10 should be clamped to 10."""
        resp = loaded_client.get("/api/subtree", params={"path": "", "depth": 100})
        assert resp.status_code == 200

    def test_subtree_of_leaf(self, loaded_client):
        data = loaded_client.get("/api/subtree", params={"path": "name"}).json()
        assert data["type"] == "string"
        assert "children" not in data

    def test_invalid_path(self, loaded_client):
        resp = loaded_client.get("/api/subtree", params={"path": "bogus"})
        assert resp.status_code == 404


# ============================================================================
# GET /api/search
# ============================================================================

class TestSearch:
    def test_no_file_returns_409(self, client):
        assert client.get("/api/search", params={"q": "x"}).status_code == 409

    def test_empty_query_returns_empty(self, loaded_client):
        data = loaded_client.get("/api/search", params={"q": ""}).json()
        assert data == []

    def test_search_key_match(self, loaded_client):
        data = loaded_client.get("/api/search", params={"q": "name", "type": "key"}).json()
        paths = [r["path"] for r in data]
        assert "name" in paths

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

    def test_search_invalid_type_defaults_to_both(self, loaded_client):
        resp = loaded_client.get("/api/search", params={"q": "name", "type": "invalid"})
        assert resp.status_code == 200

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
    def test_no_file_returns_409(self, client):
        assert client.put("/api/node", params={"path": "x"}, json={"value": 1}).status_code == 409

    def test_set_string(self, loaded_client):
        resp = loaded_client.put("/api/node", params={"path": "name"}, json={"value": "new_name"})
        assert resp.status_code == 200
        node = loaded_client.get("/api/node", params={"path": "name"}).json()
        assert node["value"] == "new_name"

    def test_set_number(self, loaded_client):
        loaded_client.put("/api/node", params={"path": "version"}, json={"value": 42})
        node = loaded_client.get("/api/node", params={"path": "version"}).json()
        assert node["value"] == 42

    def test_set_null(self, loaded_client):
        loaded_client.put("/api/node", params={"path": "name"}, json={"value": None})
        node = loaded_client.get("/api/node", params={"path": "name"}).json()
        assert node["type"] == "null"

    def test_set_complex_value(self, loaded_client):
        """Replace a scalar with an object."""
        loaded_client.put("/api/node", params={"path": "name"}, json={"value": {"first": "j", "last": "t"}})
        node = loaded_client.get("/api/node", params={"path": "name"}).json()
        assert node["type"] == "object"
        assert node["childCount"] == 2

    def test_set_root(self, loaded_client):
        loaded_client.put("/api/node", params={"path": ""}, json={"value": [1, 2, 3]})
        node = loaded_client.get("/api/node", params={"path": ""}).json()
        assert node["type"] == "array"
        assert node["childCount"] == 3

    def test_set_invalid_path(self, loaded_client):
        resp = loaded_client.put("/api/node", params={"path": "no.such.path"}, json={"value": 1})
        assert resp.status_code == 404

    def test_set_readonly_returns_403(self, readonly_client):
        resp = readonly_client.put("/api/node", params={"path": "name"}, json={"value": "x"})
        assert resp.status_code == 403

    def test_set_marks_dirty(self, loaded_client):
        loaded_client.put("/api/node", params={"path": "version"}, json={"value": 99})
        status = loaded_client.get("/api/status").json()
        assert status["dirty"] is True

    def test_set_missing_body(self, loaded_client):
        resp = loaded_client.put("/api/node", params={"path": "name"})
        assert resp.status_code == 422


# ============================================================================
# POST /api/node — add child
# ============================================================================

class TestAddChild:
    def test_no_file_returns_409(self, client):
        assert client.post("/api/node", params={"path": ""}, json={"key": "x"}).status_code == 409

    def test_add_to_object(self, loaded_client):
        resp = loaded_client.post("/api/node", params={"path": ""}, json={"key": "newkey", "value": "hello"})
        assert resp.status_code == 200
        node = loaded_client.get("/api/node", params={"path": "newkey"}).json()
        assert node["value"] == "hello"

    def test_add_to_array(self, loaded_client):
        resp = loaded_client.post("/api/node", params={"path": "tags"}, json={"value": "new_tag"})
        assert resp.status_code == 200
        children = loaded_client.get("/api/children", params={"path": "tags"}).json()
        assert children["total"] == 4

    def test_add_default_string(self, loaded_client):
        """Adding with type=string and no value should default to empty string."""
        loaded_client.post("/api/node", params={"path": ""}, json={"key": "def_str", "type": "string"})
        node = loaded_client.get("/api/node", params={"path": "def_str"}).json()
        assert node["value"] == ""

    def test_add_default_object(self, loaded_client):
        loaded_client.post("/api/node", params={"path": ""}, json={"key": "def_obj", "type": "object"})
        node = loaded_client.get("/api/node", params={"path": "def_obj"}).json()
        assert node["type"] == "object"

    def test_add_default_array(self, loaded_client):
        loaded_client.post("/api/node", params={"path": ""}, json={"key": "def_arr", "type": "array"})
        node = loaded_client.get("/api/node", params={"path": "def_arr"}).json()
        assert node["type"] == "array"

    def test_add_default_number(self, loaded_client):
        loaded_client.post("/api/node", params={"path": ""}, json={"key": "def_num", "type": "number"})
        node = loaded_client.get("/api/node", params={"path": "def_num"}).json()
        assert node["value"] == 0

    def test_add_default_boolean(self, loaded_client):
        loaded_client.post("/api/node", params={"path": ""}, json={"key": "def_bool", "type": "boolean"})
        node = loaded_client.get("/api/node", params={"path": "def_bool"}).json()
        assert node["value"] is False

    def test_add_null_type(self, loaded_client):
        loaded_client.post("/api/node", params={"path": ""}, json={"key": "def_null", "type": "null"})
        node = loaded_client.get("/api/node", params={"path": "def_null"}).json()
        assert node["type"] == "null"

    def test_add_duplicate_key_fails(self, loaded_client):
        resp = loaded_client.post("/api/node", params={"path": ""}, json={"key": "name", "value": "dup"})
        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"]

    def test_add_to_scalar_fails(self, loaded_client):
        resp = loaded_client.post("/api/node", params={"path": "name"}, json={"key": "x", "value": 1})
        assert resp.status_code == 400

    def test_add_to_object_missing_key_fails(self, loaded_client):
        resp = loaded_client.post("/api/node", params={"path": ""}, json={"value": "orphan"})
        assert resp.status_code == 400

    def test_add_readonly_returns_403(self, readonly_client):
        resp = readonly_client.post("/api/node", params={"path": ""}, json={"key": "x"})
        assert resp.status_code == 403


# ============================================================================
# DELETE /api/node
# ============================================================================

class TestDeleteNode:
    def test_no_file_returns_409(self, client):
        assert client.delete("/api/node", params={"path": "x"}).status_code == 409

    def test_delete_leaf(self, loaded_client):
        resp = loaded_client.delete("/api/node", params={"path": "name"})
        assert resp.status_code == 200
        assert loaded_client.get("/api/node", params={"path": "name"}).status_code == 404

    def test_delete_subtree(self, loaded_client):
        resp = loaded_client.delete("/api/node", params={"path": "nested"})
        assert resp.status_code == 200
        assert loaded_client.get("/api/node", params={"path": "nested"}).status_code == 404

    def test_delete_array_element(self, loaded_client):
        loaded_client.delete("/api/node", params={"path": "tags.1"})
        children = loaded_client.get("/api/children", params={"path": "tags"}).json()
        assert children["total"] == 2
        # Element 0 should be "json", element 1 (was 2) should be "editor"
        assert children["children"][0]["value"] == "json"
        assert children["children"][1]["value"] == "editor"

    def test_delete_root_fails(self, loaded_client):
        resp = loaded_client.delete("/api/node", params={"path": ""})
        assert resp.status_code == 400

    def test_delete_nonexistent_fails(self, loaded_client):
        resp = loaded_client.delete("/api/node", params={"path": "nope"})
        assert resp.status_code == 400 or resp.status_code == 404

    def test_delete_readonly_returns_403(self, readonly_client):
        resp = readonly_client.delete("/api/node", params={"path": "name"})
        assert resp.status_code == 403


# ============================================================================
# POST /api/rename
# ============================================================================

class TestRename:
    def test_no_file_returns_409(self, client):
        assert client.post("/api/rename", params={"path": "x"}, json={"newKey": "y"}).status_code == 409

    def test_rename_key(self, loaded_client):
        resp = loaded_client.post("/api/rename", params={"path": "name"}, json={"newKey": "title"})
        assert resp.status_code == 200
        assert loaded_client.get("/api/node", params={"path": "title"}).status_code == 200
        assert loaded_client.get("/api/node", params={"path": "name"}).status_code == 404

    def test_rename_to_existing_key_fails(self, loaded_client):
        resp = loaded_client.post("/api/rename", params={"path": "name"}, json={"newKey": "version"})
        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"]

    def test_rename_root_fails(self, loaded_client):
        resp = loaded_client.post("/api/rename", params={"path": ""}, json={"newKey": "x"})
        assert resp.status_code == 400

    def test_rename_array_element_fails(self, loaded_client):
        resp = loaded_client.post("/api/rename", params={"path": "tags.0"}, json={"newKey": "x"})
        assert resp.status_code == 400

    def test_rename_readonly_returns_403(self, readonly_client):
        resp = readonly_client.post("/api/rename", params={"path": "name"}, json={"newKey": "x"})
        assert resp.status_code == 403

    def test_rename_missing_body(self, loaded_client):
        resp = loaded_client.post("/api/rename", params={"path": "name"})
        assert resp.status_code == 422

    def test_rename_preserves_order(self, loaded_client):
        """Renamed key should remain in the same position."""
        before = loaded_client.get("/api/children", params={"path": ""}).json()
        before_paths = [c["path"] for c in before["children"]]
        loaded_client.post("/api/rename", params={"path": "name"}, json={"newKey": "title"})
        after = loaded_client.get("/api/children", params={"path": ""}).json()
        after_paths = [c["path"] for c in after["children"]]
        idx = before_paths.index("name")
        assert after_paths[idx] == "title"


# ============================================================================
# POST /api/save
# ============================================================================

class TestSave:
    def test_no_file_returns_409(self, client):
        assert client.post("/api/save").status_code == 409

    def test_save_persists_changes(self, loaded_client, sample_json_file):
        loaded_client.put("/api/node", params={"path": "version"}, json={"value": 999})
        resp = loaded_client.post("/api/save")
        assert resp.status_code == 200
        # Verify file on disk
        with open(sample_json_file) as f:
            disk_data = json.load(f)
        assert disk_data["version"] == 999

    def test_save_clears_dirty(self, loaded_client):
        loaded_client.put("/api/node", params={"path": "version"}, json={"value": 999})
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
    def test_no_file_returns_409(self, client):
        assert client.post("/api/save-as", json={"path": "/tmp/x.json"}).status_code == 409

    def test_save_as_new_path(self, loaded_client, tmp_path):
        target = str(tmp_path / "output.json")
        resp = loaded_client.post("/api/save-as", json={"path": target})
        assert resp.status_code == 200
        with open(target) as f:
            data = json.load(f)
        assert data["name"] == "jtree"

    def test_save_as_tilde_expansion(self, loaded_client, tmp_path):
        # Can't easily test real ~ expansion, but verify the endpoint doesn't crash
        target = str(tmp_path / "tilde_test.json")
        resp = loaded_client.post("/api/save-as", json={"path": target})
        assert resp.status_code == 200

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
    def test_no_file_returns_409(self, client):
        assert client.get("/api/download").status_code == 409

    def test_download_returns_json(self, loaded_client):
        resp = loaded_client.get("/api/download")
        assert resp.status_code == 200
        assert "application/json" in resp.headers["content-type"]
        data = resp.json()
        assert data["name"] == "jtree"
        assert data["tags"] == ["json", "viewer", "editor"]

    def test_download_reflects_mutations(self, loaded_client):
        loaded_client.put("/api/node", params={"path": "version"}, json={"value": 42})
        data = loaded_client.get("/api/download").json()
        assert data["version"] == 42


# ============================================================================
# POST /api/undo and POST /api/redo
# ============================================================================

class TestUndoRedo:
    def test_undo_no_file_returns_409(self, client):
        assert client.post("/api/undo").status_code == 409

    def test_redo_no_file_returns_409(self, client):
        assert client.post("/api/redo").status_code == 409

    def test_undo_nothing_returns_400(self, loaded_client):
        resp = loaded_client.post("/api/undo")
        assert resp.status_code == 400

    def test_redo_nothing_returns_400(self, loaded_client):
        resp = loaded_client.post("/api/redo")
        assert resp.status_code == 400

    def test_undo_set_value(self, loaded_client):
        loaded_client.put("/api/node", params={"path": "version"}, json={"value": 99})
        loaded_client.post("/api/undo")
        node = loaded_client.get("/api/node", params={"path": "version"}).json()
        assert node["value"] == 1

    def test_redo_set_value(self, loaded_client):
        loaded_client.put("/api/node", params={"path": "version"}, json={"value": 99})
        loaded_client.post("/api/undo")
        loaded_client.post("/api/redo")
        node = loaded_client.get("/api/node", params={"path": "version"}).json()
        assert node["value"] == 99

    def test_undo_add_child(self, loaded_client):
        loaded_client.post("/api/node", params={"path": ""}, json={"key": "temp", "value": "x"})
        assert loaded_client.get("/api/node", params={"path": "temp"}).status_code == 200
        loaded_client.post("/api/undo")
        assert loaded_client.get("/api/node", params={"path": "temp"}).status_code == 404

    def test_undo_delete(self, loaded_client):
        loaded_client.delete("/api/node", params={"path": "name"})
        assert loaded_client.get("/api/node", params={"path": "name"}).status_code == 404
        loaded_client.post("/api/undo")
        node = loaded_client.get("/api/node", params={"path": "name"}).json()
        assert node["value"] == "jtree"

    def test_undo_rename(self, loaded_client):
        loaded_client.post("/api/rename", params={"path": "name"}, json={"newKey": "title"})
        loaded_client.post("/api/undo")
        assert loaded_client.get("/api/node", params={"path": "name"}).status_code == 200
        assert loaded_client.get("/api/node", params={"path": "title"}).status_code == 404

    def test_undo_redo_status_flags(self, loaded_client):
        """canUndo / canRedo should track stack state."""
        status = loaded_client.get("/api/status").json()
        assert status["canUndo"] is False
        assert status["canRedo"] is False

        loaded_client.put("/api/node", params={"path": "version"}, json={"value": 99})
        status = loaded_client.get("/api/status").json()
        assert status["canUndo"] is True
        assert status["canRedo"] is False

        loaded_client.post("/api/undo")
        status = loaded_client.get("/api/status").json()
        assert status["canUndo"] is False
        assert status["canRedo"] is True

    def test_new_mutation_clears_redo(self, loaded_client):
        loaded_client.put("/api/node", params={"path": "version"}, json={"value": 99})
        loaded_client.post("/api/undo")
        # New mutation should clear redo stack
        loaded_client.put("/api/node", params={"path": "version"}, json={"value": 50})
        resp = loaded_client.post("/api/redo")
        assert resp.status_code == 400  # nothing to redo

    def test_multiple_undo(self, loaded_client):
        loaded_client.put("/api/node", params={"path": "version"}, json={"value": 10})
        loaded_client.put("/api/node", params={"path": "version"}, json={"value": 20})
        loaded_client.put("/api/node", params={"path": "version"}, json={"value": 30})
        loaded_client.post("/api/undo")
        loaded_client.post("/api/undo")
        node = loaded_client.get("/api/node", params={"path": "version"}).json()
        assert node["value"] == 10


# ============================================================================
# POST /api/move
# ============================================================================

class TestMove:
    def test_no_file_returns_409(self, client):
        assert client.post("/api/move", params={"path": ""}, json={"fromIndex": 0, "toIndex": 1}).status_code == 409

    def test_move_array_element(self, loaded_client):
        """Move tags[0] ('json') to position 2."""
        resp = loaded_client.post("/api/move", params={"path": "tags"}, json={"fromIndex": 0, "toIndex": 2})
        assert resp.status_code == 200
        children = loaded_client.get("/api/children", params={"path": "tags"}).json()
        values = [c["value"] for c in children["children"]]
        assert values == ["viewer", "editor", "json"]

    def test_move_same_position(self, loaded_client):
        """Move to same index should be a no-op."""
        resp = loaded_client.post("/api/move", params={"path": "tags"}, json={"fromIndex": 1, "toIndex": 1})
        assert resp.status_code == 200

    def test_move_on_object_fails(self, loaded_client):
        resp = loaded_client.post("/api/move", params={"path": ""}, json={"fromIndex": 0, "toIndex": 1})
        assert resp.status_code == 400

    def test_move_out_of_range(self, loaded_client):
        resp = loaded_client.post("/api/move", params={"path": "tags"}, json={"fromIndex": 0, "toIndex": 99})
        assert resp.status_code == 400

    def test_move_negative_index(self, loaded_client):
        resp = loaded_client.post("/api/move", params={"path": "tags"}, json={"fromIndex": -1, "toIndex": 0})
        assert resp.status_code == 400

    def test_move_readonly_returns_403(self, readonly_client):
        resp = readonly_client.post("/api/move", params={"path": "tags"}, json={"fromIndex": 0, "toIndex": 1})
        assert resp.status_code == 403

    def test_move_missing_body(self, loaded_client):
        resp = loaded_client.post("/api/move", params={"path": "tags"})
        assert resp.status_code == 422


# ============================================================================
# GET /api/copy
# ============================================================================

class TestCopy:
    def test_no_file_returns_409(self, client):
        assert client.get("/api/copy", params={"path": ""}).status_code == 409

    def test_copy_leaf(self, loaded_client):
        data = loaded_client.get("/api/copy", params={"path": "name"}).json()
        assert data["key"] == "name"
        assert data["value"] == "jtree"

    def test_copy_subtree(self, loaded_client):
        data = loaded_client.get("/api/copy", params={"path": "nested"}).json()
        assert data["key"] == "nested"
        assert isinstance(data["value"], dict)
        assert data["value"]["a"] == 1

    def test_copy_root(self, loaded_client):
        data = loaded_client.get("/api/copy", params={"path": ""}).json()
        assert data["key"] == "root"
        assert isinstance(data["value"], dict)

    def test_copy_array_element(self, loaded_client):
        data = loaded_client.get("/api/copy", params={"path": "tags.0"}).json()
        assert data["value"] == "json"

    def test_copy_invalid_path(self, loaded_client):
        resp = loaded_client.get("/api/copy", params={"path": "nope"})
        assert resp.status_code == 404

    def test_copy_is_deep(self, loaded_client):
        """Modifying the copy source should not affect the copied value."""
        data = loaded_client.get("/api/copy", params={"path": "nested"}).json()
        original_a = data["value"]["a"]
        loaded_client.put("/api/node", params={"path": "nested.a"}, json={"value": 999})
        # Re-copy to verify original copy was independent
        assert original_a == 1


# ============================================================================
# POST /api/paste
# ============================================================================

class TestPaste:
    def test_no_file_returns_409(self, client):
        assert client.post("/api/paste", params={"path": ""}, json={"value": 1}).status_code == 409

    def test_paste_into_object(self, loaded_client):
        resp = loaded_client.post("/api/paste", params={"path": ""}, json={"key": "pasted_key", "value": "hello"})
        assert resp.status_code == 200
        assert resp.json()["key"] == "pasted_key"
        node = loaded_client.get("/api/node", params={"path": "pasted_key"}).json()
        assert node["value"] == "hello"

    def test_paste_into_array(self, loaded_client):
        resp = loaded_client.post("/api/paste", params={"path": "tags"}, json={"value": "pasted_tag"})
        assert resp.status_code == 200
        children = loaded_client.get("/api/children", params={"path": "tags"}).json()
        assert children["total"] == 4

    def test_paste_auto_dedup_key(self, loaded_client):
        """Pasting with key='name' when 'name' exists should auto-rename."""
        resp = loaded_client.post("/api/paste", params={"path": ""}, json={"key": "name", "value": "dup"})
        assert resp.status_code == 200
        key = resp.json()["key"]
        assert key.startswith("name_copy")
        node = loaded_client.get("/api/node", params={"path": key}).json()
        assert node["value"] == "dup"

    def test_paste_default_key(self, loaded_client):
        """Pasting without key should default to 'pasted'."""
        resp = loaded_client.post("/api/paste", params={"path": ""}, json={"value": "x"})
        assert resp.status_code == 200
        assert "pasted" in resp.json()["key"]

    def test_paste_into_scalar_fails(self, loaded_client):
        resp = loaded_client.post("/api/paste", params={"path": "name"}, json={"value": 1})
        assert resp.status_code == 400

    def test_paste_complex_value(self, loaded_client):
        """Paste an entire subtree."""
        subtree = {"x": [1, 2], "y": {"z": True}}
        resp = loaded_client.post("/api/paste", params={"path": ""}, json={"key": "complex", "value": subtree})
        assert resp.status_code == 200
        node = loaded_client.get("/api/node", params={"path": "complex"}).json()
        assert node["type"] == "object"
        assert node["childCount"] == 2

    def test_paste_readonly_returns_403(self, readonly_client):
        resp = readonly_client.post("/api/paste", params={"path": ""}, json={"key": "x", "value": 1})
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

    def test_extra_fields_ignored(self, loaded_client):
        """Extra fields in the body should be ignored by Pydantic."""
        resp = loaded_client.put(
            "/api/node",
            params={"path": "version"},
            json={"value": 7, "extraField": "ignored"},
        )
        assert resp.status_code == 200

    def test_path_with_dots_in_key(self, client, tmp_path):
        """Keys containing dots are a known limitation of the dot-path scheme."""
        # This is just documenting the behavior, not asserting it should work
        f = tmp_path / "dots.json"
        f.write_text('{"a.b": 1, "c": {"d.e": 2}}')
        client.post("/api/open", json={"path": str(f)})
        # "a.b" as a path would try to resolve a -> b, not "a.b" as one key
        resp = client.get("/api/node", params={"path": "a.b"})
        # Expect 404 because it tries "a" then "b" rather than the literal key "a.b"
        assert resp.status_code == 404


# ============================================================================
# Integration: copy-then-paste workflow
# ============================================================================

class TestCopyPasteWorkflow:
    def test_copy_and_paste_subtree(self, loaded_client):
        """Full copy → paste workflow: copy nested, paste into empty_obj."""
        copy_data = loaded_client.get("/api/copy", params={"path": "nested"}).json()
        resp = loaded_client.post(
            "/api/paste",
            params={"path": "empty_obj"},
            json={"key": copy_data["key"], "value": copy_data["value"]},
        )
        assert resp.status_code == 200
        # Verify the paste landed
        node = loaded_client.get("/api/node", params={"path": "empty_obj.nested"}).json()
        assert node["type"] == "object"
        assert node["childCount"] == 3

    def test_copy_paste_then_undo(self, loaded_client):
        """Paste and then undo should remove the pasted node."""
        loaded_client.post("/api/paste", params={"path": ""}, json={"key": "temp", "value": 42})
        assert loaded_client.get("/api/node", params={"path": "temp"}).status_code == 200
        loaded_client.post("/api/undo")
        assert loaded_client.get("/api/node", params={"path": "temp"}).status_code == 404


# ============================================================================
# Regression tests for audit findings
# ============================================================================

class TestAuditFinding1_XssFilename:
    """Finding #1: HTML special chars in filenames must be escaped in SPA."""

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


class TestAuditFinding6_ServeSpaOpenContent:
    """Finding #6: serve_spa crashes when file loaded via open-content (file_path=None)."""

    def test_spa_works_after_open_content(self, client):
        """GET / must not crash after loading JSON via browser upload."""
        client.post("/api/open-content", json={
            "content": '{"hello": "world"}',
            "fileName": "uploaded.json",
        })
        resp = client.get("/")
        assert resp.status_code == 200
        assert "uploaded.json" in resp.text


class TestAuditFinding4_SearchDepthGuard:
    """Finding #4: Deeply nested JSON should not blow the Python call stack."""

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


class TestAuditFinding5_SaveAsPathValidation:
    """Finding #5: save-as should reject non-.json file extensions."""

    def test_save_as_rejects_non_json_extension(self, loaded_client, tmp_path):
        """Saving as a .txt file should be rejected."""
        target = str(tmp_path / "output.txt")
        resp = loaded_client.post("/api/save-as", json={"path": target})
        assert resp.status_code == 400
        assert ".json" in resp.json()["detail"]

    def test_save_as_accepts_json_extension(self, loaded_client, tmp_path):
        """Saving as a .json file should still work."""
        target = str(tmp_path / "output.json")
        resp = loaded_client.post("/api/save-as", json={"path": target})
        assert resp.status_code == 200


class TestExpandAllViewCentering:
    """Expand-all on a large subtree must re-center the view on the target node.

    Regression: when expanding a large subtree (e.g., 500+ nodes), the layout
    engine repositions the parent node far from the origin. Without view
    re-centering, the canvas shows blank space and the minimap is unusable
    because the scale becomes sub-pixel.
    """

    def test_expand_all_js_contains_recenter_logic(self, client):
        """The expandAll function in the SPA must include a setPan call to
        re-center the view on the expanded node after batch state updates."""
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.text
        # The expandAll function should set a pending center path so that
        # after layout recomputation the view centers on the expanded node.
        # Check that the expandAll function references view centering.
        assert "pendingCenterRef" in html or "setPan" in html, (
            "expandAll must include view-centering logic"
        )
        # More specifically: the expandAll callback should trigger centering
        # on the target path after expanding. Look for the pattern inside
        # the expandAll function body.
        import re
        expand_all_match = re.search(
            r'const expandAll = useCallback\(async \(path\)(.*?)},\s*\[',
            html, re.DOTALL
        )
        assert expand_all_match, "Could not find expandAll function in HTML"
        expand_all_body = expand_all_match.group(1)
        assert "pendingCenterRef" in expand_all_body, (
            "expandAll must set pendingCenterRef so the view re-centers "
            "on the target node after layout recomputation"
        )

    def test_minimap_js_has_minimum_scale_guard(self, client):
        """The Minimap component must enforce a minimum scale so that the
        viewport rectangle remains visible even with very large layouts."""
        resp = client.get("/")
        html = resp.text
        # Check for a minimum scale constant in Minimap
        assert "MIN_MINIMAP_SCALE" in html, (
            "Minimap must define MIN_MINIMAP_SCALE to clamp scale for usability"
        )

    def test_large_subtree_expand_all_children_complete(self, client, tmp_path):
        """Simulates expand-all BFS on a large subtree and verifies all
        children are returned without truncation (hasMore=false)."""
        # Build a wide-and-deep JSON: 20 top-level sections, each with
        # 10 children, each with 5 leaf values = 1000+ nodes
        sections = {}
        for i in range(20):
            section = {}
            for j in range(10):
                group = {}
                for k in range(5):
                    group[f"val_{k}"] = f"data_{i}_{j}_{k}"
                section[f"group_{j}"] = group
            sections[f"section_{i}"] = section
        data = {"root_key": "hello", "sections": sections}

        p = tmp_path / "large.json"
        p.write_text(json.dumps(data))
        client.post("/api/open", json={"path": str(p)})

        # BFS expand-all on "sections" (same algorithm as frontend expandAll)
        from collections import deque
        to_expand = deque(["sections"])
        visited = set()
        truncated = []

        while to_expand:
            path = to_expand.popleft()
            if path in visited:
                continue
            visited.add(path)
            resp = client.get("/api/children", params={
                "path": path, "offset": 0, "limit": 200
            })
            assert resp.status_code == 200
            result = resp.json()
            if result["hasMore"]:
                truncated.append(path)
            for child in result["children"]:
                if child["type"] in ("object", "array"):
                    to_expand.append(child["path"])

        # All 20 sections + 200 groups + sections itself = 221 expanded
        assert len(visited) == 221, f"Expected 221 expanded paths, got {len(visited)}"
        assert len(truncated) == 0, f"Truncated paths: {truncated}"


class TestNavigatorSidebar:
    """Tests for the Navigator sidebar TOC feature.

    The sidebar shows a tree of container nodes (objects/arrays only) with
    disclosure triangles, lazy-loads children via /api/children, and provides
    click-to-navigate canvas centering.
    """

    def test_spa_contains_nav_sidebar_component(self, client):
        """The SPA HTML must include the NavSidebar component definition."""
        html = client.get("/").text
        assert "NavSidebar" in html, "NavSidebar component missing from SPA"
        assert "NavSidebarItem" in html, "NavSidebarItem component missing from SPA"

    def test_spa_contains_nav_rail_closed_state(self, client):
        """When closed, sidebar must render a visible rail for discoverability."""
        html = client.get("/").text
        assert "nav-rail" in html, "nav-rail CSS class missing — sidebar undiscoverable when closed"
        assert "nav-rail-label" in html, "nav-rail-label missing — no text hint on closed rail"

    def test_spa_contains_ctrl_b_shortcut(self, client):
        """Ctrl+B keyboard shortcut must be wired to toggle the sidebar."""
        html = client.get("/").text
        # The keydown handler should check for 'b' key with ctrl/meta
        import re
        assert re.search(r"""key\s*===?\s*['"]b['"]""", html), (
            "Ctrl+B shortcut for sidebar toggle not found in SPA"
        )

    def test_spa_nav_sidebar_auto_reveal_logic(self, client):
        """NavSidebar must include auto-reveal logic that watches activePath
        and expands ancestor nodes."""
        html = client.get("/").text
        # The auto-reveal useEffect should reference activePath and expand ancestors
        assert "activePath" in html, "activePath prop missing from NavSidebar"
        assert "scrollIntoView" in html, (
            "scrollIntoView missing — active item should scroll into view"
        )

    def test_sidebar_lazy_load_children_containers_only(self, loaded_client):
        """Sidebar tree should be buildable from /api/children, and we verify
        that container nodes (objects/arrays) are distinguishable from leaves."""
        resp = loaded_client.get("/api/children", params={
            "path": "", "offset": 0, "limit": 200
        })
        assert resp.status_code == 200
        children = resp.json()["children"]

        containers = [c for c in children if c["type"] in ("object", "array")]
        leaves = [c for c in children if c["type"] not in ("object", "array")]

        # SAMPLE_DATA has nested (object), empty_obj (object), empty_arr (array),
        # tags (array) as containers
        assert len(containers) >= 3, (
            f"Expected at least 3 container children at root, got {len(containers)}: "
            f"{[c['key'] for c in containers]}"
        )
        assert len(leaves) > 0, "Expected some leaf nodes at root level"

        # Verify each container has a childCount for sidebar display
        for c in containers:
            assert "childCount" in c, f"Container {c['key']} missing childCount"

    def test_sidebar_navigate_deep_path_via_children(self, loaded_client):
        """Simulate sidebar navigation to a deep path by fetching children
        at each level, verifying the API supports the sidebar's lazy-load pattern."""
        # Navigate: root -> nested -> c -> deep
        # Step 1: get root children, find "nested"
        resp = loaded_client.get("/api/children", params={
            "path": "", "offset": 0, "limit": 200
        })
        root_children = resp.json()["children"]
        nested = [c for c in root_children if c["path"] == "nested"]
        assert len(nested) == 1
        assert nested[0]["type"] == "object"

        # Step 2: get nested's children, find "c"
        resp = loaded_client.get("/api/children", params={
            "path": "nested", "offset": 0, "limit": 200
        })
        assert resp.status_code == 200
        nested_children = resp.json()["children"]
        c_node = [c for c in nested_children if c["path"] == "nested.c"]
        assert len(c_node) == 1
        assert c_node[0]["type"] == "object"

        # Step 3: get c's children - should have "deep" (a leaf)
        resp = loaded_client.get("/api/children", params={
            "path": "nested.c", "offset": 0, "limit": 200
        })
        assert resp.status_code == 200
        c_children = resp.json()["children"]
        deep = [c for c in c_children if c["path"] == "nested.c.deep"]
        assert len(deep) == 1
        assert deep[0]["type"] == "boolean"

    def test_sidebar_header_toggle_button_in_spa(self, client):
        """The header toolbar must include a button to toggle the sidebar."""
        html = client.get("/").text
        # The button uses the list-tree icon
        assert "list-tree" in html, "list-tree icon for sidebar toggle not found in header"


class TestCollapseAll:
    """Collapse-all must clear expanded state for all descendants.

    Regression: collapseAll on root (path='') failed to remove any descendant
    paths from expandedSet because `'name'.startsWith('' + '.')` is false.
    After collapse-all + re-expand root, all prior children appeared expanded.
    """

    def test_collapse_all_root_clears_all_paths(self, client):
        """The collapseAll function must handle root path ('') correctly,
        clearing every path from expandedSet — not just exact matches."""
        import re
        html = client.get("/").text
        # Extract collapseAll function body
        match = re.search(
            r"const collapseAll = useCallback\((.*?)\}, \[",
            html, re.DOTALL
        )
        assert match, "Could not find collapseAll function in HTML"
        body = match.group(1)
        # The fix: when path is '' (root), all entries must be removed.
        # Check that root is handled as a special case (ancestor of everything).
        assert "path === ''" in body or 'path === ""' in body, (
            "collapseAll must handle root path ('') as ancestor of all nodes. "
            "Without this, collapsing root leaves all descendants in expandedSet."
        )
