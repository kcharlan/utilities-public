# Future Multi-Vendor Support

This document captures a practical shape for evolving `router_log_analyze.py` from a NETGEAR-specific ingestion tool into a router-agnostic analyzer without rewriting the learning and anomaly engine.

**Status:** Historical proposal, partially implemented. The analyzer now has in-file adapters for NETGEAR and the observed TP-Link Archer system-log snapshot format, explicit/automatic format selection, router-instance-scoped persistence, capability-gated analysis, semantic snapshot deduplication, firmware-scoped router behavior, and cross-format reporting. The NETGEAR access-control importer remains NETGEAR-specific. No declarative profile runtime, Linksys adapter, or generic vendor plugin system has been added. The approved [TP-Link Router-Instance Support Design](docs/superpowers/specs/2026-08-25-tp-link-router-instance-support-design.md) supersedes this document wherever the two conflict.

The real TP-Link snapshot requirement validated the adapter principle while also requiring schema, capability, deduplication, router-instance, and reporting changes that this earlier proposal intentionally deferred.

## Current State

The analyzer has two distinct logical layers inside the standalone launcher:

1. Ingestion and normalization
   - Reads PDF or text exports
   - Parses router log lines
   - Imports router access-control config
   - Converts raw vendor-specific data into normalized `Event` objects and normalized device/config records

2. Analysis
   - Aggregates normalized events
   - Learns device and event behavior over time
   - Detects anomalies
   - Persists learned history in SQLite
   - Renders reports

The second layer is reusable through explicit capability gates. NETGEAR and TP-Link Archer parsing now sit behind adapters; config import remains NETGEAR-coupled.

## Original NETGEAR Coupling Analysis (Historical)

The following sections preserve the original proposal's pre-implementation assessment and phase wording for context; they do not override the status above.

The current implementation is NETGEAR-shaped in these areas:

- CLI wording refers to NETGEAR logs and exports.
- Log timestamp parsing expects the current NETGEAR timestamp format.
- Event label extraction assumes square-bracketed labels in the raw log line.
- Event normalization maps NETGEAR labels into internal event keys such as `DHCP_IP` and `WLAN_ACCESS_ALLOWED`.
- Event-family classification is based on those normalized keys.
- IP extraction includes a NETGEAR-specific DHCP pattern.
- Config import expects the current NETGEAR markdown export layout and column names.

That means the analyzer is not NETGEAR-only in principle, but it is NETGEAR-only at the parser boundary.

## Recommended Direction

Do not rewrite the anomaly engine.

Instead, introduce a vendor adapter boundary and keep a stable internal vocabulary. The adapter layer should translate raw vendor-specific input into the same normalized events and config structures the analyzer already uses.

The key design rule is:

- Vendor-specific labels vary.
- Internal canonical event keys should remain stable.

Examples:

- A Linksys DHCP lease event should still normalize to `DHCP_IP`.
- A Linksys "Wi-Fi client allowed" event should still normalize to `WLAN_ACCESS_ALLOWED`.
- A vendor-specific deny/block message should normalize to `WLAN_ACCESS_REJECTED`.

If that contract holds, most of the learning database and anomaly logic can stay intact.

## Recommended Architecture

Use a hybrid adapter model.

### 1. Adapter Boundary

Introduce a `RouterFormat` abstraction with responsibilities such as:

- Parse raw log text into normalized `Event` objects
- Parse vendor config exports into normalized device/config records
- Detect whether a given input likely matches the format

This can be done with Python classes, a small protocol, or simple functions grouped per format.

### 2. Stable Canonical Event Vocabulary

Keep internal event keys and families stable across vendors.

Examples of canonical event keys:

- `DHCP_IP`
- `WLAN_ACCESS_ALLOWED`
- `WLAN_ACCESS_REJECTED`
- `INTERNET_DISCONNECTED`
- `INTERNET_CONNECTED`
- `EMAIL_SENT`
- `LOG_CLEARED`

Examples of canonical event families:

- `DHCP`
- `WLAN_ALLOWED`
- `WLAN_REJECTED`
- `OTHER`

This is the compatibility layer that protects the rest of the system from vendor churn.

### 3. Hybrid Parsing Strategy

Support two kinds of adapters:

- Declarative profiles for simple formats
  - Timestamp regex and timestamp format
  - Noise-line patterns
  - Label extraction rules
  - Event-key mapping
  - Event-family mapping
  - IP extraction regex

- Python adapters for formats that need custom parsing
  - Multiline records
  - Irregular PDF extraction cleanup
  - Vendor-specific edge cases

This avoids forcing every future format into a purely regex-driven design.

## Original Phased Implementation Plan (Historical)

### Phase 1. Isolate NETGEAR Parsing Behind An Adapter

Goal:

- No behavior change
- Move current NETGEAR-specific parsing into a dedicated adapter layer

Work:

- Extract current log parsing rules into a `netgear` adapter
- Extract current config-import parsing into a `netgear` adapter
- Keep the same normalized `Event` output
- Keep the same SQLite schema
- Keep the same anomaly logic

Result:

- The current system still only supports NETGEAR, but the boundary exists

### Phase 2. Add Format Selection

Goal:

- Make the input format explicit and future-ready

Work:

- Add `--format netgear|auto|...`
- Default to `netgear` or `auto`
- Update help text and docs to say "router log" rather than "NETGEAR log" where appropriate

For `auto`, start simple:

- Try known format detectors in order
- Pick the first one that produces a plausible parse

Result:

- The CLI is ready for multiple router vendors without changing analysis behavior

### Phase 3. Add Declarative Profile Support

Goal:

- Reduce code required for closely related vendor formats

Work:

- Define a profile schema for timestamp parsing, label extraction, noise filtering, event mapping, and IP extraction
- Let an adapter load that profile and perform generic line-by-line parsing

Result:

- New vendor support may be mostly configuration when the export format is simple

### Phase 4. Add A Second Vendor

Goal:

- Validate the architecture against a real second router format

Work:

- Collect real sample exports
- Add a `linksys` adapter or profile
- Map vendor-specific raw events into the canonical event vocabulary
- Add sample fixtures and regression tests

Result:

- Confidence that the design generalizes beyond NETGEAR

### Phase 5. Generalize Config Import

Goal:

- Avoid the current assumption that all router access-control exports are the same markdown table

Work:

- Move config import behind the adapter boundary
- Normalize all imported device/config data into the existing internal structure

Result:

- Router replacement does not imply rewriting allow/block import logic

## What Should Not Change

These parts should remain stable unless a real vendor requirement forces a change. The TP-Link snapshot format is now that real requirement.

- Existing NETGEAR normalized behavior and canonical event meanings
- Portable device identity and device-history semantics when adapters declare equivalent evidence
- Existing NETGEAR anomaly severities, risk scoring, reports, and CLI behavior
- The standalone copy-installed launcher contract

The approved TP-Link design deliberately changes the SQLite schema, normalized parse result, capability gating, semantic deduplication, and report content so repeated router snapshots cannot corrupt the otherwise stable analysis model.

## Known Areas That Depend On Canonical Events

Some analysis behavior is intentionally keyed to canonical event names and families. In particular:

- DHCP counting
- DHCP burst suppression
- Cluster analysis, which currently uses DHCP activity as the cluster signal
- Internet-reset correlation, which uses WAN transitions plus synchronized DHCP/WLAN recovery activity

That is acceptable as long as new router formats map equivalent raw events into the same canonical event vocabulary.

## Testing Expectations For A Future Refactor

Any future parser-generalization work should include:

- Fixture-based tests for each supported vendor format
- Tests that different vendor exports normalize to equivalent canonical events when the behavior is equivalent
- Regression tests that existing NETGEAR parsing remains stable
- End-to-end tests that prove anomaly outputs remain unchanged for existing NETGEAR samples

The architecture should be considered successful only if the parser layer changes without destabilizing the learned behavior model.

## Selected Initial File Shape

Adapters remain logical classes inside `router_log_analyze.py`. This preserves the established single-file, copy-based installation contract. External profile files and required parser sidecars remain out of scope until another real format justifies changing that delivery model.

## Practical Recommendation

Implement the approved TP-Link design rather than the hypothetical Linksys phase ordering above. Isolate NETGEAR behavior behind the in-launcher adapter boundary, add the observed TP-Link format, and make only the persistence and analysis changes required by snapshot semantics. Do not add a generic declarative profile runtime in this phase.
