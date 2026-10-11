"""Contract tests for the annual market-data compiler."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import io
import json
import math
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import pandas as pd
import numpy as np


MODULE_PATH = Path(__file__).with_name("compile_market_data.py")
SPEC = importlib.util.spec_from_file_location("compile_market_data", MODULE_PATH)
assert SPEC and SPEC.loader
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)


def workbook_frames(last_year: int = 2017) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the smallest workbook-shaped frames accepted by the parser."""
    count = last_year - 1928 + 1
    returns = pd.DataFrame(None, index=range(20 + count), columns=range(5), dtype=object)
    returns.iloc[19, [0, 1, 3, 4]] = [
        "Year",
        "S&P 500 (includes dividends)",
        "3-month T.Bill",
        "US T. Bond (10-year)",
    ]
    inflation = pd.DataFrame(None, index=range(11 + count), columns=range(3), dtype=object)
    inflation.iloc[10, [0, 1]] = ["observation_date", "CPIAUCNS"]
    for offset, year in enumerate(range(1928, last_year + 1)):
        returns.iloc[20 + offset, [0, 1, 3, 4]] = [year, 0.1, 0.03, 0.05]
        inflation.iloc[11 + offset, [0, 2]] = [year, 0.02]
    return returns, inflation


def shiller_frame(first_year: int = 1871, last_year: int = 1960) -> pd.DataFrame:
    """Build a complete Shiller-shaped monthly frame with deterministic returns."""
    count = (last_year - first_year + 1) * 12
    frame = pd.DataFrame(None, index=range(8 + count + 1), columns=range(18), dtype=object)
    frame.iloc[5, [4, 9, 17]] = ["Price", "Total", "Total"]
    frame.iloc[6, [4, 9, 17]] = ["Index", "Return", "Bond"]
    frame.iloc[7, [0, 4, 9, 17]] = ["Date", "CPI", "Price", "Returns"]
    for offset, (year, month) in enumerate(
        (pair for year in range(first_year, last_year + 1) for pair in ((year, month) for month in range(1, 13)))
    ):
        row = 8 + offset
        frame.iloc[row, [0, 4, 9, 17]] = [
            year + month / 100,
            100.0 * (1.02 ** (year - first_year)) * (1.001 ** month),
            10.0 * (1.08 ** (year - first_year)) * (1.002 ** month),
            1.004,
        ]
    return frame


class ParseDamodaranTests(unittest.TestCase):
    def test_numpy_integer_year_is_numeric(self) -> None:
        self.assertTrue(compiler.is_number(np.int64(1928)))

    def test_rejects_any_changed_required_header(self) -> None:
        for frame_name, column in (
            ("returns", 0),
            ("returns", 1),
            ("returns", 3),
            ("returns", 4),
            ("inflation", 0),
            ("inflation", 1),
        ):
            with self.subTest(frame=frame_name, column=column):
                returns, inflation = workbook_frames()
                frame = returns if frame_name == "returns" else inflation
                row = 19 if frame_name == "returns" else 10
                frame.iloc[row, column] = "changed"
                with mock.patch.object(
                    compiler.pd,
                    "read_excel",
                    side_effect=[returns, inflation],
                ):
                    with self.assertRaisesRegex(ValueError, "layout changed"):
                        compiler.parse_damodaran(Path("unused.xls"))

    def test_rejects_a_missing_value_in_the_annual_range(self) -> None:
        returns, inflation = workbook_frames()
        returns.iloc[25, 3] = math.nan
        with mock.patch.object(
            compiler.pd, "read_excel", side_effect=[returns, inflation]
        ):
            with self.assertRaisesRegex(ValueError, "Missing Damodaran market or CPI value for 1933"):
                compiler.parse_damodaran(Path("unused.xls"))

    def test_rejects_non_finite_annual_values(self) -> None:
        for bad_value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=bad_value):
                returns, inflation = workbook_frames()
                returns.iloc[25, 1] = bad_value
                with mock.patch.object(
                    compiler.pd, "read_excel", side_effect=[returns, inflation]
                ):
                    with self.assertRaises(ValueError):
                        compiler.parse_damodaran(Path("unused.xls"))

    def test_rejects_fractional_years(self) -> None:
        returns, inflation = workbook_frames()
        returns.iloc[25, 0] = 1933.5
        with mock.patch.object(
            compiler.pd, "read_excel", side_effect=[returns, inflation]
        ):
            with self.assertRaisesRegex(ValueError, "fractional"):
                compiler.parse_damodaran(Path("unused.xls"))

    def test_rejects_duplicate_returns_and_cpi_years(self) -> None:
        for frame_name in ("returns", "inflation"):
            with self.subTest(frame=frame_name):
                returns, inflation = workbook_frames()
                frame = returns if frame_name == "returns" else inflation
                first_data_row = 20 if frame_name == "returns" else 11
                frame.iloc[first_data_row + 1, 0] = 1928
                with mock.patch.object(
                    compiler.pd, "read_excel", side_effect=[returns, inflation]
                ):
                    with self.assertRaisesRegex(ValueError, "duplicate"):
                        compiler.parse_damodaran(Path("unused.xls"))

    def test_rejects_a_stale_baseline_or_wrong_first_year(self) -> None:
        for first_year, last_year, message in (
            (1928, 2024, "end at or after 2025"),
            (1927, 2025, "start exactly at 1928"),
        ):
            with self.subTest(first_year=first_year, last_year=last_year):
                returns, inflation = workbook_frames(last_year)
                if first_year != 1928:
                    returns.iloc[20, 0] = first_year
                    inflation.iloc[11, 0] = first_year
                with mock.patch.object(
                    compiler.pd, "read_excel", side_effect=[returns, inflation]
                ):
                    with self.assertRaisesRegex(ValueError, message):
                        compiler.parse_damodaran(Path("unused.xls"))


class AnchorTests(unittest.TestCase):
    def test_advanced_dataset_uses_matching_published_geometric_range(self) -> None:
        years = {
            year: {"stock_tr": 0.1}
            for year in range(1928, 2027)
        }
        sheet = pd.DataFrame(None, index=range(4), columns=range(2), dtype=object)
        sheet.iloc[1, 0] = "Geometric Average Historical Return"
        sheet.iloc[2, 0] = "1928-2026"
        sheet.iloc[2, 1] = 0.1
        with mock.patch("sys.stdout", io.StringIO()):
            compiler.verify_damodaran_anchor(years, sheet)

    def test_rejects_a_stale_or_shifted_range_before_anchor_lookup(self) -> None:
        for first_year, last_year, message in (
            (1928, 2024, "end at or after 2025"),
            (1929, 2025, "start exactly at 1928"),
        ):
            with self.subTest(first_year=first_year, last_year=last_year):
                years = {year: {"stock_tr": 0.1} for year in range(first_year, last_year + 1)}
                with self.assertRaisesRegex(ValueError, message):
                    compiler.verify_damodaran_anchor(years, pd.DataFrame())


class ParseShillerTests(unittest.TestCase):
    def test_builds_december_ratios_and_chains_all_twelve_bond_months(self) -> None:
        frame = shiller_frame(last_year=1960)
        with mock.patch.object(compiler.pd, "read_excel", return_value=frame) as read_excel:
            years = compiler.parse_shiller(Path("unused.xls"))

        read_excel.assert_called_once_with(
            Path("unused.xls"), sheet_name="Data", header=None, engine="xlrd"
        )
        self.assertEqual((min(years), max(years), len(years)), (1872, 1960, 89))
        self.assertAlmostEqual(years[1872]["stock_tr"], 1.08 * 1.02 - 1)
        self.assertAlmostEqual(years[1872]["cpi_change"], 0.02)
        self.assertAlmostEqual(years[1872]["bond10_tr"], 1.004**12 - 1)

    def test_rejects_changed_required_headers(self) -> None:
        for row, column in ((5, 4), (5, 9), (5, 17), (6, 4), (6, 9), (6, 17),
                            (7, 0), (7, 4), (7, 9), (7, 17)):
            with self.subTest(row=row, column=column):
                frame = shiller_frame()
                frame.iloc[row, column] = "changed"
                with mock.patch.object(compiler.pd, "read_excel", return_value=frame):
                    with self.assertRaisesRegex(ValueError, "Shiller layout changed"):
                        compiler.parse_shiller(Path("unused.xls"))

    def test_rejects_invalid_or_duplicate_month_keys(self) -> None:
        for bad_date, message in ((1871.13, "invalid month"), (1871.01, "duplicate month")):
            with self.subTest(date=bad_date):
                frame = shiller_frame()
                frame.iloc[9, 0] = bad_date
                with mock.patch.object(compiler.pd, "read_excel", return_value=frame):
                    with self.assertRaisesRegex(ValueError, message):
                        compiler.parse_shiller(Path("unused.xls"))

    def test_rejects_a_non_finite_numeric_date_instead_of_treating_it_as_a_terminator(self) -> None:
        frame = shiller_frame()
        frame.iloc[20, 0] = math.inf
        with mock.patch.object(compiler.pd, "read_excel", return_value=frame):
            with self.assertRaisesRegex(ValueError, "non-finite date"):
                compiler.parse_shiller(Path("unused.xls"))

    def test_date_grid_tolerance_accepts_float_noise_but_rejects_off_grid_values(self) -> None:
        for date_value, accepted in (
            (1871.010000001, True),
            (1871.10, True),
            (1871.016, False),
        ):
            with self.subTest(date=date_value):
                frame = shiller_frame()
                if date_value == 1871.10:
                    frame.iloc[8, 0], frame.iloc[17, 0] = frame.iloc[17, 0], frame.iloc[8, 0]
                else:
                    frame.iloc[8, 0] = date_value
                with mock.patch.object(compiler.pd, "read_excel", return_value=frame):
                    if accepted:
                        compiler.parse_shiller(Path("unused.xls"))
                    else:
                        with self.assertRaisesRegex(ValueError, "off the YYYY.MM month grid"):
                            compiler.parse_shiller(Path("unused.xls"))

    def test_rejects_non_positive_monthly_inputs(self) -> None:
        for column, label in ((4, "CPI"), (9, "real stock"), (17, "bond")):
            for bad_value in (0.0, -0.01):
                with self.subTest(column=column, value=bad_value):
                    frame = shiller_frame()
                    frame.iloc[20, column] = bad_value
                    with mock.patch.object(compiler.pd, "read_excel", return_value=frame):
                        with self.assertRaisesRegex(ValueError, f"positive {label}"):
                            compiler.parse_shiller(Path("unused.xls"))

    def test_rejects_non_finite_derived_annual_return(self) -> None:
        frame = shiller_frame()
        frame.iloc[20:32, 17] = 1e100
        with mock.patch.object(compiler.pd, "read_excel", return_value=frame):
            with self.assertRaisesRegex(ValueError, "annual returns"):
                compiler.parse_shiller(Path("unused.xls"))

    def test_rejects_an_interior_missing_month(self) -> None:
        frame = shiller_frame().drop(index=20).reset_index(drop=True)
        with mock.patch.object(compiler.pd, "read_excel", return_value=frame):
            with self.assertRaisesRegex(ValueError, "missing months"):
                compiler.parse_shiller(Path("unused.xls"))

    def test_ignores_a_partial_final_calendar_year(self) -> None:
        frame = shiller_frame(last_year=1960).iloc[:-4].copy()
        with mock.patch.object(compiler.pd, "read_excel", return_value=frame):
            years = compiler.parse_shiller(Path("unused.xls"))
        self.assertEqual(max(years), 1959)

    def test_rejects_missing_month_or_non_finite_required_value(self) -> None:
        for column, message in ((0, "missing months"), (4, "non-finite"), (9, "non-finite"),
                                (17, "non-finite")):
            with self.subTest(column=column):
                frame = shiller_frame()
                if column == 0:
                    frame.iloc[20, 0] = None
                else:
                    frame.iloc[20, column] = math.inf
                with mock.patch.object(compiler.pd, "read_excel", return_value=frame):
                    with self.assertRaisesRegex(ValueError, message):
                        compiler.parse_shiller(Path("unused.xls"))


class ReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.shiller = {
            year: {"stock_tr": 0.10 + ((year % 3) - 1) * 0.02,
                   "bond10_tr": 0.05 + ((year % 4) - 1.5) * 0.01}
            for year in range(1928, 2023)
        }
        self.damodaran = {year: values.copy() for year, values in self.shiller.items()}

    def test_reports_all_distributional_statistics_for_exact_overlap(self) -> None:
        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            metrics = compiler.reconcile(self.shiller, self.damodaran)
        self.assertEqual(set(metrics), {"stock_tr", "bond10_tr"})
        self.assertEqual(metrics["stock_tr"]["mae"], 0.0)
        self.assertEqual(metrics["bond10_tr"]["bias"], 0.0)
        self.assertIn("1928-2022", output.getvalue())
        for label in ("MAE", "bias", "stdev ratio", "geometric mean difference"):
            self.assertIn(label, output.getvalue())

    def test_fails_when_any_distributional_threshold_drifts(self) -> None:
        cases = (
            ("stock_tr", lambda year, value: value + (0.031 if year % 2 else -0.031), "MAE"),
            ("stock_tr", lambda _year, value: value + 0.007, "bias"),
            ("stock_tr", lambda _year, value: 0.10 + (value - 0.10) * 1.2, "stdev ratio"),
            ("stock_tr", lambda _year, value: value + 0.006, "geometric mean"),
            ("bond10_tr", lambda year, value: value + (0.031 if year % 2 else -0.031), "MAE"),
            ("bond10_tr", lambda _year, value: value + 0.007, "bias"),
            ("bond10_tr", lambda _year, value: 0.05 + (value - 0.05) * 1.2, "stdev ratio"),
            ("bond10_tr", lambda _year, value: value + 0.006, "geometric mean"),
        )
        for series, transform, message in cases:
            with self.subTest(series=series, metric=message):
                changed = {year: values.copy() for year, values in self.shiller.items()}
                for year in changed:
                    changed[year][series] = transform(year, changed[year][series])
                with (
                    mock.patch("sys.stdout", io.StringIO()),
                    self.assertRaisesRegex(ValueError, message),
                ):
                    compiler.reconcile(changed, self.damodaran)

    def test_requires_the_exact_reconciliation_overlap(self) -> None:
        del self.shiller[2022]
        with self.assertRaisesRegex(ValueError, "1928-2022"):
            compiler.reconcile(self.shiller, self.damodaran)

    def test_threshold_boundaries_are_inclusive(self) -> None:
        exact_limits = {
            series: {
                "mae": 0.0,
                "abs_bias": 0.0,
                "stdev_ratio": (1.0, 1.0),
                "abs_geometric_mean_difference": 0.0,
            }
            for series in ("stock_tr", "bond10_tr")
        }
        with (
            mock.patch.object(compiler, "RECONCILIATION_THRESHOLDS", exact_limits),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            compiler.reconcile(self.shiller, self.damodaran)


class SpliceTests(unittest.TestCase):
    def test_shiller_precedes_1928_and_damodaran_wins_overlap(self) -> None:
        shiller = {
            year: {"stock_tr": 0.01, "bond10_tr": 0.02, "cpi_change": 0.03}
            for year in range(1872, 2023)
        }
        damodaran = {
            year: {"stock_tr": 0.11, "bond10_tr": 0.12, "tbill_tr": 0.13,
                   "cpi_change": 0.14}
            for year in range(1928, 2026)
        }
        rows = compiler.splice(shiller, damodaran)
        self.assertEqual((len(rows), rows[0]["year"], rows[-1]["year"]), (154, 1872, 2025))
        self.assertEqual(rows[0]["quality"], "reconstructed")
        self.assertIsNone(rows[0]["tbill_tr"])
        self.assertEqual(rows[56]["stock_tr"], 0.11)
        self.assertEqual(rows[56]["quality"], "ok")


def invented_fred(first=1954, last=2025):
    """Algorithmic daily CSV, including empty observations; never source data."""
    records = [','.join(('observation_date', 'DTB3'))]
    for year in range(first, last + 1):
        day = date(year, 1, 1)
        while day.year == year:
            records.append(f"{day.isoformat()},{'3' if day.weekday() < 5 else ''}")
            day += timedelta(days=1)
    return '\n'.join(records) + '\n'


class FredTests(unittest.TestCase):
    def parse(self, text, end=2025):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'invented.csv'
            path.write_text(text, encoding='utf-8')
            return compiler.parse_fred(path, end)

    def test_daily_mean_skips_empty_and_accepts_negative_signed_decimals(self):
        text = invented_fred().replace('1954-01-01,3', '1954-01-01,-0.05')
        means = self.parse(text)
        count = sum(date(1954, 1, 1).__add__(timedelta(days=i)).weekday() < 5 for i in range(365))
        self.assertEqual(means[1954], round((3 * (count - 1) - .05) / count / 100, 8))
        self.assertEqual(means[2025], .03)
        self.assertEqual(self.parse(invented_fred().replace('1954-01-01,3', '"1954-01-01","+3"'))[1954], .03)

    def test_partial_future_year_is_ignored_but_last_year_must_be_complete(self):
        text = invented_fred()
        self.assertEqual(self.parse(text + '2026-01-01,3\n')[2025], .03)
        with self.assertRaisesRegex(ValueError, '2025'):
            self.parse(invented_fred(last=2024) + '2025-01-01,3\n')

    def test_every_selected_year_requires_count_january_and_december(self):
        text = invented_fred()
        for year, month in [(1954, 1), (1982, 12)]:
            changed = '\n'.join(line for line in text.splitlines() if not line.startswith(f'{year}-{month:02d}-')) + '\n'
            with self.subTest(year=year), self.assertRaisesRegex(ValueError, str(year)):
                self.parse(changed)
        changed = '\n'.join(line for line in text.splitlines() if not line.startswith('2000-')) + '\n'
        with self.assertRaisesRegex(ValueError, '2000'):
            self.parse(changed)
        changed = '\n'.join(line for line in text.splitlines() if not line.startswith(('1990-06-', '1990-07-'))) + '\n'
        with self.assertRaisesRegex(ValueError, '1990'):
            self.parse(changed)

    def test_strict_csv_shape_utf8_size_dates_and_values(self):
        header = ','.join(('observation_date', 'DTB3')) + '\n'
        for text in ['DATE,DTB3\n', '\uFEFF' + header, header, header + '1954-02-30,3\n', header + '1954-1-01,3\n',
                     header + '1954-01-01,3\n1954-01-01,3\n',
                     header + '1954-01-02,3\n1954-01-01,3\n',
                     header + '1954-01-01,NaN\n', header + '1954-01-01,Infinity\n',
                     header + '1954-01-01,3,4\n', header + '1954-01-01, 3\n',
                     header + '1954-01-01,1e3\n', header + '1954-01-01,.\n',
                     header + '1954-01-01,' + '9' * 400 + '\n']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.parse(text)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'invented.csv'
            path.write_bytes(b'\xff')
            with self.assertRaises(ValueError): compiler.validate_source('FRED', path)
            path.write_text(invented_fred())
            with mock.patch.object(compiler, 'MAX_DOWNLOAD_BYTES', 10):
                with self.assertRaisesRegex(ValueError, 'maximum'): compiler.validate_source('FRED', path)

    def test_splice_and_reconciliation_pass_and_fail(self):
        rows = [{'year': year, 'tbill_tr': None if year < 1928 else .03} for year in range(1872, 2026)]
        means = self.parse(invented_fred())
        merged = compiler.merge_fred(rows, means)
        self.assertIsNone(merged[0]['tbill_dtb3_tr'])
        self.assertEqual(merged[56]['tbill_dtb3_tr'], rows[56]['tbill_tr'])
        self.assertEqual(merged[81]['tbill_dtb3_tr'], rows[81]['tbill_tr'])
        self.assertEqual(merged[82]['tbill_dtb3_tr'], .03)
        means[1954] += .0000005
        compiler.merge_fred(rows, means)
        means[1954] += .000001
        with self.assertRaisesRegex(ValueError, '1954'): compiler.merge_fred(rows, means)

    def test_manual_cache_and_failed_acquisition_use_csv_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / 'invented-fred.csv'
            source.write_text(invented_fred())
            original = source.read_bytes()
            self.assertEqual(compiler.acquire_source('FRED', compiler.FRED_URL, str(source), False), source)
            self.assertEqual(source.read_bytes(), original)
            cached = root / 'DTB3.csv'
            cached.write_bytes(original)
            with mock.patch.object(compiler, 'CACHE', root), mock.patch.object(compiler, 'open_source') as opener:
                self.assertEqual(compiler.acquire_source('FRED', compiler.FRED_URL, None, False), cached)
                opener.assert_not_called()
            response = mock.MagicMock()
            response.__enter__.return_value.read.side_effect = [b'invented invalid CSV', b'']
            with mock.patch.object(compiler, 'CACHE', root), mock.patch.object(compiler, 'open_source', return_value=response):
                with self.assertRaisesRegex(RuntimeError, '--fred'):
                    compiler.acquire_source('FRED', compiler.FRED_URL, None, True)
            self.assertEqual(cached.read_bytes(), original)
            self.assertEqual({path.name for path in root.iterdir()}, {'invented-fred.csv', 'DTB3.csv'})


class EmitTests(unittest.TestCase):
    def test_csv_uses_empty_string_for_null(self) -> None:
        rows = [
            {
                "year": 1928,
                "stock_tr": 0.123456789,
                "bond10_tr": 0.05,
                "tbill_tr": None,
                "tbill_dtb3_tr": None,  # Emit always uses the current seven-field schema.
                "cpi_change": 0.02,
                "quality": "ok",
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            compiler.emit(rows, "2026-08-20", Path(temp_dir))
            csv_text = (Path(temp_dir) / "market-data.csv").read_text()
        self.assertEqual(
            csv_text,
            "year,stock_tr,bond10_tr,tbill_tr,tbill_dtb3_tr,cpi_change,quality\n"
            "1928,0.12345679,0.05,,,0.02,ok\n",
        )

    def test_rejects_non_contiguous_rows(self) -> None:
        rows = [
            {"year": year, "stock_tr": 0.1, "bond10_tr": 0.05, "tbill_tr": 0.03,
             "tbill_dtb3_tr": 0.03, "cpi_change": 0.02, "quality": "ok"}
            for year in (1928, 1930)
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "contiguous"):
                compiler.emit(rows, "2026-08-20", Path(temp_dir))

    def test_json_rejects_non_finite_values(self) -> None:
        rows = [
            {"year": 1928, "stock_tr": math.inf, "bond10_tr": 0.05, "tbill_tr": 0.03,
             "tbill_dtb3_tr": 0.03, "cpi_change": 0.02, "quality": "ok"}
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                compiler.emit(rows, "2026-08-20", Path(temp_dir))
            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_js_and_csv_have_value_parity(self) -> None:
        rows = [
            {"year": 1928, "stock_tr": 0.123456789, "bond10_tr": 0.05,
             "tbill_tr": None, "tbill_dtb3_tr": None, "cpi_change": 0.0, "quality": "ok"},
            {"year": 1929, "stock_tr": -0.1, "bond10_tr": 0.04,
             "tbill_tr": 0.03, "tbill_dtb3_tr": 0.04, "cpi_change": 0.02, "quality": "ok"},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            compiler.emit(rows, "2026-08-20", Path(temp_dir))
            js_text = (root / "market-data.js").read_text()
            payload = json.loads(js_text.removeprefix("globalThis.MARKET_DATA = ").removesuffix(";\n"))
            with (root / "market-data.csv").open(newline="") as handle:
                csv_rows = list(csv.DictReader(handle))
        for js_row, csv_row in zip(payload["rows"], csv_rows, strict=True):
            for key in ("year", "stock_tr", "bond10_tr", "tbill_tr", "tbill_dtb3_tr", "cpi_change"):
                csv_value = None if csv_row[key] == "" else float(csv_row[key])
                self.assertEqual(float(js_row[key]) if js_row[key] is not None else None, csv_value)
            self.assertEqual(js_row["quality"], csv_row["quality"])

    def test_second_replace_failure_restores_existing_pair(self) -> None:
        rows = [
            {"year": 1928, "stock_tr": 0.1, "bond10_tr": 0.05, "tbill_tr": 0.03,
             "tbill_dtb3_tr": 0.03, "cpi_change": 0.02, "quality": "ok"}
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            js_path = root / "market-data.js"
            csv_path = root / "market-data.csv"
            js_path.write_text("old-js")
            js_path.chmod(0o600)
            csv_path.write_text("old-csv")
            csv_path.chmod(0o600)
            real_replace = os.replace
            failed = False

            def fail_second_replace(source: Path, destination: Path) -> None:
                nonlocal failed
                if Path(destination) == csv_path and not failed:
                    failed = True
                    raise OSError("injected CSV replace failure")
                real_replace(source, destination)

            with (
                mock.patch.object(compiler.os, "replace", side_effect=fail_second_replace),
            ):
                with self.assertRaisesRegex(OSError, "injected CSV replace failure"):
                    compiler.emit(rows, "2026-08-20", Path(temp_dir))
            self.assertEqual(js_path.read_text(), "old-js")
            self.assertEqual(csv_path.read_text(), "old-csv")
            self.assertEqual(sorted(path.name for path in root.iterdir()), ["market-data.csv", "market-data.js"])


class AcquireSourceTests(unittest.TestCase):
    OLE_PREFIX = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

    def test_manual_missing_workbook_fails_without_network_or_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir).resolve() / "cache"
            with mock.patch.object(compiler, "CACHE", cache), mock.patch.object(compiler, "open_source") as urlopen:
                with self.assertRaisesRegex(FileNotFoundError, "source does not exist"):
                    compiler.acquire_source("Damodaran", compiler.DAMODARAN_URL, str(Path(temp_dir) / "synthetic-missing.xls"), True)
            urlopen.assert_not_called()
            self.assertFalse(cache.exists())

    def test_manual_workbook_is_validated_without_network_or_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir).resolve() / "cache"
            supplied = Path(temp_dir) / "synthetic-invalid.xls"
            supplied.write_bytes(b"synthetic non-workbook" * 40)
            with mock.patch.object(compiler, "CACHE", cache), mock.patch.object(compiler, "open_source") as urlopen:
                with self.assertRaisesRegex(ValueError, "OLE/XLS signature"):
                    compiler.acquire_source("Shiller", compiler.SHILLER_URL, str(supplied), False)
            urlopen.assert_not_called()
            self.assertFalse(cache.exists())

    def test_cache_hit_validates_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir).resolve()
            cached = cache / "histretSP.xls"
            cached.write_bytes(b"old")
            cached.chmod(0o600)
            with (
                mock.patch.object(compiler, "CACHE", cache),
                mock.patch.object(compiler, "validate_workbook") as validate,
                mock.patch.object(compiler, "open_source") as urlopen,
            ):
                result = compiler.acquire_source("Damodaran", compiler.DAMODARAN_URL, None, False)
            self.assertEqual(result, cached)
            validate.assert_called_once_with("Damodaran", cached)
            urlopen.assert_not_called()

    def test_refresh_streams_valid_download_then_promotes_it(self) -> None:
        payload = self.OLE_PREFIX + b"x" * 2048

        class RecordingResponse(io.BytesIO):
            sizes: list[int]

            def __init__(self, value: bytes) -> None:
                super().__init__(value)
                self.sizes = []

            def read(self, size: int = -1) -> bytes:
                self.sizes.append(size)
                return super().read(size)

        response = RecordingResponse(payload)
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir).resolve()
            cached = cache / "histretSP.xls"
            cached.write_bytes(b"old")
            cached.chmod(0o600)

            def validate(_name: str, path: Path) -> None:
                self.assertEqual(path.read_bytes(), payload)

            with (
                mock.patch.object(compiler, "CACHE", cache),
                mock.patch.object(compiler, "validate_workbook", side_effect=validate),
                mock.patch.object(compiler, "open_source", return_value=response),
            ):
                result = compiler.acquire_source("Damodaran", compiler.DAMODARAN_URL, None, True)
            self.assertEqual(result, cached)
            self.assertEqual(cached.read_bytes(), payload)
            self.assertTrue(response.sizes)
            self.assertTrue(all(size == compiler.DOWNLOAD_CHUNK_SIZE for size in response.sizes))
            self.assertEqual(list(cache.iterdir()), [cached])

    def test_midstream_failure_preserves_cache_and_removes_temporary_file(self) -> None:
        class FailingResponse:
            calls = 0

            def __enter__(self) -> "FailingResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self, _size: int) -> bytes:
                self.calls += 1
                if self.calls == 1:
                    return b"partial"
                raise OSError("network interrupted")

        with tempfile.TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir).resolve()
            cached = cache / "ie_data.xls"
            cached.write_bytes(b"known-good")
            cached.chmod(0o600)
            with (
                mock.patch.object(compiler, "CACHE", cache),
                mock.patch.object(compiler, "open_source", return_value=FailingResponse()),
            ):
                with self.assertRaisesRegex(RuntimeError, "--shiller"):
                    compiler.acquire_source("Shiller", compiler.SHILLER_URL, None, True)
            self.assertEqual(cached.read_bytes(), b"known-good")
            self.assertEqual(list(cache.iterdir()), [cached])

    def test_invalid_refresh_preserves_cache_and_removes_temporary_file(self) -> None:
        response = io.BytesIO(b"<html>not a workbook</html>")
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir).resolve()
            cached = cache / "histretSP.xls"
            cached.write_bytes(b"known-good")
            cached.chmod(0o600)
            with (
                mock.patch.object(compiler, "CACHE", cache),
                mock.patch.object(compiler, "open_source", return_value=response),
            ):
                with self.assertRaisesRegex(RuntimeError, "--damodaran"):
                    compiler.acquire_source("Damodaran", compiler.DAMODARAN_URL, None, True)
            self.assertEqual(cached.read_bytes(), b"known-good")
            self.assertEqual(list(cache.iterdir()), [cached])

    def test_validation_requires_ole_signature_and_source_sheets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "source.xls"
            path.write_bytes(b"not-an-ole-workbook" * 100)
            with self.assertRaisesRegex(ValueError, "OLE/XLS"):
                compiler.validate_workbook("Damodaran", path)

            path.write_bytes(self.OLE_PREFIX + b"x" * 2048)
            for source, required_sheet in (("Damodaran", "Returns by year"), ("Shiller", "Data")):
                workbook = mock.MagicMock()
                workbook.__enter__.return_value.sheet_names = []
                with (
                    self.subTest(source=source),
                    mock.patch.object(
                        compiler.pd,
                        "ExcelFile",
                        return_value=workbook,
                    ),
                ):
                    with self.assertRaisesRegex(ValueError, required_sheet):
                        compiler.validate_workbook(source, path)

    def test_oversized_refresh_preserves_cache(self) -> None:
        response = io.BytesIO(self.OLE_PREFIX + b"x" * 64)
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir).resolve()
            cached = cache / "ie_data.xls"
            cached.write_bytes(b"known-good")
            cached.chmod(0o600)
            with (
                mock.patch.object(compiler, "CACHE", cache),
                mock.patch.object(compiler, "MAX_DOWNLOAD_BYTES", 32),
                mock.patch.object(compiler, "open_source", return_value=response),
            ):
                with self.assertRaisesRegex(RuntimeError, "maximum"):
                    compiler.acquire_source("Shiller", compiler.SHILLER_URL, None, True)
            self.assertEqual(cached.read_bytes(), b"known-good")
            self.assertEqual(list(cache.iterdir()), [cached])


class CacheLocationTests(unittest.TestCase):
    def load_with_environment(self, environment: dict[str, str]) -> Path:
        spec = importlib.util.spec_from_file_location("compiler_cache_test", MODULE_PATH)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, environment, clear=True):
            spec.loader.exec_module(module)
        return module.CACHE

    def test_default_cache_is_under_user_home(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(self.load_with_environment({"HOME": home}), Path(home) / ".cache" / "market-atlas")

    def test_explicit_data_home_is_the_cache_directory(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            supplied = Path(home) / "synthetic-cache"
            self.assertEqual(self.load_with_environment({"HOME": home, "MARKET_ATLAS_DATA_HOME": str(supplied)}), supplied)

    def test_explicit_home_expands_tilde_and_empty_override_uses_default(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(self.load_with_environment({"HOME": home, "MARKET_ATLAS_DATA_HOME": "~/synthetic-cache"}), Path(home) / "synthetic-cache")
            self.assertEqual(self.load_with_environment({"HOME": home, "MARKET_ATLAS_DATA_HOME": ""}), Path(home) / ".cache" / "market-atlas")


class GeneratedDateTests(unittest.TestCase):
    def test_defaults_to_current_date(self) -> None:
        with mock.patch.object(compiler.sys, "argv", ["compiler", "--output-dir", "/synthetic/output"]):
            self.assertEqual(compiler.parse_args().generated_date, date.today().isoformat())

    def test_accepts_exact_valid_calendar_dates(self) -> None:
        for value in ("2026-08-20", "2024-02-29"):
            with self.subTest(value=value), mock.patch.object(compiler.sys, "argv", ["compiler", "--output-dir", "/synthetic/output", "--generated-date", value]):
                self.assertEqual(compiler.parse_args().generated_date, value)

    def test_rejects_invalid_calendar_dates_and_noncanonical_strings(self) -> None:
        for value in ("2025-02-29", "2026-13-01", "2026-04-31", "0000-01-01", "20260820", "2026-8-20", "2026-08-20T00:00:00", " 2026-08-20"):
            with self.subTest(value=value), mock.patch.object(compiler.sys, "argv", ["compiler", "--output-dir", "/synthetic/output", "--generated-date", value]), mock.patch.object(compiler.sys, "stderr", io.StringIO()):
                with self.assertRaises(SystemExit) as failure:
                    compiler.parse_args()
                self.assertEqual(failure.exception.code, 2)

    def test_main_uses_selected_date_only_for_output_metadata(self) -> None:
        args = argparse.Namespace(damodaran=None, shiller=None, fred=None, refresh=False, generated_date="2026-08-20", output_dir="/synthetic/output", end_year=2025)
        rows = [{"year": year} for year in range(1872, 2026)]
        damodaran, shiller = {1928: {}}, {1872: {}}
        with (
            mock.patch.object(compiler, "parse_args", return_value=args),
            mock.patch.object(compiler, "acquire_source", side_effect=[Path("d.xls"), Path("s.xls"), Path("f.csv")]),
            mock.patch.object(compiler, "parse_fred", return_value={}),
            mock.patch.object(compiler, "merge_fred", side_effect=lambda rows, _: rows),
            mock.patch.object(compiler, "parse_damodaran", return_value=(damodaran, pd.DataFrame())),
            mock.patch.object(compiler, "parse_shiller", return_value=shiller),
            mock.patch.object(compiler, "verify_damodaran_anchor"),
            mock.patch.object(compiler, "reconcile") as reconcile,
            mock.patch.object(compiler, "splice", return_value=rows) as splice,
            mock.patch.object(compiler, "emit") as emit,
            mock.patch.object(compiler.sys, "stdout", io.StringIO()),
        ):
            self.assertEqual(compiler.main(), 0)
        reconcile.assert_called_once_with(shiller, damodaran)
        splice.assert_called_once_with(shiller, damodaran)
        emit.assert_called_once_with(rows, "2026-08-20", Path("/synthetic/output"))


class MainTests(unittest.TestCase):
    def test_all_inputs_are_acquired_and_fred_reconciliation_blocks_emission(self):
        args = argparse.Namespace(damodaran=None, shiller=None, fred='invented.csv', refresh=False,
                                  generated_date='2026-08-20', output_dir='/synthetic/output', end_year=2025)
        rows = [{'year': year, 'tbill_tr': None if year < 1928 else .03} for year in range(1872, 2026)]
        with (mock.patch.object(compiler, 'parse_args', return_value=args),
              mock.patch.object(compiler, 'acquire_source', side_effect=[Path('d.xls'), Path('s.xls'), Path('f.csv')]) as acquire,
              mock.patch.object(compiler, 'parse_damodaran', return_value=({}, None)),
              mock.patch.object(compiler, 'parse_shiller', return_value={}),
              mock.patch.object(compiler, 'verify_damodaran_anchor'),
              mock.patch.object(compiler, 'reconcile'),
              mock.patch.object(compiler, 'splice', return_value=rows),
              mock.patch.object(compiler, 'parse_fred', return_value={year: .04 for year in range(1954, 2026)}),
              mock.patch.object(compiler, 'emit') as emit,
              mock.patch.object(compiler.sys, 'stderr', io.StringIO())):
            self.assertEqual(compiler.main(), 1)
        self.assertEqual(acquire.call_count, 3)
        self.assertEqual(acquire.call_args_list[-1], mock.call('FRED', compiler.FRED_URL, 'invented.csv', False))
        emit.assert_not_called()

    def test_acquires_both_sources_before_parsing(self) -> None:
        args = argparse.Namespace(
            damodaran="damodaran.xls",
            shiller="missing-shiller.xls",
            fred=None,
            refresh=False,
            generated_date="2026-08-20", output_dir="/synthetic/output", end_year=2025,
        )
        missing = FileNotFoundError("Shiller source does not exist")
        with (
            mock.patch.object(compiler, "parse_args", return_value=args),
            mock.patch.object(
                compiler,
                "acquire_source",
                side_effect=[Path("damodaran.xls"), missing],
            ) as acquire,
            mock.patch.object(compiler, "parse_damodaran") as parse,
            mock.patch.object(compiler.sys, "stderr"),
        ):
            result = compiler.main()

        self.assertEqual(result, 1)
        self.assertEqual(
            acquire.call_args_list,
            [
                mock.call(
                    "Damodaran",
                    compiler.DAMODARAN_URL,
                    "damodaran.xls",
                    False,
                ),
                mock.call(
                    "Shiller",
                    compiler.SHILLER_URL,
                    "missing-shiller.xls",
                    False,
                ),
            ],
        )
        parse.assert_not_called()

    def test_reconciliation_failure_happens_before_any_artifact_write(self) -> None:
        args = argparse.Namespace(damodaran=None, shiller=None, fred=None, refresh=False, generated_date="2026-08-20", output_dir="/synthetic/output", end_year=2025)
        damodaran = {1928: {"stock_tr": 0.1}}
        with (
            mock.patch.object(compiler, "parse_args", return_value=args),
            mock.patch.object(compiler, "acquire_source", side_effect=[Path("d.xls"), Path("s.xls"), Path("f.csv")]),
            mock.patch.object(compiler, "parse_damodaran", return_value=(damodaran, pd.DataFrame())),
            mock.patch.object(compiler, "parse_shiller", return_value={}) as parse_shiller,
            mock.patch.object(compiler, "verify_damodaran_anchor"),
            mock.patch.object(compiler, "reconcile", side_effect=ValueError("drift")),
            mock.patch.object(compiler, "emit") as emit,
            mock.patch.object(compiler.sys, "stderr"),
        ):
            result = compiler.main()
        self.assertEqual(result, 1)
        parse_shiller.assert_called_once_with(Path("s.xls"))
        emit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
