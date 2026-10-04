"""Generate the curated ledger from one explicit public models.dev snapshot.

Run with the project's virtual-environment interpreter. Never fetches a catalog
or reads runtime homes. Output is deterministic JSON for the launcher's markers.
"""

import argparse
import importlib.machinery
import importlib.util
import json
import math
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path


# CostUsagePricing.swift codexHistoricalPricing 394–407 at 3bbf6bc48,
# per-million decimal conversion (A4). gpt56Pricing 47–61 sets 272000.
HISTORICAL = {
    "gpt-5.6-sol": ((5, 0.5, 6.25, 30), (10, 1, 12.5, 45)),
    "gpt-5.6-terra": ((2.5, 0.25, 3.125, 15), (5, 0.5, 6.25, 22.5)),
    "gpt-5.6-luna": ((1, 0.1, 1.25, 6), (2, 0.2, 2.5, 9)),
}


class _SnapshotFloat(float):
    """Retain the raw spelling only until typed context acceptance is checked."""

    def __new__(cls, spelling):
        value = super().__new__(cls, spelling)
        value.spelling = spelling
        return value


def _context_integer(value: _SnapshotFloat) -> int | None:
    # JSONDecoder's Int slow path uses Double below 2^53, then Foundation Decimal
    # for larger magnitudes. Task13 standalone pinned-model probes corroborate
    # Int64 boundaries, including rejected decimal -2^63 and positive rounding
    # to 2^63. This normalization is solely a raw JSON decode boundary.
    binary = float(value)
    if not math.isfinite(binary) or not binary.is_integer() or not -(2**63) <= binary < 2**63:
        return None
    if abs(binary) < 2**53:
        return int(binary)
    # Foundation swift-6.1-RELEASE Decimal.swift _decimal 320–424 accumulates
    # a UInt128 mantissa; after overflow it discards further fractional digits.
    # Preserve that representation loss before Int(exactly:), not Python's
    # arbitrary-precision fractional value or NSNumber's wrapping Int cast.
    sign, digits, exponent = Decimal(value.spelling).as_tuple()
    coefficient = discarded = 0
    for digit in digits:
        candidate = coefficient * 10 + digit
        if discarded or candidate > 2**128 - 1:
            discarded += 1
        else:
            coefficient = candidate
    exponent += discarded
    if not -128 <= exponent <= 127:
        return None
    if exponent >= 0:
        integer = coefficient * 10**exponent
    else:
        integer, remainder = divmod(coefficient, 10**(-exponent))
        if remainder:
            return None
    if sign:
        integer = -integer
    return integer if -(2**63) < integer < 2**63 else None


def load_snapshot(text: str) -> dict:
    """Preserve source context-number acceptance without changing cost Doubles."""
    def reject_constant(spelling):
        raise ValueError(f"invalid JSON number {spelling}")

    snapshot = json.loads(text, parse_float=_SnapshotFloat, parse_constant=reject_constant)
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be a JSON object")
    # Check both possible provider containers; ModelsDevIndex still decides
    # the typed wrapper fallback. Invalid model children are skipped individually.
    for providers in (snapshot, snapshot.get("providers")):
        if not isinstance(providers, dict):
            continue
        for provider in providers.values():
            if not isinstance(provider, dict) or not isinstance(provider.get("models"), dict):
                continue
            for key, model in list(provider["models"].items()):
                limit = model.get("limit") if isinstance(model, dict) else None
                context = limit.get("context") if isinstance(limit, dict) else None
                if isinstance(context, _SnapshotFloat):
                    integer = _context_integer(context)
                    if integer is None:
                        del provider["models"][key]
                    else:
                        limit["context"] = integer

    def plain(value):
        if isinstance(value, _SnapshotFloat):
            return float(value)
        if isinstance(value, dict):
            return {key: plain(child) for key, child in value.items()}
        if isinstance(value, list):
            return [plain(child) for child in value]
        return value

    return plain(snapshot)


def load_colophon():
    path = Path(__file__).resolve().parents[2] / "colophon"
    loader = importlib.machinery.SourceFileLoader("colophon_seed_launcher", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


def build_seed(colophon, snapshot: dict, snapshot_date: str) -> dict:
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be a JSON object")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", snapshot_date):
        raise ValueError("snapshot-date must be YYYY-MM-DD")
    date.fromisoformat(snapshot_date)
    index = colophon.ModelsDevIndex.from_catalog(snapshot)
    ids = set(colophon.CURATED_BUNDLED)
    ids.update(colophon.normalize_codex_model(value["model_id"]) for value in index._models.values())
    entries = []
    keys = ("input", "cached_input", "cache_write", "output")
    for identifier in sorted(ids):
        current = colophon.resolve_rates(identifier, index)
        if current is None:
            continue
        periods = [(None, current)]
        if identifier in colophon.HISTORICAL_CUTOFFS:
            standard, long = HISTORICAL[identifier]
            old = {"per_million": dict(zip(keys, standard)),
                   "long_context": {"threshold": 272000, **dict(zip(keys, long))}}
            periods = [(None, old), (colophon.format_rfc3339(colophon.HISTORICAL_CUTOFFS[identifier]), current)]
        for at, rates in periods:
            entry = {"model": identifier, "effective_from": at, "per_million": rates["per_million"],
                     "source": "curated", "note": f"seed from models.dev snapshot {snapshot_date}"}
            if rates["long_context"] is not None:
                entry["long_context"] = rates["long_context"]
            multiplier = colophon.codex_api_fast_multiplier(identifier)
            if multiplier is not None:
                entry["priority"] = {"multiplier": multiplier,
                                     "max_input_tokens": None if identifier == "gpt-6-astra" else 272000}
            entries.append(entry)
    result = {"schema": 1, "entries": entries}
    checked = colophon.validate_ledger(result, curated=True)
    if checked.errors:
        raise ValueError("invalid generated seed: " + "; ".join(checked.errors))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--snapshot-date", required=True)
    args = parser.parse_args(argv)
    try:
        snapshot = load_snapshot(args.snapshot.read_text(encoding="utf-8"))
        result = build_seed(load_colophon(), snapshot, args.snapshot_date)
    except (OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
