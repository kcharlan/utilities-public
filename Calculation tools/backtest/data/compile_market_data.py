#!/usr/bin/env python3
"""Compile public annual US market series into static JS and CSV artifacts."""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import re
import shutil
import stat
import statistics
import sys
import tempfile
import urllib.request
import urllib.parse
from datetime import date
from numbers import Real
from pathlib import Path
from typing import Any

import pandas as pd


SOURCE_RECIPE = json.loads(Path(__file__).with_name("sources.json").read_text(encoding="utf-8"))
SOURCE_SETTINGS = {source["name"]: source for source in SOURCE_RECIPE["sources"]}
SOURCE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = next((parent for parent in Path(__file__).resolve().parents
                        if (parent / ".git").exists()), None)
WEBROOT = Path.home() / "webroot"
CONFIGURED_WEBROOT = Path(os.environ.get("UTILITIES_WEBROOT_DIR") or
                          str(Path(os.environ.get("UTILITIES_LOCAL_ROOT") or Path.home()) / "webroot")).expanduser()
CACHE = Path(os.environ.get("MARKET_ATLAS_DATA_HOME") or "~/.cache/market-atlas").expanduser()
DAMODARAN_URL = SOURCE_SETTINGS["Damodaran"]["url"]
SHILLER_URL = SOURCE_SETTINGS["Shiller"]["url"]
FRED_URL = SOURCE_SETTINGS["FRED"]["url"]
OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
MIN_XLS_BYTES = 512
MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024
DOWNLOAD_CHUNK_SIZE = 64 * 1024
REQUIRED_SHEETS = {name: set(source["requiredSheets"]) for name, source in SOURCE_SETTINGS.items()
                   if source["format"] == "OLE/XLS"}
FIRST_OUTPUT_YEAR = 1872
DAMODARAN_FIRST_YEAR = 1928
DAMODARAN_ANCHOR_LAST_YEAR = 2025
RECONCILIATION_LAST_YEAR = 2022
SHILLER_DATE_GRID_TOLERANCE = 1e-6
RECONCILIATION_RANGE = range(DAMODARAN_FIRST_YEAR, RECONCILIATION_LAST_YEAR + 1)
RECONCILIATION_THRESHOLDS = {
    "stock_tr": {"mae": 0.0300, "abs_bias": 0.0060, "stdev_ratio": (0.93, 1.07),
                 "abs_geometric_mean_difference": 0.0050},
    "bond10_tr": {"mae": 0.0300, "abs_bias": 0.0060, "stdev_ratio": (0.93, 1.10),
                  "abs_geometric_mean_difference": 0.0050},
}


def is_number(value: Any) -> bool:
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and not pd.isna(value)
        and math.isfinite(float(value))
    )


def parse_year_cell(value: Any, source: str, row_index: int) -> int | None:
    """Return an integral year, None for a terminator, or reject malformed numerics."""
    if pd.isna(value) or not isinstance(value, Real) or isinstance(value, bool):
        return None
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{source} row {row_index} has a non-finite year: {value!r}")
    if not numeric.is_integer():
        raise ValueError(f"{source} row {row_index} has a fractional year: {value!r}")
    return int(numeric)


def validate_workbook(name: str, path: Path) -> None:
    """Reject non-XLS payloads and workbooks missing the source's required sheets."""
    size = path.stat().st_size
    if size < MIN_XLS_BYTES:
        raise ValueError(f"{name} download is too small to be a usable XLS workbook ({size} bytes)")
    with path.open("rb") as handle:
        signature = handle.read(len(OLE_SIGNATURE))
    if signature != OLE_SIGNATURE:
        raise ValueError(f"{name} source does not have the expected OLE/XLS signature")
    try:
        with pd.ExcelFile(path, engine="xlrd") as workbook:
            sheet_names = set(workbook.sheet_names)
    except Exception as exc:
        raise ValueError(f"{name} source is not a readable legacy XLS workbook: {exc}") from exc
    missing = sorted(REQUIRED_SHEETS[name] - sheet_names)
    if missing:
        raise ValueError(f"{name} workbook is missing required sheet(s): {', '.join(missing)}")


def fred_observations(path: Path) -> list[tuple[date, float | None]]:
    """Validate complete raw CSV independently of selected output coverage."""
    if path.stat().st_size > MAX_DOWNLOAD_BYTES:
        raise ValueError('FRED input exceeds the byte maximum')
    observations = []
    previous = None
    try:
        with path.open(encoding='utf-8', newline='') as handle:
            if handle.readline().rstrip('\r\n') != ','.join(SOURCE_SETTINGS['FRED']['layout']['header']):
                raise ValueError('FRED CSV header changed')
            reader = csv.reader(handle, strict=True)
            for row in reader:
                if len(row) != 2 or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', row[0]):
                    raise ValueError('FRED CSV requires date-value rows')
                day = date.fromisoformat(row[0])
                if previous is not None and day <= previous:
                    raise ValueError('FRED dates must be strictly increasing')
                previous = day
                value = None
                if row[1] != '':
                    if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)', row[1]):
                        raise ValueError('FRED values must be finite signed decimals or empty')
                    value = float(row[1])
                    if not math.isfinite(value):
                        raise ValueError('FRED values must be finite')
                observations.append((day, value))
    except (UnicodeError, csv.Error) as exc:
        raise ValueError('FRED requires valid UTF-8 CSV') from exc
    if not observations:
        raise ValueError('FRED CSV has no observations')
    return observations


def validate_source(name: str, path: Path) -> None:
    if path.stat().st_size > MAX_DOWNLOAD_BYTES:
        raise ValueError(f'{name} input exceeds the byte maximum')
    if SOURCE_SETTINGS[name]['format'] == 'CSV':
        fred_observations(path)
    else:
        validate_workbook(name, path)


def parse_fred(path: Path, end_year: int) -> dict[int, float]:
    selected: dict[int, list[tuple[date, float]]] = {}
    for day, value in fred_observations(path):
        if 1954 <= day.year <= end_year and value is not None:
            selected.setdefault(day.year, []).append((day, value))
    means = {}
    for year in range(1954, end_year + 1):
        values = selected.get(year, [])
        months = {day.month for day, _ in values}
        if len(values) < 240 or not {1, 12}.issubset(months):
            raise ValueError(f'FRED {year} requires 240 numeric observations and January/December coverage')
        means[year] = round(statistics.fmean(value for _, value in values) / 100, 8)
    return means


def merge_fred(rows: list[dict[str, Any]], means: dict[int, float]) -> list[dict[str, Any]]:
    merged = []
    for row in rows:
        year = row['year']
        value = row['tbill_tr'] if year < 1954 else means[year]
        if 1954 <= year <= 1981 and abs(value - row['tbill_tr']) > 1e-6:
            raise ValueError(f'FRED reconciliation disagrees with Damodaran for {year}')
        merged.append({**row, 'tbill_dtb3_tr': value})
    return merged


def validate_source_url(name: str, url: str) -> None:
    """Constrain requests and every redirect before transmitting them."""
    parsed = urllib.parse.urlsplit(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if (parsed.scheme != "https" or parsed.username or parsed.password
            or parsed.fragment or origin not in SOURCE_SETTINGS[name]["allowedOrigins"]):
        raise ValueError(f"{name} acquisition endpoint must use approved HTTPS origins")


class OfficialRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_source_url(self.name, newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_source(name: str, request: urllib.request.Request):
    validate_source_url(name, request.full_url)
    opener = urllib.request.build_opener(OfficialRedirectHandler(name))
    return opener.open(request, timeout=60)


def acquire_source(name: str, url: str, supplied: str | None, refresh: bool) -> Path:
    if supplied:
        requested = Path(supplied).expanduser().absolute()
        for component in (requested, *requested.parents):
            if component.is_symlink() and str(component) not in ("/var", "/tmp"):
                raise ValueError(f"{name} manual source must not contain symlinks")
        path = requested.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"{name} source does not exist")
        validate_source(name, path)
        return path

    validate_source_url(name, url)
    cache = validate_output_dir(CACHE, data_pair=False)
    ensure_private_directory(cache)
    destination = cache / SOURCE_SETTINGS[name]["cacheFilename"]
    validate_owned_file(destination)
    if destination.exists() and not refresh:
        validate_source(name, destination)
        return destination

    temporary_path: Path | None = None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "market-backtest-compiler/1.0"})
        with open_source(name, request) as response:
            with tempfile.NamedTemporaryFile(dir=cache, delete=False) as temporary:
                temporary_path = Path(temporary.name)
                total_bytes = 0
                while chunk := response.read(DOWNLOAD_CHUNK_SIZE):
                    total_bytes += len(chunk)
                    if total_bytes > MAX_DOWNLOAD_BYTES:
                        raise ValueError(
                            f"{name} download exceeds the {MAX_DOWNLOAD_BYTES}-byte maximum"
                        )
                    temporary.write(chunk)
        validate_source(name, temporary_path)
        os.replace(temporary_path, destination)
    except Exception as exc:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        flag = '--' + SOURCE_SETTINGS[name]['id']
        raise RuntimeError(
            f"Could not download {name} data from {url}. Download it manually and rerun "
            f"with {flag} PATH. Underlying error: {exc}"
        ) from exc
    return destination


def parse_damodaran(path: Path) -> tuple[dict[int, dict[str, float]], pd.DataFrame]:
    returns = pd.read_excel(path, sheet_name="Returns by year", header=None, engine="xlrd")
    inflation = pd.read_excel(path, sheet_name="Inflation Rate", header=None, engine="xlrd")
    returns_headers = {
        0: "Year",
        1: "S&P 500 (includes dividends)",
        3: "3-month T.Bill",
        4: "US T. Bond (10-year)",
    }
    inflation_headers = {0: "observation_date", 1: "CPIAUCNS"}
    for column, expected in returns_headers.items():
        actual = str(returns.iloc[19, column]).strip()
        if actual != expected:
            raise ValueError(
                "Damodaran layout changed: Returns by year "
                f"row 19 column {column} is {actual!r}, expected {expected!r}"
            )
    for column, expected in inflation_headers.items():
        actual = str(inflation.iloc[10, column]).strip()
        if actual != expected:
            raise ValueError(
                "Damodaran layout changed: Inflation Rate "
                f"row 10 column {column} is {actual!r}, expected {expected!r}"
            )

    cpi: dict[int, float] = {}
    for row_index in range(11, len(inflation)):
        year_cell = inflation.iloc[row_index, 0]
        year = parse_year_cell(year_cell, "Damodaran Inflation Rate", row_index)
        if year is None:
            break
        if year in cpi:
            raise ValueError(f"Damodaran Inflation Rate has duplicate year {year}")
        value = inflation.iloc[row_index, 2]
        if not is_number(value):
            raise ValueError(f"Missing Damodaran CPI change for {year} (or value is non-finite)")
        cpi[year] = float(value)

    years: dict[int, dict[str, float]] = {}
    for row_index in range(20, len(returns)):
        year_cell = returns.iloc[row_index, 0]
        year = parse_year_cell(year_cell, "Damodaran Returns by year", row_index)
        if year is None:
            break
        if year in years:
            raise ValueError(f"Damodaran Returns by year has duplicate year {year}")
        values = [returns.iloc[row_index, col] for col in (1, 3, 4)]
        if not all(is_number(value) for value in values) or year not in cpi:
            raise ValueError(
                f"Missing Damodaran market or CPI value for {year} (or value is non-finite)"
            )
        years[year] = {
            "stock_tr": float(values[0]),
            "tbill_tr": float(values[1]),
            "bond10_tr": float(values[2]),
            "cpi_change": cpi[year],
        }

    if len(years) < 90:
        raise ValueError(f"Damodaran parse produced only {len(years)} annual rows; expected at least 90")
    validate_damodaran_range(years)
    expected = set(range(min(years), max(years) + 1))
    if set(years) != expected:
        missing = sorted(expected - set(years))
        raise ValueError(f"Damodaran annual series has missing years: {missing}")
    return years, returns


def validate_damodaran_range(years: dict[int, dict[str, float]]) -> None:
    first_year = min(years)
    last_year = max(years)
    if first_year != DAMODARAN_FIRST_YEAR:
        raise ValueError(
            f"Damodaran annual series must start exactly at {DAMODARAN_FIRST_YEAR}; "
            f"found {first_year}"
        )
    if last_year < DAMODARAN_ANCHOR_LAST_YEAR:
        raise ValueError(
            f"Damodaran annual series must end at or after {DAMODARAN_ANCHOR_LAST_YEAR}; "
            f"found {last_year}"
        )


def parse_shiller(path: Path) -> dict[int, dict[str, float]]:
    """Aggregate Shiller's monthly real indexes and bond factors to calendar years."""
    sheet = pd.read_excel(path, sheet_name="Data", header=None, engine="xlrd")
    headers = {
        (5, 4): "Price", (5, 9): "Total", (5, 17): "Total",
        (6, 4): "Index", (6, 9): "Return", (6, 17): "Bond",
        (7, 0): "Date", (7, 4): "CPI", (7, 9): "Price", (7, 17): "Returns",
    }
    for (row, column), expected in headers.items():
        actual = str(sheet.iloc[row, column]).strip()
        if actual != expected:
            raise ValueError(
                f"Shiller layout changed: Data row {row} column {column} is "
                f"{actual!r}, expected {expected!r}"
            )

    months: dict[tuple[int, int], dict[str, float | None]] = {}
    for row_index in range(8, len(sheet)):
        date_cell = sheet.iloc[row_index, 0]
        if pd.isna(date_cell):
            break
        if (
            isinstance(date_cell, Real)
            and not isinstance(date_cell, bool)
            and not math.isfinite(float(date_cell))
        ):
            raise ValueError(f"Shiller Data row {row_index} has a non-finite date")
        if not is_number(date_cell):
            break
        scaled_date = float(date_cell) * 100
        k = int(round(scaled_date))
        if abs(scaled_date - k) > SHILLER_DATE_GRID_TOLERANCE:
            raise ValueError(
                f"Shiller Data row {row_index} date {date_cell!r} is off the YYYY.MM month grid"
            )
        year, month = k // 100, k % 100
        if month < 1 or month > 12:
            raise ValueError(f"Shiller Data row {row_index} has invalid month {month}")
        key = (year, month)
        if key in months:
            raise ValueError(f"Shiller Data has duplicate month {year}-{month:02d}")
        cpi = sheet.iloc[row_index, 4]
        real_stock = sheet.iloc[row_index, 9]
        bond_factor = sheet.iloc[row_index, 17]
        if not is_number(cpi) or not is_number(real_stock):
            raise ValueError(
                f"Shiller Data row {row_index} has a non-finite CPI or real stock index"
            )
        if float(cpi) <= 0:
            raise ValueError(f"Shiller Data row {row_index} must have a positive CPI")
        if float(real_stock) <= 0:
            raise ValueError(f"Shiller Data row {row_index} must have a positive real stock index")
        if not pd.isna(bond_factor) and not is_number(bond_factor):
            raise ValueError(f"Shiller Data row {row_index} has a non-finite bond factor")
        if not pd.isna(bond_factor) and float(bond_factor) <= 0:
            raise ValueError(f"Shiller Data row {row_index} must have a positive bond factor")
        nominal_stock = float(real_stock) * float(cpi)
        if not math.isfinite(nominal_stock) or nominal_stock <= 0:
            raise ValueError(f"Shiller Data row {row_index} produced an invalid nominal stock index")
        months[key] = {
            "cpi": float(cpi),
            "nominal_stock": nominal_stock,
            "bond_factor": None if pd.isna(bond_factor) else float(bond_factor),
        }

    if not months:
        raise ValueError("Shiller parse produced no monthly rows")
    ordered_keys = sorted(months)
    first_key, last_key = ordered_keys[0], ordered_keys[-1]
    expected_keys: list[tuple[int, int]] = []
    year, month = first_key
    while (year, month) <= last_key:
        expected_keys.append((year, month))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    if ordered_keys != expected_keys:
        missing = sorted(set(expected_keys) - set(ordered_keys))
        raise ValueError(f"Shiller monthly series has missing months: {missing}")

    years: dict[int, dict[str, float]] = {}
    for annual_year in range(first_key[0] + 1, last_key[0] + 1):
        annual_keys = [(annual_year, month) for month in range(1, 13)]
        if not all(key in months for key in annual_keys) or (annual_year - 1, 12) not in months:
            continue
        bond_factors = [months[key]["bond_factor"] for key in annual_keys]
        if any(value is None for value in bond_factors):
            raise ValueError(f"Shiller {annual_year} has non-finite or missing bond monthly factors")
        previous = months[(annual_year - 1, 12)]
        current = months[(annual_year, 12)]
        annual_values = {
            "stock_tr": float(current["nominal_stock"]) / float(previous["nominal_stock"]) - 1,
            "bond10_tr": math.prod(float(value) for value in bond_factors) - 1,
            "cpi_change": float(current["cpi"]) / float(previous["cpi"]) - 1,
        }
        if any(not is_number(value) or value <= -1 for value in annual_values.values()):
            raise ValueError(f"Shiller {annual_year} produced invalid annual returns")
        years[annual_year] = annual_values
    if not years:
        raise ValueError("Shiller monthly series has missing months needed for an annual return")
    expected_years = set(range(min(years), max(years) + 1))
    if set(years) != expected_years:
        raise ValueError(f"Shiller annual series has missing years: {sorted(expected_years - set(years))}")
    return years


def geometric_mean(values: list[float]) -> float:
    return math.prod(1 + value for value in values) ** (1 / len(values)) - 1


def reconcile(
    shiller_years: dict[int, dict[str, float]],
    damodaran_years: dict[int, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """Validate distributional agreement over the fixed independent-source overlap."""
    overlap = list(RECONCILIATION_RANGE)
    for source, years in (("Shiller", shiller_years), ("Damodaran", damodaran_years)):
        missing = [year for year in overlap if year not in years]
        if missing:
            raise ValueError(f"{source} is missing required 1928-2022 overlap years: {missing}")

    metrics: dict[str, dict[str, float]] = {}
    for series in ("stock_tr", "bond10_tr"):
        shiller_values = [shiller_years[year][series] for year in overlap]
        damodaran_values = [damodaran_years[year][series] for year in overlap]
        differences = [left - right for left, right in zip(shiller_values, damodaran_values, strict=True)]
        metrics[series] = {
            "mae": statistics.fmean(abs(value) for value in differences),
            "bias": statistics.fmean(differences),
            "stdev_ratio": statistics.stdev(shiller_values) / statistics.stdev(damodaran_values),
            "geometric_mean_difference": geometric_mean(shiller_values)
            - geometric_mean(damodaran_values),
        }

    print("Shiller-Damodaran reconciliation (1928-2022)")
    print("series       MAE       bias      stdev ratio  geometric mean difference")
    for series, values in metrics.items():
        print(
            f"{series:<11} {values['mae']:>8.4f}  {values['bias']:>+9.4f}  "
            f"{values['stdev_ratio']:>11.3f}  {values['geometric_mean_difference']:>+25.4f}"
        )

    failures: list[str] = []
    for series, values in metrics.items():
        limits = RECONCILIATION_THRESHOLDS[series]
        if values["mae"] > limits["mae"]:
            failures.append(f"{series} MAE {values['mae']:.6f} exceeds {limits['mae']:.4f}")
        if abs(values["bias"]) > limits["abs_bias"]:
            failures.append(
                f"{series} absolute bias {abs(values['bias']):.6f} exceeds {limits['abs_bias']:.4f}"
            )
        lower, upper = limits["stdev_ratio"]
        if not lower <= values["stdev_ratio"] <= upper:
            failures.append(
                f"{series} stdev ratio {values['stdev_ratio']:.6f} is outside {lower:.2f}-{upper:.2f}"
            )
        if abs(values["geometric_mean_difference"]) > limits["abs_geometric_mean_difference"]:
            failures.append(
                f"{series} absolute geometric mean difference "
                f"{abs(values['geometric_mean_difference']):.6f} exceeds "
                f"{limits['abs_geometric_mean_difference']:.4f}"
            )
    if failures:
        raise ValueError("Reconciliation threshold failure: " + "; ".join(failures))
    return metrics


def splice(
    shiller_years: dict[int, dict[str, float]],
    damodaran_years: dict[int, dict[str, float]],
) -> list[dict[str, Any]]:
    """Use reconstructed Shiller data before 1928 and Damodaran thereafter."""
    rows: list[dict[str, Any]] = []
    for year in range(FIRST_OUTPUT_YEAR, DAMODARAN_FIRST_YEAR):
        if year not in shiller_years:
            raise ValueError(f"Shiller pre-1928 splice is missing year {year}")
        values = shiller_years[year]
        rows.append({"year": year, **values, "tbill_tr": None, "quality": "reconstructed"})
    for year in sorted(damodaran_years):
        values = damodaran_years[year]
        rows.append({"year": year, **values, "quality": "ok"})
    years = [row["year"] for row in rows]
    if years != list(range(FIRST_OUTPUT_YEAR, years[-1] + 1)):
        raise ValueError("Spliced annual series must be contiguous without gaps or duplicates")
    return rows


def verify_damodaran_anchor(years: dict[int, dict[str, float]], sheet: pd.DataFrame) -> None:
    validate_damodaran_range(years)
    first_year = min(years)
    last_year = max(years)
    actual = geometric_mean([years[year]["stock_tr"] for year in sorted(years)])
    if last_year == DAMODARAN_ANCHOR_LAST_YEAR:
        expected = 0.100177
    elif last_year > DAMODARAN_ANCHOR_LAST_YEAR:
        expected = None
        in_geometric_block = False
        range_label = f"{first_year}-{last_year}"
        for row_index in range(len(sheet)):
            label = str(sheet.iloc[row_index, 0]).strip()
            if "Geometric Average Historical Return" in label:
                in_geometric_block = True
                continue
            if in_geometric_block and label == range_label:
                candidate = sheet.iloc[row_index, 1]
                if is_number(candidate):
                    expected = float(candidate)
                break
        if expected is None:
            raise ValueError(
                "Could not locate Damodaran's published geometric-return anchor "
                f"for {range_label}"
            )
    else:  # validate_damodaran_range makes this unreachable.
        raise AssertionError("Damodaran anchor range validation failed to constrain the end year")
    if abs(actual - expected) > 1e-5:
        raise ValueError(
            f"Damodaran stock geometric mean drifted: parsed {actual:.8f}, expected {expected:.8f}"
        )
    print(f"Damodaran stock geometric mean: {actual:.6f} (anchor {expected:.6f})")


def rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 8)


def validate_owned_file(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("Output/input object must be a plain regular file")
    if path.exists():
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("Output/input object must be a plain regular file")


def validate_output_dir(path: Path, *, data_pair: bool = True) -> Path:
    """Validate external placement and ordinary directory/file types."""
    requested = path.expanduser()
    if not requested.is_absolute():
        requested = Path.cwd() / requested
    resolved = requested.resolve()
    for forbidden in (SOURCE_ROOT, REPOSITORY_ROOT, WEBROOT, CONFIGURED_WEBROOT):
        if forbidden is not None and resolved.is_relative_to(forbidden.resolve()):
            raise ValueError("Data/output destination must be outside source, repository and webroot")
    # Canonical macOS /var and /tmp aliases are system-owned; all other aliases
    # are refused so writes cannot be redirected through user-owned links.
    for component in (requested, *requested.parents):
        if component.is_symlink() and str(component) not in ("/var", "/tmp"):
            raise ValueError("Data/output destination must not contain symlinks")
        if component.exists():
            metadata = component.stat()
            if not stat.S_ISDIR(metadata.st_mode):
                raise ValueError("Data/output destination must contain only directories")
    if data_pair:
        for filename in ("market-data.js", "market-data.csv"):
            validate_owned_file(resolved / filename)
    return resolved


def ensure_private_directory(path: Path) -> None:
    validate_output_dir(path, data_pair=False)
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
    validate_output_dir(path, data_pair=False)


def select_output_rows(rows: list[dict[str, Any]], end_year: int) -> list[dict[str, Any]]:
    supported = SOURCE_RECIPE["output"]["lastYear"]
    if type(end_year) is not int or end_year != supported or not rows or rows[-1]["year"] < end_year:
        raise ValueError(f"Selected end year must be the reviewed recipe year {supported} and available")
    selected = [row for row in rows if row["year"] <= end_year]
    if not selected or selected[0]["year"] != FIRST_OUTPUT_YEAR or selected[-1]["year"] != end_year:
        raise ValueError("Selected end year must yield the complete reviewed output range")
    return selected


def emit(rows: list[dict[str, Any]], generated: str, output_dir: Path) -> None:
    output_dir = validate_output_dir(Path(output_dir))
    years = [row["year"] for row in rows]
    if years != list(range(years[0], years[-1] + 1)):
        raise ValueError("Output rows must be a contiguous, ascending sequence without duplicates")

    normalized_rows = [
        {
            "year": row["year"],
            "stock_tr": rounded(row["stock_tr"]),
            "bond10_tr": rounded(row["bond10_tr"]),
            "tbill_tr": rounded(row["tbill_tr"]),
            "tbill_dtb3_tr": rounded(row["tbill_dtb3_tr"]),
            "cpi_change": rounded(row["cpi_change"]),
            "quality": row["quality"],
        }
        for row in rows
    ]
    payload = {
        "generated": generated,
        "sources": {
            "stock_tr": (
                "Shiller ie_data.xls nominalized Real Total Return Price (1872-1927); "
                "Damodaran histretSP.xls S&P 500 including dividends (1928+)"
            ),
            "bond10_tr": (
                "Shiller ie_data.xls chained Monthly Total Bond Returns (1872-1927); "
                "Damodaran histretSP.xls US T. Bond 10-year (1928+)"
            ),
            "tbill_tr": "Unavailable 1872-1927; Damodaran histretSP.xls 3-month T.Bill (1928+)",
            "tbill_dtb3_tr": "Damodaran histretSP.xls 3-month T.Bill (1928-1953); FRED DTB3 3-Month Treasury Bill Secondary Market Rate, Discount Basis, annual mean of daily values (1954+)",
            "cpi_change": (
                "Shiller ie_data.xls CPI December-to-December (1872-1927); "
                "FRED CPIAUCNS via Damodaran histretSP.xls (1928+)"
            ),
        },
        "rows": normalized_rows,
    }
    js = (
        "globalThis.MARKET_DATA = "
        + json.dumps(payload, indent=2, separators=(",", ": "), allow_nan=False)
        + ";\n"
    )
    csv_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        csv_buffer, fieldnames=["year", "stock_tr", "bond10_tr", "tbill_tr", "tbill_dtb3_tr", "cpi_change", "quality"]
    )
    writer.writeheader()
    writer.writerows(normalized_rows)

    ensure_private_directory(output_dir)
    temporary_paths: list[tuple[Path, Path]] = []
    owned_paths: set[Path] = set()
    backups: dict[Path, Path | None] = {}
    retained_backups: set[Path] = set()
    promotion_started = False
    try:
        for destination, contents in (
            (output_dir / "market-data.js", js),
            (output_dir / "market-data.csv", csv_buffer.getvalue()),
        ):
            temporary = tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", dir=output_dir, delete=False
            )
            temporary_path = Path(temporary.name)
            owned_paths.add(temporary_path)
            with temporary:
                temporary.write(contents)
            temporary_paths.append((temporary_path, destination))
        for _, destination in temporary_paths:
            if destination.exists():
                backup = tempfile.NamedTemporaryFile(dir=output_dir, delete=False)
                backup_path = Path(backup.name)
                owned_paths.add(backup_path)
                backup.close()
                shutil.copyfile(destination, backup_path)
                backups[destination] = backup_path
            else:
                backups[destination] = None
        promotion_started = True
        for temporary, destination in temporary_paths:
            os.replace(temporary, destination)
    except Exception as exc:
        rollback_errors: list[str] = []
        for destination, backup in (backups.items() if promotion_started else ()):
            try:
                if backup is None:
                    destination.unlink(missing_ok=True)
                else:
                    os.replace(backup, destination)
            except Exception as rollback_exc:
                rollback_errors.append(f"{destination.name}: {rollback_exc}")
                if backup is not None:
                    retained_backups.add(backup)
        if rollback_errors:
            raise RuntimeError(
                f"Artifact replacement failed ({exc}); rollback also failed: "
                + "; ".join(rollback_errors)
            ) from exc
        raise
    finally:
        for owned_path in owned_paths:
            if owned_path not in retained_backups:
                owned_path.unlink(missing_ok=True)


def generated_date(value: str) -> str:
    """Accept only an exact ISO calendar date for reproducible metadata."""
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("generated date must be a valid YYYY-MM-DD date") from exc
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("generated date must be a valid YYYY-MM-DD date")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--damodaran", help="local histretSP.xls path")
    parser.add_argument("--shiller", help="local ie_data.xls path")
    parser.add_argument("--fred", help="local DTB3.csv path")
    parser.add_argument("--refresh", action="store_true", help="redownload cached source files")
    parser.add_argument("--acquire-only", action="store_true",
                        help="validate/acquire sources only; do not transform or emit data")
    parser.add_argument("--output-dir", required=True, help="external private output directory (required)")
    parser.add_argument("--end-year", type=int, choices=[SOURCE_RECIPE["output"]["lastYear"]],
                        default=SOURCE_RECIPE["output"]["lastYear"],
                        help="reviewed output end year (default: 2025)")
    parser.add_argument(
        "--generated-date", type=generated_date, default=date.today().isoformat(),
        metavar="YYYY-MM-DD", help="generation metadata date (default: current date)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        output_dir = validate_output_dir(Path(args.output_dir))
        damodaran_path = acquire_source("Damodaran", DAMODARAN_URL, args.damodaran, args.refresh)
        shiller_path = acquire_source("Shiller", SHILLER_URL, args.shiller, args.refresh)
        fred_path = acquire_source("FRED", FRED_URL, args.fred, args.refresh)
        if getattr(args, "acquire_only", False):
            print("Validated all three source inputs; no compiled outputs written")
            return 0
        damodaran, sheet = parse_damodaran(damodaran_path)
        shiller = parse_shiller(shiller_path)
        verify_damodaran_anchor(damodaran, sheet)
        reconcile(shiller, damodaran)
        rows = splice(shiller, damodaran)
        rows = select_output_rows(rows, args.end_year)
        rows = merge_fred(rows, parse_fred(fred_path, args.end_year))
        emit(rows, args.generated_date, output_dir)
        print(f"Wrote {len(rows)} rows ({rows[0]['year']}-{rows[-1]['year']})")
        return 0
    except Exception as exc:  # concise CLI failure; full exception remains in chained context when imported
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
