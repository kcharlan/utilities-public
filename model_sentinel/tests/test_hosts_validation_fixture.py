from pathlib import Path
import os
import subprocess
import shutil

import pytest

from model_sentinel.browse import api
from model_sentinel.config import load_provider_configs, load_settings
from tests.test_model_view_validation_fixture import _validation_context


def test_hosts_runtime_loads_exact_fixture_and_disables_notifications(tmp_path):
    from tests.hosts_validation_fixture import build_hosts_validation_home

    home = build_hosts_validation_home(tmp_path / "synthetic-runtime")
    assert home == (tmp_path / "synthetic-runtime").resolve()
    assert {p.name for p in home.iterdir()} == {"providers.env", "settings.env", "model_sentinel.db"}
    providers = load_provider_configs(home / "providers.env")
    assert {p.provider_id for p in providers} == {"hosts_synthetic", "hosts_single_synthetic"}
    settings = load_settings(home / "settings.env", runtime_home=home)
    assert settings.notify_default is False
    assert settings.notify_on == "never"
    context, database = _validation_context(home)
    try:
        data = api.hosts(context, {"provider": "hosts_synthetic", "scrape_id": "1"})
        assert len(data["endpoints"]) == 135
        assert {host["name"] for host in data["hosts"]} >= {"Synthetic Alpha", "Synthetic Beta", "Synthetic Gamma"}
        assert api.hosts(context, {"provider": "hosts_synthetic"})["endpoints"] == []
    finally:
        database.close_all()


@pytest.mark.parametrize("builder_module", ["hosts_validation_fixture", "model_view_validation_fixture"])
def test_validation_builders_reject_occupied_repository_and_aliases(tmp_path, builder_module):
    from importlib import import_module

    module = import_module("tests." + builder_module)
    build = getattr(module, "build_hosts_validation_home", None) or module.build_model_view_validation_home
    root = Path(__file__).resolve().parents[2]
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    sentinel = occupied / "synthetic-sentinel"
    sentinel.write_text("synthetic occupied directory")
    alias = tmp_path / "repository-alias"
    alias.symlink_to(root, target_is_directory=True)
    for target in [root / "synthetic-runtime-must-not-exist", alias / "synthetic-runtime-must-not-exist"]:
        with pytest.raises(ValueError, match="outside the git repository"):
            build(target)
        assert not target.exists()
    common_dir = Path(subprocess.check_output(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root, text=True).strip())
    main_target = common_dir.parent / "synthetic-runtime-must-not-exist"
    assert not main_target.exists()
    try:
        with pytest.raises(ValueError, match="outside the git repository"):
            build(main_target)
        assert not main_target.exists()
    finally:
        if main_target.exists():
            shutil.rmtree(main_target)
    for target in [occupied, sentinel]:
        with pytest.raises(ValueError, match="new or empty directory"):
            build(target)
    upper = root.with_name(root.name.upper())
    if upper.exists() and os.path.samefile(upper, root):
        with pytest.raises(ValueError, match="outside the git repository"):
            build(upper / "MODEL_SENTINEL" / "synthetic-runtime-must-not-exist")
    assert sentinel.read_text() == "synthetic occupied directory"
