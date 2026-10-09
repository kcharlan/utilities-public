import pytest
from pathlib import Path
import yaml

from taxkit.models import FilingStatus, IncomeClass
from taxkit.rules_loader import load_rules
from taxkit.utils import discover_year_files


def test_discovery_single_implementation():
    import inspect
    import taxkit.utils as utils
    import taxkit.page as page

    assert callable(getattr(utils, "discover_year_files", None))
    assert not hasattr(utils, "get_available_years")
    assert not hasattr(utils, "get_rule_path")
    source = inspect.getsource(page)
    assert ".suffix in (" not in source
    assert "stem.isdigit()" not in source


def test_discovery_groups_all_entry_types_in_filename_order(tmp_path):
    import os
    names = ["2026.yml", "02026.yaml", "2026.yaml", "02026.yml", "2027.yml"]
    for name in names[:2]:
        (tmp_path / name).touch()
    (tmp_path / names[2]).mkdir()
    (tmp_path / names[3]).symlink_to("missing.yaml")
    os.mkfifo(tmp_path / names[4])
    for name in ("٢٠٢٦.yaml", "2026.yaml.bak", "2026.yaml\n", "notes.yaml"):
        (tmp_path / name).touch()
    assert discover_year_files(tmp_path) == {
        2026: [tmp_path / name for name in sorted(names[:4])],
        2027: [tmp_path / "2027.yml"],
    }
    assert discover_year_files(tmp_path / "missing") == {}
    # Alone in its own directory, the uppercase entry really exists under that
    # exact name even on a case-insensitive volume (where, beside 2026.yaml, it
    # would only alias the lowercase entry).
    uppercase = tmp_path / "uppercase-only"
    uppercase.mkdir()
    (uppercase / "2026.YAML").touch()
    assert os.listdir(uppercase) == ["2026.YAML"]
    assert discover_year_files(uppercase) == {}


@pytest.fixture(autouse=True)
def private_scratch(tmp_path):
    assert not tmp_path.resolve().is_relative_to(Path(__file__).resolve().parents[2])
    tmp_path.chmod(0o700)


def synthetic_rules(v2=True):
    component = {"name": "synthetic", "standard_deduction": {"single": -10, "married_joint": 0},
                 "brackets": {status: [{"up_to": 0, "rate": 0}, {"up_to": None, "rate": .1}]
                              for status in ("single", "married_joint")}}
    data = {"year": 2026, "jurisdiction": "XF", "filing_statuses": ["single", "married_joint"]}
    if v2:
        data["components"] = [component]
    else:
        data.update({key: component[key] for key in ("standard_deduction", "brackets")})
    return data


def write_synthetic(path, data):
    assert not path.resolve().is_relative_to(Path(__file__).resolve().parents[2])
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.mark.parametrize("v2", [False, True])
@pytest.mark.parametrize("failure", ["status", "deduction", "brackets", "empty_brackets", "negative_rate", "duplicate", "descending", "null_first", "negative_threshold", "nonfinite", "phaseout", "negative_cap"])
@pytest.mark.parametrize("disabled", [False, True])
def test_structural_validation_names_file(tmp_path, v2, failure, disabled):
    data = synthetic_rules(v2)
    component = data["components"][0] if v2 else data
    component["enabled"] = not disabled
    if failure == "status": data["filing_statuses"] = ["single"]
    elif failure == "deduction": del component["standard_deduction"]["married_joint"]
    elif failure == "brackets": del component["brackets"]["married_joint"]
    elif failure == "empty_brackets": component["brackets"]["married_joint"] = []
    elif failure == "negative_rate": component["brackets"]["single"][0]["rate"] = -.1
    elif failure in ("duplicate", "descending", "null_first"):
        caps = {"duplicate": [10, 10], "descending": [20, 10], "null_first": [None, 10]}[failure]
        component["brackets"]["single"] = [{"up_to": cap, "rate": .1} for cap in caps]
    elif failure == "negative_threshold": component["brackets"]["single"][0]["up_to"] = -100
    elif failure == "nonfinite": component["standard_deduction"]["single"] = float("inf")
    elif failure == "phaseout": data["credits"] = [{"name": "synthetic", "phaseout": {"start_income": 0, "rate_per_dollar": -.1}}]
    elif failure == "negative_cap": data["credits"] = [{"name": "synthetic", "refundable_cap": -120}]
    path = write_synthetic(tmp_path / "invalid.yaml", data)
    with pytest.raises(ValueError, match="invalid.yaml"):
        load_rules(str(path))


@pytest.mark.parametrize("basis", [[], ["earned", "earned"], ["unearned", "unearned"], ["earned", "unearned", "earned"], {"earned": 1}, "earned"])
@pytest.mark.parametrize("disabled", [False, True])
def test_invalid_basis(tmp_path, basis, disabled):
    data = synthetic_rules()
    data["components"][0].update(applies_to=basis, enabled=not disabled)
    with pytest.raises(ValueError, match="basis.yaml"):
        load_rules(str(write_synthetic(tmp_path / "basis.yaml", data)))


@pytest.mark.parametrize("basis", [None, ["earned"], ["unearned"], ["earned", "unearned"], ["unearned", "earned"]])
@pytest.mark.parametrize("cap", ["absent", None, 0, 100])
@pytest.mark.parametrize("disabled", [False, True])
@pytest.mark.parametrize("v2", [False, True])
def test_valid_basis_caps_zero_rate_and_disabled(tmp_path, basis, cap, disabled, v2):
    data = synthetic_rules(v2)
    component = data["components"][0] if v2 else data
    component["enabled"] = not disabled
    component["brackets"] = {status: [{"up_to": None, "rate": 0}] for status in data["filing_statuses"]}
    if basis is not None: component["applies_to"] = basis
    data["credits"] = [{"name": "synthetic"}]
    if cap != "absent": data["credits"][0]["refundable_cap"] = cap
    rules = load_rules(str(write_synthetic(tmp_path / "valid.yaml", data)))
    expected = basis if v2 and basis is not None else ["earned", "unearned"]
    assert rules.components[0].applies_to == expected


@pytest.mark.parametrize("text", ["bad: [", "null", "components: []", "year: nope"])
def test_parse_and_schema_errors_name_file(tmp_path, text):
    path = tmp_path / "broken.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match="broken.yaml"):
        load_rules(str(path))


def test_empty_components_fail(tmp_path):
    data = synthetic_rules()
    data["components"] = []
    with pytest.raises(ValueError, match="empty.yaml"):
        load_rules(str(write_synthetic(tmp_path / "empty.yaml", data)))


def test_bundled_normalization_matches_frozen_rules():
    for path in Path("rules").rglob("*.yaml"):
        frozen = Path("tests/fixtures/parity/bundled") / path
        assert load_rules(str(path)).model_dump(mode="json") == load_rules(str(frozen)).model_dump(mode="json")


@pytest.mark.parametrize("status", ["single", "married_joint"])
@pytest.mark.parametrize("field", ["standard_deduction", "brackets"])
def test_either_required_key_cannot_be_defaulted(tmp_path, status, field):
    data = synthetic_rules()
    del data["components"][0][field][status]
    with pytest.raises(ValueError, match="missing.yaml"):
        load_rules(str(write_synthetic(tmp_path / "missing.yaml", data)))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", ["up_to", "rate", "amount", "amount_per_child", "refundable_cap", "start_income", "rate_per_dollar"])
def test_all_numeric_model_fields_finite(tmp_path, value, field):
    data = synthetic_rules()
    credit = {"name": "synthetic", "phaseout": {"start_income": 0, "rate_per_dollar": 0}}
    data["credits"] = [credit]
    if field in ("up_to", "rate"): data["components"][0]["brackets"]["single"][0][field] = value
    elif field in ("start_income", "rate_per_dollar"): credit["phaseout"][field] = value
    else: credit[field] = value
    with pytest.raises(ValueError, match="nonfinite.yaml"):
        load_rules(str(write_synthetic(tmp_path / "nonfinite.yaml", data)))


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
    assert sorted(discover_year_files(Path("rules/states/PA"))) == [2026]


def test_pa_2026_components_and_ga_qif_defaults():
    pa_rules = load_rules("rules/states/PA/2026.yaml")
    ga_rules = load_rules("rules/states/GA/2026.yaml")

    assert pa_rules.display_name == "Pennsylvania"
    assert len(pa_rules.components) == 2
    assert sum(1 for component in pa_rules.components if component.enabled) == 1
    assert pa_rules.components[1].label == "Local EIT (resident municipality and school district)"
    assert pa_rules.components[1].applies_to == [IncomeClass.earned]
    assert ga_rules.qif.state_transfer == "[GA State Income Taxes]"
