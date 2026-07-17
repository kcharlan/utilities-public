#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "xlsxwriter",
# ]
# ///
"""Generate a formula-driven HYSA versus CD comparison workbook."""

from __future__ import annotations

import argparse
import csv
import math
import os
import stat
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import Iterable

import xlsxwriter


DEFAULT_OUTPUT_NAME = "CD_vs_HYSA_Model.xlsx"
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
MAX_PRINCIPAL = 1e100
MAX_SENSITIVITY = 100.0
MAX_PROJECTED_ANNUAL_RATE = 1.0
MAX_DURATION_MONTHS = 1200
SAFE_BALANCE_LIMIT = 1e200
REQUIRED_PARAMETERS = (
    "Initial Principal",
    "Starting HYSA Rate",
    "Starting CD Rate",
    "Rate Step (per period)",
    "Rate Change Frequency (months)",
    "CD Sensitivity",
    "Total Duration (months)",
)
PERCENT_PARAMETERS = frozenset(
    {
        "Starting HYSA Rate",
        "Starting CD Rate",
        "Rate Step (per period)",
        "CD Sensitivity",
    }
)
INTEGER_PARAMETERS = frozenset(
    {"Rate Change Frequency (months)", "Total Duration (months)"}
)
CD_TERMS = (
    ("CD 3mo Rate", "CD 3mo", 3),
    ("CD 6mo Rate", "CD 6mo", 6),
    ("CD 12mo Rate", "CD 12mo", 12),
    ("CD 18mo Rate", "CD 18mo", 18),
    ("CD 24mo Rate", "CD 24mo", 24),
    ("CD 36mo Rate", "CD 36mo", 36),
    ("CD 60mo Rate", "CD 60mo", 60),
)


class ConfigurationError(ValueError):
    """Raised when the selected input file cannot safely drive a workbook."""

    def __init__(self, problems: Iterable[str]):
        self.problems = tuple(problems)
        super().__init__("; ".join(self.problems))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a formula-driven HYSA versus CD comparison workbook.",
    )
    parser.add_argument(
        "--inputs",
        type=Path,
        help=(
            "CSV input path. Defaults to $HYSA_EXCEL_HOME/inputs.csv or "
            "~/.hysa-excel/inputs.csv."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Workbook output path. Defaults to $HYSA_EXCEL_HOME/"
            f"{DEFAULT_OUTPUT_NAME} or ~/.hysa-excel/{DEFAULT_OUTPUT_NAME}."
        ),
    )
    return parser.parse_args(argv)


def runtime_home() -> Path:
    override = os.environ.get("HYSA_EXCEL_HOME")
    return Path(override).expanduser() if override else Path.home() / ".hysa-excel"


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    home = runtime_home()
    inputs_path = args.inputs.expanduser() if args.inputs else home / "inputs.csv"
    output_path = args.output.expanduser() if args.output else home / DEFAULT_OUTPUT_NAME
    return inputs_path, output_path


def _path_status(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def secure_private_directory(path: Path) -> None:
    """Create or harden a private directory without following its final link."""
    status = _path_status(path)
    if status is None:
        path.mkdir(parents=True, mode=PRIVATE_DIRECTORY_MODE, exist_ok=True)
        status = path.lstat()
    if stat.S_ISLNK(status.st_mode):
        raise RuntimeError(f"refusing symbolic link for private directory: {path}")
    if not stat.S_ISDIR(status.st_mode):
        raise RuntimeError(f"private directory path is not a directory: {path}")

    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened_status = os.fstat(descriptor)
        if not stat.S_ISDIR(opened_status.st_mode):
            raise RuntimeError(f"private directory path is not a directory: {path}")
        if (opened_status.st_dev, opened_status.st_ino) != (
            status.st_dev,
            status.st_ino,
        ):
            raise RuntimeError(f"private directory changed while it was opened: {path}")
        os.fchmod(descriptor, PRIVATE_DIRECTORY_MODE)
    finally:
        os.close(descriptor)


def secure_private_file(path: Path, description: str) -> None:
    """Harden an existing regular file without following symbolic links."""
    status = path.lstat()
    if stat.S_ISLNK(status.st_mode):
        raise RuntimeError(f"refusing symbolic link for {description}: {path}")
    if not stat.S_ISREG(status.st_mode):
        raise RuntimeError(f"{description} is not a regular file: {path}")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened_status = os.fstat(descriptor)
        if not stat.S_ISREG(opened_status.st_mode):
            raise RuntimeError(f"{description} is not a regular file: {path}")
        if (opened_status.st_dev, opened_status.st_ino) != (
            status.st_dev,
            status.st_ino,
        ):
            raise RuntimeError(f"{description} changed while it was opened: {path}")
        os.fchmod(descriptor, PRIVATE_FILE_MODE)
    finally:
        os.close(descriptor)


def write_incomplete_template(path: Path) -> bool:
    """Atomically create a blank local template, returning False if it exists."""
    status = _path_status(path)
    if status is not None:
        secure_private_file(path, "input file")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as handle:
            # Transfer descriptor ownership to the context manager before any
            # operation that can fail, so every path closes it exactly once.
            os.fchmod(handle.fileno(), PRIVATE_FILE_MODE)
            writer = csv.writer(handle)
            writer.writerow(["Parameter", "Value"])
            writer.writerows((name, "") for name in REQUIRED_PARAMETERS)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            return False
        return True
    finally:
        temporary_path.unlink(missing_ok=True)


def parse_number(parameter: str, raw_value: str) -> float:
    value_text = raw_value.strip()
    if not value_text:
        raise ValueError("a value is required")
    is_percentage = value_text.endswith("%")
    if is_percentage:
        value_text = value_text[:-1].strip()
    try:
        value = float(value_text)
    except ValueError as exc:
        raise ValueError("must be a number or percentage") from exc
    if is_percentage:
        value /= 100
    if not math.isfinite(value):
        raise ValueError("must be a finite number")
    if parameter in INTEGER_PARAMETERS and not value.is_integer():
        raise ValueError("must be a whole number")
    return value


def projected_max_rate(
    starting_rate: float,
    rate_step: float,
    frequency_months: int,
    duration_months: int,
    sensitivity: float = 1.0,
) -> float:
    """Return the highest clamped annual rate used over months 1 through N."""
    completed_steps = (duration_months - 1) // frequency_months
    final_unclamped = starting_rate + completed_steps * rate_step * sensitivity
    return max(0.0, starting_rate, final_unclamped)


def compound_monthly(principal: float, annual_rates: Iterable[float]) -> float:
    """Apply one monthly compounding period for every supplied annual rate."""
    balance = principal
    for annual_rate in annual_rates:
        balance *= 1 + max(annual_rate, 0.0) / 12
    return balance


def maximum_compounded_balance(
    principal: float, maximum_annual_rate: float, duration_months: int
) -> float:
    """Return a conservative balance bound without overflowing Python floats."""
    if principal == 0:
        return 0.0
    log_balance = math.log(principal) + duration_months * math.log1p(
        max(maximum_annual_rate, 0.0) / 12
    )
    if log_balance > math.log(sys.float_info.max):
        return math.inf
    return math.exp(log_balance)


def validate_values(values: OrderedDict[str, float], problems: list[str]) -> None:
    if "Initial Principal" in values:
        principal = values["Initial Principal"]
        if principal < 0:
            problems.append("Initial Principal: must be zero or greater")
        elif principal > MAX_PRINCIPAL:
            problems.append(f"Initial Principal: must be {MAX_PRINCIPAL:.0e} or less")
    for name in ("Starting HYSA Rate", "Starting CD Rate"):
        if name in values and not 0 <= values[name] <= 1:
            problems.append(f"{name}: must be between 0 and 1 (0% to 100%)")
    if "Rate Step (per period)" in values and not -1 <= values["Rate Step (per period)"] <= 1:
        problems.append("Rate Step (per period): must be between -1 and 1")
    if "CD Sensitivity" in values:
        sensitivity = values["CD Sensitivity"]
        if sensitivity < 0:
            problems.append("CD Sensitivity: must be zero or greater")
        elif sensitivity > MAX_SENSITIVITY:
            problems.append(f"CD Sensitivity: must be {MAX_SENSITIVITY:g} or less")
    if (
        "Rate Change Frequency (months)" in values
        and values["Rate Change Frequency (months)"] <= 0
    ):
        problems.append("Rate Change Frequency (months): must be greater than zero")
    if "Total Duration (months)" in values:
        duration = values["Total Duration (months)"]
        if duration <= 0:
            problems.append("Total Duration (months): must be greater than zero")
        elif duration > MAX_DURATION_MONTHS:
            problems.append(
                f"Total Duration (months): must be {MAX_DURATION_MONTHS} or less"
            )

    safety_parameters = {
        "Initial Principal",
        "Starting HYSA Rate",
        "Starting CD Rate",
        "Rate Step (per period)",
        "Rate Change Frequency (months)",
        "CD Sensitivity",
        "Total Duration (months)",
    }
    if safety_parameters.issubset(values):
        frequency = int(values["Rate Change Frequency (months)"])
        duration = int(values["Total Duration (months)"])
        sensitivity = values["CD Sensitivity"]
        principal = values["Initial Principal"]
        if (
            frequency > 0
            and duration > 0
            and duration <= MAX_DURATION_MONTHS
            and 0 <= principal <= MAX_PRINCIPAL
            and 0 <= sensitivity <= MAX_SENSITIVITY
        ):
            hysa_max = projected_max_rate(
                values["Starting HYSA Rate"],
                values["Rate Step (per period)"],
                frequency,
                duration,
            )
            cd_max = projected_max_rate(
                values["Starting CD Rate"],
                values["Rate Step (per period)"],
                frequency,
                duration,
                sensitivity,
            )
            if hysa_max > MAX_PROJECTED_ANNUAL_RATE:
                problems.append(
                    "projected HYSA rate "
                    f"({hysa_max:.2%}) exceeds the safety limit of "
                    f"{MAX_PROJECTED_ANNUAL_RATE:.0%}"
                )
            if cd_max > MAX_PROJECTED_ANNUAL_RATE:
                problems.append(
                    "projected CD rate "
                    f"({cd_max:.2%}) exceeds the safety limit of "
                    f"{MAX_PROJECTED_ANNUAL_RATE:.0%}"
                )
            if (
                hysa_max <= MAX_PROJECTED_ANNUAL_RATE
                and cd_max <= MAX_PROJECTED_ANNUAL_RATE
            ):
                worst_balance = maximum_compounded_balance(
                    principal, max(hysa_max, cd_max), duration
                )
                if worst_balance >= SAFE_BALANCE_LIMIT:
                    problems.append(
                        "projected balance exceeds the numeric safety limit; "
                        "reduce principal, rates, or duration"
                    )


def load_inputs(path: Path) -> OrderedDict[str, float]:
    problems: list[str] = []
    raw_rows: OrderedDict[str, str] = OrderedDict()
    try:
        secure_private_file(path, "input file")
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != ["Parameter", "Value"]:
                raise ConfigurationError(
                    ["CSV header must contain exactly: Parameter,Value"]
                )
            for line_number, row in enumerate(reader, start=2):
                parameter = (row.get("Parameter") or "").strip()
                value = row.get("Value") or ""
                if not parameter:
                    problems.append(f"line {line_number}: Parameter cannot be blank")
                    continue
                if parameter in raw_rows:
                    problems.append(f"line {line_number}: duplicate parameter {parameter!r}")
                    continue
                raw_rows[parameter] = value
    except (OSError, UnicodeError) as exc:
        raise ConfigurationError([f"could not read {path}: {exc}"]) from exc

    for parameter in REQUIRED_PARAMETERS:
        if parameter not in raw_rows:
            problems.append(f"{parameter}: required parameter is missing")

    values: OrderedDict[str, float] = OrderedDict()
    for parameter in REQUIRED_PARAMETERS:
        if parameter not in raw_rows:
            continue
        try:
            values[parameter] = parse_number(parameter, raw_rows[parameter])
        except ValueError as exc:
            problems.append(f"{parameter}: {exc}")

    validate_values(values, problems)
    if problems:
        raise ConfigurationError(problems)
    return values


def excel_column(index: int) -> str:
    """Return an Excel column name for a zero-based index."""
    result = ""
    number = index + 1
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def build_workbook(values: OrderedDict[str, float], output_path: Path) -> None:
    existing_status = _path_status(output_path)
    if existing_status is not None:
        if stat.S_ISLNK(existing_status.st_mode):
            raise RuntimeError(
                f"refusing symbolic link for workbook output: {output_path}"
            )
        if not stat.S_ISREG(existing_status.st_mode):
            raise RuntimeError(f"workbook output is not a regular file: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.stem}.",
        suffix=".xlsx",
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    workbook: xlsxwriter.Workbook | None = None
    close_required = False
    try:
        workbook = xlsxwriter.Workbook(temporary_path)
        close_required = True
        workbook.set_properties(
            {
                "title": "HYSA vs CD Comparison",
                "subject": "Formula-driven savings strategy comparison",
                "author": "Utilities Public",
                "comments": "Generated from local user-supplied inputs.",
            }
        )
        percent_format = workbook.add_format(
            {"num_format": "0.00%", "font_color": "#0000FF"}
        )
        number_format = workbook.add_format(
            {"num_format": "$#,##0.00;[Red]($#,##0.00);-", "font_color": "#0000FF"}
        )
        integer_format = workbook.add_format(
            {"num_format": "0", "font_color": "#0000FF"}
        )
        balance_format = workbook.add_format(
            {"num_format": "$#,##0.00;[Red]($#,##0.00);-"}
        )
        rate_formula_format = workbook.add_format({"num_format": "0.00%"})
        header_format = workbook.add_format(
            {"bold": True, "font_color": "#FFFFFF", "bg_color": "#1F4E78"}
        )
        checkmark_format = workbook.add_format(
            {"align": "center", "font_color": "#008000", "bold": True, "font_size": 16}
        )

        inputs_sheet = workbook.add_worksheet("Inputs")
        balances_sheet = workbook.add_worksheet("Monthly Balances")
        simple_sheet = workbook.add_worksheet("Simple")
        output_sheet = workbook.add_worksheet("Output")
        for sheet in (inputs_sheet, balances_sheet, simple_sheet, output_sheet):
            sheet.hide_gridlines(2)

        inputs_sheet.write_row(0, 0, ["Parameter", "Value"], header_format)
        parameter_rows: dict[str, int] = {}
        for row_index, parameter in enumerate(REQUIRED_PARAMETERS, start=1):
            parameter_rows[parameter] = row_index + 1
            inputs_sheet.write(row_index, 0, parameter)
            value = values[parameter]
            if parameter in INTEGER_PARAMETERS:
                inputs_sheet.write_number(row_index, 1, int(value), integer_format)
            elif parameter in PERCENT_PARAMETERS:
                inputs_sheet.write_number(row_index, 1, value, percent_format)
            else:
                inputs_sheet.write_number(row_index, 1, value, number_format)
        inputs_sheet.set_column("A:A", 38)
        inputs_sheet.set_column("B:B", 18)
        inputs_sheet.freeze_panes(1, 0)

        def input_cell(parameter: str) -> str:
            return f"$B${parameter_rows[parameter]}"

        principal_cell = input_cell("Initial Principal")
        hysa_rate_cell = input_cell("Starting HYSA Rate")
        cd_rate_cell = input_cell("Starting CD Rate")
        rate_step_cell = input_cell("Rate Step (per period)")
        rate_frequency_cell = input_cell("Rate Change Frequency (months)")
        cd_sensitivity_cell = input_cell("CD Sensitivity")
        duration_cell = input_cell("Total Duration (months)")
        duration = int(values["Total Duration (months)"])

        balance_headers = ["Month", "HYSA Rate", "HYSA"]
        for rate_label, balance_label, _ in CD_TERMS:
            balance_headers.extend([rate_label, balance_label])
        balances_sheet.write_row(0, 0, balance_headers, header_format)
        balances_sheet.write_formula(
            1, 0, f"=SEQUENCE('Inputs'!{duration_cell},1,1,1)"
        )

        for excel_row in range(2, duration + 2):
            balances_sheet.write_formula(
                excel_row - 1,
                1,
                f"=MAX('Inputs'!{hysa_rate_cell}+"
                f"INT((A{excel_row}-1)/'Inputs'!{rate_frequency_cell})*"
                f"'Inputs'!{rate_step_cell},0)",
                rate_formula_format,
            )
        balances_sheet.write_formula(
            1,
            2,
            f"='Inputs'!{principal_cell}*(1+B2/12)",
            balance_format,
        )
        for zero_based_row in range(2, duration + 1):
            excel_row = zero_based_row + 1
            balances_sheet.write_formula(
                zero_based_row,
                2,
                f"=C{excel_row - 1}*(1+B{excel_row}/12)",
                balance_format,
            )

        for cd_index, (_, _, cd_term) in enumerate(CD_TERMS):
            rate_column_index = 3 + cd_index * 2
            balance_column_index = rate_column_index + 1
            rate_column = excel_column(rate_column_index)
            balance_column = excel_column(balance_column_index)
            for excel_row in range(2, duration + 2):
                current_rate_formula = (
                    f"MAX('Inputs'!{cd_rate_cell}+"
                    f"INT((A{excel_row}-1)/'Inputs'!{rate_frequency_cell})*"
                    f"'Inputs'!{rate_step_cell}*'Inputs'!{cd_sensitivity_cell},0)"
                )
                if excel_row == 2:
                    formula = f"={current_rate_formula}"
                else:
                    formula = (
                        f"=IF(MOD(A{excel_row}-1,{cd_term})=0,"
                        f"{current_rate_formula},{rate_column}{excel_row - 1})"
                    )
                balances_sheet.write_formula(
                    excel_row - 1, rate_column_index, formula, rate_formula_format
                )
            balances_sheet.write_formula(
                1,
                balance_column_index,
                f"='Inputs'!{principal_cell}*(1+{rate_column}2/12)",
                balance_format,
            )
            for zero_based_row in range(2, duration + 1):
                excel_row = zero_based_row + 1
                balances_sheet.write_formula(
                    zero_based_row,
                    balance_column_index,
                    f"={balance_column}{excel_row - 1}*(1+{rate_column}{excel_row}/12)",
                    balance_format,
                )

        balances_sheet.set_column(0, 0, 10)
        balances_sheet.set_column(1, len(balance_headers) - 1, 15)
        balances_sheet.freeze_panes(1, 1)

        simple_sheet.write_row(0, 0, ["Month", "HYSA", "CD"], header_format)
        simple_sheet.set_column("A:C", 18)

        output_sheet.write_row(
            0, 0, ["Strategy", "Final Balance", "Best Performer", "Notes"], header_format
        )
        strategies = ["HYSA", *(balance_label for _, balance_label, _ in CD_TERMS)]
        for strategy_index, strategy in enumerate(strategies):
            excel_row = strategy_index + 2
            balance_column = excel_column(2 if strategy_index == 0 else 4 + (strategy_index - 1) * 2)
            output_sheet.write(strategy_index + 1, 0, strategy)
            output_sheet.write_formula(
                strategy_index + 1,
                1,
                f"='Monthly Balances'!{balance_column}{duration + 1}",
                balance_format,
            )
            output_sheet.write_formula(
                strategy_index + 1,
                2,
                f'=IF(B{excel_row}=MAX($B$2:$B${len(strategies) + 1}),"✓","")',
                checkmark_format,
            )
        output_sheet.set_column("A:A", 18)
        output_sheet.set_column("B:B", 18)
        output_sheet.set_column("C:C", 18)
        output_sheet.set_column("D:D", 30)
        output_sheet.freeze_panes(1, 0)

        close_required = False
        workbook.close()
        os.replace(temporary_path, output_path)
        secure_private_file(output_path, "workbook output")
    except Exception:
        if close_required and workbook is not None:
            try:
                workbook.close()
            except Exception:
                # Preserve the original build exception while still making a
                # best-effort close before removing the temporary package.
                pass
        temporary_path.unlink(missing_ok=True)
        raise


def configuration_message(path: Path, problems: Iterable[str] | None = None) -> str:
    lines = [
        "CONFIGURATION REQUIRED: no workbook was generated.",
        f"Edit the local input file: {path}",
        "Supply every required value, then run this command again.",
    ]
    if problems:
        lines.append("Problems found:")
        lines.extend(f"  - {problem}" for problem in problems)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    inputs_path, output_path = resolve_paths(args)
    if args.inputs is None or args.output is None:
        try:
            secure_private_directory(runtime_home())
        except (OSError, RuntimeError) as exc:
            print(f"ERROR: could not secure runtime directory: {exc}", file=sys.stderr)
            return 1
    if inputs_path.resolve() == output_path.resolve():
        print(
            "CONFIGURATION REQUIRED: --inputs and --output must be different paths; "
            "no files were changed.",
            file=sys.stderr,
        )
        return 2
    input_status = _path_status(inputs_path)
    if input_status is None:
        try:
            write_incomplete_template(inputs_path)
        except (OSError, RuntimeError) as exc:
            print(
                configuration_message(inputs_path, [f"could not create template: {exc}"]),
                file=sys.stderr,
            )
            return 2
        print(configuration_message(inputs_path), file=sys.stderr)
        return 2

    try:
        values = load_inputs(inputs_path)
    except RuntimeError as exc:
        print(configuration_message(inputs_path, [str(exc)]), file=sys.stderr)
        return 2
    except ConfigurationError as exc:
        print(configuration_message(inputs_path, exc.problems), file=sys.stderr)
        return 2

    try:
        build_workbook(values, output_path)
    except (OSError, RuntimeError, xlsxwriter.exceptions.XlsxWriterException) as exc:
        print(f"ERROR: could not write workbook {output_path}: {exc}", file=sys.stderr)
        return 1
    print(f"Workbook generated: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
