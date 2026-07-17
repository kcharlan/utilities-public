# Drift Audit After Packet 02

Date: 2026-03-09
Audit label: `drift audit after packet 02`
Highest validated packet: `02`
Overall result: `warn`

## Scope

Reviewed during this audit:

- `docs/implementation_packet_playbook.md`
- `plans/packet_status.md`
- `plans/packet_status.json`
- Validated packet docs:
  - `plans/packet_00_canonical_contracts_and_scaffold.md`
  - `plans/packet_01_pack_and_session_contract_parsing.md`
  - `plans/packet_02_task_artifact_parsing_and_scheduler_core.md`
- Relevant design sections already in scope for packets `00`-`02`:
  - `3.3`-`3.4`
  - `4.1`-`4.5`
  - `5.1`-`5.3`
  - `6.5`
  - `7.1`-`7.2`
  - `10.5`-`10.7`
  - `11`
- Live code under `cognitive_switchyard/`, `tests/`, `scripts/`
- Existing validation audits under `audits/`

## What Still Aligns

- The validated frontier in the live codebase is still packet `02`. No packet-`03`+ runtime modules (`state.py`, `worker_manager.py`, `orchestrator.py`, API, UI) have been introduced.
- The implementation still respects the packet boundaries for `00`-`02`: canonical naming/path scaffold, pure pack/session parsing, pure task-artifact parsing, and pure scheduler-core logic.
- Tracker state is internally consistent:
  - `plans/packet_status.md` and `plans/packet_status.json` both mark packets `00`-`02` as `validated`.
  - Both trackers correctly state that packet docs for the next horizon (`03` and `04`) are not present yet.
- Current packet-scoped validation remains green:
  - `.venv/bin/python -m pytest tests -v`
  - `./switchyard --help`
  - `./switchyard paths`
  - `.venv/bin/python -m cognitive_switchyard --help`

## Findings

### 1. Medium: resolution-phase defaults have drifted away from the intended architecture

Evidence:

- The design names `agent` as the default resolution mode in `docs/cognitive_switchyard_design.md:127`.
- The live manifest model and loader default resolution to `passthrough` instead:
  - `cognitive_switchyard/models.py:23`
  - `cognitive_switchyard/pack_loader.py:106`
- The tests reinforce that drift by asserting the `passthrough` default:
  - `tests/test_pack_loader.py:21`

Why this matters:

- Packet `01` is supposed to freeze pack-manifest contracts before runtime packets land.
- Defaulting to `passthrough` weakens the planned delivery path by normalizing "no resolver logic" as the baseline pack behavior, even though the design treats resolver analysis as the default and `passthrough` as the least-safe special case.
- If left in place, later packet work can build on the wrong contract and make packet `08` correction more expensive.

Recommended follow-up:

- Correct the resolution default in a deliberate contract-repair change before more pack fixtures, pack docs, or resolution-runtime work are added.
- Do not silently patch this inside a later runtime packet without updating the packet doc/tests that currently encode the wrong default.

### 2. Medium: packet-01 pack config accepts custom progress markers, but packet-02 parsing hardcodes the default marker

Evidence:

- The manifest contract already accepts a configurable `status.progress_format`:
  - `docs/cognitive_switchyard_design.md:274`
  - `cognitive_switchyard/models.py:76`
  - `cognitive_switchyard/pack_loader.py:234`
- The task-artifact parser ignores that contract and only recognizes literal `##PROGRESS##` lines:
  - `docs/cognitive_switchyard_design.md:303`
  - `cognitive_switchyard/parsers.py:21`
  - `cognitive_switchyard/parsers.py:106`

Why this matters:

- This is a cross-packet contract gap between packet `01` and packet `02`.
- A pack can currently validate with a non-default progress marker even though the only parser available for later worker/runtime packets cannot consume it.
- If this is not corrected before worker-lifecycle work begins, packet `05` and the later backend/UI packets will be built on a parser contract that is narrower than the accepted manifest surface.

Recommended follow-up:

- Add an explicit packet-scoped correction before worker/progress-consuming runtime work starts: either make progress parsing accept the configured marker, or narrow the manifest contract and document that only the default marker is supported for now.

### 3. Low: README overstated the live implementation frontier and advertised unsupported behavior

Evidence before repair:

- `README.md` claimed the root launcher was already self-bootstrapping, listed an unsupported `serve` smoke check, described `RELEASE_NOTES.md` emission, and still said only packets `00` and `01` were validated even though packet `02` is validated.

Repair applied during this audit:

- Updated `README.md` so it now reflects the actual packet-`02` surface, removes unsupported `serve`/bootstrap/release-notes claims, and accurately reports that scheduler-core logic is present while runtime/orchestration work is still absent.

Why this was safe to fix now:

- The change was documentation-only, tightly scoped, and did not alter trackers or packet boundaries.

## Fixes Applied

- Updated `README.md` to align the human-facing project status and validation guidance with the live packet-`02` implementation.

## Validation Rerun After Fix

Targeted smoke rerun after the README repair:

- `./switchyard --help`
- `./switchyard paths`
- `.venv/bin/python -m cognitive_switchyard --help`

## Conclusion

The repository has not drifted into future-packet implementation or invalid tracker state, but two medium-severity contract issues are now visible across packets `01` and `02`:

- wrong default resolution semantics
- accepted-but-unusable custom progress marker configuration

Those should be corrected intentionally before the implementation flow moves deeper into runtime packets. The README drift was repaired during this audit.
