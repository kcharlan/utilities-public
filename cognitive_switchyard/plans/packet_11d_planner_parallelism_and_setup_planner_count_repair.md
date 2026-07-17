# Packet 11D - Planner Parallelism and Setup Planner-Count Repair

## Why This Packet Exists

Packet `11C` repaired most of the Setup View contract, but packet `12` is still not truly UI-only. The design's Setup View includes a real planner-count control, and the planning architecture requires `1-N` planners in parallel. The live backend/runtime still serializes planning work, does not persist a session-scoped planner-count override, and would force packet `12` either to omit the control or to render a cosmetic field that the runtime ignores.

This repair packet finishes that setup-side and planning-side contract before the SPA lands so packet `12` can remain a consumer of an already-settled backend/runtime surface.

## Scope

- Add typed session-scoped `planner_count` overrides through the existing `sessions.config_json` field and expose them through backend session create/detail/list payloads as additive setup metadata.
- Define an effective planner-count value that is clamped to the selected pack's `phases.planning.max_instances` and remains absent/ignored when planning is disabled.
- Route the effective planner count into the existing planning runtime so planning-enabled sessions can launch up to `N` planner workers in parallel instead of always serializing intake items.
- Preserve packet-`08` planning recovery semantics (`claimed/` reversion, `review/` halt behavior, rerun safety) while adding bounded planning parallelism.
- Keep packet-`11` through `11C` route shapes stable apart from additive planner-count payload enrichment needed by packet `12`.

## Non-Goals

- No embedded HTML, React, Tailwind, or other packet-`12` frontend work.
- No new pack-manifest schema, planner-provider registry, or pack-author tooling changes.
- No redesign of resolution, execution, verification, or auto-fix semantics beyond consuming the repaired planner-count contract.
- No broad planning architecture rewrite beyond the bounded concurrency and setup transport needed to keep packet `12` backend-neutral.

## Relevant Design Sections

- `3.2` Planning (optional)
- `6.3.1.4` Setup View
- `6.4` Navigation
- `6.6` REST API Endpoints
- `7.3` Orchestrator Loop
- `10.3` Planning Phase Recovery
- `10.5` Session State Machine
- `10.6` Idempotency Guarantees by Operation

## Allowed Files

- `cognitive_switchyard/models.py`
- `cognitive_switchyard/planning_runtime.py`
- `cognitive_switchyard/orchestrator.py`
- `cognitive_switchyard/server.py`
- `tests/test_planning_runtime.py`
- `tests/test_orchestrator.py`
- `tests/test_server.py`

## Tests To Write First

- `tests/test_server.py::test_create_session_accepts_planner_count_override_and_returns_effective_planner_count`
- `tests/test_planning_runtime.py::test_planning_enabled_session_uses_effective_planner_count_up_to_pack_max_instances`
- `tests/test_planning_runtime.py::test_parallel_planning_preserves_claim_recovery_when_a_planner_fails`
- `tests/test_orchestrator.py::test_start_session_routes_session_planner_count_into_planning_runtime_without_changing_execution_contracts`

## Implementation Notes

- Reuse `sessions.config_json`; do not add a dedicated planner-count column.
- Keep a clear distinction between stored planner-count overrides and the effective planner-count value actually used for the run.
- Planner-count serialization should be additive and backward compatible with the existing packet-`11C` session payloads.
- Parallel planning must keep the packet-`08` atomic-claim contract: each planner claims exactly one intake item via filesystem move, and interrupted `claimed/` work must still return safely to `intake/`.
- Prefer a narrow bounded-concurrency implementation over a planning-runtime rewrite. The goal is to honor the design's parallel-planner contract without widening into unrelated provider or watcher work.
- Packet `12` should be able to render the Setup View's planner-count control and rely on it affecting real runtime behavior. If the implementation would still leave the control cosmetic, the repair is incomplete.

## Acceptance Criteria

- Backend session create/detail/list payloads accept, persist, and serialize planner-count overrides without regressing the existing packet-`11C` setup fields.
- The backend exposes an effective planner-count value clamped to the selected pack's planning limit and suitable for packet-`12` Setup View rendering.
- Planning-enabled sessions launch up to the effective planner-count planner workers in parallel, while planning-disabled sessions keep the existing `.plan.md` promotion behavior unchanged.
- Planning failures still preserve packet-`08` recovery guarantees: unfinished `claimed/` work returns to `intake/`, `review/` still halts before resolution, and reruns stay deterministic.
- Packet `11` through `11C` control routes and packet-`08` execution handoff semantics remain unchanged apart from additive planner-count setup enrichment.
- No packet-`12` HTML, React, or other frontend assets land in this repair packet.

## Validation Focus

- `.venv/bin/python -m pytest tests/test_planning_runtime.py tests/test_orchestrator.py -q`
- `.venv/bin/python -m pytest tests/test_server.py -q`
