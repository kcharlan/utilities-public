# Operational Terminal Report Implementation Plan

> **Execution note for Codex:** The user requested subagent-driven development for implementation. That is an execution workflow for this task, not a runtime dependency or a requirement for other developers. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unreadable TP-Link terminal dump with a compact operational briefing that preserves findings, everyday activity counts, change context, and consequential limitations, with exhaustive human-readable evidence available through `--verbose`.

**Architecture:** Keep the standalone launcher and all existing analysis semantics. Preserve source-row multiplicity on normalized `Event` representatives, add one renderer-neutral router-activity count projection, then dispatch TP-Link text reports to a dedicated operational renderer; the existing NETGEAR text renderer and JSON semantics remain compatible. `--verbose` changes only TP-Link human-readable text presentation and does not create a logging or debug subsystem.

**Tech Stack:** Python 3.12+, standard library (`argparse`, `collections.Counter`, `textwrap`), pytest, existing uv-managed single-file launcher.

**Approved design:** `docs/superpowers/specs/2026-08-26-operational-terminal-report-design.md`

---

## Scope and File Map

- Modify `router_log_analyze.py`:
  - preserve source-row multiplicity through TP-Link semantic deduplication and project exact router component, outcome/state, and event-type source-record counts into `report["router_activity"]`;
  - preserve the current text renderer as the NETGEAR compatibility path;
  - add the TP-Link operational text renderer and its default/verbose detail levels;
  - add and plumb `--verbose` through persistent, non-persistent, and explicit text-report output paths.
  - remove the same `Router/System` event-type wall from Markdown and HTML device tables and replace it with counted router-component and event-type activity.
- Modify `test_router_log_analyze.py`:
  - add focused RED/GREEN tests for aggregation, operational hierarchy, width behavior, findings, limitations, verbose detail, CLI plumbing, and JSON/NETGEAR compatibility;
  - revise TP-Link renderer assertions that currently require debug evidence in every human-readable format without weakening the established analysis contracts.
- Modify `README.md`:
  - document the default operational briefing, `--verbose`, and the distinction between a clean result and unavailable checks.
- No new runtime modules, data migrations, dependencies, policy fields, or configuration files.

## Binding Behavioral Decisions

1. The new layout applies when `has_extended_router_report(report)` is true. Existing NETGEAR text output remains byte-for-byte compatible under its characterization tests.
2. The default output never claims “no security/device problems” when the corresponding checks were unavailable. A zero-finding sentence is phrased as “No findings were detected by the checks that were available.”
3. `status == "Clean"` does not imply zero findings because low findings may be score-capped to Clean. Every entry in `report["findings"]["all"]` remains visible in the default findings section.
4. Activity counts describe source records contained in the snapshot, including repeated and report-only records. A semantically deduplicated `Event` may represent more than one source row, so the new projection is weighted by explicit source-record multiplicity. Existing occurrence, novelty, and persistence counters retain their semantic-occurrence meanings. The Baseline and Change section explains those meanings separately so snapshot contents are not misrepresented as newly learned activity.
5. `Router/System` is excluded from the TP-Link device pulse and rendered only in Router Activity. It remains untouched in the NETGEAR compatibility renderer.
6. The default shows up to five highest-volume router components plus every additional low-volume component carrying a consequential health/security outcome (`failure`, `rejected`, `blocked`, `denied`, `disconnected`, or `timeout`). Remaining components collapse into one reconciled tail count. `--verbose` shows every component and every event type.
7. `--verbose` affects TP-Link text output only. With NETGEAR text, `--json`, Markdown, or HTML it has no effect; JSON is already exhaustive and NETGEAR text is a compatibility contract. With `--report text,...`, the rendered TP-Link report body printed to stdout is the same body written to the generated `.txt` report; stdout may additionally list generated report paths.
8. The default exposes malformed-line counts and unmapped parser warnings when nonzero because they can affect confidence. It translates known gaps into plain language and summarizes unknown warnings rather than silently dropping them.
9. Router export timestamps are displayed as router-local values without inventing a timezone or UTC conversion.
10. No color, terminal control sequences, paging, interactivity, report-template framework, or `--debug` option is introduced.
11. History is tri-state in presentation: queried with prior history, queried with none, or unavailable/not queried. A numeric zero alone never proves first-run state.
12. Saved Markdown and HTML reports remain self-contained human reports: they retain complete counted router event-type evidence, presented as tables rather than a comma-separated wall.

## Adversarial Review Resolutions

The post-draft adversarial pass produced the following binding corrections:

- **Do not hide consequential low-volume activity:** volume ranking alone could bury a one-off failure, disconnect, or timeout beneath five noisy components. Components containing failure/rejection/block/deny/disconnect/timeout outcomes are promoted in addition to the five volume leaders, without converting those raw outcomes into findings.
- **Do not conflate reset coverage gaps:** missing per-client activity and missing WAN transitions have different operational meanings. Default limitation projection describes client telemetry separately from internet-reset analysis and combines only equivalent causes.
- **Do not overstate security mapping knowledge:** the current report records whether an explicit mapping was evidenced in this export, not a complete vendor/model/firmware mapping registry. Default wording says that no recognized mapping was available in the export; it does not claim the router model has no mapping in principle.
- **Do not conflate baseline types:** snapshot-count history and router-behavior history are separate. First-run wording states which comparison lacks history and combines them only when both facts are true.
- **Do not call snapshot contents newly learned activity:** Router Activity describes the buffer contents. Baseline and Change separately states novelty, repetition, report-only status, and persistence.
- **Do not leave other human formats knowingly broken:** inspection confirmed that Markdown and HTML also render the `Router/System` event vocabulary in one Device Summary cell. The plan now replaces that row with counted component and event-type tables while preserving the rest of those formats.
- **Keep compatibility verification executable:** the plan now names the exact existing NETGEAR characterization test rather than an inferred node ID.
- **Keep the implementation local and small:** the review rejected a general report framework, configurable templates, a debug subsystem, and new persistence. The plan remains helper functions inside the standalone launcher.
- **Preserve source-record multiplicity:** TP-Link persistence stores `source_count` while retaining one representative `Event`; counting representatives would understate the exported snapshot. The projection now weights representatives by a non-persistent `source_record_count` field, preserves existing occurrence counters, and tests first-ingest and exact-duplicate reconstruction.
- **Protect disconnects and timeouts:** an explicit WAN disconnect or timeout can fail to become a reset finding when reset checks lack sufficient coverage. These outcomes now promote their components into the default activity pulse even at low volume.
- **Do not infer history from zero:** snapshot and router-behavior history now carry an explicit `history_queried` state. Zero means “first comparable observation” only when the corresponding query actually ran.
- **Render router findings as router findings:** router security, firmware, behavior/state, event-type, and client-count findings receive a router subject and kind-specific evidence instead of falling through to `Unknown device` and a generic message.
- **Keep tracked material private:** the plan no longer contains a user-specific repository path or real router-specific scan literals. Privacy checks are generic, staged-diff based, and gating.
- **Hide generated identity material:** the ordinary unlabeled persistent path uses a friendly vendor/model label without an instance-hash suffix, including a targeted compatibility cleanup for previously auto-generated labels.
- **Scope time limitations accurately:** untrusted body timestamps prevent body-event calendar/time analysis; they do not invalidate an export-timestamp snapshot-count comparison that actually ran.
- **Keep saved reports self-contained:** Markdown and HTML receive counted event-type tables as well as component tables, so fixing the wall does not discard evidence.
- **State CLI contracts precisely:** tests compare the rendered report body, not complete stdout that also contains generated-path notices, and help text identifies `--verbose` as TP-Link text behavior.
- **Test binding edge cases directly:** the plan now covers multiplicity, action/outcome reconciliation, zero events, missing projection, duplicate-run history, unavailable history, unlabeled routers, consequential tail promotion, and a 60-column terminal.
- **Use accurate outcome terminology:** the additive schema uses `outcome_counts`, with stored state preferred over action when present; its display vocabulary includes both stored state forms and parser action forms.

The external review also raised process coupling. The runtime architecture has no such coupling. The remaining Codex subagent note is retained only because the user explicitly requested that execution method; the implementation plan itself remains usable by a developer without those tools.

---

### Task 1: Add renderer-neutral router activity counts

**Files:**
- Modify: `router_log_analyze.py` near `Event`, `StateStore.collapse_existing_run_events`, and `StateStore.persist_router_provenance`
- Modify: `test_router_log_analyze.py` near the existing `build_router_report_sections` tests (`test_snapshot_report_ranges_use_the_detector_numeric_profiles` and `test_snapshot_change_detail_excludes_noncount_router_changes`)
- Modify: `router_log_analyze.py:9721-9872` (`build_router_report_sections`)

- [ ] **Step 1: Write a failing projection test**

Add `test_router_report_projects_reconciled_component_outcome_and_event_type_counts`. Construct three conspicuously synthetic router-scoped `Event` representatives:

- one event for component `synthetic_firewall`, event key `SYNTHETIC_FIREWALL_9001_FAILURE`, vendor code `9001`, action `failure`, and `source_record_count=2`;
- one event for component `synthetic_service`, event key `SYNTHETIC_SERVICE_9002_START`, vendor code `9002`, action `start`;
- one event with no component, event key `SYNTHETIC_UNKNOWN_9003_OTHER`, no code, and no action.

Call `build_router_report_sections(...)` and require this additive schema under `sections["router_activity"]`:

```python
{
    "source_record_count": 4,
    "component_counts": [
        {"component": "other", "event_count": 1},
        {"component": "synthetic_firewall", "event_count": 2},
        {"component": "synthetic_service", "event_count": 1},
    ],
    "outcome_counts": [
        {"outcome": "failure", "event_count": 2},
        {"outcome": "other", "event_count": 1},
        {"outcome": "start", "event_count": 1},
    ],
    "event_type_counts": [
        {
            "component": "other",
            "event_key": "SYNTHETIC_UNKNOWN_9003_OTHER",
            "vendor_event_code": None,
            "outcome": "other",
            "event_count": 1,
        },
        {
            "component": "synthetic_firewall",
            "event_key": "SYNTHETIC_FIREWALL_9001_FAILURE",
            "vendor_event_code": "9001",
            "outcome": "failure",
            "event_count": 2,
        },
        {
            "component": "synthetic_service",
            "event_key": "SYNTHETIC_SERVICE_9002_START",
            "vendor_event_code": "9002",
            "outcome": "start",
            "event_count": 1,
        },
    ],
}
```

Also assert that component, outcome, and event-type counts each sum to `source_record_count == 4`, while the existing `system_event_count == 3` continues to count semantic `Event` representatives. This pins both count units rather than making internally consistent but incorrect projections from the same collapsed list.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```zsh
.venv/bin/python -m pytest -q test_router_log_analyze.py::test_router_report_projects_reconciled_component_outcome_and_event_type_counts
```

Expected: FAIL because source multiplicity and the three activity-count collections do not yet exist.

- [ ] **Step 3: Preserve source-record multiplicity through semantic deduplication**

Add `source_record_count: int = 1` to `Event`. This field is report-time provenance, not a new database column and not part of occurrence identity, hashing, learned history, finding classification, or policy.

In `StateStore.persist_router_provenance`, set each persistable representative's `source_record_count` to the same positive `source_count` written to `run_event_occurrences`; report-only events remain separate representatives with the default count of one.

In `StateStore.collapse_existing_run_events`, accumulate identical parsed digests instead of merely skipping later instances, then emit one representative with the accumulated `source_record_count`. This must reproduce the same source-record totals on an exact duplicate run without changing its repeated/novel semantics. Validate or clamp internal multiplicity to at least one; malformed nonpositive values must never create negative or disappearing report counts.

Add `test_tp_link_activity_preserves_source_record_multiplicity_on_first_and_duplicate_ingest`. Ingest a synthetic TP-Link snapshot containing at least two identical persistable source records. Assert on both the first ingest and an exact duplicate ingest that:

- one semantic representative carries `source_record_count == 2`;
- the stored `run_event_occurrences.source_count == 2`;
- the activity projection totals two source records for that event type;
- semantic occurrence novelty/repetition counts remain one occurrence, not two.

- [ ] **Step 4: Implement the minimal semantic projection**

Add a focused helper immediately before `build_router_report_sections`:

```python
def project_router_activity(events: Sequence[Event]) -> Dict[str, Any]:
```

Binding rules:

- Consider only `event.actor_scope == "router"`.
- Normalize component as collapsed, case-folded text; use `"other"` when absent.
- Normalize outcome from the first nonempty value of `structured_evidence["state"]` and `structured_evidence["action"]`, otherwise `"other"`; collapse whitespace and case-fold it. Call the collection `outcome_counts` because it intentionally accepts both stored state and action vocabularies.
- Weight component, outcome, and event-type counters by `event.source_record_count`, never by one representative per `Event`.
- Count event types by `(component, event_key, vendor_event_code, outcome)`. Process identifiers and full messages do not split a display event type.
- Return semantic values, not humanized labels or preformatted rows.
- Sort each list lexicographically by its semantic identity so JSON is deterministic. Volume ranking remains a renderer decision.

Merge the projection into `router_activity` while preserving all existing keys. Add `source_record_count` as the authoritative reconciliation total for the new collections. Preserve `system_event_count` as the semantic router-representative count; do not change finding classification, novelty, persistence ownership, or existing occurrence keys. Add `occurrences.source_record_count` for verbose count provenance while retaining `occurrences.body_count` as the semantic representative count.

- [ ] **Step 5: Run the focused projection, multiplicity, and existing router-section tests**

Run:

```zsh
.venv/bin/python -m pytest -q \
  test_router_log_analyze.py::test_router_report_projects_reconciled_component_outcome_and_event_type_counts \
  test_router_log_analyze.py::test_snapshot_report_ranges_use_the_detector_numeric_profiles \
  test_router_log_analyze.py::test_snapshot_change_detail_excludes_noncount_router_changes
```

Also run `test_router_log_analyze.py::test_tp_link_activity_preserves_source_record_multiplicity_on_first_and_duplicate_ingest`.

Expected: all selected tests PASS; existing semantic occurrence values are unchanged, source-record counts survive both persistence paths, and the activity schema is additive.

- [ ] **Step 6: Commit the projection**

Before committing, inspect the staged file list and full staged diff for private data. Stage only `router_log_analyze.py` and `test_router_log_analyze.py`.

```zsh
git commit -m "Add router activity count projection"
```

---

### Task 2: Render the default TP-Link operational briefing

**Files:**
- Modify: `test_router_log_analyze.py` near `test_tp_link_report_contract_surfaces_router_snapshot_occurrence_and_coverage_facts`, `test_tp_link_fully_repeated_snapshot_is_explicit_in_all_renderers`, and text-renderer tests
- Modify: `router_log_analyze.py:9934-10606` (text formatting helpers, `router_report_summary_items`, and `render_text_report`)
- Modify: `router_log_analyze.py` at `default_router_label` and `StateStore.resolve_router_instance`

- [ ] **Step 1: Add failing tests for a clean operational report**

Create a synthetic TP-Link report through the existing parse/analyze test helpers rather than hand-writing an incomplete report dictionary. Add tests that fix the following contract:

- Title is `Network Analysis Report — <synthetic router label>` when a label is supplied.
- The ordinary persistent path without `--router-label` uses only a friendly synthetic vendor/model label. It never exposes an instance-key/hash suffix. A stored label matching the tool's former auto-generated vendor/model/hash form is upgraded to the friendly default, while any user-supplied stored label is preserved.
- Status line contains `CLEAN` and `Risk 0/100`.
- With no findings but unavailable checks, the report says `No findings were detected by the checks that were available.` It does not claim all security or device checks passed.
- Sections appear in this order when applicable: `Router Snapshot`, `Baseline and Change`, `Router Activity`, `Attention / Limitations`.
- Empty `Finding Index`, `Findings by Device/Group`, and `Risk Breakdown` sections are absent.
- `Router/System` and the comma-separated event-key wall are absent.
- The snapshot combines total, Wi-Fi, and wired client counts on one line.
- Component counts and the collapsed tail reconcile to `source_record_count`; the distinct semantic occurrence count remains separately labeled.
- A snapshot with `history_queried is True` and zero history says it is the first comparable client-count snapshot; `router_activity.behavior_history_queried is True` with zero history separately says it is the first comparable router-behavior observation. Combine the sentence only when both queries ran and both facts are true. A false query flag says comparison was unavailable/not evaluated and never interprets the numeric zero as no prior history.
- Novel, repeated, and report-only occurrence wording preserves their separate meanings.

Use only conspicuously synthetic router metadata and event records.

- [ ] **Step 2: Add failing tests for findings, limitations, and edge wording**

Add focused cases for:

1. A report with low findings and overall status `Clean`: the finding still appears with its `LOW` severity and rendered evidence.
2. A mapped high router-security finding: it appears immediately after status and before the routine snapshot, its subject is the router rather than `Unknown device`, and its event/component/outcome evidence is visible.
3. A synthetic new-device finding at effective `MEDIUM`: it remains prominent and is not reduced to device-pulse activity.
4. A fully repeated snapshot: it says the snapshot body was already seen and does not describe the repeated records as newly learned.
5. Untrusted/report-only records: they remain counted as snapshot contents but are explicitly excluded from calendar/time-based history.
6. Capability and parser gaps: stable-client and rejected-client gaps collapse into one identity limitation; device DHCP/behavior/reset gaps collapse into one client-telemetry limitation; missing LAN/WAN headers become plain-language bullets; malformed lines are shown when nonzero.
7. An unexpected parser warning: default output reports that an additional warning exists and directs the user to `--verbose` without dumping its internal token.
8. Width behavior: monkeypatch `shutil.get_terminal_size` separately to 80 and 60 columns. Assert no non-rule TP-Link output line exceeds the available width and important long content wraps instead of disappearing. The NETGEAR compatibility renderer retains its existing minimum-width behavior.
9. More than five components with low-volume `failure`, `disconnected`, and `timeout` components outside the volume leaders: every consequential component remains visible in the default pulse exactly once and the collapsed tail still reconciles exactly. Cover overlap where one consequential component is already in the top five.
10. Zero router events: the Router Activity section gives a short explicit zero-activity statement rather than an empty table or missing-key failure.
11. A compatibility report lacking `component_counts`, `outcome_counts`, and `event_type_counts`: default rendering degrades to the available semantic total plus a one-line component-detail limitation.
12. History tri-state: cover queried-with-history, queried-with-none, exact-duplicate/not-queried, and ambiguous-firmware/not-queried behavior. The latter two must never claim to be first observations.
13. Router finding evidence: add focused entries for `router_firmware_change`, `router_new_event_type`, `router_state_change`, and `router_client_count_anomaly`; each uses a router subject and includes its material metadata (old/new firmware, event/component/state, or observed/range/direction/history evidence as applicable).

Use clear final node IDs, including at minimum:

- `test_tp_link_operational_report_clean_hierarchy_and_history_state`;
- `test_tp_link_operational_report_surfaces_router_finding_evidence`;
- `test_tp_link_operational_report_promotes_consequential_tail_outcomes`;
- `test_tp_link_operational_report_handles_zero_events_and_missing_projection`;
- `test_tp_link_operational_report_wraps_at_60_and_80_columns`;
- `test_tp_link_history_wording_distinguishes_queried_none_from_unavailable`; and
- `test_persistent_tp_link_default_label_omits_instance_hash_and_preserves_custom_label`.

- [ ] **Step 3: Run the new renderer tests and verify RED**

Run the newly added test node IDs with `.venv/bin/python -m pytest -q ...`.

Expected: FAIL against the current flat renderer for the intended hierarchy, wording, and width assertions—not because of malformed test fixtures.

- [ ] **Step 4: Preserve the NETGEAR renderer and add an explicit dispatcher**

Move the current `render_text_report` body unchanged into:

```python
def render_legacy_text_report(report: Dict[str, Any], width: int) -> str:
```

Change the public entry point to:

```python
def render_text_report(report: Dict[str, Any], verbose: bool = False) -> str:
```

Read the terminal width once. If `has_extended_router_report(report)` is false, pass the existing `80..120` bounded width to the legacy function and ignore `verbose`. Otherwise pass the actual width bounded to `40..120` to the new TP-Link operational renderer so terminals below 80 columns wrap correctly. This preserves direct callers and the characterized NETGEAR text contract.

- [ ] **Step 5: Implement focused operational presentation helpers**

Add small helpers adjacent to the text renderer; do not introduce a class hierarchy or general report framework. The executor may choose exact local names, but preserve these responsibilities and interfaces:

- a wrapped label/value or bullet helper that never loses content at the TP-Link renderer's bounded width;
- a router-local export-time formatter that parses the existing ISO value but adds no timezone conversion;
- a finding summary renderer that iterates all `report["findings"]["all"]` in existing severity order and uses existing finding projections without reclassifying severity;
- explicit router branches in `finding_subject_label`, `finding_issue_summary`, and `finding_field_lines`: all `router_*` kinds use subject `Router`; security entries show event/component/outcome, firmware entries show previous/current firmware, behavior/state entries show event/component/state and date, and client-count entries show each changed metric's observed value, learned range, direction, and history count. Device and cluster branches remain unchanged;
- a baseline/change renderer that uses only `snapshot.history_count`, `snapshot.history_queried`, `occurrences`, `router_activity.behavior_history_count`, `router_activity.behavior_history_queried`, and run persistence evidence already present in the report;
- an activity renderer that sorts component source-record counts by descending count and then humanized name, shows five volume leaders plus any additional component with a consequential outcome, and reconciles the remaining source-record count as one tail line;
- a device-pulse renderer that calls `group_device_summary` only after filtering out `mac == SYSTEM_ACTOR`, omits the entire section when no client device activity exists, and omits the default event-type list;
- a limitation projector that returns deduplicated user-impact messages.

Default outcome display uses the existing closed state/action vocabularies. Omit `other`; display nonzero outcomes in a stable order with consequential values first: `failure`, `rejected`, `blocked`, `denied`, `disconnected`, `timeout`, followed by applicable transition/state values such as `stopped`, `disabled`, `stop`, `disable`, `release`, `restart`, `start`, `running`, `enabled`, `enable`, `connected`, `ready`, and `success`. Preserve stored semantic spellings in JSON. Findings remain the authoritative severity signal; the activity pulse must not invent a finding from an outcome word.

For default limitations, use these evidence rules:

- combine unavailable `stable_client_discovery` and `current_rejected_client` checks caused by missing stable identity into one client-identity message;
- combine unavailable client DHCP, event-volume, behavior, and cluster checks caused by missing client-equivalent telemetry into one client-telemetry/comparison message;
- combine `confirmed_reset` reason `no_wan_transition_coverage` and `inferred_reset` reason `no_client_recovery_equivalence` into one internet-reset limitation that names both missing evidence classes; do not mislabel WAN transition coverage as client telemetry;
- when `router_security` has reason `no_router_security_mapping`, say no recognized security-event mapping was available in this export, not that security was normal or that the router model can never be mapped;
- translate known missing LAN/WAN header warnings once each;
- if `coverage.trusted_records == 0` and body records exist, state specifically that body-event calendar/time analysis was unavailable. Do not imply that export-timestamp snapshot-count comparison was unavailable when `snapshot.history_queried` proves that comparison ran;
- surface invalid/unavailable snapshot counts, malformed lines, and the count of any remaining parser warnings;
- do not show `duration_based_partial (point_snapshot_not_continuous)` as a limitation for a point-snapshot format.

If an old/compatibility report lacks the additive activity projection, render the available semantic occurrence total and a one-line note that source-record/component detail is unavailable; never call the value a source-record count, fall back to the old comma wall, or raise `KeyError`.

Change `default_router_label` to return only the friendly vendor/model label. In `StateStore.resolve_router_instance`, when no explicit label is supplied for an existing router, replace a stored label only if it exactly equals the former auto-generated `vendor + model + instance_key[:8]` value. Do not rewrite any other stored label; this is targeted compatibility cleanup, not a schema migration.

Extend `build_router_report_sections` with keyword parameters `snapshot_history_queried: bool = False` and `router_behavior_history_queried: bool = False` after the existing required parameters so compatibility callers remain valid. Initialize both false in `main`, and set each true only after its corresponding history fetch succeeds. Non-persistent, exact-duplicate, missing-export-time, ineligible-snapshot, absent-firmware-profile, and ambiguous-firmware paths retain false unless that specific query ran. Store the booleans beside their respective counts in the additive report sections.

- [ ] **Step 6: Implement the section hierarchy**

Implement the default TP-Link output in this conditional order:

1. title;
2. status/risk and accurate finding summary;
3. Findings, only when nonempty;
4. Router Snapshot;
5. Baseline and Change;
6. Router Activity;
7. Device Activity, only when non-system device events exist;
8. Attention / Limitations, only when consequential limitations exist.

Do not print empty `None` sections. Treat `fully_repeated` as snapshot-buffer context, not zero activity. For persistence wording, say an occurrence was learned/stored only when the report indicates persistence was available; otherwise use current-only language.

- [ ] **Step 7: Run the focused renderer tests and established text contracts**

Run all new operational renderer node IDs plus:

```zsh
.venv/bin/python -m pytest -q \
  test_router_log_analyze.py::test_render_text_report_uses_finding_index_and_device_grouping \
  test_router_log_analyze.py::test_synthetic_netgear_regression_locks_parser_and_v3_report_contract
```

Expected: new TP-Link operational tests PASS and the exact NETGEAR text projection remains PASS.

- [ ] **Step 8: Commit the default renderer**

Inspect the staged file list and full staged diff for private data, then commit only the launcher and test changes.

```zsh
git commit -m "Render concise TP-Link operational reports"
```

---

### Task 3: Add verbose text evidence and CLI plumbing

**Files:**
- Modify: `test_router_log_analyze.py` near CLI help/report-output tests and the new operational renderer tests
- Modify: `router_log_analyze.py:491-560` (`parse_args`)
- Modify: `router_log_analyze.py:10492-10606` (operational text renderer)
- Modify: `router_log_analyze.py:10872-10904` (`emit_report_outputs`)
- Modify: `router_log_analyze.py:11316-11386` (`emit_nonpersistent_report`)
- Modify: `router_log_analyze.py:11903-11913` (persistent output selection in `main`)

- [ ] **Step 1: Add failing verbose renderer tests**

For the same synthetic TP-Link report, assert `render_text_report(report, verbose=True)` appends a `Technical Details` section after the operational briefing containing:

- every component count;
- every event-type source-record count, with component, humanized event key, optional vendor code, outcome, and count in aligned/wrapped rows rather than comma-separated prose;
- every availability check with a human-readable label and reason;
- occurrence counts, clock segments, boot resolution/warnings, parser warnings, coverage records/lines/LAN/WAN evidence;
- database and run-persistence details;
- complete client identifiers and event-type lists already permitted by the existing text renderer.

Assert that these technical rows are absent from default output. Show both source-record and semantic-occurrence totals when they differ, name each unit, and pin component/outcome/event-type reconciliation to the source-record total.

- [ ] **Step 2: Add failing CLI plumbing tests**

Add tests proving:

- `parse_args(["--verbose"]).verbose is True` and `--help` describes it as expanded TP-Link human-readable text evidence while stating that NETGEAR text remains unchanged;
- the persistent default text path passes `verbose=True` when invoked with `--verbose`;
- the identity-less non-persistent text path also honors `--verbose` without opening SQLite;
- `--report text,json --verbose` writes `.txt` content equal to `report_body + "\n"`, while stdout begins with that same body and then separately prints the `Generated reports:` notice; JSON remains valid and contains the same existing semantic values;
- `--json --verbose` emits JSON only and does not contaminate stdout with text;
- Markdown and HTML output are unchanged by `--verbose`.

Use temporary paths and synthetic logs only.

- [ ] **Step 3: Run verbose and CLI tests and verify RED**

Run the new node IDs with `.venv/bin/python -m pytest -q ...`.

Expected: FAIL because `--verbose`, the renderer parameter, and technical detail section do not yet exist.

- [ ] **Step 4: Implement verbose technical details**

Add a `verbose` branch to the TP-Link operational renderer. Reuse `router_report_summary_items(report)` as evidence input where appropriate, but render it as grouped technical sections rather than restoring the flat default dump. Add display maps for known check names and unavailable reasons, with `humanize_event_key` as a deterministic fallback for future keys.

Verbose output may expose internal check names parenthetically after the plain label, but the plain-language description comes first. Render all count collections from `router_activity`; never reconstruct per-type counts from `device_summary.event_types`.

- [ ] **Step 5: Plumb `--verbose` through every text path**

Add:

```python
parser.add_argument(
    "--verbose",
    action="store_true",
    help="Include expanded event and diagnostic details in TP-Link text output; NETGEAR text is unchanged.",
)
```

Then:

- add `verbose: bool = False` to `emit_report_outputs`; render the text body once, print it, and reuse that exact body for the `.txt` file so two terminal-width reads cannot diverge;
- pass `args.verbose` from `main` when emitting explicit reports and default persistent text;
- pass `args.verbose` from `emit_nonpersistent_report`;
- leave JSON, Markdown, and HTML renderer calls unchanged.

Do not add conflict validation for `--verbose` plus non-text formats. Ignoring it for NETGEAR compatibility text, already-exhaustive JSON, and other human report formats is simpler, safe, and documented.

- [ ] **Step 6: Run focused verbose/CLI tests**

Run the new verbose and CLI node IDs plus existing report-output and help tests:

```zsh
.venv/bin/python -m pytest -q \
  test_router_log_analyze.py::test_tp_link_cli_writes_consistent_markdown_html_and_json_reports \
  test_router_log_analyze.py::test_cli_version_and_help_describe_supported_router_contracts \
  test_router_log_analyze.py::test_help_examples_use_invoked_program_name
```

Expected: all selected tests PASS, with no text leakage into JSON stdout.

- [ ] **Step 7: Commit verbose support**

Inspect the staged file list and full staged diff for private data, then commit only the launcher and test changes.

```zsh
git commit -m "Add verbose router report details"
```

---

### Task 4: Align saved human reports, renderer contracts, and documentation

**Files:**
- Modify: `test_router_log_analyze.py:4640-4815` and other TP-Link cross-renderer assertions surfaced by the focused/full suite
- Modify: `router_log_analyze.py:10609-10870` (`render_markdown_report` and `render_html_report`)
- Modify: `README.md` reporting and usage sections

- [ ] **Step 1: Add failing Markdown and HTML router-activity tests**

Using a synthetic TP-Link report with several router components, require both saved human renderers to:

- omit the `Router/System` row from Device Summary;
- include a Router Activity section/table with every component and its count;
- include a separate Router Event Types table with every event type, optional vendor code, component, outcome, and source-record count;
- reconcile component and event-type counts to `router_activity.source_record_count`;
- avoid placing the complete comma-separated event-type vocabulary in one table cell;
- retain all findings and existing router/snapshot/coverage evidence.

Do not redesign the rest of either saved format or add a verbose variant for them.

- [ ] **Step 2: Run the saved-renderer tests and verify RED**

Run the new Markdown/HTML node IDs with `.venv/bin/python -m pytest -q ...`.

Expected: FAIL because both current Device Summary tables still contain the `Router/System` event-type wall.

- [ ] **Step 3: Render counted router activity in Markdown and HTML**

Filter `SYSTEM_ACTOR` from the Device Summary rows in both renderers. For extended TP-Link reports, insert:

- a Router Activity component table sourced from `router_activity.component_counts`, sorted by descending count then humanized component name; and
- a Router Event Types table sourced from `router_activity.event_type_counts`, sorted by descending count and then stable semantic identity.

Show every component and event type because saved reports are self-contained and scrollable. Use ordinary table rows rather than comma-separated prose, and include optional vendor code and outcome without exposing raw messages. Keep existing NETGEAR Markdown and HTML contracts unchanged by applying this branch only when `has_extended_router_report(report)` is true.

- [ ] **Step 4: Update TP-Link cross-renderer contract tests without weakening evidence checks**

Revise `test_tp_link_report_contract_surfaces_router_snapshot_occurrence_and_coverage_facts` so it asserts:

- default text contains operational router/snapshot/change/finding information and plain-language consequential limitations;
- verbose text contains the detailed clock, parser, availability, and coverage evidence;
- Markdown and HTML retain their existing complete structured evidence while replacing the confirmed router-event device-summary wall with the counted component and event-type tables from Step 3;
- JSON preserves all existing keys/values and contains the additive activity-count projection.

Do not delete assertions simply because evidence moved from default to verbose. Move them to the renderer/detail level where the approved design requires them.

- [ ] **Step 5: Run the affected cross-renderer tests**

Run all tests containing `tp_link` and `report` in their node names using pytest collection/filtering, then run the complete `test_router_log_analyze.py` file if the filter passes.

Expected: all selected tests PASS. Any failure is investigated and fixed; no failure is dismissed as unrelated.

- [ ] **Step 6: Update README behavior and examples**

Document:

- default text is an operational briefing showing status, findings, snapshot state, baseline/change context, activity pulse, and consequential limitations;
- `--verbose` adds exhaustive human-readable event counts and technical evidence to TP-Link text reports; NETGEAR text remains unchanged;
- `--json` remains the complete structured record;
- a Clean status means no elevated result from available checks, not that unavailable checks were assumed normal;
- `--verbose` affects TP-Link text only, including `--report text,...`;
- source-record activity totals and semantic occurrence/novelty totals are distinct when persistence collapses duplicate source rows;
- saved Markdown and HTML reports remain self-contained and use counted tables rather than the router event wall;
- the tool remains local, single-user, single-process, and standalone.

Add a synthetic command example:

```zsh
router_log_analyze.py router-log.txt --router-instance home-router --verbose
```

Do not include real router names, firmware, client counts, paths, device data, or log excerpts.

- [ ] **Step 7: Run documentation consistency and sensitive-data checks**

Run:

```zsh
git diff --check
if rg -n '/(Users|home)/[^/[:space:]]+' README.md router_log_analyze.py test_router_log_analyze.py; then
  echo "Refusing delivery: an absolute user-home path appears in a changed product file." >&2
  exit 1
fi
```

Expected: both commands exit 0. The path scan is deliberately generic, contains no private search literals, and fails the step if it finds a match. Also inspect `git diff --name-only` and the complete `git diff` for router metadata, client/device information, private paths, log excerpts, generated reports, or other sensitive data that a generic pattern cannot identify.

- [ ] **Step 8: Commit saved-renderer, docs, and contract alignment**

Inspect the staged file list and full staged diff, then commit the README and any final test/renderer alignment changes.

```zsh
git commit -m "Document operational router reports"
```

---

### Task 5: Complete verification and handoff

**Files:**
- Verify only; modify code/tests/docs only if a failure exposes a real defect

- [ ] **Step 1: Run the entire project suite**

From `router-log-analyzer/`, run:

```zsh
.venv/bin/python -m pytest -q
```

Expected: every collected test passes with zero failures, errors, or skips introduced to bypass coverage. Investigate and fix every failure before continuing.

- [ ] **Step 2: Run the uv launcher fleet drift guard**

From the repository root (the parent of `router-log-analyzer/`), run:

```zsh
uv run --script tools/check_uv_headers.py
```

Expected: exit 0 and the registered `router-log-analyzer/router_log_analyze.py` header/dependency manifest remains valid.

- [ ] **Step 3: Run synthetic CLI smoke checks**

Use a temporary database and the tracked synthetic fixture. Run default text, verbose text, and JSON commands through the repository launcher. Verify:

- default text is compact and has no event wall;
- verbose text contains complete reconciled event counts;
- JSON parses successfully;
- no private runtime state or reports are written inside the repository.

Do not use or copy a private router log into the public repository. A private-log smoke may be performed only from its external location and must not print or commit sensitive contents.

- [ ] **Step 4: Inspect final history and worktree**

Run:

```zsh
git status --short --branch
git log --oneline --decorate -8
```

Expected: only intentional implementation commits are present and the worktree is clean. If safe unrelated user changes exist, leave them untouched and report them explicitly rather than staging them.

- [ ] **Step 5: Perform adversarial code review before delivery**

Review the complete implementation diff, using an independent reviewer when available. Address every valid correctness, readability, compatibility, privacy, and scope finding. Re-run the complete suite and uv guard after any code change.

- [ ] **Step 6: Final implementation commit only if review changes were required**

Inspect staged files and the complete staged diff for sensitive data before committing review fixes.

```zsh
git commit -m "Harden operational router reports"
```

Do not push, open a pull request, deploy the copied launcher, or modify the user's live database unless the user separately authorizes those delivery actions.
