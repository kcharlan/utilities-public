from taxkit.page import build_payload
from tests.test_engine_parity import FIXTURES, engine_page

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


def test_single_ga_qif_golden_baseline(engine_page):
    rules = build_payload(FIXTURES / 'bundled/rules', rules_source='custom')
    assert engine_page.evaluate('r => Tax2Engine.buildQif({federal_cents:234567,states:[{code:"GA",state_cents:51234}]},{txDate:"2026-09-15"},{},r)', rules) == EXPECTED_QIF
