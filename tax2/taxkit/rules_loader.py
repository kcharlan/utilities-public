from __future__ import annotations
import yaml
import json
from .models import (
    Bracket,
    Credit,
    FilingStatus,
    IncomeClass,
    QIFDefaults,
    TaxComponent,
    TaxRules,
)

def load_rules(path: str) -> TaxRules:
    """Normalize legacy rules and reject unsupported page structures by filename."""
    try:
        rules = _load_rules(path)
        _validate_rules(rules)
        json.dumps(rules.model_dump(mode="json"), allow_nan=False)
        return rules
    except Exception as exc:
        raise ValueError(f"Invalid rules file {path}: {exc}") from exc


def _validate_rules(rules: TaxRules) -> None:
    required = (FilingStatus.single, FilingStatus.married_joint)
    if any(status not in rules.filing_statuses for status in required):
        raise ValueError("Both single and married_joint filing statuses are required")
    if not rules.components:
        raise ValueError("Components must be nonempty")
    for component in rules.components:
        basis = component.applies_to
        if not basis or len(set(basis)) != len(basis):
            raise ValueError("Income basis must contain unique earned/unearned classes")
        for status in required:
            if status not in component.standard_deduction or status not in component.brackets:
                raise ValueError(f"Missing deduction or brackets for {status.value}")
            brackets = component.brackets[status]
            if not brackets:
                raise ValueError(f"Brackets must be nonempty for {status.value}")
            previous = None
            for index, bracket in enumerate(brackets):
                if bracket.rate < 0:
                    raise ValueError("Bracket rates must be nonnegative")
                cap = bracket.up_to
                if cap is None:
                    if index != len(brackets) - 1:
                        raise ValueError("Null bracket threshold must be last")
                else:
                    if cap < 0 or (previous is not None and cap <= previous):
                        raise ValueError("Bracket thresholds must be nonnegative and strictly ascending")
                    previous = cap
    for credit in rules.credits:
        if credit.refundable_cap is not None and credit.refundable_cap < 0:
            raise ValueError("Refundable caps must be nonnegative")
        if credit.phaseout is not None and credit.phaseout.rate_per_dollar < 0:
            raise ValueError("Phaseout rates must be nonnegative")


def _load_rules(path: str) -> TaxRules:
    with open(path, 'r') as f:
        data = yaml.safe_load(f)

    # Convert keys for enums
    fs_list = [FilingStatus(x) for x in data['filing_statuses']]
    credits = [Credit(**c) for c in data.get('credits', [])]
    has_components = 'components' in data
    has_v1_brackets = 'standard_deduction' in data or 'brackets' in data

    if has_components and has_v1_brackets:
        raise ValueError(
            f"Ambiguous rules file {path}: use either components or top-level "
            "standard_deduction/brackets, not both"
        )

    components = _load_components(data, path)
    qif = QIFDefaults(**data['qif']) if data.get('qif') else None

    return TaxRules(
        year=int(data['year']),
        jurisdiction=str(data['jurisdiction']),
        display_name=data.get('display_name'),
        filing_statuses=fs_list,
        components=components,
        credits=credits,
        qif=qif,
    )


def _load_components(data: dict, path: str) -> list[TaxComponent]:
    if 'components' not in data:
        if 'standard_deduction' not in data or 'brackets' not in data:
            raise ValueError(
                f"Rules file {path} must define either components or "
                "top-level standard_deduction/brackets"
            )
        # Compatibility boundary: v1 rules are normalized here so the engine
        # can operate on one component-only rules shape.
        data = {
            **data,
            'components': [
                {
                    'name': 'default',
                    'enabled': True,
                    'applies_to': [IncomeClass.earned, IncomeClass.unearned],
                    'standard_deduction': data['standard_deduction'],
                    'brackets': data['brackets'],
                }
            ],
        }

    components = []
    for raw in data['components']:
        standard_deduction = {
            FilingStatus(k): float(v)
            for k, v in raw['standard_deduction'].items()
        }
        brackets = {
            FilingStatus(k): [Bracket(**b) for b in v]
            for k, v in raw['brackets'].items()
        }
        raw_basis = raw.get('applies_to', [IncomeClass.earned, IncomeClass.unearned])
        if not isinstance(raw_basis, list):
            raise ValueError("Income basis must be a list")
        applies_to = [
            item if isinstance(item, IncomeClass) else IncomeClass(item)
            for item in raw_basis
        ]
        components.append(
            TaxComponent(
                name=str(raw['name']),
                label=raw.get('label'),
                enabled=bool(raw.get('enabled', True)),
                applies_to=applies_to,
                standard_deduction=standard_deduction,
                brackets=brackets,
            )
        )
    return components
