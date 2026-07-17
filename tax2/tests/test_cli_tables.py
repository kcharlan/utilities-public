from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cli import app


runner = CliRunner()


def test_generate_combined_multistate_outputs(monkeypatch, tmp_path):
    monkeypatch.setenv("TAX2_HOME", str(tmp_path / "runtime"))
    out_dir = tmp_path / "tables"

    result = runner.invoke(
        app,
        [
            "generate-combined",
            "--states",
            "GA,PA",
            "--year",
            "2026",
            "--out-dir",
            str(out_dir),
            "--inc-max",
            "10000",
            "--step",
            "10000",
        ],
    )

    assert result.exit_code == 0, result.output
    expected_files = {
        "federal_2026.parquet",
        "ga_2026.parquet",
        "pa_2026.parquet",
        "combined_2026_GA.csv",
        "combined_2026_PA.csv",
        "combined_2026.csv",
    }
    assert {path.name for path in out_dir.iterdir()} == expected_files

    ga_alias = (out_dir / "combined_2026.csv").read_text(encoding="utf-8")
    ga_combined = (out_dir / "combined_2026_GA.csv").read_text(encoding="utf-8")
    assert ga_alias == ga_combined

    pa = pd.read_csv(out_dir / "combined_2026_PA.csv")
    assert list(pa.columns) == ["MonthlyIncome", "FederalMonthlyTax", "StateMonthlyTax"]
    row = pa.loc[pa["MonthlyIncome"] == 10000].iloc[0]
    assert row["StateMonthlyTax"] == 307.00


def test_generate_combined_missing_state_year_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("TAX2_HOME", str(tmp_path / "runtime"))

    result = runner.invoke(
        app,
        [
            "generate-combined",
            "--states",
            "PA",
            "--year",
            "2025",
            "--out-dir",
            str(tmp_path / "tables"),
            "--inc-max",
            "0",
        ],
    )

    assert result.exit_code != 0
    assert "State PA has no rules for 2025" in result.output
