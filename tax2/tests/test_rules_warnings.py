import logging
from pathlib import Path

import pytest
import yaml

from taxkit.rules_loader import _load_rules, load_rules


@pytest.mark.parametrize("cap,rate,expected", [
    (1000, 0.2, "final"),
    (None, 1.0, "rate"),
    (None, 5.09, "rate"),
])
def test_suspicious_brackets_warn_without_changing_rules(tmp_path, caplog, cap, rate, expected):
    data = {
        "year": 2026, "jurisdiction": "XF",
        "filing_statuses": ["single", "married_joint"],
        "components": [{
            "name": "synthetic",
            "standard_deduction": {"single": 0, "married_joint": 0},
            "brackets": {
                "single": [{"up_to": cap, "rate": rate}],
                "married_joint": [{"up_to": None, "rate": 0.2}],
            },
        }],
    }
    path = tmp_path / "synthetic.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    before = _load_rules(str(path)).model_dump()
    with caplog.at_level(logging.WARNING, logger="taxkit.rules_loader"):
        after = load_rules(str(path)).model_dump()
    assert after == before
    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert all(part in message for part in (str(path), "synthetic", "single", expected))


def test_bundled_rules_load_without_warnings_or_model_changes(caplog):
    paths = sorted((Path(__file__).resolve().parents[1] / "rules").rglob("*.yaml"))
    assert paths
    with caplog.at_level(logging.WARNING, logger="taxkit.rules_loader"):
        for path in paths:
            before = _load_rules(str(path)).model_dump()
            assert load_rules(str(path)).model_dump() == before
    assert not caplog.records
