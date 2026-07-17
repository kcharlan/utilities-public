from taxkit.engine import compute_tax
from taxkit.models import (
    Bracket,
    FilingStatus,
    IncomeClass,
    TaxComponent,
    TaxInput,
    TaxRules,
)


def _flat_component(
    name: str,
    rate: float,
    applies_to: list[IncomeClass] | None = None,
    enabled: bool = True,
) -> TaxComponent:
    return TaxComponent(
        name=name,
        enabled=enabled,
        applies_to=applies_to or [IncomeClass.earned, IncomeClass.unearned],
        standard_deduction={
            FilingStatus.single: 0,
            FilingStatus.married_joint: 0,
        },
        brackets={
            FilingStatus.single: [Bracket(up_to=None, rate=rate)],
            FilingStatus.married_joint: [Bracket(up_to=None, rate=rate)],
        },
    )


def _rules(*components: TaxComponent) -> TaxRules:
    return TaxRules(
        year=2026,
        jurisdiction="TS",
        filing_statuses=[FilingStatus.single, FilingStatus.married_joint],
        components=list(components),
    )


def test_earned_only_component_ignores_unearned_income():
    rules = _rules(_flat_component("earned_only", 0.01, [IncomeClass.earned]))

    assert (
        compute_tax(
            TaxInput(
                earned_income=0,
                unearned_income=100000,
                filing_status=FilingStatus.single,
            ),
            rules,
        )
        == 0
    )


def test_two_component_sum_uses_income_classes():
    rules = _rules(
        _flat_component("all_income", 0.03),
        _flat_component("earned_extra", 0.01, [IncomeClass.earned]),
    )

    tax = compute_tax(
        TaxInput(
            earned_income=10000,
            unearned_income=5000,
            filing_status=FilingStatus.single,
        ),
        rules,
    )

    assert tax == 550


def test_disabled_component_contributes_nothing():
    rules = _rules(
        _flat_component("all_income", 0.03),
        _flat_component("disabled", 0.99, enabled=False),
    )

    tax = compute_tax(
        TaxInput(
            earned_income=0,
            unearned_income=10000,
            filing_status=FilingStatus.single,
        ),
        rules,
    )

    assert tax == 300
