import pytest
from datetime import date, datetime, time, timezone

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - exercised in 3.10
    import tomli as tomllib  # type: ignore

from src.converters.toml_conv import dump_toml, load_toml


@pytest.fixture
def sample_data():
    return {"a": "hello", "z": 1, "nested": {"x": 3.14, "y": True}}


@pytest.fixture
def sample_toml():
    return (
        'a = "hello"\n'
        "z = 1\n\n"
        "[nested]\n"
        "x = 3.14\n"
        "y = true\n"
    )


def test_load_toml(sample_toml):
    data = load_toml(sample_toml)
    assert data["a"] == "hello"
    assert data["nested"]["y"] is True


def test_dump_toml_round_trip(sample_data):
    toml_text = dump_toml(sample_data)
    reloaded = tomllib.loads(toml_text)
    assert reloaded == sample_data


@pytest.mark.parametrize("value", [
    date(2030, 1, 2), datetime(2030, 1, 2, 3, 4, 5, 123456),
    datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc), time(3, 4, 5, 123456),
    "2030-01-02", "2030-01-02T03:04:05Z", "03:04:05", "synthetic",
])
def test_toml_temporal_policy(value):
    data = {"value": value, "nested": {"items": [value]}, "name": "synthetic"}
    loaded = load_toml(dump_toml(data))
    assert loaded == data
    assert type(loaded["value"]) is type(value)
    assert type(loaded["nested"]["items"][0]) is type(value)
