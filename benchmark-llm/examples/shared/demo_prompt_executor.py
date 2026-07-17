#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys


def main() -> int:
    case_id = os.environ["CASE_ID"]
    responses = json.loads(os.environ.get("TASK_RESPONSE_FIXTURES_JSON", "{}"))
    if case_id not in responses:
        print(f"Missing demo response for case id {case_id}", file=sys.stderr)
        return 1
    print(responses[case_id])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
