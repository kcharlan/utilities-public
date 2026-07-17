from __future__ import annotations
import pandas as pd
import math
from .engine import compute_tax
from .rules_loader import load_rules
from .models import TaxInput, FilingStatus

def generate_table(rules_path: str, filing_status: str = "single",
                   inc_min: int = 0, inc_max: int = 500000, step: int = 50,
                   period: str = "monthly") -> pd.DataFrame:
    if step <= 0:
        step = 1  # Fallback to avoid ZeroDivisionError in range()
        
    rules = load_rules(rules_path)
    fs = FilingStatus(filing_status)
    rows = []
    for mi in range(inc_min, inc_max + 1, step):
        annual = mi * 12 if period == "monthly" else mi
        tin = TaxInput(unearned_income=annual, filing_status=fs)
        tax_annual = compute_tax(tin, rules)
        
        # Safety check for division by zero or non-finite results
        tax_monthly_raw = tax_annual / 12.0
        tax_monthly = round(tax_monthly_raw, 2) if math.isfinite(tax_monthly_raw) else 0.0
        
        rows.append({"MonthlyIncome": mi, "MonthlyTax": tax_monthly})
    return pd.DataFrame(rows)
