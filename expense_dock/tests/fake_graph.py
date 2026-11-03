"""Stateful, offline Graph HTTP boundary for submission tests."""

import io
import json
import re

import httpx
from openpyxl import Workbook, load_workbook


class FakeGraph:
    def __init__(self, headers, *, workbook_failure=None, page_size=1):
        workbook = Workbook()
        workbook.active.title = "Expense Log"
        workbook.active.append(headers)
        output = io.BytesIO()
        workbook.save(output)
        self.workbook = output.getvalue()
        self.version = 1
        self.workbook_failure = workbook_failure
        self.page_size = page_size
        self.items = {"root": {"id": "root", "name": "SYNTHETIC ROOT", "folder": {}}}
        self.children = {"root": []}
        self.files = {}
        self.sessions = {}
        self.requests = []
        self.conflict_folder_once = False

    def install(self, module, monkeypatch):
        def init(client, token):
            client.access_token = token
            client.client = httpx.Client(transport=httpx.MockTransport(self.handle))

        monkeypatch.setattr(module.GraphClient, "__init__", init)
        monkeypatch.setattr(module, "get_access_token", lambda config: "SYNTHETIC TOKEN")
        monkeypatch.setattr(module, "resolve_root_and_workbook", lambda *args: ({"id": "root"}, {"id": "workbook"}, "drive"))

    def sheet(self):
        return load_workbook(io.BytesIO(self.workbook))["Expense Log"]

    def paste_row(self, row):
        workbook = load_workbook(io.BytesIO(self.workbook))
        workbook["Expense Log"].append(row)
        output = io.BytesIO()
        workbook.save(output)
        self.workbook = output.getvalue()
        self.version += 1

    def add_item(self, parent, name, kind, content=None):
        assert parent in self.children
        assert not any(self.items[item]["name"].lower() == name.lower() for item in self.children[parent])
        item_id = f"synthetic-{len(self.items)}"
        item = {"id": item_id, "name": name, kind: {}, "parentReference": {"id": parent, "driveId": "drive"}, "webUrl": f"https://example.invalid/items/{item_id}"}
        self.items[item_id] = item
        self.children[parent].append(item_id)
        if kind == "folder":
            self.children[item_id] = []
        else:
            self.files[(parent, name)] = content
        return item

    def handle(self, request):
        self.requests.append((request.method, str(request.url), dict(request.headers), request.content))
        method, path = request.method, request.url.path
        if request.url.host == "upload.example.invalid":
            assert method == "PUT" and "authorization" not in request.headers
            session = self.sessions[path]
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", request.headers["content-range"])
            assert match
            start, end, total = map(int, match.groups())
            assert start == len(session["content"]) and end - start + 1 == len(request.content)
            assert int(request.headers["content-length"]) == len(request.content)
            session["content"] += request.content
            if end + 1 < total:
                return httpx.Response(202, json={"nextExpectedRanges": [f"{end + 1}-"]})
            assert end + 1 == total
            return httpx.Response(201, json=self.add_item(session["parent"], session["name"], "file", session["content"]))
        assert request.url.host in ("graph.microsoft.com", "example.invalid")
        assert request.headers.get("authorization") == "Bearer SYNTHETIC TOKEN"
        if request.url.host == "example.invalid":
            assert method == "GET" and path == "/page"
            parent, offset = request.url.params["parent"], int(request.url.params["offset"])
            return self.list_page(parent, offset)
        prefix = "/v1.0/drives/drive/items/"
        assert path.startswith(prefix)
        tail = path[len(prefix):]
        if tail == "workbook" and method == "GET":
            assert request.url.params.get("$select") == "eTag"
            return httpx.Response(200, json={"eTag": f'"v{self.version}"'})
        if tail == "workbook/content":
            if method == "GET":
                return httpx.Response(200, content=self.workbook)
            assert method == "PUT"
            if request.headers.get("if-match") != f'"v{self.version}"':
                return httpx.Response(412, json={"error": {"message": "synthetic conflict"}})
            failure, self.workbook_failure = self.workbook_failure, None
            if failure != "before":
                self.workbook = request.content
                self.version += 1
            if failure:
                raise httpx.ReadTimeout("synthetic workbook response lost", request=request)
            return httpx.Response(200, json={"id": "workbook"})
        if tail.endswith("/children"):
            parent = tail.removesuffix("/children")
            assert parent in self.children
            if method == "GET":
                return self.list_page(parent, 0)
            assert method == "POST"
            body = json.loads(request.content)
            assert body["folder"] == {} and body["@microsoft.graph.conflictBehavior"] == "fail"
            item = self.add_item(parent, body["name"], "folder")
            if self.conflict_folder_once:
                self.conflict_folder_once = False
                return httpx.Response(409, json={"error": {"message": "synthetic conflict"}})
            return httpx.Response(201, json=item)
        if tail.endswith("/createLink"):
            assert method == "POST"
            item_id = tail.removesuffix("/createLink")
            assert item_id in self.items and "file" in self.items[item_id]
            assert json.loads(request.content) == {"type": "view", "scope": "anonymous"}
            return httpx.Response(200, json={"link": {"webUrl": f"https://example.invalid/receipts/{item_id}"}})
        match = re.fullmatch(r"([^/]+):/(.+):/(content|createUploadSession)", tail)
        if match:
            parent, name, action = match.groups()
            assert parent in self.children
            if action == "content":
                assert method == "PUT"
                return httpx.Response(201, json=self.add_item(parent, name, "file", request.content))
            assert method == "POST"
            assert json.loads(request.content) == {"item": {"@microsoft.graph.conflictBehavior": "fail"}}
            session_path = f"/session-{len(self.sessions) + 1}"
            self.sessions[session_path] = {"parent": parent, "name": name, "content": b""}
            return httpx.Response(200, json={"uploadUrl": f"https://upload.example.invalid{session_path}"})
        raise AssertionError(f"Unexpected request: {method} {request.url}")

    def list_page(self, parent, offset):
        ids = self.children[parent]
        result = {"value": [self.items[item] for item in ids[offset:offset + self.page_size]]}
        if offset + self.page_size < len(ids):
            result["@odata.nextLink"] = f"https://example.invalid/page?parent={parent}&offset={offset + self.page_size}"
        return httpx.Response(200, json=result)
