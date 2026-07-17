from datetime import date

from taxkit.qif import QIFConfig, StateQIFItem, build_qif_entries


def test_multistate_qif_has_one_federal_pair_and_ordered_states():
    qif = build_qif_entries(
        date(2026, 9, 15),
        100,
        [
            StateQIFItem(
                code="GA",
                amount=20,
                expense="Tax:GA",
                transfer="[GA Taxes]",
            ),
            StateQIFItem(
                code="PA",
                amount=30,
                expense="Tax:PA",
                transfer="[PA Taxes]",
            ),
        ],
        QIFConfig(),
    )

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
