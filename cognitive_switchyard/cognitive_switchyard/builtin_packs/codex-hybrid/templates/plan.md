---
PLAN_ID: 000
PRIORITY: normal
ESTIMATED_SCOPE: src/example.py
DEPENDS_ON: none
FULL_TEST_AFTER: no
---

# Plan: Example Task

## Testing

### Entry tests
- .venv/bin/python -m pytest

### Exit tests
- .venv/bin/python -m pytest

### Regression test
- Add one packet-scoped regression.

## Operator Actions

None — standard image deployment, no manual steps required.
