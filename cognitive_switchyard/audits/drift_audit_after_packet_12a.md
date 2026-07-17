# Drift Audit After Packet 12A

Date: 2026-03-10
Audit label: `drift audit after packet 12A`
Highest validated packet: `12A`
Validated packet count: `18`
Overall result: `repair_now`

## Scope

Reviewed during this audit:

- `README.md`
- `docs/implementation_packet_playbook.md`
- `plans/packet_status.md`
- `plans/packet_status.json`
- Validated packet docs `plans/packet_00_canonical_contracts_and_scaffold.md` through `plans/packet_12a_history_summary_and_successful_session_trim_repair.md`
- Relevant design sections in scope through packet `12A`, especially:
  - `3.2`-`3.6`
  - `4.1`-`4.5`
  - `5.1`-`5.3`
  - `6.1`-`6.6`
  - `7.1`-`7.5`
  - `9`
  - `10.1`-`10.7`
  - `11`
- Live code under `cognitive_switchyard/`, `tests/`, and `switchyard`
- Existing audit artifacts affecting this review:
  - `audits/drift_audit_after_packet_11a.md`
  - `audits/drift_audit_after_packet_11b.md`
  - `audits/drift_audit_after_packet_11c.md`
  - `audits/drift_audit_after_packet_11d.md`
  - `audits/drift_audit_after_packet_12.md`
  - `audits/packet_12a_history_summary_and_successful_session_trim_repair_validation.md`
  - `audits/drift_audit_state.json`
  - `audits/full_suite_state.json`

## What Still Aligns

- The validated frontier is still packet `12A`; I did not find packet-`13` pack-tooling, release-notes generation, or operator-doc scope pulled forward into the live code.
- The packet-`11A` through `12A` repair chain remains in place:
  - live backend runtime events still feed the transport seam
  - reconnect-safe monitor/setup contracts remain backend-owned
  - setup runtime overrides and bounded planner parallelism still flow end to end
  - successful sessions still emit `summary.json` and trim to the packet-`12A` retained artifact set
- `plans/packet_status.md` and `plans/packet_status.json` correctly describe `12A` as the highest validated packet; no tracker downgrade or repair packet insertion was needed.

## Finding

### 1. Medium: the self-bootstrapping operator contract had drifted behind the validated `serve` surface

Evidence before repair:

- Packet `10` and design section `7.2` require a single self-bootstrapping operator entrypoint rather than a split "some commands bootstrap, some commands require manual venv activation" path.
- Packet `11` validated `serve` as part of the operator surface, so `./switchyard serve` is part of that same contract.
- Before this repair, the bootstrap gate still omitted `serve` from the command set and only probed `yaml`, which meant a clean machine could fall through to raw `fastapi` / `uvicorn` import failures instead of re-execing into the private bootstrap venv.

Why this mattered:

- The delivery path had drifted away from the packet-`10` contract: headless commands self-bootstrapped, but the validated backend operator path still depended on ambient Python state.
- This was architecturally unambiguous and bounded to the existing bootstrap seam, so it did not justify a repair packet or a strategic halt.

## Repair Applied Now

I repaired the drift inline.

Applied changes:

- Extended the bootstrap command gate to include `serve` and widened the default dependency probe set to cover `yaml`, `fastapi`, and `uvicorn` so the validated backend path now re-execs into the private venv when needed (`cognitive_switchyard/bootstrap.py:15-39`).
- Added targeted CLI coverage proving:
  - successful-session CLI tests now assert the packet-`12A` trimmed completion contract instead of the pre-`12A` untrimmed `done/` tree
  - `bootstrap_if_needed(...)` still re-execs for `start`
  - `bootstrap_if_needed(...)` also re-execs for `serve` when backend dependencies are missing
  (`tests/test_cli.py:289-449`)
- Repaired stale operator-facing README prose so it reflects the validated frontier through packet `12A` and includes `serve` in the current smoke surface (`README.md:145-177`).

No packet tracker changes were made because this audit returned `repair_now`, not `repair_packet`.

## Validation

Reran targeted validation after the repair:

- `.venv/bin/python -m pytest tests/test_cli.py tests/test_bootstrap_smoke.py -q`
  - Result: `15 passed in 4.47s`

The harness will run the required full-suite verification pass afterward.

## Conclusion

The cumulative path after packet `12A` had one meaningful remaining delivery-system drift: the validated `serve` command was still outside the self-bootstrapping contract, and adjacent docs/tests were lagging the repaired frontier. The issue stayed within the existing architecture and fit the audit's small-effort budget, so `repair_now` was the correct outcome.
