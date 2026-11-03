from __future__ import annotations

import ast
import csv
import importlib.util
from datetime import date
from importlib.machinery import SourceFileLoader
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yfinance


PROJECT_DIR = Path(__file__).resolve().parents[1]
LAUNCHER = PROJECT_DIR / "etf_montecarlo"
SYNTHETIC_SHARES = 2.0
PAYMENT_SENTINELS = (1.0, 1.5, 2.0)
SYNTHETIC_TRIALS = 16
SYNTHETIC_YEARS = 4
SYNTHETIC_SEED = 1234
AS_OF = date(2030, 12, 31)


def load_module():
    loader = SourceFileLoader("etf_montecarlo", str(LAUNCHER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def synthetic_config(*, output: str = "", placeholders: bool = False) -> dict[str, object]:
    symbols = ("SYNTH1", "SYNTH2") if placeholders else ("TEST0000", "TEST0001")
    return {
        "schema_version": 1,
        "holdings": [
            {"symbol": symbol, "shares": SYNTHETIC_SHARES}
            for symbol in symbols
        ],
        "history": {"years": SYNTHETIC_YEARS},
        "simulation": {"trials": SYNTHETIC_TRIALS, "seed": SYNTHETIC_SEED},
        "output": {"results_csv": output},
    }


def write_config(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["ETF_MONTECARLO_HOME"] = str(tmp_path / "runtime")
    return subprocess.run(
        [sys.executable, str(LAUNCHER), *args],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )


def test_first_run_atomically_creates_incomplete_private_skeleton(tmp_path: Path) -> None:
    result = run_cli(tmp_path)

    config_path = tmp_path / "runtime" / "config.json"
    assert result.returncode == 2
    assert "CONFIGURATION REQUIRED" in result.stderr
    assert str(config_path) in result.stderr
    assert stat.S_IMODE(config_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600
    assert not list(config_path.parent.glob("*.tmp"))
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "holdings": [],
        "history": {"years": 0},
        "simulation": {"trials": 0, "seed": None},
        "output": {"results_csv": ""},
    }


def test_help_does_not_create_runtime_state(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "--help")

    assert result.returncode == 0
    assert "--config" in result.stdout
    assert "--overwrite" in result.stdout
    assert not (tmp_path / "runtime").exists()


def test_explicit_missing_config_is_created_at_requested_path(tmp_path: Path) -> None:
    config_path = tmp_path / "private" / "scenario.json"

    result = run_cli(tmp_path, "--config", str(config_path))

    assert result.returncode == 2
    assert str(config_path) in result.stderr
    assert config_path.exists()
    assert not (tmp_path / "runtime").exists()


def test_adjacent_or_legacy_config_is_never_migrated(tmp_path: Path) -> None:
    write_config(tmp_path / "config.json", synthetic_config())
    write_config(tmp_path / ".legacy_etf" / "config.json", synthetic_config())

    result = run_cli(tmp_path)

    runtime_config = tmp_path / "runtime" / "config.json"
    assert result.returncode == 2
    assert json.loads(runtime_config.read_text(encoding="utf-8"))["holdings"] == []


def test_tracked_example_has_only_zero_share_placeholders() -> None:
    payload = json.loads((PROJECT_DIR / "config.example.json").read_text(encoding="utf-8"))

    assert [row["symbol"] for row in payload["holdings"]] == ["SYNTH1", "SYNTH2"]
    assert all(row["shares"] == 0 for row in payload["holdings"])
    assert payload["history"] == {"years": 0}
    assert payload["simulation"] == {"trials": 0, "seed": None}
    assert payload["output"] == {"results_csv": ""}


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update({"schema_version": 2}), "schema_version"),
        (lambda value: value.update({"schema_version": True}), "schema_version"),
        (lambda value: value.update({"holdings": []}), "holdings"),
        (lambda value: value["holdings"][0].update({"shares": 0}), "shares must be greater"),
        (lambda value: value["holdings"][1].update({"symbol": "TEST0000"}), "duplicate"),
        (
            lambda value: value["holdings"][0].update(
                {"symbol": "".join(("TEST", "\n", "0000"))}
            ),
            "unsupported characters",
        ),
        (lambda value: value["history"].update({"years": 0}), "history.years"),
        (lambda value: value["simulation"].update({"trials": 0}), "simulation.trials"),
        (lambda value: value["simulation"].update({"seed": -1}), "simulation.seed"),
        (lambda value: value["simulation"].update({"seed": 1 << 32}), "simulation.seed"),
    ],
)
def test_invalid_config_fails_before_finance_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutate, message: str
) -> None:
    module = load_module()
    config_path = tmp_path / "config.json"
    payload = synthetic_config()
    mutate(payload)
    write_config(config_path, payload)
    monkeypatch.setattr(
        module,
        "fetch_dividend_history",
        lambda *_args, **_kwargs: pytest.fail("finance access should be blocked"),
    )

    assert module.main(["--config", str(config_path)]) == 2
    assert message in module.LAST_ERROR_FOR_TESTS


def test_placeholder_symbols_are_rejected_before_finance_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    config_path = tmp_path / "config.json"
    write_config(config_path, synthetic_config(placeholders=True))
    monkeypatch.setattr(
        module,
        "fetch_dividend_history",
        lambda *_args, **_kwargs: pytest.fail("finance access should be blocked"),
    )

    assert module.main(["--config", str(config_path)]) == 2
    assert "replace placeholder symbol SYNTH1" in module.LAST_ERROR_FOR_TESTS


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@"])
def test_formula_leading_symbols_are_rejected_before_finance_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    module = load_module()
    config_path = tmp_path / "config.json"
    payload = synthetic_config()
    payload["holdings"][0]["symbol"] = "".join((prefix, "TEST0000"))
    write_config(config_path, payload)
    monkeypatch.setattr(
        module,
        "fetch_dividend_history",
        lambda *_args, **_kwargs: pytest.fail("finance access should be blocked"),
    )

    assert module.main(["--config", str(config_path)]) == 2
    assert "spreadsheet formula" in module.LAST_ERROR_FOR_TESTS


@pytest.mark.parametrize("control", ["\x00", "\n", "\t", "\x7f"])
def test_control_characters_in_output_path_raise_configuration_error(
    tmp_path: Path, control: str
) -> None:
    module = load_module()
    config_path = tmp_path / "config.json"
    payload = synthetic_config(output="".join(("results", control, ".csv")))

    with pytest.raises(module.ConfigurationError, match="control characters"):
        module.validate_config(payload, config_path)


def test_huge_integer_share_fails_cleanly_before_finance_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    config_path = tmp_path / "config.json"
    payload = synthetic_config()
    payload["holdings"] = [{"symbol": "TEST0000", "shares": 1 << 4096}]
    write_config(config_path, payload)
    monkeypatch.setattr(
        module,
        "fetch_dividend_history",
        lambda *_args, **_kwargs: pytest.fail("finance access should be blocked"),
    )

    assert module.main(["--config", str(config_path)]) == 2
    assert "finite number" in module.LAST_ERROR_FOR_TESTS


def test_existing_runtime_and_config_permissions_are_hardened(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o755)
    config_path = runtime / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    config_path.chmod(0o644)

    result = run_cli(tmp_path)

    assert result.returncode == 2
    assert stat.S_IMODE(runtime.stat().st_mode) == 0o700
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


def test_config_symlink_is_rejected_without_following_target(tmp_path: Path) -> None:
    module = load_module()
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o644)
    config_link = tmp_path / "config.json"
    config_link.symlink_to(target)

    assert module.main(["--config", str(config_link)]) == 1
    assert "symbolic link" in module.LAST_ERROR_FOR_TESTS
    assert target.read_text(encoding="utf-8") == "{}"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_default_runtime_home_symlink_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    target = tmp_path / "target-runtime"
    target.mkdir(mode=0o755)
    target.chmod(0o755)
    assert stat.S_IMODE(target.stat().st_mode) == 0o755
    runtime_link = tmp_path / "runtime-link"
    runtime_link.symlink_to(target, target_is_directory=True)
    monkeypatch.setenv("ETF_MONTECARLO_HOME", str(runtime_link))

    assert module.main([]) == 1
    assert "symbolic link" in module.LAST_ERROR_FOR_TESTS
    assert stat.S_IMODE(target.stat().st_mode) == 0o755
    assert not (target / "config.json").exists()


def test_explicitly_trusted_system_path_alias_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    target = tmp_path / "canonical-root"
    target.mkdir(mode=0o755)
    runtime_link = tmp_path / "system-alias"
    runtime_link.symlink_to(target, target_is_directory=True)
    monkeypatch.setitem(module.TRUSTED_SYSTEM_PATH_ALIASES, runtime_link, target)
    monkeypatch.setenv("ETF_MONTECARLO_HOME", str(runtime_link / "runtime"))

    assert module.main([]) == 2
    assert "CONFIGURATION REQUIRED" in module.LAST_ERROR_FOR_TESTS
    assert stat.S_IMODE((target / "runtime").stat().st_mode) == 0o700
    assert stat.S_IMODE((target / "runtime" / "config.json").stat().st_mode) == 0o600


@pytest.mark.parametrize("role", ["config", "output"])
def test_symlinked_ancestor_is_rejected_without_touching_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    module = load_module()
    target_root = tmp_path / "target-root"
    target_parent = target_root / "private"
    target_parent.mkdir(parents=True, mode=0o755)
    target_parent.chmod(0o755)
    assert stat.S_IMODE(target_parent.stat().st_mode) == 0o755
    ancestor_link = tmp_path / "ancestor-link"
    ancestor_link.symlink_to(target_root, target_is_directory=True)
    target_name = "config.json" if role == "config" else "results.csv"
    linked_path = ancestor_link / "private" / target_name
    config_path = linked_path if role == "config" else tmp_path / "config.json"
    if role == "output":
        write_config(config_path, synthetic_config(output=str(linked_path)))
        monkeypatch.setattr(
            module,
            "fetch_dividend_history",
            lambda *_args, **_kwargs: pytest.fail("finance access should be blocked"),
        )

    assert module.main(["--config", str(config_path)]) == 1
    assert "symbolic link" in module.LAST_ERROR_FOR_TESTS
    assert stat.S_IMODE(target_parent.stat().st_mode) == 0o755
    assert not (target_parent / target_name).exists()


def test_private_config_and_output_canonical_alias_are_rejected(tmp_path: Path) -> None:
    module = load_module()
    source_dir = tmp_path / "public-source"
    module.SOURCE_DIR = source_dir
    source_config = source_dir / "config.json"
    assert module.main(["--config", str(source_config)]) == 2
    assert "must live outside the public source directory" in module.LAST_ERROR_FOR_TESTS

    config_path = tmp_path / "private" / "config.json"
    payload = synthetic_config(output="staging/../config.json")
    with pytest.raises(module.ConfigurationError, match="must not overwrite"):
        module.validate_config(payload, config_path)


def test_casefold_and_inode_aliases_cannot_bypass_private_path_boundaries(
    tmp_path: Path
) -> None:
    module = load_module()
    source_dir = tmp_path / "Public-Source"
    source_dir.mkdir()
    source_file = source_dir / "tracked-source.txt"
    source_file.write_text("SYNTHETIC SOURCE\n", encoding="utf-8")
    module.SOURCE_DIR = source_dir

    case_variant_config = tmp_path / "public-source" / "CONFIG.JSON"
    assert module.main(["--config", str(case_variant_config)]) == 2
    assert "outside the public source directory" in module.LAST_ERROR_FOR_TESTS
    assert not case_variant_config.exists()

    private_dir = tmp_path / "Private"
    private_dir.mkdir()
    source_alias_config = private_dir / "source-alias.json"
    os.link(source_file, source_alias_config)
    assert module.main(["--config", str(source_alias_config)]) == 2
    assert "outside the public source directory" in module.LAST_ERROR_FOR_TESTS
    assert source_file.read_text(encoding="utf-8") == "SYNTHETIC SOURCE\n"

    config_path = private_dir / "Config.json"
    output_alias = private_dir / "results.csv"
    payload = synthetic_config(output=str(output_alias))
    write_config(config_path, payload)
    os.link(config_path, output_alias)
    with pytest.raises(module.ConfigurationError, match="must not overwrite"):
        module.validate_config(payload, config_path)

    case_variant_payload = synthetic_config(output=str(tmp_path / "private" / "CONFIG.JSON"))
    with pytest.raises(module.ConfigurationError, match="must not overwrite"):
        module.validate_config(case_variant_payload, config_path)

    source_output_alias = private_dir / "source-output.csv"
    os.link(source_file, source_output_alias)
    source_alias_payload = synthetic_config(output=str(source_output_alias))
    with pytest.raises(module.ConfigurationError, match="outside the public source"):
        module.validate_config(source_alias_payload, config_path)


def test_existing_output_requires_overwrite_before_finance_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    config_path = tmp_path / "config.json"
    output_path = tmp_path / "results.csv"
    output_path.write_text("SYNTHETIC EXISTING OUTPUT\n", encoding="utf-8")
    write_config(config_path, synthetic_config(output=str(output_path)))
    monkeypatch.setattr(
        module,
        "fetch_dividend_history",
        lambda *_args, **_kwargs: pytest.fail("finance access should be blocked"),
    )

    assert module.main(["--config", str(config_path)]) == 1
    assert "already exists" in module.LAST_ERROR_FOR_TESTS
    assert "--overwrite" in module.LAST_ERROR_FOR_TESTS
    assert output_path.read_text(encoding="utf-8") == "SYNTHETIC EXISTING OUTPUT\n"


def test_output_symlink_is_rejected_even_with_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    config_path = tmp_path / "config.json"
    target = tmp_path / "target.csv"
    target.write_text("SYNTHETIC TARGET\n", encoding="utf-8")
    output_link = tmp_path / "results.csv"
    output_link.symlink_to(target)
    write_config(config_path, synthetic_config(output=str(output_link)))
    monkeypatch.setattr(
        module,
        "fetch_dividend_history",
        lambda *_args, **_kwargs: pytest.fail("finance access should be blocked"),
    )

    assert module.main(["--config", str(config_path), "--overwrite"]) == 1
    assert "symbolic link" in module.LAST_ERROR_FOR_TESTS
    assert target.read_text(encoding="utf-8") == "SYNTHETIC TARGET\n"


def test_finance_boundary_uses_yfinance_dividend_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    calls: list[str] = []
    index = pd.to_datetime(["2029-01-02", "2030-02-03"]).tz_localize("America/New_York")
    series = pd.Series(PAYMENT_SENTINELS[:2], index=index)

    class FakeTicker:
        def __init__(self, symbol: str):
            calls.append(symbol)
            self.dividends = series

    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)

    history = module.fetch_dividend_history("TEST0000")

    assert calls == ["TEST0000"]
    assert history.symbol == "TEST0000"
    assert history.payments == (
        module.DividendPayment(date(2029, 1, 2), PAYMENT_SENTINELS[0]),
        module.DividendPayment(date(2030, 2, 3), PAYMENT_SENTINELS[1]),
    )


def test_trailing_year_filter_uses_configured_calendar_window() -> None:
    module = load_module()
    payments = (
        module.DividendPayment(date(2027, 12, 30), PAYMENT_SENTINELS[0]),
        module.DividendPayment(date(2027, 12, 31), PAYMENT_SENTINELS[1]),
        module.DividendPayment(date(2030, 1, 2), PAYMENT_SENTINELS[2]),
        module.DividendPayment(date(2031, 1, 2), PAYMENT_SENTINELS[0]),
    )

    filtered = module.trailing_payments(payments, years=3, as_of=AS_OF)

    assert [payment.payment_date for payment in filtered] == [
        date(2027, 12, 31),
        date(2030, 1, 2),
    ]


def test_typical_payments_per_year_uses_median_annual_count() -> None:
    module = load_module()
    payments = tuple(
        module.DividendPayment(date(year, month, 1), PAYMENT_SENTINELS[month % 3])
        for year, count in ((2028, 2), (2029, 4), (2030, 6))
        for month in range(1, count + 1)
    )

    assert module.typical_payments_per_year(payments) == 4


def test_partial_calendar_years_infer_quarterly_frequency() -> None:
    module = load_module()
    payments = tuple(module.DividendPayment(date(2030, month, 1), 1.0) for month in (4, 7, 10)) + (
        module.DividendPayment(date(2031, 1, 1), 1.0),
    )
    assert module.typical_payments_per_year(
        payments, window_start=date(2030, 2, 1), window_end=date(2031, 2, 1)
    ) == 4


def test_complete_year_excludes_partial_year_counts() -> None:
    module = load_module()
    payments = tuple(
        module.DividendPayment(date(year, month, 1), 1.0)
        for year, months in ((2030, (10,)), (2031, (1, 4, 7, 10)), (2032, (1,)))
        for month in months
    )
    assert module.typical_payments_per_year(
        payments, window_start=date(2030, 9, 1), window_end=date(2032, 2, 1)
    ) == 4


def test_simulation_uses_window_aware_frequency(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module()
    payments = tuple(module.DividendPayment(date(2030, month, 1), 1.0) for month in (4, 7, 10)) + (
        module.DividendPayment(date(2031, 1, 1), 1.0),
    )
    monkeypatch.setattr(module, "fetch_dividend_history", lambda symbol: module.DividendHistory(symbol, payments))
    settings = module.Settings((module.Holding("TEST0000", 1),), 1, 5, 0, None)
    simulations, _ = module.simulate(settings, as_of=date(2031, 2, 1))
    assert simulations[0].payments_per_year == 4
    assert (simulations[0].per_share_samples == 4.0).all()


def test_empirical_dividend_bootstrap_is_deterministic() -> None:
    module = load_module()
    amounts = np.asarray([1.0, 2.0, 3.0])

    first = module.bootstrap_annual_income(
        amounts,
        payments_per_year=4,
        trials=50,
        rng=np.random.default_rng(SYNTHETIC_SEED),
    )
    second = module.bootstrap_annual_income(
        amounts,
        payments_per_year=4,
        trials=50,
        rng=np.random.default_rng(SYNTHETIC_SEED),
    )

    assert np.array_equal(first, second)
    assert first.shape == (50,)
    assert ((first >= 4) & (first <= 12)).all()
    assert (first == np.floor(first)).all()
    constant = module.bootstrap_annual_income(
        np.asarray([2.5]), payments_per_year=4, trials=50,
        rng=np.random.default_rng(SYNTHETIC_SEED),
    )
    assert np.array_equal(constant, np.full(50, 10.0))


def test_simulate_scales_by_shares_and_sums_portfolio(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module()
    histories = {
        "TEST0000": module.DividendHistory("TEST0000", tuple(
            module.DividendPayment(date(year, month, 1), 1.0)
            for year in (2029, 2030) for month in (3, 6, 9, 12)
        )),
        "TEST0001": module.DividendHistory("TEST0001", tuple(
            module.DividendPayment(date(year, month, 1), 0.5)
            for year in (2029, 2030) for month in (6, 12)
        )),
    }
    monkeypatch.setattr(module, "fetch_dividend_history", histories.__getitem__)
    settings = module.Settings(
        (module.Holding("TEST0000", 3.0), module.Holding("TEST0001", 2.0)),
        2, 5, 0, None,
    )

    simulations, portfolio = module.simulate(settings, as_of=date(2030, 12, 31))

    assert [simulation.payments_per_year for simulation in simulations] == [4, 2]
    assert np.array_equal(simulations[0].per_share_samples, np.full(5, 4.0))
    assert np.array_equal(simulations[1].per_share_samples, np.full(5, 1.0))
    assert np.array_equal(simulations[0].scaled_samples, np.full(5, 12.0))
    assert np.array_equal(simulations[1].scaled_samples, np.full(5, 2.0))
    assert np.array_equal(portfolio, np.full(5, 14.0))

    rows = module.build_summary_rows(simulations, portfolio)
    portfolio_rows = [row for row in rows if row.scope == "portfolio"]
    assert {row.percentile for row in portfolio_rows} == {"P5", "P25", "P50", "P75", "P95"}
    assert all(row.annual_income_scaled == 14.0 for row in portfolio_rows)
    holding_p50 = next(row for row in rows if row.symbol == "TEST0000" and row.percentile == "P50")
    assert holding_p50.annual_income_per_share == 4.0
    assert holding_p50.annual_income_scaled == 12.0


def test_percentiles_report_all_required_bands() -> None:
    module = load_module()
    samples = np.asarray([1.0, 2.0, 3.0, 4.0, 5.0])

    result = module.income_percentiles(samples)

    assert tuple(result) == ("P5", "P25", "P50", "P75", "P95")
    assert list(result.values()) == sorted(result.values())


def synthetic_history(module, symbol: str, offset: int):
    payments = tuple(
        module.DividendPayment(
            date(year, month, 1), PAYMENT_SENTINELS[(month + offset) % 3]
        )
        for year in (2028, 2029, 2030)
        for month in range(1, len("PAY") + 1)
    )
    return module.DividendHistory(symbol=symbol, payments=payments)


def test_valid_run_writes_atomic_percentile_csv_and_portfolio_distribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load_module()
    config_path = tmp_path / "config.json"
    output_path = tmp_path / "private-results" / "income.csv"
    write_config(config_path, synthetic_config(output=str(output_path)))
    output_path.parent.mkdir(parents=True)
    output_path.write_text("SYNTHETIC OLD OUTPUT\n", encoding="utf-8")
    calls: list[str] = []

    def fake_history(symbol: str):
        calls.append(symbol)
        return synthetic_history(module, symbol, len(calls))

    monkeypatch.setattr(module, "fetch_dividend_history", fake_history)
    monkeypatch.setattr(module, "current_date", lambda: AS_OF)

    assert module.main(["--config", str(config_path), "--overwrite"]) == 0
    assert calls == ["TEST0000", "TEST0001"]
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert not list(output_path.parent.glob("*.tmp"))
    with output_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 15
    assert set(row["scope"] for row in rows) == {"holding", "portfolio"}
    assert set(row["percentile"] for row in rows) == {"P5", "P25", "P50", "P75", "P95"}
    assert all(row["annual_income_scaled"] for row in rows)
    shares = {holding["symbol"]: holding["shares"] for holding in synthetic_config()["holdings"]}
    for row in rows:
        if row["scope"] == "holding":
            assert float(row["annual_income_scaled"]) == pytest.approx(
                float(row["annual_income_per_share"]) * shares[row["symbol"]], rel=1e-10, abs=0
            )
    captured = capsys.readouterr()
    assert "Annual dividend income Monte Carlo" in captured.out
    assert "TEST0000" in captured.out
    assert "Portfolio aggregate" in captured.out
    assert str(output_path) in captured.out


def test_no_overwrite_atomic_install_preserves_target_created_after_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    output_path = tmp_path / "results.csv"
    racing_content = "SYNTHETIC RACING OUTPUT\n"
    original_install = module.install_results_no_replace

    def race_before_install(source: Path, target: Path) -> None:
        target.write_text(racing_content, encoding="utf-8")
        original_install(source, target)

    monkeypatch.setattr(module, "install_results_no_replace", race_before_install)
    rows = [
        module.SummaryRow(
            scope="holding",
            symbol="TEST0000",
            payments_per_year=4,
            percentile="P50",
            annual_income_per_share=PAYMENT_SENTINELS[0],
            annual_income_scaled=PAYMENT_SENTINELS[1],
        )
    ]

    with pytest.raises(FileExistsError):
        module.write_results_csv(output_path, rows, overwrite=False)

    assert output_path.read_text(encoding="utf-8") == racing_content
    assert not list(tmp_path.glob("*.tmp"))


def test_empty_or_invalid_dividend_history_fails_without_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    config_path = tmp_path / "config.json"
    output_path = tmp_path / "results.csv"
    payload = synthetic_config(output=str(output_path))
    payload["holdings"] = [payload["holdings"][0]]
    write_config(config_path, payload)
    monkeypatch.setattr(
        module,
        "fetch_dividend_history",
        lambda symbol: module.DividendHistory(symbol=symbol, payments=()),
    )
    monkeypatch.setattr(module, "current_date", lambda: AS_OF)

    assert module.main(["--config", str(config_path)]) == 1
    assert "dividend payments" in module.LAST_ERROR_FOR_TESTS
    assert not output_path.exists()


def test_source_tree_contains_only_approved_synthetic_symbol_literals() -> None:
    allowed_symbols = {"SYNTH1", "SYNTH2", "TEST0000", "TEST0001"}
    for path in PROJECT_DIR.rglob("*"):
        if not path.is_file() or ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for symbol in re.findall(r'["\']symbol["\']\s*:\s*["\']([^"\']+)', text):
            assert symbol in allowed_symbols


def test_source_tree_contains_no_literal_positive_share_fixtures() -> None:
    for path in (LAUNCHER, Path(__file__)):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "shares"
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, (int, float))
                ):
                    assert value.value == 0, f"literal positive share fixture at {path}:{value.lineno}"
