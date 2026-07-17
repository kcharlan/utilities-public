from __future__ import annotations
import os
import shutil

import pandas as pd
import typer

from taxkit.config import load_config
from taxkit.tablegen import generate_table
from taxkit.utils import get_available_years, resolve_year, get_rule_path

app = typer.Typer(add_completion=False)

@app.command()
def tablegen(rules: str = None, filing_status: str = "single", year: int = None,
             inc_min: int = 0, inc_max: int = 500000, step: int = 50,
             period: str = "monthly", out: str = "tables/out.parquet"):
    """
    Generate tax tables. 
    If '--rules' is a specific file, it is used.
    If '--rules' is a directory or None, we attempt to find the best rule file based on --year.
    """
    if rules is None:
        # Default to federal rules dir relative to here
        rules = os.path.join(os.path.dirname(__file__), "rules", "federal")
    
    if os.path.isdir(rules):
        # Resolve year
        avail = get_available_years(rules)
        target = year if year else pd.Timestamp.now().year
        
        resolved_year, is_fallback = resolve_year(target, avail)
        if is_fallback and resolved_year != target:
            typer.echo(f"Warning: Rules for {target} not found. Using {resolved_year}.", err=True)
            
        rules = get_rule_path(rules, resolved_year)
        typer.echo(f"Using rules: {rules}")

    df = generate_table(rules, filing_status, inc_min, inc_max, step, period)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if out.lower().endswith(".csv"):
        df.to_csv(out, index=False)
    else:
        df.to_parquet(out, index=False)
    typer.echo(f"Saved {len(df)} rows to {out}")

@app.command("generate-combined")
def generate_combined(
    year: int = None,
    states: str = typer.Option(None, "--states", help="Comma-separated state codes."),
    state: str = typer.Option(None, "--state", help="Deprecated alias for --states."),
    out_dir: str = "tables",
    filing_status: str = "single",
    inc_max: int = 500000,
    step: int = 50,
):
    """
    Generate federal and state tables for a given year (or current year) and merge them.
    This replaces the old generate_tables.sh and merge_tables.py scripts.
    """
    cfg = load_config()
    if state:
        typer.echo("Warning: --state is deprecated; use --states instead.", err=True)
        requested_states = [state.upper()]
    elif states:
        requested_states = _parse_states(states)
    else:
        requested_states = _parse_states(",".join(cfg["default_states"]))

    fed_rules_dir = os.path.join(os.path.dirname(__file__), "rules", "federal")
    avail = get_available_years(fed_rules_dir)
    target = year if year else pd.Timestamp.now().year
    
    resolved_year, is_fallback = resolve_year(target, avail)
    if is_fallback and resolved_year != target:
        typer.echo(f"Warning: Rules for {target} not found. Using {resolved_year}.", err=True)
    
    typer.echo(f"Generating tables for Tax Year: {resolved_year}")

    fed_path = get_rule_path(fed_rules_dir, resolved_year)

    if not os.path.exists(fed_path):
        typer.echo(f"Error: Federal rules not found at {fed_path}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Processing Federal: {os.path.basename(fed_path)}")
    df_fed = generate_table(fed_path, filing_status, 0, inc_max, step, "monthly")

    os.makedirs(out_dir, exist_ok=True)

    fed_out = os.path.join(out_dir, f"federal_{resolved_year}.parquet")
    df_fed.to_parquet(fed_out, index=False)

    rf = df_fed.rename(columns={"MonthlyTax": "FederalMonthlyTax"})
    rf = rf[["MonthlyIncome", "FederalMonthlyTax"]]

    outputs = [fed_out]
    combined_by_state = {}
    failed = False
    rules_root = os.path.join(os.path.dirname(__file__), "rules", "states")
    for state_code in requested_states:
        state_rules_dir = os.path.join(rules_root, state_code)
        available_state_years = get_available_years(state_rules_dir)
        if resolved_year not in available_state_years:
            typer.echo(
                f"Error: State {state_code} has no rules for {resolved_year}. "
                f"Available years: {available_state_years or 'none'}",
                err=True,
            )
            failed = True
            continue

        state_path = get_rule_path(state_rules_dir, resolved_year)
        typer.echo(f"Processing State ({state_code}): {os.path.basename(state_path)}")
        df_state = generate_table(state_path, filing_status, 0, inc_max, step, "monthly")

        state_out = os.path.join(out_dir, f"{state_code.lower()}_{resolved_year}.parquet")
        df_state.to_parquet(state_out, index=False)
        outputs.append(state_out)

        rs = df_state.rename(columns={"MonthlyTax": "StateMonthlyTax"})
        rs = rs[["MonthlyIncome", "StateMonthlyTax"]]
        combined = pd.merge(rf, rs, on="MonthlyIncome", how="outer").sort_values("MonthlyIncome")
        combined_out = os.path.join(out_dir, f"combined_{resolved_year}_{state_code}.csv")
        combined.to_csv(combined_out, index=False)
        combined_by_state[state_code] = combined_out
        outputs.append(combined_out)

    alias_state = cfg["legacy_combined_alias"].upper()
    if alias_state in combined_by_state:
        legacy_out = os.path.join(out_dir, f"combined_{resolved_year}.csv")
        shutil.copyfile(combined_by_state[alias_state], legacy_out)
        outputs.append(legacy_out)
    elif combined_by_state:
        typer.echo(
            f"Warning: legacy alias state {alias_state} was not generated; "
            "combined alias was not written.",
            err=True,
        )

    if failed:
        raise typer.Exit(code=1)

    typer.echo(f"Success! Generated tables for {', '.join(combined_by_state)}.")
    typer.echo("Outputs:\n  - " + "\n  - ".join(outputs))


def _parse_states(value: str) -> list[str]:
    parsed = [item.strip().upper() for item in value.split(",") if item.strip()]
    return list(dict.fromkeys(parsed))


if __name__ == "__main__":
    app()
