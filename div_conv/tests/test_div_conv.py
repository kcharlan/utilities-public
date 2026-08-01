from __future__ import annotations

import csv
import dataclasses
import json
import os
import runpy
import stat
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest


PROJECT = Path(__file__).resolve().parents[1]
LAUNCHER = PROJECT / "div_conv"
APP = runpy.run_path(str(LAUNCHER))

VANGUARD_HOLDINGS_HEADERS = [
    "Account Number",
    "Investment Name",
    "Symbol",
    "Shares",
    "Share Price",
    "Total Value",
    "",
]
VANGUARD_ACCOUNT_ACTIVITY_HEADERS = [
    "Account Number",
    "Trade Date",
    "Run Date",
    "Transaction Activity",
    "Transaction Description",
    "Investment Name",
    "Share Price",
    "Transaction Shares",
    "Dollar Amount",
    "",
]
VANGUARD_COMPOSITE_TRANSACTION_HEADERS = [
    *APP["VANGUARD_HEADERS"],
    "Accrued Interest",
    "Account Type",
    "",
]


def run_cli(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DIV_CONV_HOME"] = str(home)
    return subprocess.run(
        [sys.executable, str(LAUNCHER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
        timeout=10,
    )


def write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def write_fidelity_history_csv(
    path: Path, rows: list[list[str]], *, include_notices: bool = True
) -> None:
    """Write the public shape of a Fidelity History export using fake data."""
    path.write_text("\ufeff\n\n", encoding="utf-8")
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(APP["FIDELITY_HISTORY_HEADERS"])
        writer.writerows(rows)
        if include_notices:
            writer.writerow([])
            writer.writerow(["SYNTHETIC FIDELITY EXPORT NOTICE"])
            writer.writerow(["SYNTHETIC FIDELITY LEGAL NOTICE"])


def write_vanguard_composite_csv(
    path: Path, transaction_rows: list[list[str]]
) -> None:
    """Write Vanguard's public multi-table export shape using fake data."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(VANGUARD_HOLDINGS_HEADERS)
        writer.writerow(
            [
                "SYNTHETIC VANGUARD ACCOUNT",
                "SYNTHETIC HOLDING ONLY",
                "SYNTH0",
                "1",
                "1.00",
                "1.00",
                "",
            ]
        )
        writer.writerows([[], [], []])
        writer.writerow(VANGUARD_COMPOSITE_TRANSACTION_HEADERS)
        writer.writerows(transaction_rows)
        writer.writerows([[], []])
        writer.writerow(VANGUARD_ACCOUNT_ACTIVITY_HEADERS)
        writer.writerow(
            [
                "SYNTHETIC VANGUARD ACCOUNT",
                "2030-01-04",
                "2030-01-05",
                "SYNTHETIC ACCOUNT ACTIVITY",
                "SYNTHETIC ACTIVITY ONLY",
                "SYNTHETIC SETTLEMENT FUND",
                "",
                "",
                "1.00",
                "",
            ]
        )


def configured_section(account: str, security: str, *, brokerage: str = "fidelity") -> dict:
    securities = {security: "SYNTHETIC INCOME FUND"}
    if brokerage == "vanguard":
        securities["@withdrawal"] = "SYNTHETIC CASH"
    return {
        "accounts": {account: "SYNTHETIC CHECKING"},
        "securities": securities,
        "categories": {"dividend": "Synthetic:Dividends"},
        "transfers": (
            {"withdrawal": "SYNTHETIC CASH"} if brokerage == "vanguard" else {}
        ),
    }


def write_config(home: Path, brokerages: dict, **extra: object) -> Path:
    home.mkdir(parents=True)
    path = home / "config.json"
    payload = {"schema_version": 1, "brokerages": brokerages, **extra}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_help_does_not_create_runtime_home(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    result = run_cli(home, "--help")
    assert result.returncode == 0
    assert "Fidelity and Vanguard" in result.stdout
    assert not home.exists()


def test_first_run_writes_empty_skeleton_and_stops(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    source = tmp_path / "input.csv"
    source.write_text("not,read\n", encoding="utf-8")

    result = run_cli(home, str(source))

    assert result.returncode == 2
    assert "CONFIGURATION REQUIRED" in result.stderr
    assert str(home / "config.json") in result.stderr
    config = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert config == {
        "schema_version": 1,
        "brokerages": {
            "fidelity": {
                "accounts": {},
                "securities": {},
                "categories": {},
                "transfers": {},
            },
            "vanguard": {
                "accounts": {},
                "securities": {},
                "categories": {},
                "transfers": {},
            },
        },
    }
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    assert stat.S_IMODE((home / "config.json").stat().st_mode) == 0o600
    assert not list(tmp_path.glob("*.qif"))


def test_missing_section_is_backfilled_without_losing_unknown_keys(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    path = write_config(
        home,
        {"fidelity": configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")},
        future_top_level={"keep": True},
    )
    config = json.loads(path.read_text(encoding="utf-8"))
    config["brokerages"]["fidelity"]["future_section_key"] = ["keep"]
    config["brokerages"]["future_brokerage"] = {"keep": "yes"}
    path.write_text(json.dumps(config), encoding="utf-8")

    loaded, added = APP["load_config"](path, warn=lambda _message: None)

    assert added == ["vanguard"]
    assert loaded["future_top_level"] == {"keep": True}
    assert loaded["brokerages"]["fidelity"]["future_section_key"] == ["keep"]
    assert loaded["brokerages"]["future_brokerage"] == {"keep": "yes"}
    assert loaded["brokerages"]["vanguard"] == APP["empty_brokerage_section"]()


def test_backfill_warning_is_prominent_and_configured_brokerage_continues(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    write_config(
        home,
        {"fidelity": configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")},
    )
    source = tmp_path / "synthetic-fidelity.csv"
    write_csv(
        source,
        APP["FIDELITY_HEADERS"],
        [[
            "SYNTHETIC FIDELITY ACCOUNT",
            "2030-01-02",
            "DIVIDEND RECEIVED",
            "SYNTH1",
            "SYNTHETIC INCOME FUND",
            "",
            "",
            "",
            "",
            "",
            "10.00",
            "2030-01-05",
        ]],
    )

    result = run_cli(home, str(source))

    assert result.returncode == 0, result.stderr
    assert "CONFIG SECTION BACKFILLED" in result.stderr
    assert "vanguard" in result.stderr
    assert str(home / "config.json") in result.stderr
    assert (tmp_path / "synthetic-fidelity.cooked.csv").is_file()
    assert (tmp_path / "synthetic-fidelity.qif").is_file()


def test_selecting_incomplete_backfilled_section_fails_actionably(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    write_config(
        home,
        {"fidelity": configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")},
    )
    source = tmp_path / "synthetic-vanguard.csv"
    write_csv(source, APP["VANGUARD_HEADERS"], [])

    result = run_cli(home, "--brokerage", "vanguard", str(source))

    assert result.returncode == 2
    assert "INCOMPLETE CONFIGURATION" in result.stderr
    assert "vanguard" in result.stderr
    assert "accounts" in result.stderr
    assert not (tmp_path / "synthetic-vanguard.qif").exists()


def test_vanguard_requires_reserved_fixed_withdrawal_security(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    section = configured_section(
        "SYNTHETIC VANGUARD ACCOUNT", "SYNTH2", brokerage="vanguard"
    )
    del section["securities"]["@withdrawal"]
    write_config(home, {"vanguard": section})
    source = tmp_path / "synthetic-vanguard.csv"
    write_csv(source, APP["VANGUARD_HEADERS"], [])

    result = run_cli(home, "--brokerage", "vanguard", str(source))

    assert result.returncode == 2
    assert "securities.@withdrawal" in result.stderr
    assert not (tmp_path / "synthetic-vanguard.qif").exists()


def test_schema_version_boolean_is_rejected(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    path = write_config(home, {}, schema_version=True)

    with pytest.raises(APP["UserError"], match="schema_version 1"):
        APP["load_config"](path, warn=lambda _message: None)


@pytest.mark.parametrize("mapping_key", ["accounts", "securities", "categories", "transfers"])
@pytest.mark.parametrize("blank_side", ["source", "output"])
def test_config_mappings_reject_whitespace_only_strings(
    tmp_path: Path, mapping_key: str, blank_side: str
) -> None:
    home = tmp_path / "runtime"
    section = configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")
    source_value = "   " if blank_side == "source" else "SYNTHETIC CASH"
    output_value = "   " if blank_side == "output" else "SYNTHETIC CASH"
    section[mapping_key][source_value] = output_value
    path = write_config(home, {"fidelity": section})

    with pytest.raises(APP["UserError"], match="non-empty strings"):
        APP["selected_section"](
            json.loads(path.read_text(encoding="utf-8")), "fidelity", path
        )


@pytest.mark.parametrize(
    ("mapping_key", "output_value", "message"),
    [
        ("categories", "[SYNTHETIC CASH]", "category mappings cannot contain"),
        ("transfers", "SYNTHETIC [CASH]", "provide the account name without"),
    ],
)
def test_qif_mapping_values_reject_transfer_brackets(
    tmp_path: Path, mapping_key: str, output_value: str, message: str
) -> None:
    home = tmp_path / "runtime"
    section = configured_section(
        "SYNTHETIC VANGUARD ACCOUNT", "SYNTH2", brokerage="vanguard"
    )
    required_key = "dividend" if mapping_key == "categories" else "withdrawal"
    section[mapping_key][required_key] = output_value
    path = write_config(home, {"vanguard": section})

    with pytest.raises(APP["UserError"], match=message):
        APP["selected_section"](
            json.loads(path.read_text(encoding="utf-8")), "vanguard", path
        )


def test_atomic_write_cleans_temporary_file_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.json"

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="synthetic replace failure"):
        APP["atomic_write_json"](path, {"schema_version": 1})

    assert not path.exists()
    assert not list(tmp_path.glob(".config.json.*.tmp"))


def test_auto_detection_rejects_mixed_brokerage_batch(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    write_config(
        home,
        {
            "fidelity": configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1"),
            "vanguard": configured_section(
                "SYNTHETIC VANGUARD ACCOUNT", "SYNTH2", brokerage="vanguard"
            ),
        },
    )
    fidelity = tmp_path / "fidelity.csv"
    vanguard = tmp_path / "vanguard.csv"
    write_csv(fidelity, APP["FIDELITY_HEADERS"], [])
    write_csv(vanguard, APP["VANGUARD_HEADERS"], [])

    result = run_cli(home, str(fidelity), str(vanguard))

    assert result.returncode == 2
    assert "MIXED BROKERAGES" in result.stderr
    assert not list(tmp_path.glob("*.qif"))


def test_explicit_override_rejects_wrong_csv_contract(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    write_config(
        home,
        {"fidelity": configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")},
    )
    source = tmp_path / "synthetic-vanguard.csv"
    write_csv(source, APP["VANGUARD_HEADERS"], [])

    result = run_cli(home, "--brokerage", "fidelity", str(source))

    assert result.returncode == 2
    assert "does not match the fidelity CSV contract" in result.stderr


def test_explicit_brokerage_resolves_union_header_ambiguity(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    write_config(
        home,
        {"fidelity": configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")},
    )
    source = tmp_path / "synthetic-union.csv"
    headers = [
        *APP["FIDELITY_HEADERS"],
        *(header for header in APP["VANGUARD_HEADERS"] if header not in APP["FIDELITY_HEADERS"]),
    ]
    values = {
        "Account": "SYNTHETIC FIDELITY ACCOUNT",
        "Run Date": "2030-01-02",
        "Action": "DIVIDEND RECEIVED",
        "Symbol": "SYNTH1",
        "Description": "SYNTHETIC INCOME FUND",
        "Amount ($)": "10.00",
        "Settlement Date": "2030-01-05",
    }
    write_csv(source, headers, [[values.get(header, "") for header in headers]])

    ambiguous = run_cli(home, str(source))
    explicit = run_cli(home, "--brokerage", "fidelity", str(source))

    assert ambiguous.returncode == 2
    assert "AMBIGUOUS CSV CONTRACT" in ambiguous.stderr
    assert explicit.returncode == 0, explicit.stderr
    assert (tmp_path / "synthetic-union.qif").is_file()


def test_fidelity_history_export_is_detected_and_converted(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    write_config(
        home,
        {"fidelity": configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")},
    )
    source = tmp_path / "synthetic-fidelity-history.csv"
    common = [
        "01/02/2030",
        "Dividend Received Synthetic Income Distribution (Cash)",
        "SYNTH1",
        "SYNTHETIC INCOME FUND",
        "SYNTHETIC CASH TYPE",
        "",
        "2.000",
        "",
        "",
        "",
        "10.00",
        "100.00",
        "01/05/2030",
    ]
    reinvestment = [
        *common[:1],
        "Reinvestment Synthetic Income Distribution",
        *common[2:],
    ]
    write_fidelity_history_csv(source, [common, reinvestment])

    result = run_cli(home, str(source))

    assert result.returncode == 0, result.stderr
    cooked_path = tmp_path / "synthetic-fidelity-history.cooked.csv"
    assert cooked_path.read_bytes().splitlines(keepends=True)[0].endswith(b"\r\n")
    cooked = list(csv.DictReader(cooked_path.open(encoding="utf-8")))
    assert len(cooked) == 2
    assert list(cooked[0]) == APP["FIDELITY_HISTORY_HEADERS"]
    assert cooked[0]["Run Date"] == "1/2/30"
    assert cooked[0]["Quantity"] == "2"
    assert cooked[1]["Run Date"] == "1/2/30"
    assert cooked[1]["Action"].startswith("Reinvestment")
    qif = (tmp_path / "synthetic-fidelity-history.qif").read_text(encoding="utf-8")
    assert qif.startswith("!Type:Invst\n")
    assert "!Account" not in qif
    assert qif.count("^\n") == 1
    assert "D1/2'30\n" in qif
    assert "NMiscInc\n" in qif
    assert "T10.00\nMDividend SYNTH1\nLSynthetic:Dividends\n" in qif
    assert "Skipped action 'REINVESTMENT'" in result.stderr
    assert "1 transaction(s)" in result.stdout
    assert (
        "synthetic-fidelity-history.csv: row 4 | 2030-01-02 | dividend | "
        "SYNTHETIC INCOME FUND | 10.00"
    ) in result.stdout


def test_accountless_fidelity_history_rejects_multiple_configured_accounts(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    section = configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")
    section["accounts"]["SYNTHETIC SECOND FIDELITY ACCOUNT"] = "SYNTHETIC SAVINGS"
    write_config(home, {"fidelity": section})
    source = tmp_path / "synthetic-fidelity-history.csv"
    write_fidelity_history_csv(source, [], include_notices=False)

    result = run_cli(home, str(source))

    assert result.returncode == 2
    assert "without an Account column" in result.stderr
    assert "Exactly one mapping is required" in result.stderr
    assert not (tmp_path / "synthetic-fidelity-history.qif").exists()


def test_fidelity_history_rejects_short_tabular_row_before_trailer(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    write_config(
        home,
        {"fidelity": configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")},
    )
    source = tmp_path / "synthetic-fidelity-history.csv"
    write_fidelity_history_csv(
        source,
        [["01/02/2030", "Dividend Received"]],
        include_notices=False,
    )

    result = run_cli(home, str(source))

    assert result.returncode == 2
    assert "missing" in result.stderr
    assert "row 4" in result.stderr
    assert not (tmp_path / "synthetic-fidelity-history.qif").exists()


def test_glob_multi_file_conversion_writes_cooked_csv_qif_and_summary(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    write_config(
        home,
        {"fidelity": configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")},
    )
    for index, amount in enumerate(("10.00", "20.00"), start=1):
        write_csv(
            tmp_path / f"synthetic-{index}.csv",
            APP["FIDELITY_HEADERS"],
            [[
                "SYNTHETIC FIDELITY ACCOUNT",
                f"2030-01-0{index + 1}",
                "DIVIDEND RECEIVED",
                "SYNTH1",
                "SYNTHETIC INCOME FUND",
                "",
                "",
                "",
                "",
                "",
                amount,
                "2030-01-05",
            ]],
        )

    result = run_cli(home, str(tmp_path / "synthetic-*.csv"))

    assert result.returncode == 0, result.stderr
    assert "2 file(s), 2 transaction(s)" in result.stdout
    assert "30.00" in result.stdout
    for index in (1, 2):
        cooked = tmp_path / f"synthetic-{index}.cooked.csv"
        qif = tmp_path / f"synthetic-{index}.qif"
        assert cooked.is_file()
        assert qif.is_file()
        rows = list(csv.DictReader(cooked.open(encoding="utf-8")))
        assert list(rows[0]) == APP["FIDELITY_HEADERS"]
        assert rows[0]["Account"] == "SYNTHETIC FIDELITY ACCOUNT"
        assert rows[0]["Run Date"] == f"1/{index + 1}/30"
        qif_text = qif.read_text(encoding="utf-8")
        assert qif_text.startswith("!Type:Invst\n")
        assert "!Account" not in qif_text
        assert "NMiscInc\n" in qif_text
        assert "LSynthetic:Dividends\n" in qif_text
        assert (
            f"synthetic-{index}.csv: row 2 | 2030-01-0{index + 1} | dividend | "
            f"SYNTHETIC INCOME FUND | {index}0.00"
        ) in result.stdout


def test_unknown_account_fails_before_any_outputs_are_committed(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    write_config(
        home,
        {"fidelity": configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")},
    )
    source = tmp_path / "unknown.csv"
    write_csv(
        source,
        APP["FIDELITY_HEADERS"],
        [[
            "SYNTHETIC UNKNOWN ACCOUNT",
            "2030-01-02",
            "DIVIDEND RECEIVED",
            "SYNTH1",
            "SYNTHETIC INCOME FUND",
            "",
            "",
            "",
            "",
            "",
            "10.00",
            "2030-01-05",
        ]],
    )

    result = run_cli(home, str(source))

    assert result.returncode == 2
    assert "unmapped account" in result.stderr
    assert "accounts" in result.stderr
    assert not (tmp_path / "unknown.cooked.csv").exists()
    assert not (tmp_path / "unknown.qif").exists()


def test_fidelity_processes_dividend_and_visibly_skips_reinvestment(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    write_config(
        home,
        {"fidelity": configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")},
    )
    source = tmp_path / "synthetic-fidelity.csv"
    common = [
        "SYNTHETIC FIDELITY ACCOUNT",
        "2030-01-02",
        "DIVIDEND RECEIVED",
        "SYNTH1",
        "SYNTHETIC INCOME FUND",
        "",
        "",
        "",
        "",
        "",
        "10.00",
        "2030-01-05",
    ]
    write_csv(
        source,
        APP["FIDELITY_HEADERS"],
        [common, [*common[:2], "REINVESTMENT", *common[3:]]],
    )

    result = run_cli(home, str(source))

    assert result.returncode == 0, result.stderr
    qif = (tmp_path / "synthetic-fidelity.qif").read_text(encoding="utf-8")
    assert qif.count("NMiscInc\n") == 1
    assert "ReinvDiv" not in qif
    assert "D1/2'30\n" in qif
    assert "MDividend SYNTH1\n" in qif
    assert "Skipped action 'REINVESTMENT'" in result.stderr
    assert "1 transaction(s)" in result.stdout


def test_invocation_wide_source_output_collision_is_rejected_even_with_overwrite(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    write_config(
        home,
        {"fidelity": configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")},
    )
    first = tmp_path / "synthetic.csv"
    colliding_source = tmp_path / "synthetic.cooked.csv"
    row = [
        "SYNTHETIC FIDELITY ACCOUNT",
        "2030-01-02",
        "DIVIDEND RECEIVED",
        "SYNTH1",
        "SYNTHETIC INCOME FUND",
        "",
        "",
        "",
        "",
        "",
        "10.00",
        "2030-01-05",
    ]
    write_csv(first, APP["FIDELITY_HEADERS"], [row])
    write_csv(colliding_source, APP["FIDELITY_HEADERS"], [row])
    original = colliding_source.read_bytes()

    result = run_cli(home, "--overwrite", str(first), str(colliding_source))

    assert result.returncode == 2
    assert "output path collides with an input" in result.stderr
    assert str(colliding_source) in result.stderr
    assert colliding_source.read_bytes() == original
    assert not (tmp_path / "synthetic.qif").exists()
    assert_no_transaction_temps(tmp_path)


def test_qif_control_character_from_config_is_rejected(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    section = configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")
    section["accounts"]["SYNTHETIC FIDELITY ACCOUNT"] = "SYNTHETIC\n^"
    write_config(home, {"fidelity": section})
    source = tmp_path / "synthetic.csv"
    write_csv(source, APP["FIDELITY_HEADERS"], [])

    result = run_cli(home, str(source))

    assert result.returncode == 2
    assert "control character" in result.stderr
    assert "brokerages.fidelity.accounts" in result.stderr
    assert not (tmp_path / "synthetic.qif").exists()


def test_control_character_in_source_output_field_is_rejected(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    source_account = "SYNTHETIC\nACCOUNT"
    write_config(
        home,
        {"fidelity": configured_section(source_account, "SYNTH1")},
    )
    source = tmp_path / "synthetic.csv"
    write_csv(
        source,
        APP["FIDELITY_HEADERS"],
        [[
            source_account,
            "2030-01-02",
            "DIVIDEND RECEIVED",
            "SYNTH1",
            "SYNTHETIC INCOME FUND",
            "",
            "",
            "",
            "",
            "",
            "10.00",
            "2030-01-05",
        ]],
    )

    result = run_cli(home, str(source))

    assert result.returncode == 2
    assert "control character" in result.stderr
    assert "source account" in result.stderr
    assert not (tmp_path / "synthetic.qif").exists()


def test_spreadsheet_formula_from_config_is_rejected_actionably(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    section = configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")
    section["securities"]["SYNTH1"] = "=SYNTHETIC()"
    write_config(home, {"fidelity": section})
    source = tmp_path / "synthetic.csv"
    write_csv(source, APP["FIDELITY_HEADERS"], [])

    result = run_cli(home, str(source))

    assert result.returncode == 2
    assert "spreadsheet formula" in result.stderr
    assert "brokerages.fidelity.securities" in result.stderr
    assert "Change the configured value" in result.stderr


def test_spreadsheet_formula_source_filename_is_rejected_actionably(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    write_config(
        home,
        {"fidelity": configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")},
    )
    source = tmp_path / "=SYNTHETIC.csv"
    write_csv(source, APP["FIDELITY_HEADERS"], [])

    result = run_cli(home, str(source))

    assert result.returncode == 2
    assert "spreadsheet formula" in result.stderr
    assert "Rename the source file" in result.stderr
    assert not (tmp_path / "=SYNTHETIC.cooked.csv").exists()


def test_existing_runtime_paths_are_hardened_to_private_modes(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    path = write_config(
        home,
        {"fidelity": configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")},
    )
    home.chmod(0o777)
    path.chmod(0o666)
    source = tmp_path / "synthetic.csv"
    write_csv(source, APP["FIDELITY_HEADERS"], [])

    result = run_cli(home, str(source))

    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_runtime_home_symlink_is_rejected_without_chmodding_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "runtime-target"
    target.mkdir(mode=0o755)
    target.chmod(0o755)
    home = tmp_path / "runtime-link"
    home.symlink_to(target, target_is_directory=True)
    source = tmp_path / "synthetic.csv"
    source.write_text("not,read\n", encoding="utf-8")

    result = run_cli(home, str(source))

    assert result.returncode == 2
    assert "runtime directory" in result.stderr
    assert "symbolic link" in result.stderr
    assert stat.S_IMODE(target.stat().st_mode) == 0o755
    assert not (target / "config.json").exists()


def test_config_symlink_is_rejected_without_chmodding_or_reading_target(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    home.mkdir()
    target = tmp_path / "synthetic-config-target.json"
    payload = {
        "schema_version": 1,
        "brokerages": {
            "fidelity": configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")
        },
    }
    target.write_text(json.dumps(payload), encoding="utf-8")
    target.chmod(0o644)
    original = target.read_bytes()
    (home / "config.json").symlink_to(target)
    source = tmp_path / "synthetic.csv"
    write_csv(source, APP["FIDELITY_HEADERS"], [])

    result = run_cli(home, str(source))

    assert result.returncode == 2
    assert "configuration file" in result.stderr
    assert "symbolic link" in result.stderr
    assert target.read_bytes() == original
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_runtime_mode_hardening_error_is_reported_actionably(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    home.mkdir()

    def fail_fchmod(_descriptor: int, _mode: int) -> None:
        raise PermissionError("synthetic permission failure")

    monkeypatch.setattr(os, "fchmod", fail_fchmod)

    with pytest.raises(APP["UserError"], match="mode 0700.*synthetic permission failure"):
        APP["secure_runtime_directory"](home)


def test_huge_finite_amount_is_rejected_without_render_crash(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    write_config(
        home,
        {"fidelity": configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")},
    )
    source = tmp_path / "synthetic.csv"
    row = [
        "SYNTHETIC FIDELITY ACCOUNT",
        "2030-01-02",
        "DIVIDEND RECEIVED",
        "SYNTH1",
        "SYNTHETIC INCOME FUND",
        "",
        "",
        "",
        "",
        "",
        "9" * 101,
        "2030-01-05",
    ]
    write_csv(source, APP["FIDELITY_HEADERS"], [row])

    result = run_cli(home, str(source))

    assert result.returncode == 2
    assert "too large to render safely" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "synthetic.cooked.csv").exists()
    assert not (tmp_path / "synthetic.qif").exists()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1234.56", Decimal("1234.56")),
        ("-1234.56", Decimal("-1234.56")),
        ("$1,234.56", Decimal("1234.56")),
        ("-$1,234.56", Decimal("-1234.56")),
        ("$-1,234.56", Decimal("-1234.56")),
        ("(1,234.56)", Decimal("-1234.56")),
        ("($1,234.56)", Decimal("-1234.56")),
    ],
)
def test_parse_amount_accepts_strict_ordinary_financial_forms(
    tmp_path: Path, text: str, expected: Decimal
) -> None:
    assert APP["parse_amount"](text, tmp_path / "synthetic.csv", 2) == expected


@pytest.mark.parametrize("text", ["1$2", "12,34", "$1$2", "--12", "(12.00"])
def test_parse_amount_rejects_malformed_financial_forms(
    tmp_path: Path, text: str
) -> None:
    with pytest.raises(APP["UserError"], match="invalid amount"):
        APP["parse_amount"](text, tmp_path / "synthetic.csv", 2)


def test_extra_undeclared_csv_row_cells_are_rejected(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    write_config(
        home,
        {"fidelity": configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")},
    )
    source = tmp_path / "synthetic.csv"
    row = [
        "SYNTHETIC FIDELITY ACCOUNT",
        "2030-01-02",
        "DIVIDEND RECEIVED",
        "SYNTH1",
        "SYNTHETIC INCOME FUND",
        "",
        "",
        "",
        "",
        "",
        "10.00",
        "2030-01-05",
        "SYNTHETIC EXTRA CELL",
    ]
    write_csv(source, APP["FIDELITY_HEADERS"], [row])

    result = run_cli(home, str(source))

    assert result.returncode == 2
    assert "extra cell" in result.stderr
    assert "row 2" in result.stderr
    assert not (tmp_path / "synthetic.qif").exists()


def test_vanguard_composite_export_selects_embedded_transaction_table(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    write_config(
        home,
        {
            "vanguard": configured_section(
                "SYNTHETIC VANGUARD ACCOUNT", "SYNTH2", brokerage="vanguard"
            )
        },
    )
    source = tmp_path / "synthetic-vanguard-composite.csv"
    write_vanguard_composite_csv(
        source,
        [[
            "SYNTHETIC VANGUARD ACCOUNT",
            "2030-01-03",
            "2030-01-05",
            "Dividend",
            "SYNTHETIC DIVIDEND DESCRIPTION",
            "SYNTHETIC SETTLEMENT FUND",
            "SYNTH2",
            "",
            "",
            "",
            "",
            "40.00",
            "",
            "SYNTHETIC BROKERAGE",
            "",
        ]],
    )

    result = run_cli(home, str(source))

    assert result.returncode == 0, result.stderr
    cooked_path = tmp_path / "synthetic-vanguard-composite.cooked.csv"
    cooked_text = cooked_path.read_text(encoding="utf-8")
    cooked = list(csv.DictReader(cooked_text.splitlines()))
    assert len(cooked) == 1
    assert list(cooked[0]) == VANGUARD_COMPOSITE_TRANSACTION_HEADERS
    assert cooked[0]["Transaction Type"] == "Dividend"
    assert cooked[0]["Account Type"] == "SYNTHETIC BROKERAGE"
    assert "SYNTHETIC HOLDING ONLY" not in cooked_text
    assert "SYNTHETIC ACTIVITY ONLY" not in cooked_text

    qif = (tmp_path / "synthetic-vanguard-composite.qif").read_text(
        encoding="utf-8"
    )
    assert qif.count("NMiscInc\n") == 1
    assert "SYNTHETIC HOLDING ONLY" not in qif
    assert "SYNTHETIC ACTIVITY ONLY" not in qif
    assert (
        "synthetic-vanguard-composite.csv: row 7 | 2030-01-03 | dividend | "
        "SYNTHETIC INCOME FUND | 40.00"
    ) in result.stdout


def test_vanguard_composite_export_rejects_multiple_transaction_tables(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    write_config(
        home,
        {
            "vanguard": configured_section(
                "SYNTHETIC VANGUARD ACCOUNT", "SYNTH2", brokerage="vanguard"
            )
        },
    )
    source = tmp_path / "synthetic-duplicate-vanguard-tables.csv"
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(VANGUARD_COMPOSITE_TRANSACTION_HEADERS)
        writer.writerows([[], []])
        writer.writerow(VANGUARD_COMPOSITE_TRANSACTION_HEADERS)

    result = run_cli(home, str(source))

    assert result.returncode == 2
    assert "MULTIPLE CSV CONTRACT SECTIONS" in result.stderr
    assert "more than one vanguard transaction table" in result.stderr
    assert not (tmp_path / "synthetic-duplicate-vanguard-tables.cooked.csv").exists()
    assert not (tmp_path / "synthetic-duplicate-vanguard-tables.qif").exists()


def test_vanguard_composite_export_does_not_hide_malformed_row_after_blank(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    write_config(
        home,
        {
            "vanguard": configured_section(
                "SYNTHETIC VANGUARD ACCOUNT", "SYNTH2", brokerage="vanguard"
            )
        },
    )
    source = tmp_path / "synthetic-malformed-vanguard-composite.csv"
    write_vanguard_composite_csv(
        source,
        [
            [
                "SYNTHETIC VANGUARD ACCOUNT",
                "2030-01-03",
                "2030-01-05",
                "Dividend",
                "SYNTHETIC DIVIDEND DESCRIPTION",
                "SYNTHETIC SETTLEMENT FUND",
                "SYNTH2",
                "",
                "",
                "",
                "",
                "40.00",
                "",
                "SYNTHETIC BROKERAGE",
                "",
            ],
            [],
            ["SYNTHETIC VANGUARD ACCOUNT"],
        ],
    )

    result = run_cli(home, str(source))

    assert result.returncode == 2
    assert "row 9" in result.stderr
    assert "missing" in result.stderr
    assert not (tmp_path / "synthetic-malformed-vanguard-composite.cooked.csv").exists()
    assert not (tmp_path / "synthetic-malformed-vanguard-composite.qif").exists()


def test_vanguard_processes_dividend_and_withdrawal_and_visibly_skips_legacy_rows(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    write_config(
        home,
        {
            "vanguard": configured_section(
                "SYNTHETIC VANGUARD ACCOUNT", "SYNTH2", brokerage="vanguard"
            )
        },
    )
    source = tmp_path / "synthetic-vanguard.csv"
    write_csv(
        source,
        APP["VANGUARD_HEADERS"],
        [
            [
                "SYNTHETIC VANGUARD ACCOUNT",
                "2030-01-03",
                "2030-01-05",
                action,
                description,
                "SYNTHETIC SETTLEMENT FUND",
                "SYNTH2",
                "",
                "",
                "",
                "",
                amount,
            ]
            for action, amount, description in (
                ("Dividend", "40.00", "SYNTHETIC DIVIDEND DESCRIPTION"),
                ("Withdrawal", "-15.00", "SYNTHETIC WITHDRAWAL MEMO"),
                ("Withdrawal", "-5.00", ""),
                ("Reinvestment", "-40.00", "SYNTHETIC REINVESTMENT DESCRIPTION"),
                ("Sweep out", "15.00", "SYNTHETIC SWEEP DESCRIPTION"),
            )
        ],
    )

    result = run_cli(home, str(source))

    assert result.returncode == 0, result.stderr
    cooked = list(
        csv.DictReader(
            (tmp_path / "synthetic-vanguard.cooked.csv").open(encoding="utf-8")
        )
    )
    assert len(cooked) == 5
    assert list(cooked[0]) == APP["VANGUARD_HEADERS"]
    assert [row["Transaction Type"] for row in cooked] == [
        "Dividend",
        "Withdrawal",
        "Withdrawal",
        "Reinvestment",
        "Sweep out",
    ]
    qif = (tmp_path / "synthetic-vanguard.qif").read_text(encoding="utf-8")
    assert qif.startswith("!Type:Invst\n")
    assert "!Account" not in qif
    assert qif.count("^\n") == 3
    assert "NMiscInc\n" in qif
    assert "NXOut\n" in qif
    assert "NMiscInc\nYSYNTHETIC INCOME FUND\n" in qif
    assert "MDividend SYNTH2\n" in qif
    assert "NXOut\nYSYNTHETIC CASH\n" in qif
    assert "MSYNTHETIC WITHDRAWAL MEMO\nL[SYNTHETIC CASH]\n" in qif
    assert "MWithdrawal\n" in qif
    assert "D1/3'30\n" in qif
    assert "T15.00\n" in qif
    assert "Skipped action 'Reinvestment'" in result.stderr
    assert "Skipped action 'Sweep out'" in result.stderr
    assert "3 transaction(s)" in result.stdout
    assert (
        "synthetic-vanguard.csv: row 2 | 2030-01-03 | dividend | "
        "SYNTHETIC INCOME FUND | 40.00"
    ) in result.stdout
    assert (
        "synthetic-vanguard.csv: row 3 | 2030-01-03 | withdrawal | "
        "SYNTHETIC CASH | 15.00"
    ) in result.stdout


def test_vanguard_withdrawal_memo_rejects_qif_record_injection(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    write_config(
        home,
        {
            "vanguard": configured_section(
                "SYNTHETIC VANGUARD ACCOUNT", "SYNTH2", brokerage="vanguard"
            )
        },
    )
    source = tmp_path / "synthetic-vanguard.csv"
    write_csv(
        source,
        APP["VANGUARD_HEADERS"],
        [[
            "SYNTHETIC VANGUARD ACCOUNT",
            "2030-01-03",
            "2030-01-05",
            "Withdrawal",
            "SYNTHETIC\n^",
            "",
            "",
            "",
            "",
            "",
            "",
            "-5.00",
        ]],
    )

    result = run_cli(home, str(source))

    assert result.returncode == 2
    assert "withdrawal description" in result.stderr
    assert "control character" in result.stderr
    assert not (tmp_path / "synthetic-vanguard.qif").exists()


def test_invalid_row_in_later_file_prevents_all_batch_outputs(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    write_config(
        home,
        {"fidelity": configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")},
    )
    valid = tmp_path / "synthetic-valid.csv"
    invalid = tmp_path / "synthetic-invalid.csv"
    common = [
        "SYNTHETIC FIDELITY ACCOUNT",
        "2030-01-04",
        "DIVIDEND RECEIVED",
        "SYNTH1",
        "SYNTHETIC INCOME FUND",
        "",
        "",
        "",
        "",
        "",
        "30.00",
        "2030-01-05",
    ]
    write_csv(valid, APP["FIDELITY_HEADERS"], [common])
    write_csv(
        invalid,
        APP["FIDELITY_HEADERS"],
        [[*common[:2], "SYNTHETIC UNKNOWN ACTION", *common[3:]]],
    )

    result = run_cli(home, str(valid), str(invalid))

    assert result.returncode == 2
    assert "unsupported action" in result.stderr
    assert not (tmp_path / "synthetic-valid.cooked.csv").exists()
    assert not (tmp_path / "synthetic-valid.qif").exists()


def test_adapter_registry_owns_contracts_and_keeps_extractors_separate() -> None:
    adapters = APP["ADAPTERS"]

    assert set(adapters) == {"fidelity", "vanguard"}
    assert "Commissions and Fees" in APP["VANGUARD_HEADERS"]
    assert "Commission Fees" not in APP["VANGUARD_HEADERS"]
    assert adapters["fidelity"].required_headers == tuple(APP["FIDELITY_HEADERS"])
    assert adapters["fidelity"].alternate_required_headers == (
        tuple(APP["FIDELITY_HISTORY_HEADERS"]),
    )
    assert adapters["vanguard"].required_headers == tuple(APP["VANGUARD_HEADERS"])
    assert adapters["vanguard"].alternate_required_headers == ()
    assert adapters["fidelity"].actions == {
        "DIVIDEND RECEIVED": "dividend",
    }
    assert adapters["vanguard"].actions == {
        "Dividend": "dividend",
        "Withdrawal": "withdrawal",
    }
    assert adapters["fidelity"].skipped_actions == ("REINVESTMENT",)
    assert adapters["vanguard"].skipped_actions == ("Reinvestment", "Sweep out")
    assert adapters["fidelity"].required_security_keys == ()
    assert adapters["vanguard"].required_security_keys == ("@withdrawal",)
    assert adapters["fidelity"].surrounding_section_headers == ()
    assert adapters["vanguard"].surrounding_section_headers == (
        tuple(APP["VANGUARD_HOLDINGS_HEADERS"]),
        tuple(APP["VANGUARD_ACCOUNT_ACTIVITY_HEADERS"]),
    )
    assert adapters["fidelity"].allows_trailing_notices is True
    assert adapters["vanguard"].allows_trailing_notices is False
    assert adapters["fidelity"].extractor is not adapters["vanguard"].extractor


def test_registry_dispatch_calls_only_selected_adapter_extractor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "synthetic-fidelity.csv"
    write_csv(
        source,
        APP["FIDELITY_HEADERS"],
        [[
            "SYNTHETIC FIDELITY ACCOUNT",
            "2030-01-02",
            "DIVIDEND RECEIVED",
            "SYNTH1",
            "SYNTHETIC INCOME FUND",
            "",
            "",
            "",
            "",
            "",
            "10.00",
            "2030-01-05",
        ]],
    )
    calls = {"fidelity": 0, "vanguard": 0}
    fidelity = APP["ADAPTERS"]["fidelity"]
    vanguard = APP["ADAPTERS"]["vanguard"]

    def fidelity_extractor(row: dict[str, str]) -> object:
        calls["fidelity"] += 1
        return fidelity.extractor(row)

    def vanguard_extractor(row: dict[str, str]) -> object:
        calls["vanguard"] += 1
        return vanguard.extractor(row)

    monkeypatch.setitem(
        APP["ADAPTERS"],
        "fidelity",
        dataclasses.replace(fidelity, extractor=fidelity_extractor),
    )
    monkeypatch.setitem(
        APP["ADAPTERS"],
        "vanguard",
        dataclasses.replace(vanguard, extractor=vanguard_extractor),
    )

    transactions = APP["read_raw_transactions"](source, "fidelity")

    assert len(transactions) == 1
    assert calls == {"fidelity": 1, "vanguard": 0}


def assert_no_transaction_temps(directory: Path) -> None:
    assert not list(directory.glob(".*.div-conv-stage-*.tmp"))
    assert not list(directory.glob(".*.div-conv-backup-*.tmp"))


@pytest.mark.parametrize("overwrite", [False, True])
def test_dangling_output_symlink_is_rejected_and_preserved(
    tmp_path: Path, overwrite: bool
) -> None:
    home = tmp_path / "runtime"
    write_config(
        home,
        {"fidelity": configured_section("SYNTHETIC FIDELITY ACCOUNT", "SYNTH1")},
    )
    source = tmp_path / "synthetic.csv"
    write_csv(source, APP["FIDELITY_HEADERS"], [])
    output = tmp_path / "synthetic.cooked.csv"
    output.symlink_to(tmp_path / "SYNTHETIC MISSING OUTPUT")
    arguments = ["--overwrite"] if overwrite else []

    result = run_cli(home, *arguments, str(source))

    assert result.returncode == 2
    assert "symbolic-link output path" in result.stderr
    assert output.is_symlink()
    assert not (tmp_path / "synthetic.qif").exists()


def test_no_overwrite_commit_does_not_replace_target_created_during_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cooked = tmp_path / "synthetic.cooked.csv"
    qif = tmp_path / "synthetic.qif"
    original_link = APP["transaction_link_no_replace"]

    def create_racing_target(source: Path, target: Path) -> None:
        if target == qif:
            target.write_bytes(b"synthetic racing writer")
        original_link(source, target)

    monkeypatch.setitem(
        APP["commit_output_transaction"].__globals__,
        "transaction_link_no_replace",
        create_racing_target,
    )

    with pytest.raises(FileExistsError):
        APP["commit_output_transaction"](
            [(cooked, b"cooked"), (qif, b"qif")], overwrite=False
        )

    assert not cooked.exists()
    assert qif.read_bytes() == b"synthetic racing writer"
    assert_no_transaction_temps(tmp_path)


def test_overwrite_commit_preserves_target_created_after_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "synthetic.qif"
    target.write_bytes(b"original qif")
    original_link = APP["transaction_link_no_replace"]
    racing_content = b"synthetic racing writer"
    raced = False

    def create_target_after_backup(source: Path, destination: Path) -> None:
        nonlocal raced
        if not raced and "div-conv-stage" in source.name and destination == target:
            raced = True
            destination.write_bytes(racing_content)
        original_link(source, destination)

    monkeypatch.setitem(
        APP["commit_output_transaction"].__globals__,
        "transaction_link_no_replace",
        create_target_after_backup,
    )

    with pytest.raises(OSError) as captured:
        APP["commit_output_transaction"]([(target, b"new qif")], overwrite=True)

    assert "rollback also failed" in str(captured.value)
    assert target.read_bytes() == racing_content
    backups = list(tmp_path.glob(".synthetic.qif.div-conv-backup-*.tmp"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"original qif"
    assert str(backups[0]) in str(captured.value)
    assert not list(tmp_path.glob(".*.div-conv-stage-*.tmp"))


@pytest.mark.parametrize("target_kind", ["directory", "fifo"])
def test_overwrite_rejects_every_existing_non_regular_output_target(
    tmp_path: Path, target_kind: str
) -> None:
    source = tmp_path / "synthetic.csv"
    source.write_bytes(b"synthetic input")
    target = tmp_path / "synthetic.qif"
    if target_kind == "directory":
        target.mkdir()
    else:
        os.mkfifo(target)

    with pytest.raises(APP["UserError"], match="not a regular file"):
        APP["plan_output_paths"]([source], None, overwrite=True)
    with pytest.raises(APP["UserError"], match="not a regular file"):
        APP["commit_output_transaction"]([(target, b"new qif")], overwrite=True)

    assert target.exists()
    if target_kind == "directory":
        assert stat.S_ISDIR(target.lstat().st_mode)
    else:
        assert stat.S_ISFIFO(target.lstat().st_mode)
    assert_no_transaction_temps(tmp_path)


def test_paired_output_staging_failure_leaves_no_final_or_temporary_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cooked = tmp_path / "synthetic.cooked.csv"
    qif = tmp_path / "synthetic.qif"
    original_stage = APP["stage_artifact"]
    calls = 0

    def fail_second(target: Path, content: bytes) -> Path:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic paired staging failure")
        return original_stage(target, content)

    monkeypatch.setitem(
        APP["commit_output_transaction"].__globals__, "stage_artifact", fail_second
    )

    with pytest.raises(OSError, match="synthetic paired staging failure"):
        APP["commit_output_transaction"](
            [(cooked, b"cooked"), (qif, b"qif")], overwrite=False
        )

    assert not cooked.exists()
    assert not qif.exists()
    assert_no_transaction_temps(tmp_path)


def test_later_file_staging_failure_rolls_back_entire_multifile_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    targets = [
        tmp_path / "synthetic-1.cooked.csv",
        tmp_path / "synthetic-1.qif",
        tmp_path / "synthetic-2.cooked.csv",
        tmp_path / "synthetic-2.qif",
    ]
    original_stage = APP["stage_artifact"]
    calls = 0

    def fail_later(target: Path, content: bytes) -> Path:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("synthetic later-file staging failure")
        return original_stage(target, content)

    monkeypatch.setitem(
        APP["commit_output_transaction"].__globals__, "stage_artifact", fail_later
    )

    with pytest.raises(OSError, match="synthetic later-file staging failure"):
        APP["commit_output_transaction"](
            [(target, f"artifact-{index}".encode()) for index, target in enumerate(targets)],
            overwrite=False,
        )

    assert not any(target.exists() for target in targets)
    assert_no_transaction_temps(tmp_path)


def test_commit_failure_restores_overwritten_outputs_and_removes_new_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cooked = tmp_path / "synthetic.cooked.csv"
    qif = tmp_path / "synthetic.qif"
    later = tmp_path / "synthetic-later.cooked.csv"
    cooked.write_bytes(b"original cooked")
    qif.write_bytes(b"original qif")
    original_link = APP["transaction_link_no_replace"]
    failed = False

    def fail_qif_install(source: Path, target: Path) -> None:
        nonlocal failed
        if not failed and "div-conv-stage" in source.name and target == qif:
            failed = True
            raise OSError("synthetic commit failure")
        original_link(source, target)

    monkeypatch.setitem(
        APP["commit_output_transaction"].__globals__,
        "transaction_link_no_replace",
        fail_qif_install,
    )

    with pytest.raises(OSError, match="synthetic commit failure"):
        APP["commit_output_transaction"](
            [(cooked, b"new cooked"), (qif, b"new qif"), (later, b"new later")],
            overwrite=True,
        )

    assert cooked.read_bytes() == b"original cooked"
    assert qif.read_bytes() == b"original qif"
    assert not later.exists()
    assert_no_transaction_temps(tmp_path)


def test_restore_failure_preserves_backup_and_reports_manual_recovery_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cooked = tmp_path / "synthetic.cooked.csv"
    qif = tmp_path / "synthetic.qif"
    newly_installed = tmp_path / "synthetic-later.cooked.csv"
    commit_failure_target = tmp_path / "synthetic-later.qif"
    cooked.write_bytes(b"original cooked")
    qif.write_bytes(b"original qif")
    original_link = APP["transaction_link_no_replace"]
    commit_failed = False
    restore_failed = False

    def fail_commit_and_one_restore(source: Path, target: Path) -> None:
        nonlocal commit_failed, restore_failed
        if (
            not commit_failed
            and "div-conv-stage" in source.name
            and target == commit_failure_target
        ):
            commit_failed = True
            raise OSError("synthetic commit failure")
        if (
            not restore_failed
            and "div-conv-backup" in source.name
            and target == qif
        ):
            restore_failed = True
            raise OSError("synthetic restore failure")
        original_link(source, target)

    monkeypatch.setitem(
        APP["commit_output_transaction"].__globals__,
        "transaction_link_no_replace",
        fail_commit_and_one_restore,
    )

    with pytest.raises(OSError) as captured:
        APP["commit_output_transaction"](
            [
                (cooked, b"new cooked"),
                (qif, b"new qif"),
                (newly_installed, b"new later cooked"),
                (commit_failure_target, b"new later qif"),
            ],
            overwrite=True,
        )

    backups = list(tmp_path.glob(".synthetic.qif.div-conv-backup-*.tmp"))
    assert len(backups) == 1
    preserved_backup = backups[0]
    assert preserved_backup.read_bytes() == b"original qif"
    error = str(captured.value)
    assert str(preserved_backup) in error
    assert str(qif) in error
    assert "synthetic restore failure" in error
    assert cooked.read_bytes() == b"original cooked"
    assert not qif.exists()
    assert not newly_installed.exists()
    assert not commit_failure_target.exists()
    assert not list(tmp_path.glob(".*.div-conv-stage-*.tmp"))


def test_staging_cleanup_error_does_not_mask_original_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cooked = tmp_path / "synthetic.cooked.csv"
    qif = tmp_path / "synthetic.qif"
    original_stage = APP["stage_artifact"]
    original_remove = APP["remove_if_present"]
    staged_path: Path | None = None

    def fail_second_stage(target: Path, content: bytes) -> Path:
        nonlocal staged_path
        if staged_path is None:
            staged_path = original_stage(target, content)
            return staged_path
        raise OSError("synthetic original staging failure")

    def fail_staged_cleanup(path: Path) -> None:
        if path == staged_path:
            raise OSError("synthetic cleanup failure")
        original_remove(path)

    monkeypatch.setitem(
        APP["commit_output_transaction"].__globals__, "stage_artifact", fail_second_stage
    )
    monkeypatch.setitem(
        APP["commit_output_transaction"].__globals__, "remove_if_present", fail_staged_cleanup
    )

    with pytest.raises(OSError, match="synthetic original staging failure") as captured:
        APP["commit_output_transaction"](
            [(cooked, b"cooked"), (qif, b"qif")], overwrite=False
        )

    assert "synthetic cleanup failure" in " ".join(getattr(captured.value, "__notes__", ()))
    assert not cooked.exists()
    assert not qif.exists()
    assert staged_path is not None
    staged_path.unlink()


def test_successful_commit_is_not_reported_failed_when_backup_cleanup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "synthetic.qif"
    target.write_bytes(b"original qif")
    original_remove = APP["remove_if_present"]

    def fail_backup_cleanup(path: Path) -> None:
        if "div-conv-backup" in path.name:
            raise OSError("synthetic backup cleanup failure")
        original_remove(path)

    monkeypatch.setitem(
        APP["commit_output_transaction"].__globals__, "remove_if_present", fail_backup_cleanup
    )

    APP["commit_output_transaction"]([(target, b"new qif")], overwrite=True)

    assert target.read_bytes() == b"new qif"
    backups = list(tmp_path.glob(".synthetic.qif.div-conv-backup-*.tmp"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"original qif"
    backups[0].unlink()
