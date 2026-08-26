# Operational Terminal Report Design

**Date:** 2026-08-26

**Status:** Approved design; awaiting implementation planning.

**Scope:** Replace the TP-Link terminal report's flat diagnostic dump with a compact operational briefing. Preserve analysis, scoring, persistence, JSON evidence, and established NETGEAR semantics.

## Problem

The current TP-Link text report exposes almost every available metric at the same level. It also renders the synthetic `Router/System` subject through the ordinary device-summary path. That produces a comma-separated list of every distinct router event type without per-type counts, useful grouping, or terminal-width wrapping.

The output is technically complete but operationally poor: findings, everyday activity, first-run context, coverage limitations, parser evidence, and storage details compete for attention. Merely wrapping the existing list would make it longer without making it easier to understand.

## Goals

The default terminal report must let a local user answer, in order:

1. Is anything wrong?
2. What changed?
3. What does the router and client snapshot look like now?
4. What ordinary activity establishes today's operating pulse?
5. Which meaningful conclusions could not be drawn from this export?

It must preserve counts and important evidence without flooding the terminal with exhaustive event keys or parser internals. Findings must never be hidden. Normal activity must remain visible so gradual or daily changes are perceptible even when the risk score is zero.

## Non-Goals

- Changing parsing, detection, severity, scoring, learning, deduplication, or persistence behavior.
- Building an interactive terminal UI, pager, dashboard, or external reporting service.
- Adding a configurable report-template framework.
- Adding a separate debug subsystem without a demonstrated need.
- Treating missing telemetry as an observed zero.
- Changing JSON into a presentation-oriented format.
- Exposing private router logs or real router metadata in repository fixtures or documentation.

## Considered Approaches

### Wrap the current output

This is the smallest code change, but it preserves the incorrect hierarchy and still omits event counts. Rejected.

### Show findings only

This makes clean reports short, but hides the ordinary pulse needed to notice operational changes. Rejected.

### Tiered operational report

Selected. The default is a concise operational briefing. `--verbose` expands the human-readable evidence, while `--json` remains the exhaustive structured record.

## Default Report Structure

### 1. Status

Lead with router label, overall status, risk score, and a one-sentence result. A clean run says that no findings were detected. A non-clean run summarizes finding counts by severity and directs attention immediately to the findings section.

### 2. Findings

When findings exist, show them directly after status. Each entry includes severity, subject, concise explanation, and the relevant count or time evidence. Do not render separate empty finding-index, finding-detail, and risk-breakdown sections. When there are no findings, the status sentence is sufficient; do not print multiple `None` sections.

### 3. Router Snapshot

Show the router's friendly label, model/hardware, firmware, export time, and available client counts. Present the total, Wi-Fi, and wired counts together on one line. Omit internal router-instance identifiers.

### 4. Baseline and Change

Explain the comparison state in plain language:

- first comparable snapshot;
- compared with a stated number of prior snapshots;
- snapshot counts within or outside the learned range;
- novel, repeated, and report-only occurrences.

Novelty, source coverage, and learned ownership remain distinct. Report-only occurrences remain visible as reviewed current evidence, but the report must not imply they were added to calendar or time-based history. Calendar ranges are derived only from trusted timestamps.

### 5. Activity Pulse

Remove `Router/System` from the ordinary device summary and render it as router activity. The default shows:

- total router event count;
- number of active router components;
- the most active components with counts;
- a compact outcome/state summary when meaningful;
- noteworthy mapped security or health activity even if its count is small.

The renderer aggregates from the parsed occurrence data; it must not infer counts from the existing set of distinct `event_types`. Component and outcome ordering is deterministic. The default may collapse a low-volume tail into a phrase such as `6 other components — 9 events`, but the collapsed total must reconcile exactly with the displayed overall total.

Known client activity remains a separate compact device pulse. Show name, total activity, DHCP count, and incident-explained count only when relevant. A genuinely new device remains a finding at the effective policy severity and is never buried in the pulse.

### 6. Attention and Limitations

Show only limitations that materially affect what a user could conclude. Translate internal capability keys and reasons into short user language, combine entries with the same practical impact, and avoid presenting a long list of detector names.

Examples of consequential limitations include:

- client identities were not exported, so new-device and rejected-device checks were unavailable;
- client DHCP telemetry was not exported;
- this router/firmware profile has no explicit security-event mapping;
- expected LAN or WAN header evidence was absent;
- no trusted timestamps were available for calendar comparison.

Do not promote internal clock segment identifiers, sequence ranges, boot-candidate mechanics, database paths, or raw coverage dictionaries into the default report. A limitation must not be phrased as a normal result or a measured zero.

## Detail Levels

### Default text

The operational briefing described above. It must be readable without horizontal scrolling in a terminal at least 80 columns wide. Long values wrap under their labels. Sections with no content are omitted rather than printed as `None`.

### `--verbose`

Add human-readable supporting evidence after the operational briefing:

- complete component and event-type counts;
- all availability checks with plain-language reasons;
- occurrence, clock, boot, parser, and coverage details;
- database path and run-persistence details;
- complete device identifiers already permitted by the existing text report.

Verbose output is still a report, not a raw debug log. Event counts use aligned rows or compact wrapped groups rather than comma-separated prose.

### `--json`

Remain unchanged as the exhaustive renderer-neutral report contract. The implementation may add renderer-neutral aggregate data only if it is additive and necessary to prevent presentation code from reconstructing analysis semantics.

No `--debug` option is added in this scope. If future troubleshooting requires execution traces rather than report evidence, that should be designed from a concrete diagnostic need.

## Architecture and Data Flow

Keep report presentation inside the standalone `router_log_analyze.py` launcher. Do not add required sidecar modules or runtime dependencies.

The implementation should introduce one renderer-neutral projection for operational activity counts, derived from the normalized events already available while building report data. The projection carries semantic values, not preformatted strings. Text presentation consumes that projection at either default or verbose detail level.

The report flow remains:

`parse and analyze -> build renderer-neutral report data -> render selected format`

Presentation code must not reclassify security findings, determine novelty, or create new detector semantics. Format-specific display ordering belongs at the presentation boundary. Existing Markdown and HTML rendering must remain correct; sharing the new aggregate projection is appropriate, but redesigning those formats is outside this change unless needed to prevent the same unreadable router-event wall.

Established NETGEAR analysis and output semantics remain intact. A TP-Link-specific operational text path is acceptable when that is the smallest safe change. Shared helpers should be used only where they simplify behavior rather than create a report framework.

## Error and Edge Behavior

- Narrow terminals wrap; they do not truncate counts or findings.
- Zero events produce a short explicit statement rather than an empty table.
- Missing component names fall into a stable `Other` group.
- Aggregated component, tail, and total counts must reconcile.
- If all body occurrences are repeated, say so plainly and avoid implying new router activity was learned.
- If timestamps are untrusted, current activity remains visible but calendar claims are withheld.
- If a report dictionary from a compatibility path lacks the additive aggregate projection, rendering degrades to a correct compact summary rather than failing.
- Color is not required; meaning must not depend on ANSI support.

## Documentation

Update the README's reporting section and command examples to explain the default operational briefing, `--verbose`, and `--json`. Documentation must distinguish ordinary router activity from findings and explicitly state that limitations represent unavailable checks rather than normal results.

## Testing and Acceptance Criteria

Use test-driven development. At minimum, tests must prove:

- a clean TP-Link report has one clear clean-status statement and no repeated empty findings sections;
- `Router/System` is absent from the device summary;
- router components are aggregated with counts and reconcile to the overall event count;
- the default output contains no comma-separated wall of event types;
- significant findings remain prominent and include their evidence;
- a new-device finding remains visible at its effective policy severity;
- limitations are plain-language, consequential, deduplicated, and never reported as zero;
- first-snapshot, prior-history, repeated-snapshot, and untrusted-time wording is accurate;
- default output wraps at 80 columns without losing content;
- `--verbose` contains exhaustive event-count and diagnostic evidence omitted from default output;
- `--json` remains compatible;
- established NETGEAR report contracts remain passing;
- the complete repository test suite and uv launcher drift guard pass.

The delivered default report should be scannable in roughly one terminal screen for an ordinary clean snapshot. Additional lines are warranted by actual findings, meaningful changes, or consequential limitations—not by the number of internal detector or event keys.
