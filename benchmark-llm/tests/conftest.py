from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_bench_base_python(monkeypatch):
    # An exported BENCH_BASE_PYTHON must never reach tests that call main();
    # tests needing an override pass it explicitly through main's environ.
    monkeypatch.delenv("BENCH_BASE_PYTHON", raising=False)
