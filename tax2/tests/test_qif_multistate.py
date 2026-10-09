from taxkit.page import build_payload
from tests.test_engine_parity import FIXTURES, engine_page


def test_multistate_qif_has_one_federal_pair_and_ordered_states(engine_page):
    rules = build_payload(FIXTURES / 'bundled/rules', rules_source='custom')
    qif = engine_page.evaluate('''r => Tax2Engine.buildQif(
        {federal_cents:10000,states:[{code:'GA',state_cents:2000},{code:'PA',state_cents:3000}]},
        {txDate:'2026-09-15'},
        {GA:{expense:'Tax:GA',transfer:'[GA Taxes]'},PA:{expense:'Tax:PA',transfer:'[PA Taxes]'}},r)''',rules)

    lines = qif.splitlines()
    assert lines[0] == "!Type:Bank"
    assert len(lines[1:]) == 36
    assert lines.count("^") == 6
    assert lines.count("MEstimated Federal taxes - 09/15/2026") == 2
    assert lines.index("LTax:Federal Income Tax Estimated Paid") < lines.index("L[GA Taxes]")
    assert lines.index("L[GA Taxes]") < lines.index("L[PA Taxes]")
    assert "T-20.00" in lines
    assert "T20.00" in lines
    assert "T-30.00" in lines
    assert "T30.00" in lines
    assert "MEstimated GA State taxes - 09/15/2026" in lines
    assert "MEstimated PA State taxes - 09/15/2026" in lines
