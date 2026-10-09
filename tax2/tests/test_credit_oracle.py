"""Retain the legacy one-child placeholder contract during the engine port."""

from taxkit.page import build_payload
from tests.test_engine_parity import FIXTURES, engine_page


def test_amount_per_child_uses_larger_credit_then_phaseout_and_cap(engine_page):
    rules = build_payload(FIXTURES / 'synthetic/rules', rules_source='custom')['states'][1]['rules']['2026']
    rules['credits'] = [dict(name='synthetic_child_placeholder', amount=100, amount_per_child=1000,
        refundable_cap=500, phaseout=dict(start_income=20000, rate_per_dollar=0.05))]
    for status in ('single', 'married_joint'):
        # The placeholder represents one child; credit amount is max, not sum.
        for income, expected in ((10000, 500), (30000, 2500), (35000, 3250), (40000, 4000)):
            assert engine_page.evaluate('({income,status,rules}) => Tax2Engine.computeTax({earned_income:0,unearned_income:income},rules,status)',
                dict(income=income, status=status, rules=rules)) == expected
