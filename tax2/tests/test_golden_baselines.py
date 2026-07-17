from datetime import date
from pathlib import Path

from taxkit.engine import compute_tax
from taxkit.models import FilingStatus, TaxInput
from taxkit.qif import QIFConfig, build_qif_entries
from taxkit.rules_loader import load_rules


MONTHLY_INCOMES = [0, 1000, 5000, 8333.33, 20000, 41666.67]

EXPECTED_FEDERAL = {
    2025: {
        "single": [0.0, 0.0, 5090.0, 13842.4912, 50592.0, 141382.014],
        "married_joint": [0.0, 0.0, 2980.0, 7779.9952, 36840.0, 107764.014],
    },
    2026: {
        "single": [0.0, 0.0, 5020.0, 13169.9912, 48104.0, 138134.264],
        "married_joint": [0.0, 0.0, 2840.0, 7639.9952, 35140.0, 102608.0128],
    },
}

EXPECTED_GA = {
    2025: {
        "single": [0.0, 0.0, 2296.575, 4372.572924, 11638.575, 25132.577076],
        "married_joint": [0.0, 0.0, 1479.15, 3555.147924, 10821.15, 24315.152076],
    },
    2026: {
        "single": [0.0, 0.0, 2443.2, 4479.197964, 11605.2, 24839.202036],
        "married_joint": [0.0, 0.0, 1832.4, 3868.397964, 10994.4, 24228.402036],
    },
}

EXPECTED_QIF = """!Type:Bank
D09/15/26
T-2345.67
PEstimated Taxes Withholding
MEstimated Federal taxes - 09/15/2026
LTax:Federal Income Tax Estimated Paid
^
D09/15/26
T2345.67
PEstimated Taxes Withholding
MEstimated Federal taxes - 09/15/2026
L[Federal Income Taxes]
^
D09/15/26
T-512.34
PEstimated Taxes Withholding
MEstimated State taxes - 09/15/2026
LTax:State Income Tax Estimated Paid
^
D09/15/26
T512.34
PEstimated Taxes Withholding
MEstimated State taxes - 09/15/2026
L[GA State Income Taxes]
^"""


def _tax_input(annual_income: float, filing_status: FilingStatus) -> TaxInput:
    if "annual_income" in TaxInput.model_fields:
        return TaxInput(annual_income=annual_income, filing_status=filing_status)
    return TaxInput(unearned_income=annual_income, filing_status=filing_status)


def _actual_values(rules_path: Path, status: str) -> list[float]:
    rules = load_rules(str(rules_path))
    filing_status = FilingStatus(status)
    return [
        round(
            compute_tax(_tax_input(monthly_income * 12, filing_status), rules),
            10,
        )
        for monthly_income in MONTHLY_INCOMES
    ]


def test_federal_golden_baselines():
    base = Path(__file__).resolve().parents[1] / "rules" / "federal"
    for year, by_status in EXPECTED_FEDERAL.items():
        for status, expected in by_status.items():
            assert _actual_values(base / f"{year}.yaml", status) == expected


def test_ga_golden_baselines():
    base = Path(__file__).resolve().parents[1] / "rules" / "states" / "GA"
    for year, by_status in EXPECTED_GA.items():
        for status, expected in by_status.items():
            assert _actual_values(base / f"{year}.yaml", status) == expected


def test_single_ga_qif_golden_baseline():
    assert (
        build_qif_entries(date(2026, 9, 15), 2345.67, 512.34, QIFConfig())
        == EXPECTED_QIF
    )
