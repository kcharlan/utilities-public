# Model Sentinel Report Detail Policy Plan

## Summary

Implement a configurable, generic report detail policy for Model Sentinel so daily reports stay concise while preserving full collection and surfacing new upstream fields.

The selected design is a hybrid field-pattern policy:

- `show_fields`: field patterns rendered in full in default reports.
- `squelch_fields`: field patterns summarized in default reports.
- `unclassified_fields`: changed fields matching neither list, rendered by default with a defensive cap so new upstream keys remain visible.
- `--detail all`: render every field detail.
- `--detail default`: render shown and unclassified details, summarize squelched details.
- `--detail squelched`: render only squelched field details, mainly for benchmark review.
- Daily scan runs still save a full-detail HTML companion report by default when the normal HTML companion is generated.

This is field-path based, not category based. Existing presentation categories may remain for grouping and labels, but inclusion and exclusion decisions use configurable dotted field paths such as `pricing.*`, `supported_parameters`, `benchmarks.*`, and future provider keys.

## Implementation Notes

- Field paths are generated in `model_sentinel/diffing.py` by `_diff_values()`.
- Field paths are stored verbatim in `field_changes.field_name`.
- Report detail filtering is presentation-only; collection, normalization, snapshot storage, and change recording remain unchanged.
- JSON output remains full fidelity for machine consumers.
- Human-readable scan, changes, and history reports use the configured detail policy.
- Unknown fields remain visible by default, capped by `MODEL_SENTINEL_REPORT_UNCLASSIFIED_LIMIT`.

## Public Interface

- `scan --detail default|all|squelched`
- `changes --detail default|all|squelched`
- `history --detail default|all|squelched`

Runtime settings:

```env
MODEL_SENTINEL_REPORT_DETAIL=default
MODEL_SENTINEL_REPORT_SHOW_FIELDS=pricing.*,context_length,top_provider.context_length,top_provider.max_completion_tokens,supported_parameters,default_parameters,default_parameters.*,architecture.*,reasoning,reasoning.*,expiration_date,status,deprecated,knowledge_cutoff,top_provider.is_moderated
MODEL_SENTINEL_REPORT_SQUELCH_FIELDS=benchmarks,benchmarks.*
MODEL_SENTINEL_REPORT_UNCLASSIFIED_LIMIT=20
```

## Acceptance Criteria

- Default daily reports no longer print benchmark field payloads.
- Default reports still show important operational changes.
- New or unclassified upstream keys still appear by default.
- Full benchmark details remain available with `--detail all`.
- Squelched benchmark details are available with `--detail squelched`.
- A full-detail HTML companion report is generated for scan runs with changes when the normal HTML companion report is generated.
- Existing reports in JSON remain full fidelity.
- Tests cover config, policy resolution, text rendering, HTML rendering, changes rendering, history rendering, and JSON fidelity.
