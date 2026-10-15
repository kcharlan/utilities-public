"""Tests for packet 12: Dependency Detection & Parsing.

All tests use temporary directories to avoid touching real repos.
No network calls, no DB writes — pure logic tests.
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

# ── Ensure project root is on sys.path ────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

from git_dashboard import (
    detect_dep_files,
    parse_requirements_txt,
    parse_pyproject_toml,
    parse_package_json,
    parse_go_mod,
    parse_cargo_toml,
    parse_gemfile,
    parse_composer_json,
    parse_deps_for_repo,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_tmpdir(files: dict) -> Path:
    """Create a temp dir with the given filename→content mapping and return its path."""
    d = tempfile.mkdtemp()
    root = Path(d)
    for name, content in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return root


# ── detect_dep_files tests ────────────────────────────────────────────────────

def test_detect_dep_files_requirements_txt():
    """Test 1: single Python (requirements.txt)"""
    root = make_tmpdir({"requirements.txt": "flask==2.3.0\n"})
    result = detect_dep_files(root)
    assert len(result) == 1
    assert result[0]["file"] == "requirements.txt"
    assert result[0]["manager"] == "pip"
    assert result[0]["runtime"] == "python"


def test_detect_dep_files_pyproject_toml():
    """Test 2: single Python (pyproject.toml)"""
    root = make_tmpdir({"pyproject.toml": "[project]\nname = 'mypkg'\n"})
    result = detect_dep_files(root)
    assert len(result) == 1
    assert result[0]["file"] == "pyproject.toml"
    assert result[0]["manager"] == "pip"
    assert result[0]["runtime"] == "python"


def test_detect_dep_files_package_json():
    """Test 3: single Node"""
    root = make_tmpdir({"package.json": '{"name": "myapp"}\n'})
    result = detect_dep_files(root)
    assert len(result) == 1
    assert result[0]["file"] == "package.json"
    assert result[0]["manager"] == "npm"
    assert result[0]["runtime"] == "node"


def test_detect_dep_files_go_mod():
    """Test 4: single Go"""
    root = make_tmpdir({"go.mod": "module example.com/mymod\n\ngo 1.21\n"})
    result = detect_dep_files(root)
    assert len(result) == 1
    assert result[0]["file"] == "go.mod"
    assert result[0]["manager"] == "gomod"
    assert result[0]["runtime"] == "go"


def test_detect_dep_files_cargo_toml():
    """Test 5: single Rust"""
    root = make_tmpdir({"Cargo.toml": "[package]\nname = 'mycrate'\n"})
    result = detect_dep_files(root)
    assert len(result) == 1
    assert result[0]["file"] == "Cargo.toml"
    assert result[0]["manager"] == "cargo"
    assert result[0]["runtime"] == "rust"


def test_detect_dep_files_gemfile():
    """Test 6: single Ruby"""
    root = make_tmpdir({"Gemfile": "source 'https://rubygems.org'\ngem 'rails'\n"})
    result = detect_dep_files(root)
    assert len(result) == 1
    assert result[0]["file"] == "Gemfile"
    assert result[0]["manager"] == "bundler"
    assert result[0]["runtime"] == "ruby"


def test_detect_dep_files_composer_json():
    """Test 7: single PHP"""
    root = make_tmpdir({"composer.json": '{"require": {}}\n'})
    result = detect_dep_files(root)
    assert len(result) == 1
    assert result[0]["file"] == "composer.json"
    assert result[0]["manager"] == "composer"
    assert result[0]["runtime"] == "php"


def test_detect_dep_files_mixed_ecosystem():
    """Test 8: mixed ecosystem (pyproject.toml + package.json → both returned)"""
    root = make_tmpdir({
        "pyproject.toml": "[project]\nname = 'mypkg'\n",
        "package.json": '{"name": "myapp"}\n',
    })
    result = detect_dep_files(root)
    managers = {r["manager"] for r in result}
    runtimes = {r["runtime"] for r in result}
    assert "pip" in managers
    assert "npm" in managers
    assert "python" in runtimes
    assert "node" in runtimes
    assert len(result) == 2


def test_detect_dep_files_empty_dir():
    """Test 9: no manifest files → []"""
    root = make_tmpdir({})
    result = detect_dep_files(root)
    assert result == []


def test_detect_dep_files_priority_order_python():
    """Test 10: pyproject.toml has higher priority than requirements.txt for same runtime"""
    root = make_tmpdir({
        "pyproject.toml": "[project]\nname = 'mypkg'\n",
        "requirements.txt": "flask==2.3.0\n",
    })
    result = detect_dep_files(root)
    # Only one python file returned, and it must be pyproject.toml
    python_results = [r for r in result if r["runtime"] == "python"]
    assert len(python_results) == 1
    assert python_results[0]["file"] == "pyproject.toml"
    # pyproject.toml must appear before requirements.txt (if somehow both appeared)
    files = [r["file"] for r in result]
    assert "pyproject.toml" in files
    assert "requirements.txt" not in files


# ── parse_requirements_txt tests ──────────────────────────────────────────────

def test_parse_requirements_txt_basic():
    """Test 11: basic pinned deps"""
    root = make_tmpdir({"requirements.txt": "flask==2.3.0\nrequests==2.31.0\n"})
    result = parse_requirements_txt(root / "requirements.txt")
    assert len(result) == 2
    names = {r["name"] for r in result}
    assert "flask" in names
    assert "requests" in names
    versions = {r["name"]: r["version"] for r in result}
    assert versions["flask"] == "2.3.0"
    assert versions["requests"] == "2.31.0"
    for r in result:
        assert r["manager"] == "pip"


def test_parse_requirements_txt_comments_and_blanks():
    """Test 12: comments and blank lines are skipped"""
    content = "# comment\n\nflask==2.3.0\n  # indented comment\n"
    root = make_tmpdir({"requirements.txt": content})
    result = parse_requirements_txt(root / "requirements.txt")
    assert len(result) == 1
    assert result[0]["name"] == "flask"


def test_parse_requirements_txt_unpinned():
    """Test 13: unpinned deps → version None; constrained → version None"""
    content = "flask\nrequests>=2.0\n"
    root = make_tmpdir({"requirements.txt": content})
    result = parse_requirements_txt(root / "requirements.txt")
    assert len(result) == 2
    names = {r["name"] for r in result}
    assert "flask" in names
    assert "requests" in names
    # Both should have version None (no == pin)
    for r in result:
        assert r["version"] is None


def test_parse_requirements_txt_editable_skipped():
    """Test 14: -e editable installs are skipped"""
    content = "-e ./local_pkg\nflask==2.3.0\n"
    root = make_tmpdir({"requirements.txt": content})
    result = parse_requirements_txt(root / "requirements.txt")
    assert len(result) == 1
    assert result[0]["name"] == "flask"


def test_parse_requirements_txt_include():
    """Test 15: -r include follows one level"""
    root = make_tmpdir({
        "requirements.txt": "-r other.txt\nflask==2.3.0\n",
        "other.txt": "requests==2.31.0\n",
    })
    result = parse_requirements_txt(root / "requirements.txt")
    names = {r["name"] for r in result}
    assert "flask" in names
    assert "requests" in names
    assert len(result) == 2


def test_parse_requirements_txt_circular_include():
    """Test 16: circular -r include → no infinite loop, returns available deps"""
    root = make_tmpdir({
        "requirements.txt": "-r other.txt\nflask==2.3.0\n",
        "other.txt": "-r requirements.txt\nrequests==2.31.0\n",
    })
    # Must not raise or loop forever
    result = parse_requirements_txt(root / "requirements.txt")
    names = {r["name"] for r in result}
    # Both packages should appear (though exact order depends on parsing order)
    assert "flask" in names
    assert "requests" in names


def test_parse_requirements_txt_missing_include():
    """Validation: -r pointing to nonexistent file → no crash, returns other deps"""
    root = make_tmpdir({
        "requirements.txt": "-r nonexistent.txt\nflask==2.3.0\n",
    })
    result = parse_requirements_txt(root / "requirements.txt")
    assert len(result) == 1
    assert result[0]["name"] == "flask"


# ── parse_pyproject_toml tests ────────────────────────────────────────────────

def test_parse_pyproject_toml_pep621():
    """Test 17: [project].dependencies (PEP 621)"""
    content = '[project]\ndependencies = ["flask>=2.0", "requests==2.31.0"]\n'
    root = make_tmpdir({"pyproject.toml": content})
    result = parse_pyproject_toml(root / "pyproject.toml")
    names = {r["name"] for r in result}
    assert "flask" in names
    assert "requests" in names
    versions = {r["name"]: r["version"] for r in result}
    assert versions["requests"] == "2.31.0"
    for r in result:
        assert r["manager"] == "pip"


def test_parse_pyproject_toml_poetry():
    """Test 18: [tool.poetry.dependencies]"""
    content = '[tool.poetry.dependencies]\npython = "^3.11"\nflask = "^2.3"\nrequests = {version = "^2.31", extras = ["security"]}\n'
    root = make_tmpdir({"pyproject.toml": content})
    result = parse_pyproject_toml(root / "pyproject.toml")
    names = {r["name"] for r in result}
    # flask and requests must be present; python key is included as-is
    # (spec doesn't require filtering it, unlike php/ext-* in composer.json)
    assert "flask" in names
    assert "requests" in names
    versions = {r["name"]: r["version"] for r in result}
    assert versions["flask"] == "^2.3"
    assert versions["requests"] == "^2.31"
    for r in result:
        assert r["manager"] == "pip"


def test_parse_pyproject_toml_no_deps():
    """Test 19: no dependencies section → []"""
    content = '[build-system]\nrequires = ["setuptools"]\n'
    root = make_tmpdir({"pyproject.toml": content})
    result = parse_pyproject_toml(root / "pyproject.toml")
    assert result == []


# ── parse_package_json tests ──────────────────────────────────────────────────

def test_parse_package_json_deps_and_devdeps():
    """Test 20: both dependencies and devDependencies"""
    pkg = {
        "name": "myapp",
        "dependencies": {"react": "^18.0.0", "axios": "^1.0.0"},
        "devDependencies": {"jest": "^29.0.0"},
    }
    root = make_tmpdir({"package.json": json.dumps(pkg)})
    result = parse_package_json(root / "package.json")
    names = {r["name"] for r in result}
    assert "react" in names
    assert "axios" in names
    assert "jest" in names
    for r in result:
        assert r["manager"] == "npm"


def test_parse_package_json_no_deps():
    """Test 21: no dependencies key → []"""
    pkg = {"name": "myapp", "version": "1.0.0"}
    root = make_tmpdir({"package.json": json.dumps(pkg)})
    result = parse_package_json(root / "package.json")
    assert result == []


def test_parse_package_json_version_ranges():
    """Test 22: version ranges preserved as-is"""
    pkg = {
        "dependencies": {
            "a": "^1.2.3",
            "b": "~2.0.0",
            "c": ">=3.0.0",
        }
    }
    root = make_tmpdir({"package.json": json.dumps(pkg)})
    result = parse_package_json(root / "package.json")
    versions = {r["name"]: r["version"] for r in result}
    assert versions["a"] == "^1.2.3"
    assert versions["b"] == "~2.0.0"
    assert versions["c"] == ">=3.0.0"


# ── parse_go_mod tests ────────────────────────────────────────────────────────

def test_parse_go_mod_require_block():
    """Test 23: standard require (...) block"""
    content = (
        "module example.com/mymod\n\n"
        "go 1.21\n\n"
        "require (\n"
        "\tgithub.com/pkg/errors v0.9.1\n"
        "\tgolang.org/x/net v0.17.0\n"
        ")\n"
    )
    root = make_tmpdir({"go.mod": content})
    result = parse_go_mod(root / "go.mod")
    names = {r["name"] for r in result}
    assert "github.com/pkg/errors" in names
    assert "golang.org/x/net" in names
    versions = {r["name"]: r["version"] for r in result}
    assert versions["github.com/pkg/errors"] == "v0.9.1"
    for r in result:
        assert r["manager"] == "gomod"


def test_parse_go_mod_single_require():
    """Test 24: single-line require (no parens)"""
    content = "module example.com/mymod\n\ngo 1.21\n\nrequire github.com/pkg/errors v0.9.1\n"
    root = make_tmpdir({"go.mod": content})
    result = parse_go_mod(root / "go.mod")
    assert len(result) >= 1
    names = {r["name"] for r in result}
    assert "github.com/pkg/errors" in names


def test_parse_go_mod_indirect():
    """Test 25: indirect deps are still included"""
    content = (
        "module example.com/mymod\n\n"
        "go 1.21\n\n"
        "require (\n"
        "\tgithub.com/pkg/errors v0.9.1 // indirect\n"
        "\tgolang.org/x/net v0.17.0\n"
        ")\n"
    )
    root = make_tmpdir({"go.mod": content})
    result = parse_go_mod(root / "go.mod")
    names = {r["name"] for r in result}
    assert "github.com/pkg/errors" in names  # indirect still included


# ── parse_cargo_toml tests ────────────────────────────────────────────────────

def test_parse_cargo_toml_string_versions():
    """Test 26: serde = "1.0" format"""
    content = '[package]\nname = "mycrate"\nversion = "0.1.0"\n\n[dependencies]\nserde = "1.0"\ntokio = "1.28"\n'
    root = make_tmpdir({"Cargo.toml": content})
    result = parse_cargo_toml(root / "Cargo.toml")
    names = {r["name"] for r in result}
    assert "serde" in names
    assert "tokio" in names
    versions = {r["name"]: r["version"] for r in result}
    assert versions["serde"] == "1.0"
    for r in result:
        assert r["manager"] == "cargo"


def test_parse_cargo_toml_table_versions():
    """Test 27: serde = { version = "1.0", features = [...] } format"""
    content = '[package]\nname = "mycrate"\nversion = "0.1.0"\n\n[dependencies]\nserde = { version = "1.0", features = ["derive"] }\n'
    root = make_tmpdir({"Cargo.toml": content})
    result = parse_cargo_toml(root / "Cargo.toml")
    assert len(result) >= 1
    versions = {r["name"]: r["version"] for r in result}
    assert versions.get("serde") == "1.0"


def test_parse_cargo_toml_no_deps():
    """Test 28: no [dependencies] section → []"""
    content = '[package]\nname = "mycrate"\nversion = "0.1.0"\n'
    root = make_tmpdir({"Cargo.toml": content})
    result = parse_cargo_toml(root / "Cargo.toml")
    assert result == []


# ── parse_gemfile tests ───────────────────────────────────────────────────────

def test_parse_gemfile_basic():
    """Test 29: basic gems with version constraints"""
    content = "source 'https://rubygems.org'\ngem 'rails', '~> 7.0'\ngem 'puma', '>= 5.0'\n"
    root = make_tmpdir({"Gemfile": content})
    result = parse_gemfile(root / "Gemfile")
    assert len(result) == 2
    names = {r["name"] for r in result}
    assert "rails" in names
    assert "puma" in names
    versions = {r["name"]: r["version"] for r in result}
    assert versions["rails"] == "~> 7.0"
    assert versions["puma"] == ">= 5.0"
    for r in result:
        assert r["manager"] == "bundler"


def test_parse_gemfile_no_version():
    """Test 30: gem without version → version None"""
    content = "gem 'rake'\n"
    root = make_tmpdir({"Gemfile": content})
    result = parse_gemfile(root / "Gemfile")
    assert len(result) == 1
    assert result[0]["name"] == "rake"
    assert result[0]["version"] is None


# ── parse_composer_json tests ─────────────────────────────────────────────────

def test_parse_composer_json_require_and_require_dev():
    """Test 31: both require and require-dev"""
    pkg = {
        "require": {
            "laravel/framework": "^10.0",
            "php": ">=8.1",
            "ext-mbstring": "*",
        },
        "require-dev": {
            "phpunit/phpunit": "^10.0",
        },
    }
    root = make_tmpdir({"composer.json": json.dumps(pkg)})
    result = parse_composer_json(root / "composer.json")
    names = {r["name"] for r in result}
    assert "laravel/framework" in names
    assert "phpunit/phpunit" in names
    # php and ext-* are platform requirements, must be skipped
    assert "php" not in names
    assert "ext-mbstring" not in names
    for r in result:
        assert r["manager"] == "composer"


def test_parse_composer_json_no_require():
    """Test 32: no require key → []"""
    pkg = {"name": "myvendor/myapp"}
    root = make_tmpdir({"composer.json": json.dumps(pkg)})
    result = parse_composer_json(root / "composer.json")
    assert result == []


# ── parse_deps_for_repo orchestrator tests ────────────────────────────────────

def test_parse_deps_for_repo_python():
    """Test 33: python repo → merged list with pip manager"""
    root = make_tmpdir({"requirements.txt": "flask==2.3.0\nrequests==2.31.0\n"})
    result = parse_deps_for_repo(root)
    assert len(result) == 2
    for r in result:
        assert r["manager"] == "pip"
        assert "name" in r
        assert "version" in r


def test_parse_deps_for_repo_mixed():
    """Test 34: mixed repo (requirements.txt + package.json) → deps from both"""
    root = make_tmpdir({
        "requirements.txt": "flask==2.3.0\n",
        "package.json": json.dumps({"dependencies": {"react": "^18.0.0"}}),
    })
    result = parse_deps_for_repo(root)
    managers = {r["manager"] for r in result}
    assert "pip" in managers
    assert "npm" in managers
    names = {r["name"] for r in result}
    assert "flask" in names
    assert "react" in names


def test_parse_deps_for_repo_empty():
    """Test 35: no manifest files → []"""
    root = make_tmpdir({})
    result = parse_deps_for_repo(root)
    assert result == []


# ── TOML unavailability graceful degradation ──────────────────────────────────

def test_parse_pyproject_toml_no_tomllib(monkeypatch):
    """AC 18: when tomllib is unavailable, return [] without crashing."""
    import git_dashboard
    monkeypatch.setattr(git_dashboard, "tomllib", None)
    content = '[project]\ndependencies = ["flask>=2.0"]\n'
    root = make_tmpdir({"pyproject.toml": content})
    result = parse_pyproject_toml(root / "pyproject.toml")
    assert result == []


def test_parse_cargo_toml_no_tomllib(monkeypatch):
    """AC 18: when tomllib is unavailable, Cargo.toml returns [] without crashing."""
    import git_dashboard
    monkeypatch.setattr(git_dashboard, "tomllib", None)
    content = '[package]\nname = "mycrate"\n\n[dependencies]\nserde = "1.0"\n'
    root = make_tmpdir({"Cargo.toml": content})
    result = parse_cargo_toml(root / "Cargo.toml")
    assert result == []


# ── Standard shape enforcement ────────────────────────────────────────────────

@pytest.mark.parametrize("manager,content,filename", [
    ("pip", "flask==2.3.0\n", "requirements.txt"),
    ("npm", '{"dependencies": {"react": "^18.0.0"}}', "package.json"),
    ("bundler", "gem 'rails', '~> 7.0'\n", "Gemfile"),
    ("composer", '{"require": {"laravel/framework": "^10.0"}}', "composer.json"),
])
def test_standard_shape(manager, content, filename):
    """All parsers return dicts with {name, version, manager}."""
    root = make_tmpdir({filename: content})
    result = parse_deps_for_repo(root)
    assert len(result) >= 1
    for r in result:
        assert "name" in r
        assert "version" in r
        assert "manager" in r
        assert r["manager"] == manager


def test_parse_deps_for_repo_keeps_manifest_identities(tmp_path):
    for manifest, text in {
        'requirements.txt': 'SYNTHETIC_Pkg.Name==1.0\nsynthetic-pkg-name==9.0\n',
        'child/requirements.txt': 'synthetic.pkg_name==2.0\n',
    }.items():
        path = tmp_path / manifest
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    deps = parse_deps_for_repo(tmp_path)
    assert {(d['source_path'], d['name'], d['version']) for d in deps} == {
        ('requirements.txt', 'synthetic-pkg-name', '1.0'),
        ('child/requirements.txt', 'synthetic-pkg-name', '2.0'),
    }


def test_dependency_identity_normalizes_package_names_only():
    import git_dashboard
    assert git_dashboard.dependency_identity_name({'manager': 'pip', 'name': 'SYNTHETIC_Pkg.Name'}) == 'synthetic-pkg-name'
    assert git_dashboard.dependency_identity_name({'manager': 'npm', 'name': '@Synthetic/Pkg.Name'}) == '@Synthetic/Pkg.Name'
    assert git_dashboard.dependency_identity_name({'manager': 'pip', 'name': 'https://synthetic.invalid/Name.git', 'reference_identity': True}) == 'https://synthetic.invalid/Name.git'


@pytest.mark.parametrize("transport", ["https", "ssh"])
def test_direct_reference_identity_survives_repo_pipeline(tmp_path, transport):
    import git_dashboard
    authority = "git@git.example.invalid" if transport == "ssh" else "git.example.invalid"
    url = f"git+{transport}://{authority}/acme/widget-kit.git@feature/fix"
    (tmp_path / "requirements.txt").write_text(url + "\n")
    [row] = git_dashboard.parse_deps_for_repo(tmp_path)
    assert row["name"] == "git.example.invalid/acme/widget-kit"
    assert row["current_version"] == "git:feature/fix"
    assert git_dashboard.dependency_identity_name(row) == row["name"]


@pytest.mark.parametrize('text', [
    'Synthetic_Widget.Name @ git+https://git.example.invalid/acme/repo.git@v1',
    'git+ssh://git@git.example.invalid/acme/repo.git@v1#egg=Synthetic_Widget.Name',
])
def test_named_and_egg_references_normalize_distribution_name(tmp_path, text):
    (tmp_path / 'requirements.txt').write_text(text + '\n')
    [row] = parse_requirements_txt(tmp_path / 'requirements.txt')
    assert row['name'] == 'synthetic-widget-name'
    assert row['current_version'] == 'git:v1'
    assert row['declared_spec'] == text
    assert row['direct_ref'] is True
    assert row['reference_identity'] is False


def test_wheel_reference_uses_wheel_metadata(tmp_path):
    text = 'https://packages.example.invalid/synthetic_widget-1.2.3-py3-none-any.whl'
    (tmp_path / 'requirements.txt').write_text(text)
    [row] = parse_requirements_txt(tmp_path / 'requirements.txt')
    assert row['name'] == 'synthetic-widget'
    assert row['current_version'] == '1.2.3'
    assert row['version'] is None
    assert row['direct_ref'] is True


def test_pep508_extras_markers_wildcards_and_continuations(tmp_path):
    (tmp_path / 'requirements.txt').write_text(
        'Synthetic_Widget[extra]==1.2.3 ; python_version < "0" \\\n'
        ' --hash=sha256:synthetic # comment\n'
        'synthetic-wild==1.2.*\ninvalid ???\n'
        'synthetic-range>=1,<3 ; sys_platform == "synthetic"\n')
    rows = parse_requirements_txt(tmp_path / 'requirements.txt')
    assert len(rows) == 3
    assert rows[0]['version'] == '1.2.3'
    assert rows[0]['declared_spec'] == 'Synthetic_Widget[extra]==1.2.3 ; python_version < "0"'
    assert rows[1]['version'] is None
    assert rows[2]['version'] is None
    (tmp_path / 'pyproject.toml').write_text('[project]\ndependencies = [\'Synthetic_Widget[extra]==1.2.3 ; python_version < "0"\', "synthetic-wild==1.2.*"]\n')
    pep_rows = parse_pyproject_toml(tmp_path / 'pyproject.toml')
    assert pep_rows == rows[:2]


def test_poetry_declaration_text_is_not_a_mapping(tmp_path):
    (tmp_path / 'pyproject.toml').write_text('[tool.poetry.dependencies]\nsynthetic = {version = "^1.2", extras = ["example"]}\n')
    [row] = parse_pyproject_toml(tmp_path / 'pyproject.toml')
    assert row['version'] == '^1.2'
    assert isinstance(row['declared_spec'], str)
    assert '^1.2' in row['declared_spec']
