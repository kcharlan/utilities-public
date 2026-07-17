#!/usr/bin/env python3
"""Generate estimated-tax QIF transactions from a private local config."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from md_autotax_core import (
    ConfigError,
    generate_qif_content,
    load_config,
    load_tax_table,
    write_qif,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate QIF for estimated taxes.")
    parser.add_argument("--income", type=float, required=True, help="Monthly gross income")
    parser.add_argument("--date", required=True, help="Target date (MM/DD/YYYY)")
    parser.add_argument(
        "--config",
        type=Path,
        help="Private config path (default: ~/.md-autotax/config.json)",
    )
    parser.add_argument(
        "--tax-table",
        type=Path,
        help="Override the private config's tax-table path for this invocation",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("."))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    table_path = args.tax_table or Path(config["tax_table"])
    tax_frame, error = load_tax_table(table_path)
    if error:
        print(f"Error loading tax table: {error}", file=sys.stderr)
        return 2

    try:
        date_obj = datetime.strptime(args.date, "%m/%d/%Y")
    except ValueError:
        print("Error: Date must be in MM/DD/YYYY format.", file=sys.stderr)
        return 2

    match = tax_frame[tax_frame["MonthlyIncome"] == args.income]
    if match.empty:
        print("Error: Requested monthly income was not found in the tax table.", file=sys.stderr)
        return 2

    row = match.iloc[0]
    content = generate_qif_content(date_obj, row["FederalTax"], row["StateTax"], config)
    output = args.output_dir / f"tax_entries_{date_obj.strftime('%Y-%m-%d')}.qif"
    try:
        write_qif(output, content)
    except OSError as exc:
        print(f"Error writing {output}: {exc}", file=sys.stderr)
        return 2
    print(f"QIF file generated: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
