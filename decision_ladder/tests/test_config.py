import json
import pytest


@pytest.mark.parametrize("age", [0, -1, True, None, "24", float("inf"), 87601])
def test_rejects_invalid_age(dl, age):
    home = dl.ensure_runtime_home(dl.runtime_home())
    (home / "config.json").write_text(json.dumps({"max_age_hours": age}))
    with pytest.raises(ValueError, match="max_age_hours"):
        dl.load_config()


def test_default_config_and_private_modes(dl):
    assert dl.load_config() == {"max_age_hours": 24}
    home = dl.runtime_home()
    assert home.stat().st_mode & 0o777 == 0o700
    assert (home / "config.json").stat().st_mode & 0o777 == 0o600
