import pytest

from taxkit.models import FilingStatus, IncomeClass
from taxkit.rules_loader import load_rules
from taxkit.utils import get_available_years


def test_v1_ga_2025_normalizes_to_default_component():
    rules = load_rules("rules/states/GA/2025.yaml")

    assert len(rules.components) == 1
    component = rules.components[0]
    assert component.name == "default"
    assert component.enabled is True
    assert component.applies_to == [IncomeClass.earned, IncomeClass.unearned]
    assert component.standard_deduction[FilingStatus.single] == 15750
    assert component.brackets[FilingStatus.single][0].rate == 0.0519


def test_v1_federal_2026_normalizes_to_default_component():
    rules = load_rules("rules/federal/2026.yaml")

    assert len(rules.components) == 1
    component = rules.components[0]
    assert component.name == "default"
    assert component.enabled is True
    assert component.applies_to == [IncomeClass.earned, IncomeClass.unearned]
    assert component.standard_deduction[FilingStatus.married_joint] == 32200
    assert len(component.brackets[FilingStatus.single]) == 7


def test_v2_components_parse(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        """
year: 2026
jurisdiction: TS
display_name: Test State
filing_statuses: [single, married_joint]
components:
  - name: main
    standard_deduction: { single: 100, married_joint: 200 }
    brackets:
      single: [ { up_to: null, rate: 0.03 } ]
      married_joint: [ { up_to: null, rate: 0.03 } ]
  - name: earned_extra
    label: Earned Extra
    enabled: false
    applies_to: [earned]
    standard_deduction: { single: 0, married_joint: 0 }
    brackets:
      single: [ { up_to: null, rate: 0.01 } ]
      married_joint: [ { up_to: null, rate: 0.01 } ]
credits: []
qif:
  state_expense: Tax:State
  state_transfer: "[TS Taxes]"
""",
        encoding="utf-8",
    )

    rules = load_rules(str(path))

    assert rules.display_name == "Test State"
    assert rules.qif.state_transfer == "[TS Taxes]"
    assert len(rules.components) == 2
    assert rules.components[0].applies_to == [IncomeClass.earned, IncomeClass.unearned]
    assert rules.components[1].enabled is False
    assert rules.components[1].applies_to == [IncomeClass.earned]


def test_ambiguous_v1_and_v2_file_raises(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        """
year: 2026
jurisdiction: TS
filing_statuses: [single]
standard_deduction: { single: 0 }
brackets:
  single: [ { up_to: null, rate: 0.03 } ]
components:
  - name: main
    standard_deduction: { single: 0 }
    brackets:
      single: [ { up_to: null, rate: 0.03 } ]
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Ambiguous rules file"):
        load_rules(str(path))


def test_pa_years_after_rules_added():
    assert get_available_years("rules/states/PA") == [2026]


def test_pa_2026_components_and_ga_qif_defaults():
    pa_rules = load_rules("rules/states/PA/2026.yaml")
    ga_rules = load_rules("rules/states/GA/2026.yaml")

    assert pa_rules.display_name == "Pennsylvania"
    assert len(pa_rules.components) == 2
    assert sum(1 for component in pa_rules.components if component.enabled) == 1
    assert pa_rules.components[1].label == "Local EIT (West York Boro / West York Area SD)"
    assert pa_rules.components[1].applies_to == [IncomeClass.earned]
    assert ga_rules.qif.state_transfer == "[GA State Income Taxes]"
