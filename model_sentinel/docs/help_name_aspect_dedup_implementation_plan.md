# Help Invocation Name and Aspect Deduplication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every CLI help example reflect the actual invocation name and remove discovered Models aspects that duplicate canonical provider fields.

**Architecture:** Resolve the display command once while building the argparse tree, using `sys.argv[0]` for scripts/zipapps and a specific package-`__main__.py` detection for module execution. In the aspect catalog, retain canonical aspects as authoritative and suppress discovered raw paths only when the exact provider/path identity is already represented canonically.

**Tech Stack:** Python 3.11+ stdlib, argparse, SQLite JSON1, pytest; all Python commands run inside the project `.venv`.

---

## File map

- `model_sentinel/cli.py` — invocation-name resolution and all argparse usage/example/version display text.
- `tests/test_cli.py` — unit and subprocess coverage for renamed executables, module invocation, help text, and version output.
- `model_sentinel/browse/aspects.py` — canonical-path identity collection and discovered-path suppression.
- `tests/test_browse_aspects.py` — catalog identity/deduplication and distinct-path retention coverage.

No schema, stored snapshots, hash format, API route, or frontend component changes are required.

### Task 1: Resolve the displayed CLI command from the invocation

**Files:**
- Modify: `model_sentinel/cli.py` (`build_parser` and parser epilogs)
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Add failing invocation-name unit tests**

Add focused tests for a private resolver accepting an explicit `argv0` for deterministic coverage:

- `/opt/tools/renamed-sentinel` → `renamed-sentinel`
- `/checkout/model_sentinel/__main__.py` → `python -m model_sentinel`
- empty string and unusable basename values → `model-sentinel`

Also parameterize root and each subcommand help (`scan`, `history`, `changes`, `providers`, `browse`, `healthcheck`) with `sys.argv[0]` monkeypatched to `/opt/tools/renamed-sentinel`. Assert usage and every command example use `renamed-sentinel`, and that no command-position `model_sentinel` remains. Update the configuration-free version test to expect the resolved name.

- [ ] **Step 2: Add a failing module-invocation integration test**

Run `[sys.executable, "-m", "model_sentinel", "--help"]` in a subprocess from the project directory. Assert exit 0, `usage: python -m model_sentinel`, and module-form examples. This is the binding proof for the approved module behavior; do not infer it solely from a unit test.

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
source .venv/bin/activate
pytest tests/test_cli.py -q
```

Expected: the new tests fail because `build_parser()` and its epilogs still hard-code `model_sentinel` and no resolver exists.

- [ ] **Step 4: Implement one invocation-name resolver**

Add a side-effect-free helper in `model_sentinel/cli.py`, conceptually:

```python
def _invocation_name(argv0: str | None = None) -> str:
    value = sys.argv[0] if argv0 is None else argv0
    path = Path(value) if value else None
    if path and path.name == "__main__.py" and path.parent.name == "model_sentinel":
        return "python -m model_sentinel"
    if path and path.name not in {"", ".", "..", "__main__.py"}:
        return path.name
    return "model-sentinel"
```

The executor must inspect `cli.py` imports and reuse its existing `Path` import. In `build_parser()`, resolve the command once and use it for:

- root `ArgumentParser(prog=...)`;
- root epilog and first-run command;
- every subparser epilog example;
- `--version` display prefix.

Use interpolated strings or a small formatting helper so there is one resolved value, not repeated calls. Do not alter internal logger names, module/package names, database filenames, or runtime messages outside the approved parser/help/version scope.

- [ ] **Step 5: Run Task 1 verification**

Run:

```bash
source .venv/bin/activate
pytest tests/test_cli.py -q
./model-sentinel --help
./model-sentinel scan --help
python -m model_sentinel --help
```

Expected: tests pass; launcher help uses `model-sentinel`; module help uses `python -m model_sentinel`; no help example instructs users to run `model_sentinel` as an executable.

- [ ] **Step 6: Inspect and commit Task 1**

Inspect `git diff --check`, the staged file list, and the complete staged diff for sensitive data. Commit only the Task 1 code/tests with:

```text
Use the invoked executable name in CLI help
```

### Task 2: Suppress discovered aspects already represented canonically

**Files:**
- Modify: `model_sentinel/browse/aspects.py` (`build_aspect_catalog`)
- Modify: `tests/test_browse_aspects.py`

- [ ] **Step 1: Replace duplicate-preserving assertions with failing identity tests**

Update the fixture-backed tests to assert:

- `example-provider:input_price` exists and its representative field is `pricing.prompt`;
- `example-provider:path:pricing.prompt` does not exist;
- `example-provider:context_window` exists;
- `example-provider:path:context_length` does not exist;
- unrelated discovered paths such as `supported_parameters` and `benchmarks.design_arena.score` remain.

The old raw-`pricing.prompt` scaling assertion must not be weakened into a vacuous test; replace it with direct canonical price assertions plus retention coverage for a genuinely distinct discovered path.

- [ ] **Step 2: Add a failing same-label/different-path retention test**

Extend the chronology fixture setup or add a focused helper so the latest saved model makes `pricing.input` the canonical `input_price` representative while history also contains a sampled `pricing.prompt` field change. Assert both of these remain:

- canonical `example-provider:input_price` backed by `pricing.input`;
- discovered `example-provider:path:pricing.prompt`.

This proves deduplication uses exact `(provider_id, path)` identity rather than label, kind, unit, or equal series values.

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
source .venv/bin/activate
pytest tests/test_browse_aspects.py -q
```

Expected: duplicate-absence assertions fail because discovered canonical backing paths are still appended.

- [ ] **Step 4: Implement provider/path identity suppression**

In `build_aspect_catalog`:

1. Create a set of canonical `(provider_id, field_name)` identities.
2. While constructing each canonical aspect, add the exact representative field path to that set.
3. In the discovered-field loop, after resolving `provider_id` and `path` but before JSON type sampling, skip the row when `(provider_id, path)` is already canonical.

Keep canonical aspects authoritative. Do not deduplicate by display label, normalized column name alone, current value, or cross-provider path. Do not mutate provider profiles or delete stored field changes.

- [ ] **Step 5: Run Task 2 verification**

Run:

```bash
source .venv/bin/activate
pytest tests/test_browse_aspects.py tests/test_browse_api.py tests/test_browse_offline.py -q
```

Expected: all focused tests pass; API metadata no longer contains duplicate canonical/raw identities; offline frontend contracts remain green.

Perform a read-only real-database check by starting the installed or source browser with `--no-open --port 0`, fetching `/api/meta`, and confirming OpenRouter exposes the canonical IDs but not the exact raw duplicates for Input, Output, Cache read/write, Context length (model), and Max output. Distinct raw pricing fields must remain. Stop the server afterward.

- [ ] **Step 6: Inspect and commit Task 2**

Inspect `git diff --check`, the staged file list, and the full staged diff for sensitive data. Commit only the Task 2 code/tests with:

```text
Omit raw aspects represented by canonical fields
```

### Task 3: Final regression and delivery verification

**Files:**
- No production changes expected
- Update tests only if a genuine uncovered requirement is found; route any change back through RED/GREEN and re-review

- [ ] **Step 1: Run the complete suite**

Run:

```bash
source .venv/bin/activate
pytest
```

Expected: every collected test passes. Report and fix every failure before proceeding.

- [ ] **Step 2: Run launcher and module smoke checks**

Run:

```bash
source .venv/bin/activate
./model-sentinel --help
./model-sentinel --version
python -m model_sentinel --help
```

Expected: the launcher displays `model-sentinel`; module invocation displays `python -m model_sentinel`; build metadata remains intact.

- [ ] **Step 3: Audit the final diff and branch**

Confirm:

- `git diff --check` is clean;
- `git status --short --branch` shows no uncommitted changes;
- only the approved spec, plan, CLI/tests, and aspect/tests changed from `main`;
- no sensitive values appear in any commit or diff;
- the installed standalone is not rebuilt on the feature branch.

- [ ] **Step 4: Holistic review**

Review the full range from `main` to `HEAD` against the approved design and this plan, including CLI rename behavior, exact aspect identity, backward-compatible API/hash handling, and test quality. Fix all Important or higher findings and repeat verification.

## Acceptance criteria

- Running a renamed executable prints that basename in root/subcommand help, examples, first-run guidance, and version output.
- `python -m model_sentinel` prints the module-form command in help and examples.
- OpenRouter canonical/raw duplicate pairs are represented once, by the canonical aspect.
- Distinct raw paths remain available even when their label or values match a canonical aspect.
- No stored data or schema is changed.
- The complete test suite passes.
- The installed standalone remains untouched until the change is merged to `main` and explicitly deployed.
