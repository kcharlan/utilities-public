#!/usr/bin/env python3
"""
Abacus.AI Usage Log Converter

Converts JSON usage logs from Abacus.AI (captured via DevTools) into
CSV format for analysis.

Usage:
    python3 de-abacus.py input.json [output.csv]
    python3 de-abacus.py --help
"""

import csv
import json
import sys
import argparse
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

def to_number(v: Any) -> Optional[float]:
    """Convert value to float if possible, else return None."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (ValueError, TypeError):
        return None

def round2(v: Any) -> Any:
    """Round float to 2 decimal places with epsilon handling."""
    if isinstance(v, float):
        # Add epsilon to handle floating point anomalies before rounding
        return round(v + 1e-12, 2)
    return v

def validate_json_structure(payload: Dict[str, Any]) -> None:
    """Validate the expected JSON structure."""
    if not isinstance(payload, dict):
        raise ValueError("Root JSON element must be a dictionary/object.")
    
    # "success" is typically true, but if false, check if we have results anyway or fail.
    if "success" in payload and not payload["success"]:
         logger.warning(f"JSON 'success' field is false. Error info: {payload.get('error')}")

    if "result" not in payload:
        raise ValueError("JSON payload missing 'result' key.")

def extract_columns(result: Dict[str, Any], rows: List[Dict[str, Any]]) -> List[str]:
    """Determine the column headers from the result object or row data."""
    columns_map = result.get("columns") or {}
    
    # 1. Prefer explicit columns from the 'columns' key
    col_keys = list(columns_map.keys())
    
    # 2. Fallback: Scan all rows if explicit columns are missing
    if not col_keys:
        logger.info("No 'columns' definition found in JSON. Inferring from data rows...")
        keys: Set[str] = set()
        for r in rows:
            keys.update(r.keys())
        col_keys = sorted(keys)

    # 3. Ensure 'date' is the first column if it exists
    if "date" in col_keys:
        col_keys = ["date"] + [c for c in col_keys if c != "date"]
        
    return col_keys

def convert(json_path: Path, csv_path: Path, missing_as_zero: bool = True) -> None:
    """
    Reads JSON from json_path and writes CSV to csv_path.
    """
    logger.info(f"Reading {json_path}...")
    
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Could not read input file: {e}")
        sys.exit(1)

    try:
        validate_json_structure(payload)
    except ValueError as e:
        logger.error(f"Validation Error: {e}")
        sys.exit(1)

    result = payload.get("result") or {}
    rows = result.get("log") or []
    
    if not rows:
        logger.warning("No data rows found in 'result.log'. CSV will be empty.")

    col_keys = extract_columns(result, rows)
    
    logger.info(f"Found {len(col_keys)} columns: {', '.join(col_keys)}")
    logger.info(f"Processing {len(rows)} rows...")

    try:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=col_keys, extrasaction="ignore")
            w.writeheader()

            for r in rows:
                out = {}
                for k in col_keys:
                    # Keep date as string (or format it if needed, currently keeping raw)
                    if k == "date":
                        out[k] = r.get(k, "")
                        continue

                    raw_val = r.get(k, None)
                    
                    if raw_val is None:
                        out[k] = 0 if missing_as_zero else ""
                    else:
                        n = to_number(raw_val)
                        if n is not None:
                            out[k] = round2(n)
                        else:
                            # Fallback for non-numeric data in value columns (e.g. notes?)
                            out[k] = raw_val

                w.writerow(out)
                
        logger.info(f"Successfully wrote {csv_path}")

    except IOError as e:
        logger.error(f"Failed to write to CSV file: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        description="Convert Abacus.AI JSON usage logs to CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument("input", type=Path, help="Path to input JSON file")
    parser.add_argument("output", type=Path, nargs="?", help="Path to output CSV file (default: input_filename.csv)")
    parser.add_argument(
        "--no-zeros", 
        action="store_false", 
        dest="missing_as_zero",
        help="Leave missing values empty instead of filling with 0"
    )
    parser.add_argument(
        "-v", "--verbose", 
        action="store_true", 
        help="Enable verbose debug logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    if not args.input.exists():
        logger.error(f"Input file not found: {args.input}")
        sys.exit(1)

    # Determine output path if not provided
    if not args.output:
        args.output = args.input.with_suffix(".csv")

    convert(args.input, args.output, missing_as_zero=args.missing_as_zero)

if __name__ == "__main__":
    main()