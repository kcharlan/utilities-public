from pathlib import Path

from model_sentinel.envfile import parse_env_file


def test_parse_env_file_supports_basic_assignments(tmp_path: Path) -> None:
    env_path = tmp_path / "sample.env"
    env_path.write_text(
        "ALPHA=one\n"
        "BETA='two words'\n"
        "# comment\n"
        "GAMMA=\"three\"\n",
        encoding="utf-8",
    )
    assert parse_env_file(env_path) == {
        "ALPHA": "one",
        "BETA": "two words",
        "GAMMA": "three",
    }

