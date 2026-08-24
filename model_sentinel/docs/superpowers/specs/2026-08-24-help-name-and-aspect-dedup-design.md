# Help Invocation Name and Aspect Deduplication Design

**Date:** 2026-08-24
**Status:** Approved for planning

## Scope

Correct two user-visible Model Sentinel defects:

1. CLI help and examples currently hard-code `model_sentinel`, even though the
   installed executable is `model-sentinel` and may be renamed.
2. The Models aspect picker exposes both a canonical aspect and a discovered
   raw-path aspect when both represent the same provider field, producing
   duplicate controls and identical graphs.

No other CLI wording, aspect ordering, series behavior, or persisted data will
change.

## Invocation Name

Introduce one resolver for the command name shown by argparse. All root and
subcommand usage lines, examples, first-run guidance, and version output will
use the resolved name.

- A script, zipapp, symlink, or renamed executable uses the basename of
  `sys.argv[0]`.
- Module invocation displays `python -m model_sentinel`. Because Python does
  not preserve the originally typed command in `sys.argv[0]`, module invocation
  is identified from the package `__main__.py` entry path.
- An empty or unusable invocation value falls back to `model-sentinel`.

The resolved value is display text only. It does not affect parsing, runtime
paths, logging, configuration, or build identity.

## Aspect Deduplication

The aspect catalog will continue to create the canonical provider-scoped
columns first. While doing so, it will record each canonical aspect's exact
`(provider_id, representative field path)` pair.

When field-change history is scanned for discovered raw paths, a raw-path
aspect will be omitted if its exact provider/path pair is already represented
by a canonical aspect. Deduplication is based on identity, not label or current
series values.

This removes pairs such as:

- OpenRouter `input_price` and `pricing.prompt`
- `output_price` and `pricing.completion`
- cache read/write canonical columns and their backing pricing paths
- `context_window` and `context_length`
- `max_output_tokens` and `top_provider.max_completion_tokens`

Distinct raw fields remain visible, including cache-write duration variants,
audio/image pricing, and provider-specific limits that do not back the selected
canonical column.

Existing hashes containing an omitted raw aspect are handled by the existing
aspect-state normalization: the unknown selection is removed and the canonical
aspect remains available.

## Verification

Tests will be written before production changes and will prove:

- a renamed script or zipapp basename appears throughout root and subcommand
  help;
- module invocation displays `python -m model_sentinel`;
- fallback naming is safe;
- `--version` uses the same resolved invocation name;
- canonical/raw pairs sharing the exact provider/path produce only the
  canonical aspect;
- same-label or same-value aspects with different paths are retained;
- existing aspect order and series contracts remain unchanged.

Run the complete pytest suite before delivery. Rebuild and validate the
standalone only after the change is merged to `main`, so its embedded revision
identifies the durable commit.
