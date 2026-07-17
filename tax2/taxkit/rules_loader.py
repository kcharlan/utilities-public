from __future__ import annotations
import yaml
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
        applies_to = [
            item if isinstance(item, IncomeClass) else IncomeClass(item)
            for item in raw.get('applies_to', [IncomeClass.earned, IncomeClass.unearned])
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
