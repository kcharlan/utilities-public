from taxkit.page import build_payload
from tests.test_engine_parity import FIXTURES, ORACLE, engine_page


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


def test_historical_rounded_arrays_agree_with_frozen_fixture():
    # These legacy arrays were rounded at capture. They are historical evidence,
    # never the tolerance or rounding policy for browser annual calculations.
    for year in EXPECTED_FEDERAL:
        for status in EXPECTED_FEDERAL[year]:
            cases = [next(c for c in ORACLE['compute_cases'] if c['root']=='bundled'
                and c['input']['year']==year and c['input']['filing_status']==status
                and c['input']['monthly_earned']==0 and c['input']['monthly_unearned']==income
                and c['input']['states']==[{'code':'GA','allocation_pct':100}]) for income in MONTHLY_INCOMES]
            assert [round(c['expected']['federal_annual'],10) for c in cases] == EXPECTED_FEDERAL[year][status]
            assert [round(c['expected']['states'][0]['annual'],10) for c in cases] == EXPECTED_GA[year][status]


def test_single_ga_qif_golden_baseline(engine_page):
    rules = build_payload(FIXTURES / 'bundled/rules', rules_source='custom')
    assert engine_page.evaluate('r => Tax2Engine.buildQif({federal_cents:234567,states:[{code:"GA",state_cents:51234}]},{txDate:"2026-09-15"},{},r)', rules) == EXPECTED_QIF


def test_live_annual_golden_baselines_match_exact_frozen_values(engine_page):
    rules = build_payload(FIXTURES / 'bundled/rules', rules_source='custom')
    cases = [next(c for c in ORACLE['compute_cases'] if c['root'] == 'bundled'
                  and c['input']['year'] == year and c['input']['filing_status'] == status
                  and c['input']['monthly_earned'] == 0
                  and c['input']['monthly_unearned'] == income
                  and c['input']['states'] == [{'code': 'GA', 'allocation_pct': 100}])
             for year in (2025, 2026) for status in ('single', 'married_joint')
             for income in MONTHLY_INCOMES]
    results = engine_page.evaluate('''({cases, rules}) => cases.map(({input:i}) => {
        const annual = Tax2Engine.computeAnnual(i.monthly_earned, i.monthly_unearned,
            i.filing_status, i.year, i.states, rules);
        return {federal:annual.federal_annual, ga:annual.states[0].annual};
    })''', {'cases': cases, 'rules': rules})
    assert len(results) == 24
    for case, actual in zip(cases, results):
        assert actual == {'federal': case['expected']['federal_annual'],
                          'ga': case['expected']['states'][0]['annual']}, case['id']
