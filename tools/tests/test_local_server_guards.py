"""Keep the tracked local-server fleet on the shared request boundary."""

import ast
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def calls_guard_test(path):
    tree = ast.parse(path.read_bytes(), filename=str(path))

    def is_helper(node):
        return ((isinstance(node, ast.Name) and node.id == "assert_local_server_guard")
                or (isinstance(node, ast.Attribute) and node.attr == "assert_local_server_guard"))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if is_helper(node.func):
            return True
        if (isinstance(node.func, ast.Attribute) and node.func.attr == "submit"
                and node.args and is_helper(node.args[0])):
            return True
    return False


def test_tracked_uvicorn_servers_have_guard_and_behavior_test():
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT
    ).decode().split("\0")
    paths = [Path(name) for name in tracked if name]
    for path in paths:
        if path.parts[0] in {"docker", "tools"} or "tests" in path.parts:
            continue
        source = (ROOT / path).read_bytes()
        if b"uvicorn.run(" not in source:
            continue
        assert b"# local-server-guard:begin" in source, str(path)
        assert b"# local-server-guard:end" in source, str(path)
        assert re.search(rb"add_middleware\(\s*LocalOriginGuard\s*\)", source), str(path)
        assert b"CORSMiddleware" not in source, str(path)
        project = path.parts[0]
        tests = [
            p for p in paths
            if p.parts[0] == project
            and (p.name.startswith("test_") or p.name.endswith("_test.py"))
            and p.suffix == ".py"
        ]
        assert any(calls_guard_test(ROOT / test) for test in tests), str(path)
