"""Retained API scenarios and independent live bundled-rule arithmetic."""
from pathlib import Path

import pytest

from taxkit.page import build_payload
from tests.test_engine_parity import engine_page

PROJECT = Path(__file__).resolve().parents[1]


def test_state_inventory_retains_names_years_and_qif(monkeypatch, tmp_path):
    monkeypatch.setenv('TAX2_HOME', str(tmp_path / 'runtime'))
    assert not tmp_path.resolve().is_relative_to(PROJECT.parent)
    states = {state['code']: state for state in build_payload(PROJECT / 'rules', rules_source='bundled')['states']}
    assert states['GA']['display_name'] == 'Georgia'
    assert states['GA']['years'] == [2025, 2026]
    assert states['GA']['qif']['state_transfer'] == '[GA State Income Taxes]'
    assert states['PA']['display_name'] == 'Pennsylvania'
    assert states['PA']['years'] == [2026]
    assert states['PA']['qif']['state_transfer'] == '[PA State Income Taxes]'


@pytest.mark.parametrize('selections, amounts, total', [
    ([{'code':'GA','allocation_pct':100}], [20360], 62194),
    ([{'code':'GA','allocation_pct':100},{'code':'PA','allocation_pct':100}], [20360,15350], 77544),
    ([{'code':'GA','allocation_pct':100},{'code':'PA','allocation_pct':50}], [20360,7675], 69869)])
def test_retained_api_calculation_scenarios(engine_page, selections, amounts, total):
    rules = build_payload(PROJECT / 'rules', rules_source='bundled')
    result = engine_page.evaluate('({rules,selections}) => Tax2Engine.computeMonthly({earnedCents:0,unearnedCents:500000,filingStatus:"single",year:2026,states:selections},rules)',
                                  dict(rules=rules, selections=selections))
    assert result['federal_cents'] == 41834
    assert [state['state_cents'] for state in result['states']] == amounts
    assert result['total_monthly_cents'] == total


@pytest.mark.parametrize('year,status,monthly,annual', [
    (2026,'single',1000,0), (2026,'single',2375,1240), (2026,'single',5000,5020),
    (2026,'married_joint',1000,0), (2026,'married_joint',4750,2480), (2026,'married_joint',5000,2840),
    (2025,'single',1000,0), (2025,'single',5000,5090),
    (2025,'married_joint',1000,0), (2025,'married_joint',5000,2980)])
def test_live_bundled_federal_hand_calculations(engine_page, year, status, monthly, annual):
    # 2026: 60,000 - 16,100 = 43,900; 1,240 + 31,500*.12 = 5,020.
    # Joint: 60,000 - 32,200 = 27,800; 2,480 + 3,000*.12 = 2,840.
    # 2025: single taxable 44,250 => 1,100 + 33,250*.12 = 5,090;
    # joint taxable 28,500 => 2,200 + 6,500*.12 = 2,980.
    rules = build_payload(PROJECT / 'rules', rules_source='bundled')
    result = engine_page.evaluate('({rules,year,status,monthly}) => Tax2Engine.computeAnnual(0,monthly,status,year,[{code:"GA",allocation_pct:100}],rules)',
                                  dict(rules=rules, year=year, status=status, monthly=monthly))
    assert result['federal_annual'] == annual
