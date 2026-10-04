"""Workspace facts use only isolated synthetic homes, paths and remotes."""

import copy
import json
from pathlib import Path

import pytest

from fixturegen import CodexHome

BASE = 1_893_974_400_000
ORIGIN = "https://example.invalid/synthetic/tools"


def corpus(colophon, tmp_path, entries, *, database=None):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    records = []
    for identifier, fields in entries:
        # The fixture builder supplies a remote by default. Workspace fallback
        # cases explicitly remove it; raw logs spell origin as repository_url.
        path = home.log(identifier).meta(at=BASE, **({"git": {}} | fields)).task_started(
            "synthetic-turn", at=BASE + 1).task_complete(at=BASE + 2).write()
        records.append(colophon.parse_log_file(path, size=path.stat().st_size,
                                               mtime_ns=BASE * 1_000_000, archived=False))
    return colophon.build_corpus(records, colophon.CodexMetadata(threads=database or {}), BASE + 100)


def alias(name="Synthetic Tools", *, origins=None, paths=None):
    return {"name": name, "origins": origins or [], "paths": paths or []}


@pytest.mark.parametrize("url", [
    "git@example.invalid:synthetic/tools.git",
    "ssh://git@example.invalid:2222/synthetic/tools.git",
    "https://synthetic-user:synthetic-token@EXAMPLE.INVALID:8443/synthetic/tools.git/",
    "HTTP://EXAMPLE.INVALID/synthetic/tools/",
    "https://example.invalid/synthetic/tools.git",
    "https://example.invalid/synthetic/tools/",
    ORIGIN,
])
def test_origin_forms_have_same_credential_free_identity(colophon, url):
    normalized = colophon.normalize_origin_url(url)
    assert normalized == ORIGIN
    assert "synthetic-token" not in normalized
    assert "@" not in normalized


@pytest.mark.parametrize("url", [None, "", " ", "relative/path", "https://", "https://example.invalid",
                                "https://[broken/synthetic/tools", 42, {}, "https://example.invalid/"])
def test_invalid_origins_are_not_workspace_evidence(colophon, url):
    assert colophon.normalize_origin_url(url) is None


def test_origin_preserves_path_case_and_discards_query_and_fragment(colophon):
    assert colophon.normalize_origin_url("https://EXAMPLE.INVALID/Synthetic/Tools.git/?synthetic=x#part") == (
        "https://example.invalid/Synthetic/Tools")


@pytest.mark.parametrize("entry_kind", ["file", "directory"])
def test_git_root_and_subfolder_with_git_entry(colophon, tmp_path, entry_kind):
    root = tmp_path / "synthetic-repo"
    cwd = root / "nested" / "tool"
    cwd.mkdir(parents=True)
    marker = root / ".git"
    marker.mkdir() if entry_kind == "directory" else marker.write_text("gitdir: /synthetic/elsewhere\n")
    assert colophon.find_git_root(str(cwd)) == root
    result = corpus(colophon, tmp_path, [("synthetic-session", {"cwd": str(cwd)})])
    workspaces = colophon.resolve_workspaces(result, [])
    model = result.sessions["synthetic-session"]
    assert model.workspace == f"git:{root}"
    assert model.subfolder == "nested/tool"
    assert workspaces[model.workspace] == {"name": root.name, "kind": "git_root",
                                           "keys": sorted([str(root), str(cwd)]), "alias": None}


def test_git_root_memo_is_reset_for_each_resolution_run(colophon, tmp_path, monkeypatch):
    root = tmp_path / "synthetic-repo"
    cwd = root / "nested"
    cwd.mkdir(parents=True)
    calls = []
    original = Path.exists
    def exists(path):
        calls.append(path)
        return original(path)
    colophon.find_git_root.cache_clear()
    monkeypatch.setattr(Path, "exists", exists)
    assert colophon.find_git_root(str(cwd)) is None
    count = len(calls)
    assert colophon.find_git_root(str(cwd)) is None
    assert len(calls) == count
    (root / ".git").mkdir()
    result = corpus(colophon, tmp_path, [("synthetic-session", {"cwd": str(cwd)})])
    colophon.resolve_workspaces(result, [])
    assert result.sessions["synthetic-session"].workspace == f"git:{root}"


def test_missing_cwd_path_and_unknown_cwd_fallback(colophon, tmp_path):
    missing = tmp_path / "synthetic-missing"
    assert colophon.find_git_root(str(missing)) is None
    result = corpus(colophon, tmp_path, [("synthetic-missing", {"cwd": str(missing)}),
                                       ("synthetic-unknown", {"cwd": None})])
    workspaces = colophon.resolve_workspaces(result, [])
    assert result.sessions["synthetic-missing"].workspace == f"cwd:{missing}"
    assert workspaces[f"cwd:{missing}"]["name"] == f"{missing} (no repo)"
    assert result.sessions["synthetic-unknown"].workspace == "cwd:"
    assert workspaces["cwd:"] == {"name": "(unknown)", "kind": "cwd", "keys": [], "alias": None}
    assert all(session.subfolder is None for session in result.sessions.values())


def test_meta_precedes_db_origin_and_cwd_without_mutating_sources(colophon, tmp_path):
    cwd = tmp_path / "synthetic-repo" / "nested"
    cwd.mkdir(parents=True)
    (cwd.parent / ".git").mkdir()
    result = corpus(colophon, tmp_path, [("synthetic-session", {
        "cwd": str(cwd), "git": {"repository_url": "git@example.invalid:synthetic/tools.git"}})],
        database={"synthetic-session": {"cwd": "/synthetic/database", "git_origin_url": "https://example.invalid/synthetic/other"}})
    model = result.sessions["synthetic-session"]
    before = copy.deepcopy((model.meta, model.db_info, model.record, model.records))
    workspaces = colophon.resolve_workspaces(result, [])
    assert model.workspace == f"origin:{ORIGIN}"
    assert model.subfolder == "nested"
    assert workspaces[model.workspace] == {"name": "tools", "kind": "origin",
        "keys": sorted([ORIGIN, str(cwd.parent), str(cwd)]), "alias": None}
    assert (model.meta, model.db_info, model.record, model.records) == before


@pytest.mark.parametrize("bad", [None, "", " ", 42])
def test_invalid_meta_falls_back_to_independent_database_fields(colophon, tmp_path, bad):
    result = corpus(colophon, tmp_path, [("synthetic-session", {"cwd": bad, "git": {"repository_url": bad}})],
        database={"synthetic-session": {"cwd": "/synthetic/database", "git_origin_url": ORIGIN}})
    workspaces = colophon.resolve_workspaces(result, [])
    assert result.sessions["synthetic-session"].workspace == f"origin:{ORIGIN}"
    assert workspaces[f"origin:{ORIGIN}"]["keys"] == ["/synthetic/database", ORIGIN]


def test_alias_origin_merges_distinct_remotes_and_paths(colophon, tmp_path):
    other = "https://example.invalid/synthetic/alternate"
    entries = [("synthetic-one", {"cwd": "/synthetic/one", "git": {"repository_url": ORIGIN}}),
               ("synthetic-two", {"cwd": "/synthetic/two", "git": {"repository_url": other}})]
    result = corpus(colophon, tmp_path, entries)
    aliases = [alias(origins=["git@example.invalid:synthetic/tools.git", other])]
    workspaces = colophon.resolve_workspaces(result, aliases)
    assert list(workspaces) == ["alias:Synthetic Tools"]
    assert workspaces["alias:Synthetic Tools"] == {"name": "Synthetic Tools", "kind": "alias",
        "keys": sorted([ORIGIN, other, "/synthetic/one", "/synthetic/two"]), "alias": "Synthetic Tools"}
    assert all(model.workspace == "alias:Synthetic Tools" for model in result.sessions.values())


def test_alias_path_components_precedence_and_subfolder(colophon, tmp_path):
    result = corpus(colophon, tmp_path, [("synthetic-nested", {"cwd": "/synthetic/a/b/c", "git": {"repository_url": ORIGIN}}),
        ("synthetic-boundary", {"cwd": "/synthetic/a/bc"}), ("synthetic-equal", {"cwd": "/synthetic/a/b"})])
    aliases = [alias("Synthetic First", paths=["/synthetic/a/b"]),
               alias("Synthetic Second", origins=[ORIGIN], paths=["/synthetic/a"])]
    colophon.resolve_workspaces(result, aliases)
    assert result.sessions["synthetic-nested"].workspace == "alias:Synthetic First"
    assert result.sessions["synthetic-nested"].subfolder == "c"
    assert result.sessions["synthetic-equal"].subfolder is None
    assert result.sessions["synthetic-boundary"].workspace == "alias:Synthetic Second"


def test_alias_matching_path_wins_subfolder_even_when_origin_also_matches(colophon, tmp_path):
    cwd = tmp_path / "synthetic-repo" / "nested" / "leaf"
    cwd.mkdir(parents=True)
    (cwd.parents[1] / ".git").mkdir()
    result = corpus(colophon, tmp_path, [("synthetic-session", {"cwd": str(cwd), "git": {"repository_url": ORIGIN}})])
    colophon.resolve_workspaces(result, [alias(origins=[ORIGIN], paths=[str(cwd.parent)])])
    assert result.sessions["synthetic-session"].subfolder == "leaf"


def test_home_name_and_abbreviated_non_repo_cwd(colophon, tmp_path, monkeypatch):
    home = tmp_path / "synthetic-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    result = corpus(colophon, tmp_path, [("synthetic-home", {"cwd": str(home)}),
        ("synthetic-child", {"cwd": str(home / "tools")})])
    workspaces = colophon.resolve_workspaces(result, [])
    assert workspaces[f"cwd:{home}"]["name"] == "~ (home)"
    assert workspaces[f"cwd:{home / 'tools'}"]["name"] == "~/tools (no repo)"
    (home / ".git").mkdir()
    workspaces = colophon.resolve_workspaces(result, [])
    assert workspaces[f"git:{home}"]["name"] == "~"


def test_subagent_retains_its_own_workspace(colophon, tmp_path):
    result = corpus(colophon, tmp_path, [("synthetic-parent", {"cwd": "/synthetic/parent"}),
        ("synthetic-child", {"cwd": "/synthetic/child", "parent_thread_id": "synthetic-parent", "agent_path": "/root/synthetic_child"})])
    colophon.link_subagents(result, colophon.CodexMetadata(), BASE + 100)
    colophon.resolve_workspaces(result, [])
    assert result.sessions["synthetic-parent"].workspace == "cwd:/synthetic/parent"
    assert result.sessions["synthetic-child"].workspace == "cwd:/synthetic/child"


def test_missing_alias_file_is_not_an_error(colophon, tmp_path, capsys):
    assert colophon.load_workspace_aliases(tmp_path / "workspaces.json") == ([], [])
    assert capsys.readouterr().err == ""


def test_alias_json_line_error_ignores_entire_file_and_resolution_continues(colophon, tmp_path, capsys):
    path = tmp_path / "workspaces.json"
    path.write_text('{\n"schema": 1,\n"aliases": [\n}\n')
    aliases, errors = colophon.load_workspace_aliases(path)
    assert aliases == []
    assert len(errors) == 1 and "line 4" in errors[0] and str(path) in errors[0]
    assert errors[0] in capsys.readouterr().err
    result = corpus(colophon, tmp_path, [("synthetic-session", {"cwd": None})])
    assert "cwd:" in colophon.resolve_workspaces(result, aliases)


@pytest.mark.parametrize("change, field", [
    ({"name": 42}, "name"), ({"name": " "}, "name"), ({"origins": "invalid"}, "origins"),
    ({"origins": [42]}, "origins"), ({"origins": ["relative/path"]}, "origins"),
    ({"paths": None}, "paths"), ({"paths": [42]}, "paths"), ({"paths": ["relative/path"]}, "paths"),
])
def test_invalid_alias_schema_reports_index_and_field(colophon, tmp_path, capsys, change, field):
    path = tmp_path / "workspaces.json"
    invalid = alias("Synthetic Invalid", origins=[ORIGIN]) | change
    path.write_text(json.dumps({"schema": 1, "aliases": [alias(), invalid]}))
    aliases, errors = colophon.load_workspace_aliases(path)
    assert aliases == []
    assert len(errors) == 1 and "alias index 1" in errors[0] and field in errors[0]
    assert errors[0] in capsys.readouterr().err


@pytest.mark.parametrize("payload, field", [({}, "schema"), ({"schema": True, "aliases": []}, "schema"),
    ({"schema": 2, "aliases": []}, "schema"), ({"schema": 1, "aliases": {}}, "aliases"),
    ({"schema": 1, "aliases": [None]}, "alias index 0"),
    ({"schema": 1, "aliases": [{"name": "Synthetic"}]}, "origins")])
def test_invalid_top_level_and_missing_alias_fields(colophon, tmp_path, payload, field):
    path = tmp_path / "workspaces.json"
    path.write_text(json.dumps(payload))
    aliases, errors = colophon.load_workspace_aliases(path)
    assert aliases == [] and len(errors) == 1 and field in errors[0]


def test_valid_alias_file_preserves_order_and_source_values(colophon, tmp_path):
    path = tmp_path / "workspaces.json"
    aliases = [alias("Synthetic First", origins=["git@example.invalid:synthetic/tools.git"]),
               alias("Synthetic Second", paths=["/synthetic/deployed/tools"])]
    path.write_text(json.dumps({"schema": 1, "aliases": aliases}))
    assert colophon.load_workspace_aliases(path) == (aliases, [])


def test_unreadable_alias_file_is_ignored(colophon, tmp_path, capsys):
    path = tmp_path / "workspaces.json"
    path.mkdir()
    aliases, errors = colophon.load_workspace_aliases(path)
    assert aliases == [] and len(errors) == 1 and str(path) in errors[0]
    assert errors[0] in capsys.readouterr().err


@pytest.mark.parametrize("paths, expected", [
    (["/synthetic/a", "/synthetic/a/b"], None),
    (["/synthetic/a/b", "/synthetic/a/b/"], "c"),
])
def test_alias_conflicting_roots_have_unknown_subfolder(colophon, tmp_path, paths, expected):
    result = corpus(colophon, tmp_path, [("synthetic-session", {"cwd": "/synthetic/a/b/c"})])
    colophon.resolve_workspaces(result, [alias(paths=paths)])
    assert result.sessions["synthetic-session"].workspace == "alias:Synthetic Tools"
    assert result.sessions["synthetic-session"].subfolder == expected


@pytest.mark.parametrize("url", ["https://example.invalid/synthetic/\ntools", "https://example.invalid/synthetic/\0tools"])
def test_control_characters_do_not_become_origin_evidence(colophon, url):
    assert colophon.normalize_origin_url(url) is None


def test_parent_traversal_path_does_not_invent_alias_match(colophon, tmp_path):
    result = corpus(colophon, tmp_path, [("synthetic-session", {"cwd": "/synthetic/a/b/../outside"})])
    workspaces = colophon.resolve_workspaces(result, [alias(paths=["/synthetic/a/b"])])
    assert result.sessions["synthetic-session"].workspace == "cwd:"
    assert workspaces["cwd:"]["name"] == "(unknown)"
