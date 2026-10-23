# Model Sentinel parameter diffs and concise capability reporting implementation plan

**Status and authorization:** Implementation authorized after independent plan review. The user requested subagent-driven development in a worktree, incremental commits, a PR squash-merged to main, remote-branch deletion, deployment, and cleanup. Reconcile the affected source against concurrent changes before execution. No live provider scan is required for this release.

**Goal:** Make parameter differences readable for every model and captured serving endpoint, show endpoint capability changes in concise reports, and retain price-driven placement.

**Requirement source:** The user's request in this conversation. The interfaces proposed below are implementation decisions, not existing APIs. Root `agents.md` and the user-supplied AGENTS instructions govern execution.

## Source map

Path notation: `pkg/` means `model_sentinel/model_sentinel/`; `tests/` means `model_sentinel/tests/`. Other paths are relative to the repository root. Resolve references by symbol after concurrent work merges.

| Concern | Source |
| --- | --- |
| Maintained behavior and development workflow | `model_sentinel/README.md`: Report Formatting, Alias Check and Provider Endpoints, Color Semantics, HTML Auto-Reports, Testing; `docs/lessons_learned.md` |
| Comparison evidence | `pkg/models.py::FieldChange`, `canonical_json`; `pkg/conditional_pricing.py::_freeze_json`, `_thaw_json`, `PricingComparisonEvent.__post_init__`; `pkg/diffing.py::diff_values`; `pkg/endpoints.py::_diff_states` |
| Change classification | `pkg/change_render.py::classify_change`, `_scalar_display`, `_list_item_text`, `_list_diff_members` |
| Report projection | `pkg/reporting.py::_mutable_json`, `_field_display_plan`, `_expand_structured_field_changes`, `_bulk_change_signature`, `build_model_event_semantic_core`, `_split_provider_tiers`, `_model_price_impact` |
| Endpoint policy and rendering | `pkg/provider_profiles.py::ProviderProfile`, `default_categorize`, `OPENROUTER_PROFILE`; `pkg/endpoint_report.py::endpoint_change_rendering`, `_analyse_list`, `_has_default_content`, `endpoint_report`; `pkg/endpoint_html.py::_endpoint_list`; `pkg/reporting.py::_endpoint_row_texts` |
| Browse consumers | `pkg/browse/api.py`; `pkg/browse/endpoints_api.py::endpoint_change_json`; `pkg/browse/json_values.py::rendered_change_to_json`; `pkg/browse/assets/app.js::ChangeTable`, `endpointChangeCells`, `EndpointChanges`, `RawDrawer` |
| Shared synthetic fixtures and browser setup | `tests/endpoint_report_fixtures.py`, `tests/conditional_pricing_fixtures.py`, `tests/browse_fixtures.py`, `tests/test_report_html_browser.py`, `tests/test_browse_smoke.py`, `tests/validation_runtime.py` |

## Behavioral contract

These named rules are authoritative; tasks and regression cases refer to them instead of defining alternate versions.

- **Member presentation:** Individual parameter rows show sorted Added/Removed member names and a size transition, omitting unchanged names from the main explanation. Bulk groups follow `pkg/reporting.py::_render_bulk_list_diff_text` and `_bulk_list_diff_body` for cardinality presentation; do not invent a shared size transition for members with different sizes.
- **Parameter sets:** Valid parameter-name collections contain strings only. Human membership semantics ignore ordering and duplicates, including unique cardinalities. Equivalent sets produce no primary change row. This applies only to provider-policy-recognized parameter-name fields, not arbitrary arrays or ordered pricing policies.
- **Unknown operands:** Missing/null or malformed parameter-name operands stay neutral, without inferred support loss or capability-member deltas. A valid empty collection remains a known set. Preserve any absence/null distinction the current source model represents. Invalid collection pairs must not enter capability bulk groups.
- **Attribute changes:** Report supplied parameter-attribute objects as named leaf transitions. Name-only lists establish no meanings, renames, ranges, defaults, or runtime semantics. Arbitrary object arrays retain the established safe fallback; this change adds no object identity-matching algorithm.
- **Capability selection:** Default endpoint content includes fields admitted by the provider policy defined in Task Capability visibility. Apply across models/hosts without identity-specific branches. Providers without endpoint capture remain outside serving-endpoint coverage. Catalog detail configuration and explicit squelching remain authoritative for catalog rows.
- **Audit integrity:** Preserve comparison-event immutability, occurrence/change identities, source arrays/deltas, raw JSON schemas/evidence, SQLite contracts, capture requests, and telemetry exclusion. Human no-op suppression must not erase recorded evidence or make a partial history claim to be exhaustive. Existing static report files are not rewritten.
- **Placement:** Behave as `pkg/reporting.py::_split_provider_tiers` and `_model_price_impact` do. Preserve combined model cards and their price accounting. Endpoint-only changes retain `pkg/cli.py::run_scan` artifact/notification behavior.
- **Endpoint report envelope:** Behave as `pkg/endpoint_report.py::endpoint_report` and `_order_endpoint_lists` do for the displayed-list cap, ordering, full-detail remainder, and squelched mode. Behave as the endpoint companion/disclosure renderers do for navigation and placement. Add a summary tally of changed capability lists over uncapped analyses, deduplicated by list rather than by endpoint, field, mapping, or expanded row.
- **Colors:** Follow Model Sentinel README Color Semantics.

## Task 1: Parameter differences through reports and browse

**Deliverable:** Shared presentation handles frozen parameter collections and displays their differences throughout human report and browse consumers.

**Files:** Modify `pkg/models.py`, `pkg/change_render.py`, `pkg/reporting.py`, `pkg/provider_profiles.py`, and `pkg/browse/assets/app.js`. Extend the test modules named in the regression table and the source-map fixtures they already use. Update `model_sentinel/README.md` Report Formatting and add the container-boundary bug lesson to `docs/lessons_learned.md` as part of this deliverable.

**Proposed interfaces and changes:**

- `models.mutable_json_value(value: Any) -> Any`: recursively copy mappings into dicts and lists/tuples into lists; leave JSON scalars unchanged. Extract the conversion convention from `reporting._mutable_json`, extend recursion through lists, and replace that implementation with an import alias to this helper. This is the shared conversion boundary, not another serializer.
- Keep `classify_change(field_change, *, profile, allow_unmatched_prices=True) -> RenderedChange`. Convert local operands with the helper before equality, shape recognition, and formatting. `_field_display_plan(...) -> _FieldDisplayPlan` similarly builds detached `FieldChange` operands before structured expansion. Its normalized output feeds the existing no-op and bulk-planning paths, including callers without semantic cores.
- Add `ProviderProfile.parameter_membership_fields: tuple[str, ...] = ("supported_parameters", "parameters")` and `is_parameter_membership_field(field_path: str) -> bool`. Recognize these exact names at top level or as a dotted leaf; also match configured exact full paths.
- Add a parameter-field branch before generic list classification. Use the Parameter sets and Unknown operands rules to select `noop`, member diff, or neutral scalar evidence. In `_expand_structured_field_change`, keep invalid parameter-field structures intact for that neutral fallback rather than flattening malformed arrays into apparent capability leaves. Reuse `_list_diff_members` for valid member differences. `_list_change_signature` must use the same validated, unique membership representation; `_bulk_change_signature` must require list-classified eligible changes rather than list operand types alone.
- Extract `changeTransition(change)` in `pkg/browse/assets/app.js` from `ChangeTable`'s local transition logic. Implement Member presentation once and use it in `ChangeTable`, `endpointChangeCells`, and `RawDrawer`; retain each caller's action/provenance hooks.
- In `EndpointChanges`, derive displayed rows by excluding `rendered.kind === "noop"`. Apply this in the shared component used by dossier and Hosts history. Under Audit integrity, derive the empty state and displayed-row count from the filtered rows, and separately identify loaded recorded rows and existing truncation evidence. A loaded page of no-ops must not claim the provider has no earlier meaningful changes.

**Regression cases to write first:** Test names are proposed; the owning module is explicit. Each case asserts the named contract against a distinct entry path.

| Test | Trigger and observations |
| --- | --- |
| `tests/test_conditional_pricing_reporting.py::test_parameter_diff_survives_frozen_comparison_event` | Compare direct classification with `PricingComparisonEvent` → `build_model_event_semantic_core` → projection; assert Member presentation and Audit integrity. |
| `tests/test_change_render.py::test_parameter_membership_shapes_and_noops` | Mutable, frozen, and mixed list/tuple inputs; additions/removals, equal-size replacement, known-empty, reordered and duplicate-only inputs. Assert Parameter sets and Unknown operands. |
| `tests/test_reporting.py::test_invalid_parameter_shapes_cannot_expand_or_bulk_group` | Malformed arrays, object members, and scalar/collection pairs enter planning directly and through a frozen event. Assert Unknown operands after expansion and bulk eligibility, and Audit integrity against the source records. |
| `tests/test_conditional_pricing_reporting.py::test_nested_frozen_metadata_expands_without_python_repr` | One-sided nested objects and supplied default-parameter attributes; assert Attribute changes through semantic planning. |
| `tests/test_reporting.py::test_parameter_diff_live_stored_and_format_parity` | Normalize/diff-to-event and stored-comparison entry paths, a generic profile with a custom membership path, and colliding model names across providers. Check Member presentation and Audit integrity in scan text/Markdown/concise/full HTML, history text/Markdown, and changes text/HTML. |
| `tests/test_reporting.py::test_parameter_bulk_grouping_after_semantic_projection` | Group members have different collection sizes but the same member delta. Check Member presentation using the referenced bulk cardinality contract; exercise mixed pricing and no-op inputs against Placement. |
| `tests/test_browse_api.py::test_parameter_member_evidence_and_noop_records` | Catalog and endpoint API responses for genuine member changes and a recorded parameter no-op. Assert Member presentation and Audit integrity using source records as the oracle. |
| `tests/test_browse_smoke.py::test_parameter_change_browser_surfaces_show_members` | Growing and equal-size changes in Activity, dossier/Hosts endpoint histories, and raw drawer. Assert Member presentation and actionable change identity. Exercise reorder-only, duplicate-only, mixed, all-no-op, and truncated pages through `EndpointChanges`; compare displayed and recorded counts under Audit integrity. |
| `tests/test_report_html_browser.py::test_parameter_diff_price_placement_is_preserved` | Inspect disclosure ancestry for capability-only and mixed-price model cards; assert Placement and visible member text. |

- [ ] Extend the existing synthetic fixtures and add the owning regressions.
- [ ] Run their modules with the project venv. Record assertion failures demonstrating the representation/display defects; setup errors or missing imports do not prove the regression.
- [ ] Implement the proposed changes.
- [ ] Run the targeted modules and the complete suite under Validation before accepting this deliverable.

## Task 2: Capability visibility in concise endpoint reports

**Deliverable:** Provider-owned capability policy integrated into the existing endpoint report projection.

**Files:** Modify `pkg/provider_profiles.py`, `pkg/endpoint_report.py`, and the shared consumers `pkg/reporting.py`/`pkg/endpoint_html.py` as needed. Extend the owning test modules below and `tests/endpoint_report_fixtures.py`. Update the README's Alias Check and Provider Endpoints and HTML Auto-Reports sections within this deliverable.

**Consumes:** The parameter policy, classifier, and presentation conversion/expansion established in Task Parameter differences. Reuse those interfaces.

**Proposed interfaces and changes:**

- Add `ProviderProfile.endpoint_capability_fields: tuple[str, ...] = ("default_parameters", "default_parameters.*", "architecture", "architecture.*", "supports_implicit_caching")` and `is_endpoint_capability_field(field_path: str) -> bool`. Admit parameter-membership paths, profile categories Parameters/Capabilities, and the additional patterns via `fnmatchcase`. Profiles may replace or extend the tuple. Before consulting it, retain the existing routing for prices, pricing policy/selectors, endpoint status, and Context & Limits; use negative policy tests to guard those boundaries.
- In `_analyse_list`, use this policy and `endpoint_change_rendering` to select metadata. Reuse the normalized structured-expansion path for capability parents. Retain each original `EndpointChangeRecord` on its presentation rows; the rendered field/label may be a child path. Omit rendered no-ops from selected metadata in either detail mode.
- Implement Capability selection by populating `EndpointListView.metadata_rows` and consulting those rows in `_has_default_content(view)`. Apply Endpoint report envelope to the full-detail remainder instead of creating a parallel capability-row collection.
- **No-content pruning:** Exclude analyses with no displayable content in either mode from shown lists and detail-only counts; a recorded parameter no-op must not leave an empty full-detail list heading.
- Add `_ListAnalysis.has_capability_change: bool`, derived before detail/cap selection from meaningful capability changes. Use it for Endpoint report envelope's new summary tally in `endpoint_report`. Compute omission/detail-only counts from the resulting eligibility.
- Let `_endpoint_row_texts` and `endpoint_html._endpoint_list` consume the selected rows through the existing shared field formatters.

**Regression cases to write first:**

| Test | Trigger and observations |
| --- | --- |
| `tests/test_provider_profiles.py::test_endpoint_capability_policy_is_provider_owned` | Admit common/custom parameter paths, native tools, modality and reasoning flags, supplied defaults and implicit caching; exercise custom additional patterns and the routing exclusions in the proposed predicate. |
| `tests/test_reporting.py::test_concise_endpoint_capability_changes_are_visible` | Capability-only and mixed endpoint lists, one-sided capability objects, no-op-only lists, unrelated metadata/status, and squelched detail. Assert Capability selection, Attribute changes, No-content pruning, and Endpoint report envelope in text/Markdown/HTML. |
| `tests/test_reporting.py::test_endpoint_capability_summary_cap_and_shared_mapping` | Enough synthetic lists to cross the existing cap, repeated fields/endpoints, and shared catalog mappings. Assert Endpoint report envelope, companion navigation, full-detail remainder and no-change wording; include a metadata-only list. |
| `tests/test_reporting.py::test_endpoint_capability_unknowns_are_not_removals` | Failed/unsent captures, comparison gaps, known-empty membership, missing/null and malformed operands. Assert Unknown operands and Audit integrity. |
| `tests/test_report_html_browser.py::test_endpoint_capability_report_browser` | Use the companion pair and maintained viewport fixtures. Expand the endpoint section; inspect member and leaf text, long names, overflow containment and companion links under Capability selection, Colors, and Endpoint report envelope. Retain existing browser error/request guards. |
| `tests/test_cli.py::test_endpoint_capability_only_scan_keeps_artifact_policy` | Stub a saved capture with unchanged catalog and changed endpoint capability; assert Placement's CLI policy on stdout, explicit output, managed artifacts and notifications. |

- [ ] Add these cases using the maintained endpoint fixtures and stubbed CLI harness.
- [ ] Observe visibility assertion failures against current behavior.
- [ ] Implement the proposed changes.
- [ ] Re-run the owning modules and the complete suite under Validation; inspect the synthetic rendered report before accepting this deliverable.

## Validation and evidence

Run from `model_sentinel/` with its own existing venv. The focused development command is:

```sh
.venv/bin/python -m pytest tests/test_change_render.py tests/test_conditional_pricing_reporting.py tests/test_provider_profiles.py tests/test_reporting.py tests/test_browse_api.py tests/test_browse_smoke.py tests/test_report_html_browser.py tests/test_cli.py
```

The executable-change acceptance gate is:

```sh
.venv/bin/python -m pytest
```

Expected: no failures or skips, including the CLI/integration, build/installer and Playwright categories collected by that suite. These are future execution gates, not a claim that tests ran during plan authoring. Follow the README Testing setup and user-supplied Python rules when prerequisites are missing. Resolve failures or report each failing test and its output; do not weaken assertions to produce a pass.

Conspicuously synthetic source fixtures may be tracked in the named test modules. Generated runtime homes, databases, reports, screenshots and acceptance evidence must stay outside public checkouts, using existing temporary fixtures and `tests/validation_runtime.py` where applicable. Do not copy real reports, runtime state, provider captures, configuration, or credentials into the plan or fixtures.

Before implementation handoff, inspect the scoped diff for unintended changes, sensitivity, and compliance with Audit integrity. Release/version and deployment procedures remain governed by the repository rules when separately authorized.
