from __future__ import annotations
from .models import TaxInput, TaxRules, FilingStatus, Bracket
from typing import List

def apply_brackets(taxable: float, brackets: List[Bracket]) -> float:
    tax = 0.0
    prev_cap = 0.0
    for b in brackets:
        cap = b.up_to if b.up_to is not None else taxable
        if taxable > prev_cap:
            slice_amt = min(taxable, cap) - prev_cap
            if slice_amt > 0:
                tax += slice_amt * b.rate
            prev_cap = cap
        if b.up_to is None or taxable <= cap:
            break
    return max(tax, 0.0)

def compute_tax(tax_in: TaxInput, rules: TaxRules) -> float:
    base = 0.0
    for component in rules.components:
        if not component.enabled:
            continue
        applicable = 0.0
        for income_class in component.applies_to:
            applicable += getattr(tax_in, f"{income_class.value}_income")
        std_ded = component.standard_deduction[tax_in.filing_status]
        taxable = max(0.0, applicable - std_ded)
        base += apply_brackets(taxable, component.brackets[tax_in.filing_status])

    # credits (simple additive model with optional phaseouts)
    credit_total = 0.0
    for c in rules.credits:
        effective = 0.0
        if c.amount is not None:
            effective = max(effective, c.amount)
        if c.amount_per_child is not None:
            # Extend here with actual number of children if needed
            effective = max(effective, c.amount_per_child)  # placeholder for 1 child

        if c.phaseout:
            over = max(0.0, tax_in.annual_income - c.phaseout.start_income)
            reduction = over * c.phaseout.rate_per_dollar
            effective = max(0.0, effective - reduction)

        if c.refundable_cap is not None:
            effective = min(effective, c.refundable_cap)

        credit_total += effective

    return max(0.0, base - credit_total)
