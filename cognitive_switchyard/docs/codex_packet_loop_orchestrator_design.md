# Codex Packet Loop Orchestrator Design

## Purpose

This document describes the intent and operating model of `scripts/codex_packet_loop.zsh`.

It is not the product design for Cognitive Switchyard itself. It is the design for the meta-orchestrator that drives packetized implementation work against this repository using a supported agent CLI.

The goal is to make the automation understandable and maintainable without reverse engineering the shell script from scratch later.

## Scope

The orchestrator owns:

- packet bootstrap from the packetization playbook
- limited-horizon packet planning
- single-packet implementation
- single-packet validation
- periodic full-suite repository verification
- periodic cumulative drift audits
- optional per-stage profiling artifacts
- stage heartbeat monitoring, stall diagnostics, and idle-timeout enforcement
- optional cooperative stop requests
- optional auto-commit after validated packets

It does not own:

- the underlying Cognitive Switchyard product runtime
- packet content semantics beyond prompt contracts
- any direct project-specific business logic

## Inputs

Primary inputs:

- `docs/design_doc_packetization_playbook.md`
- `docs/cognitive_switchyard_design.md`
- `docs/implementation_packet_playbook.md`
- `plans/packet_status.md`
- `plans/packet_status.json`
- packet docs under `plans/`
- current repository state
- read-only reference material under `reference/work/`

## High-Level Flow

The orchestrator runs a constrained loop:

1. `bootstrap` if packetization artifacts are missing
2. `planner` when no actionable packet docs remain
3. `implementer` for exactly one packet
4. `validator` for exactly one packet
5. `full-suite verifier` periodically and at final completion
6. `drift auditor` periodically and at final completion

Normal steady-state operation is:

`plan -> implement -> validate -> maybe full suite verify -> maybe drift audit -> repeat`

## Stage Intent

### Bootstrap

Bootstrap converts the product design doc plus packetization playbook into the working packet system:

- `docs/implementation_packet_playbook.md`
- `plans/packet_status.md`
- `plans/packet_status.json`
- initial packet docs

Bootstrap only runs when those core artifacts are missing.

### Planner

Planner extends the packet frontier by producing only the next narrow horizon of packet docs. It must reconcile packet tracker state with the live codebase instead of trusting stale plan docs.

### Implementer

Implementer works on exactly one packet. It is instructed to stay within packet scope, write tests first, and avoid starting later packets.

### Validator

Validator is packet-local. It reviews the current packet implementation for correctness, regressions, weak tests, and scope creep. It may repair issues inside packet scope and is responsible for advancing packet status to `validated` or `blocked`.

The validator prompt is intentionally biased toward convergence:

- gather packet-scope evidence
- run the packet tests and obvious adjacent regressions
- once decisive evidence is available, finish immediately

The validator should not continue broad design-doc or reference-system exploration after passing tests unless a specific unresolved packet-scope issue requires it. This prompt constraint exists because the most common validator failure mode is not bad test execution, but post-test reasoning drift that never returns to the required audit/tracker update steps.

### Drift Auditor

Drift audit is cumulative rather than packet-local. It compares:

- current validated frontier
- packet ladder and tracker state
- cumulative code changes
- design-doc constraints
- implementation playbook contracts

This stage exists to catch broad architectural drift that packet-local validation can miss.

### Full-Suite Verifier

Full-suite verification is repo-wide rather than packet-local. It runs the repository's full test command at a fixed cadence so regressions that escape packet-local validation are caught before they compound across several packets.

## Full-Suite Verification Cadence

The orchestrator runs a repo-wide full-suite verification pass:

- every `FULL_TEST_INTERVAL` newly validated packets
- immediately after any drift audit that returns `repair_now`
- once at the end when the project reaches completion

The default command is:

- `.venv/bin/python -m pytest tests -v`

The persisted scheduler state lives in:

- `audits/full_suite_state.json`

## Drift Audit Cadence

The orchestrator runs drift audit:

- every `DRIFT_AUDIT_INTERVAL` newly validated packets
- once at the end when the project reaches completion

The persisted scheduler state lives in:

- `audits/drift_audit_state.json`

This state tracks the last audited validated count, next due point, and whether the final audit has already been satisfied.

## Drift Audit Result Contract

Every drift audit writes:

- `audits/drift_audit_<label>.md`
- `audits/drift_audit_<label>.json`

The JSON result contains:

- `status`: `pass | repair_now | repair_packet | halt`
- `severity`: `low | medium | high`
- `effort`: `small | medium | high`
- `summary`
- `fixes_applied`
- `validation_rerun`
- `repair_packet_id`
- `repair_packet_doc`
- `notes`

Interpretation:

- `pass`: continue normally
- `repair_now`: apply the architecturally unambiguous correction immediately, then rerun targeted validation and a full-suite verification pass
- `repair_packet`: create a narrowly scoped repair packet immediately after the validated frontier, update trackers, and continue the run against that new packet
- `halt`: stop only because the issue requires an operator-level architectural decision
- Repair packet IDs sort by numeric prefix plus optional uppercase suffix, so a drift-created packet such as `11A` runs after `11` and before `12`.

## State Model

The orchestrator depends on tracker state rather than in-memory progress:

- packet state comes from `plans/packet_status.json`
- actionable packet selection is recomputed each cycle
- drift-audit cadence comes from `audits/drift_audit_state.json`
- timeout retry counts come from `audits/stage_retry_state.json`
- stop intent comes from a filesystem flag

This is what allows a run to be interrupted and restarted without requiring a bespoke session database.

## Stall Diagnostics and Timeouts

Every active Codex stage emits heartbeat summaries derived from parsed JSON events. If a stage goes quiet for long enough, the orchestrator captures a compact stall diagnostic under the current run directory:

- `<stage_slug>.stall_diagnostic.json`

The diagnostic includes:

- stage name
- agent PID
- current parsed state summary
- event-log size and modification time
- output-file size and modification time
- a `ps` snapshot for the live CLI process
- the tail of the raw event log

This is intentionally low-noise. The normal console output stays at heartbeat granularity; the extra artifact is only written when a stage appears stalled.

Two thresholds control this:

- `STALL_DIAGNOSTIC_AFTER`
- `STALL_DIAGNOSTIC_INTERVAL`

Separate idle timeouts control when a stage is forcibly terminated:

- `VALIDATOR_IDLE_TIMEOUT`
- `DRIFT_AUDIT_IDLE_TIMEOUT`

When an idle timeout fires, the orchestrator:

1. writes a fresh stall diagnostic
2. writes a timeout marker under the current run directory
3. sends `TERM`
4. waits briefly
5. escalates to `KILL` if needed

The goal is not to guess the root cause. The goal is to make a silent stall survivable and diagnosable.

## Stage Profiling

The orchestrator can also emit compact profiling artifacts when explicitly enabled:

- `PROFILE_STAGES=true`

When profiling is enabled, each stage writes:

- `automation_logs/<timestamp>/<stage_slug>.profile.json`

and the run appends a compact ledger entry to:

- `automation_logs/<timestamp>/stage_profiles.jsonl`

These profiles are intended for orchestration tuning rather than correctness validation. They capture:

- wall-clock stage duration
- CLI family, resolved model choice, and service-tier setting when applicable
- prompt path, byte size, and content hash
- output path, byte size, and content hash
- event-log size and parsed event counts
- command-execution counts derived from the JSON event stream
- first-event timing
- time to first command start
- time to first command completion
- time from last command completion to turn completion
- time from last event arrival to process exit
- final parsed state summary
- whether the stage timed out or produced stall diagnostics

The intent is to answer questions like:

- is the stage slow before issuing commands, during command execution, or after commands finish
- is a large prompt or event log correlating with bad behavior
- are validators and drift audits spending disproportionate time relative to implementation work

Profiling is off by default because it is an operator diagnostic aid, not part of the core control flow.

## Timeout Retry Policy

Idle timeout enforcement is paired with a small retry budget rather than an immediate hard stop.

Persisted retry state lives in:

- `audits/stage_retry_state.json`

Timeout handling for validator and drift-audit stages is:

1. first timeout: write timeout report artifacts and retry once
2. second timeout for the same stage identity: halt the loop

This is intentionally conservative:

- a single transient CLI stall should not force operator intervention
- repeated stalls on the same packet/stage are treated as genuine blockers

Timeout reports are written under `audits/` as durable operator artifacts.

## Stop Semantics

The orchestrator supports a cooperative stop flag:

- request stop with `stop`
- clear it with `clear-stop`

The flag is checked after stage boundaries, not mid-stage. This is deliberate. The automation avoids interrupting an active CLI stage and instead exits cleanly after the current stage completes.

For an already-running shell process that loaded an older version of the script, new stop behavior does not apply retroactively.

## Auto-Commit Semantics

When `AUTO_COMMIT_VALIDATED=true`, the orchestrator commits durable repo state as the loop advances.

This includes:

- after packet validation:
  - packet-scoped files derived from the packet doc's `Allowed Files`
  - `plans/packet_status.md`
  - `plans/packet_status.json`
  - the packet validation audit note under `audits/`
  - any newly created durable `plans/` and `audits/` artifacts
- after bootstrap, planner, drift audit, and full-suite verification:
  - newly changed durable planning and audit artifacts under `docs/implementation_packet_playbook.md`, `plans/`, and `audits/`
- after a drift audit that returns `repair_now` and then passes its required post-repair full-suite verification:
  - the stage-local code and test changes introduced by that repair, based on the drift-audit stage's git delta
  - any still-dirty durable audit artifacts from that same stage

The intent is that ephemeral run output stays ignored while the durable orchestration record does not pile up as unstaged changes during long runs.

Auto-commit path selection filters out empty path entries before calling `git add`. This avoids false fatal pathspec errors when a post-stage commit hook finds no remaining dirty paths.

This is still opt-in because auto-committing in a dirty worktree can be risky if the file-selection rules are wrong or if a packet doc is inaccurate.

## CLI Selection and Model Controls

The orchestrator currently supports two CLI families:

- `AGENT_CLI=codex`
- `AGENT_CLI=claude`

Codex stages use:

- `MODEL_NAME`
- `SERVICE_TIER`
- per-stage reasoning effort variables such as `PLANNER_EFFORT`, `VALIDATOR_EFFORT`, `AUDIT_EFFORT`
- `PROFILE_STAGES`

`SERVICE_TIER=fast` is passed through as a Codex config override for each non-interactive stage.

This is treated as an execution-shape knob rather than a contract knob. If a stage begins hanging or degrading more often under `SERVICE_TIER=fast`, operators can rerun without that override before changing prompts or loop policy.

Claude stages use the user's configured shell wrappers:

- `CLAUDE_SONNET_COMMAND`
- `CLAUDE_OPUS_COMMAND`

Routing is effort-based:

- `medium` routes to the Sonnet wrapper
- `high` and `xhigh` route to the Opus wrapper

Claude does not use `SERVICE_TIER`. The orchestrator preserves the requested stage effort for routing, but only passes through a Claude `--effort` flag when that level is natively supported by the CLI.

## Generated Artifacts

Operational artifacts are written to:

- `automation_logs/<timestamp>/` for per-run prompts, event logs, and last messages
- `automation_logs/<timestamp>/` for per-run event timelines used by profiling
- `automation_logs/<timestamp>/` also contains stall diagnostics and timeout markers when stages go idle
- `automation_logs/<timestamp>/` contains optional per-stage profiles and a run-level profile ledger when profiling is enabled
- `audits/` for validator and drift-audit reports
- `audits/` for full-suite verification reports
- `audits/` also stores durable timeout reports and retry scheduler state

The automation log directory is ephemeral run output. The audit directory is part of the durable orchestration record.

## Artifact Tracking Policy

The orchestrator intentionally produces two different artifact classes:

- Durable repo artifacts that should normally be committed:
  - `plans/packet_status.md`
  - `plans/packet_status.json`
  - packet docs under `plans/packet_*.md`
  - packet validation reports under `audits/packet_*_validation.md`
  - drift audit reports under `audits/drift_audit_*.md` and `audits/drift_audit_*.json`
  - full-suite verification reports under `audits/full_suite_verification_*.md` and `audits/full_suite_verification_*.json`
- Ephemeral operator/runtime artifacts that should remain ignored:
  - `automation_logs/`
  - scheduler state files such as `audits/drift_audit_state.json`, `audits/full_suite_state.json`, and `audits/stage_retry_state.json`
  - one-off scratch directories or probes that are not part of the packet ladder

Rationale:

- The `plans/` files are part of the canonical delivery state and must survive branch switches, pauses, and future rebuilds.
- Audit and verification reports are the durable evidence trail explaining why packets were validated, repaired, or blocked.
- `automation_logs/` are high-volume execution traces useful for debugging and profiling, but they are not the canonical record and will overwhelm the repo if committed routinely.

## Resumability and Idempotency

The orchestrator is intended to be resumable at stage boundaries:

- if interrupted after implementation but before validation, a rerun should resume at validation
- if interrupted after validation, a rerun should continue from the next packet
- if interrupted before a drift audit completes, packet tracker state remains authoritative and the run can continue safely
- if validator or drift audit is terminated by idle-timeout enforcement, the packet remains at its pre-stage durable tracker state and the retry policy determines whether the stage is retried or surfaced as blocked

This is not perfect transactional idempotency. It is practical stage-boundary resumability based on durable tracker files.

## Known Tradeoffs

- Drift audit is triggered after validated packets, not before beginning the next packet. This favors simpler trigger logic over earliest-possible enforcement.
- The stop flag is stage-boundary only. This avoids corrupting active work but can delay exit until a long validator or drift audit finishes.
- Auto-commit relies on packet docs accurately listing `Allowed Files`. If the packet boundary docs drift from reality, commit selection can become too narrow or too broad.
- Timeout/retry hardening makes stalls survivable, but it does not by itself explain the underlying CLI failure mode. It is an operational guardrail, not a root-cause fix.
- The orchestrator is implemented in zsh for pragmatism and portability within the repo, not because shell is the ideal long-term language for this logic.

## Operator Interface

The script's built-in help is the intended operator reference for commands and environment toggles:

```bash
./scripts/codex_packet_loop.zsh --help
```

This should be kept current enough that a separate step-by-step user manual is unnecessary for normal use. The help text includes the main commands plus example invocations for non-obvious toggles such as:

- `AGENT_CLI=claude`
- `SERVICE_TIER=fast`
- `AUTO_COMMIT_VALIDATED=true`
- `DRIFT_AUDIT_INTERVAL=<n>`
- `STALL_DIAGNOSTIC_AFTER=<seconds>`
- `VALIDATOR_IDLE_TIMEOUT=<seconds>`
