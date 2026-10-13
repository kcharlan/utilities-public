from pathlib import Path

import pytest
import traceback

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



def test_nonstrict_parser_preserves_duplicate_and_permissive_key_behavior(tmp_path: Path) -> None:
    env_path = tmp_path / "synthetic.env"
    env_path.write_text("export KEY=first\nodd-name=one\nodd-name=last\n", encoding="utf-8")
    assert parse_env_file(env_path) == {"export KEY": "first", "odd-name": "last"}


def test_strict_parser_supports_literal_assignment_subset() -> None:
    from model_sentinel.envfile import parse_env_text

    assert parse_env_text(
        "\n# comment\nEMPTY=\nKEY=unquoted # $ `literal` $(literal)\n"
        "SINGLE='SYNTHETIC_NOT_A_REAL_SECRET'\nDOUBLE=\"one\\ttwo\"\n",
        source=Path("synthetic.env"), strict=True,
    ) == {"EMPTY": "", "KEY": "unquoted # $ `literal` $(literal)",
          "SINGLE": "SYNTHETIC_NOT_A_REAL_SECRET", "DOUBLE": "one\ttwo"}


def test_text_parser_defaults_to_previous_permissive_behavior() -> None:
    from model_sentinel.envfile import parse_env_text

    assert parse_env_text("odd-key=first\nodd-key=last\n", source=Path("synthetic.env")) == {"odd-key": "last"}


@pytest.mark.parametrize("text", [
    "odd-key=value", "1KEY=value", "ÜKEY=value", "export KEY=value",
    "KEY=first\nKEY=second", "KEY", "=value", "KEY='unterminated",
    'KEY="unterminated', "KEY='one' 'two'", "KEY='first\nsecond'",
    "KEY=first\\\nsecond", "KEY='''multiline'''", "KEY=value'",
    "KEY=one\x00two",
])
def test_strict_parser_rejects_invalid_assignment_subset(text: str) -> None:
    from model_sentinel.envfile import EnvFileError, parse_env_text

    with pytest.raises(EnvFileError) as error:
        parse_env_text(text, source=Path("synthetic.env"), strict=True)
    assert str(error.value).startswith("synthetic.env:")


@pytest.mark.parametrize("ending", ["", "\\xZZ'"])
def test_strict_parser_errors_do_not_disclose_source_values_or_exception_chain(ending: str) -> None:
    from model_sentinel.envfile import EnvFileError, parse_env_text

    text = "KEY='SYNTHETIC_NOT_A_REAL_SECRET" + ending
    with pytest.raises(EnvFileError) as error:
        parse_env_text(text, source=Path("synthetic.env"), strict=True)
    formatted = "".join(traceback.format_exception(error.value))
    assert "SYNTHETIC_NOT_A_REAL_SECRET" not in formatted
    assert error.value.__cause__ is None
