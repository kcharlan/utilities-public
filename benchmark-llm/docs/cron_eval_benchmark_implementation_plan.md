# Cron Evaluator Benchmark — Implementation Plan

## 1. Overview & decisions

This plan describes how to build a new `examples/cron-eval` benchmark for `benchmark-llm`. The benchmark asks a model to implement a single-function cron expression evaluator against a precise spec, then grades it against a hidden conformance suite of 100 deterministic test cases.

**Locked decisions:**

- **Source repo:** A fresh git repo at `/Users/example/source/cron-eval-beta`, parallel to `policy-engine-beta`. Initialized with one empty commit on `main` so the worktree machinery has a base to branch from.
- **Env vars (mirror policy-engine):**
  - `BENCH_CRON_EVAL_SOURCE_REPO` — path to the source repo
  - `BENCH_CRON_EVAL_OUTPUT_DIR` — output directory for run artifacts
  - `BENCH_CRON_EVAL_ADJUDICATOR_BIN` — adjudicator binary (default `cx`)
  - `BENCH_CRON_EVAL_ADJUDICATOR_MODEL` — pinned model id (optional)
  - `BENCH_CRON_EVAL_ADJUDICATOR_ARGS` — extra args appended to the adjudicator invocation
- **Grading split:** Deterministic validator owns the score. LLM adjudicator owns the narrative explanation only — must not propose score adjustments.
- **Default adjudicator:** `cx exec` invoked through `zsh -lic` so shell-defined wrappers resolve.
- **Runs per model:** 3 (matches policy-engine).
- **Run order:** breadth.

**What this benchmark tests that policy-engine does not:**

- Many independent edge cases (100 vs ~5 in policy-engine), so scores have real granularity.
- Subtle semantic correctness (POSIX dom/dow OR-rule, DST transitions, leap year rules) that separate "read the spec carefully" from "wrote a tutorial-grade implementation."
- A pure-function contract (no I/O, no CLI plumbing, no output-directory creation friction). Removes the largest noise sources observed in policy-engine.

## 2. Repo bootstrap

Create `/Users/example/source/cron-eval-beta` as a fresh git repo. Steps:

1. `mkdir /Users/example/source/cron-eval-beta`
2. `cd /Users/example/source/cron-eval-beta && git init -b main`
3. Create a minimal `README.md` at the repo root that:
   - Identifies this as the source repo for the `cron-eval` benchmark in `benchmark-llm`.
   - Notes that benchmark runs land on `bench/cron-eval/<model-slug>/<timestamp>__aNN` branches.
   - Points readers at `examples/cron-eval/` in the `benchmark-llm` repo for the actual benchmark definition.
4. `git add README.md && git commit -m "init"`

Do not pre-populate the repo with any cron implementation. The benchmark exposes its visible assets via the harness `visibility.expose` mechanism, copying them into the worktree at run time. The repo's job is just to host the result branches.

## 3. Benchmark package layout

Build under `examples/cron-eval/` in the `benchmark-llm` repo. Final layout:

```
examples/cron-eval/
  bench.yaml
  prompt.txt
  README.md
  report_template.md
  models-openrouter.txt          # optional, mirror policy-engine
  visible/
    spec.md
    examples.md
    starter_test.py
    .gitignore
  hidden/
    conformance/                 # 100 JSON test fixtures
      001_field_bounds_minute.json
      002_field_bounds_hour.json
      ...
      100_invalid_expr_garbage.json
    reference_impl.py            # known-good cron evaluator used to self-check the suite
    rubric.yaml
    adjudicator_prompt.md
  scripts/
    prepare.sh
    invoke_model.sh
    run_checks.py
    run_checks.sh
    adjudicate.sh
    render_adjudication_prompt.py
    render_report.py
    render_final_summary_prompt.py
    findings_io.py
    harness_metrics.py
```

Several scripts (`invoke_model.sh`, `prepare.sh`, `harness_metrics.py`, `findings_io.py`, `render_final_summary_prompt.py`) can be near-copies of their `policy-engine` counterparts with renamed env-var prefixes. Reuse aggressively rather than rewriting.

**Per `CLAUDE.md` "No Duplicate Logic":** before copying any helper from `policy-engine`, check whether the same logic could live in a shared `examples/shared/` location callable by both benchmarks. If yes, extract first, then call from both. Candidates: env-var resolution, adjudicator-wrapper invocation, harness metrics, findings IO, final summary rendering. The extraction can happen as a follow-on PR if it bloats this one.

## 4. The dialect spec

The cron dialect is defined precisely so models cannot defend a wrong implementation by claiming a different convention. The spec lives in `visible/spec.md`.

> **Authoritative source:** This section explains the dialect for plan readers. The verbatim content for `visible/spec.md` is in **Section 14.B**. Use 14.B as the source when authoring the file. If 14.B and the prose below ever drift, **14.B wins**.

### Fields

Five space-separated fields, in this order:

| Field | Range | Notes |
|---|---|---|
| minute | 0–59 | |
| hour | 0–23 | |
| dom (day of month) | 1–31 | |
| month | 1–12 | Names not accepted; numeric only. |
| dow (day of week) | 0–6 | 0 = Sunday. `7` is **not** accepted as Sunday. Names not accepted. |

Invalid number of fields → `InvalidCronExpr`.

### Field grammar

Each field is one of:

- `*` — any value in range
- A literal integer in range
- A range `a-b` where `a <= b`, both in range
- A list of any of the above, comma-separated, e.g. `1,5,10-15`
- A step expression `<base>/<step>` where:
  - `<base>` is `*`, a single integer, or a range `a-b`
  - `<step>` is a positive integer
  - When `<base>` is a single integer `n`, the resulting set is `{n, n+step, n+2*step, ...}` ∩ `[n, field_max]`
  - When `<base>` is `*` or a range, the set is generated from the base's start, incrementing by `step`, stopping at the base's end
- `?` — only valid in `dom` and `dow`, meaning "no opinion." See "DOM/DOW interaction" below.
- `L` — only valid in `dom`, meaning "last day of the given month."
- `W` — only valid in `dom`, immediately following an integer `n`, e.g. `15W`. Means "weekday (Mon–Fri) nearest to day `n` of the month, without crossing month boundaries." If `n` falls on a weekday, that's the answer. If on Saturday, use Friday unless that's in the previous month, in which case use Monday. If on Sunday, use Monday unless that's in the next month, in which case use Friday.

Steps with non-positive values → `InvalidCronExpr`. Ranges with `a > b` → `InvalidCronExpr`. Out-of-range literals → `InvalidCronExpr`.

### DOM/DOW interaction (POSIX OR-rule)

This is the most-violated rule in cron implementations. Be precise:

- If **both** `dom` and `dow` are restricted (neither is `*` and neither is `?`), a date matches if it satisfies **either** field. (POSIX semantics.)
- If `dom` is `*` or `?`, only `dow` matters.
- If `dow` is `*` or `?`, only `dom` matters.
- If both are `*`, both effectively any.
- `?` is identical in match semantics to `*` for these purposes; it exists only to make the "the other field is the one I care about" intent explicit. `?` may not be used in both dom and dow simultaneously.

### Function contract

```python
def next_fires(
    expr: str,
    after: datetime,
    n: int = 1,
    tz: str = "UTC",
) -> list[datetime]:
    ...
```

- `expr`: the 5-field expression.
- `after`: a timezone-aware `datetime` (caller's responsibility). The function must reject naive datetimes with `InvalidCronExpr("after must be timezone-aware")`.
- `n`: number of fire times to return; must be `>= 1`. Otherwise `InvalidCronExpr`.
- `tz`: IANA timezone name. The function interprets the cron schedule as wall-clock time in `tz`, then returns timezone-aware datetimes in that same zone. Default `"UTC"`.
- Returns the next `n` fire times **strictly after** `after`, in ascending order.

### Timezone & DST

The schedule is wall-clock in `tz`. During DST transitions:

- **Spring-forward (skipped hour):** if a scheduled fire falls in the skipped local interval, the fire is silently skipped. (Do not retro-fire and do not slide it forward.)
- **Fall-back (duplicated hour):** if a scheduled fire falls during the duplicated hour, fire **once** at the first occurrence (the pre-transition wall-clock instant) and not again at the second occurrence.

For cron expressions that fire every minute or every few minutes, this means the duplicated hour appears once in the result list and the skipped hour appears not at all.

### Error class

A single exception type:

```python
class InvalidCronExpr(ValueError):
    """Raised for any malformed expression or invalid argument."""
```

All malformed inputs — bad fields, out-of-range integers, bad steps, bad chars, naive datetimes, `n < 1`, unknown timezone, both `?` simultaneously — raise `InvalidCronExpr`. Do not raise `ValueError`, `TypeError`, generic `Exception`, or library-specific errors at the API boundary.

### Out of scope

These are explicitly NOT part of the dialect:

- Year field
- Seconds field
- Jenkins `H` (hash) operator
- Quartz `#` operator (Nth weekday-of-month)
- Month or day names (`JAN`, `MON`, etc.)
- `@yearly` / `@daily` / `@reboot` / other macros
- Negative offsets like `L-2`

If a model implements them, they are ignored by the conformance suite (no bonus, no penalty) — but extra surface increases risk of breaking the spec'd behavior, so the spec discourages it.

## 5. Hidden conformance suite

100 fixtures under `hidden/conformance/`. Each fixture is one JSON file.

> **Authoritative fixtures:** The 25 `errors`, 10 `dom_dow_interaction`, and 8 `timezone_dst` fixtures are inlined verbatim in **Sections 14.F, 14.G, and 14.H**. Author the remaining 57 fixtures (across the other five categories) following the schema, weights, and authoring guidance in this section. Do not modify the inlined fixtures except to correct any `expected.value` that disagrees with the reference impl during the self-check (Section 11 Step 1) — see the per-section note in 14.G/14.H for the cross-check procedure.

```json
{
  "id": "042_dst_fallback_repeat_handled_once",
  "category": "timezone_dst",
  "weight": 2,
  "input": {
    "expr": "30 * * * *",
    "after": "2026-11-01T05:00:00+00:00",
    "n": 5,
    "tz": "America/Los_Angeles"
  },
  "expected": {
    "kind": "fires",
    "value": [
      "2026-11-01T01:30:00-07:00",
      "2026-11-01T02:30:00-07:00",
      "2026-11-01T03:30:00-08:00",
      "2026-11-01T04:30:00-08:00",
      "2026-11-01T05:30:00-08:00"
    ]
  }
}
```

For invalid-expression cases:

```json
{
  "id": "099_invalid_expr_negative_step",
  "category": "errors",
  "weight": 1,
  "input": {
    "expr": "*/-1 * * * *",
    "after": "2026-01-01T00:00:00+00:00",
    "n": 1,
    "tz": "UTC"
  },
  "expected": {
    "kind": "raises",
    "value": "InvalidCronExpr"
  }
}
```

The `weight` field is the points the case contributes when correct. The 100 cases sum to **100 points**.

### Category breakdown

Author the fixtures so the per-category point totals match the rubric:

| Category | Cases | Points | Avg weight |
|---|---:|---:|---:|
| `field_validity_basic` | 20 | 20 | 1.0 |
| `step_alignment` | 10 | 15 | 1.5 |
| `lists_and_ranges` | 8 | 10 | 1.25 |
| `dom_dow_interaction` | 10 | 15 | 1.5 |
| `l_and_w` | 7 | 10 | 1.43 |
| `calendar_edges` | 12 | 15 | 1.25 |
| `timezone_dst` | 8 | 10 | 1.25 |
| `errors` | 25 | 5 | 0.2 |
| **Total** | **100** | **100** | |

Errors are intentionally low-weight per case because they are easier to get right; the 25 cases ensure no single error type goes untested.

### Coverage guidance for fixture authoring

`field_validity_basic`: hit each of the 5 fields with single literals, with `*`, with simple ranges. Different hours, days, months, dows, with `after` chosen so the expected fires are unambiguous.

`step_alignment`: include `*/n` for `n in {2, 5, 7, 13}`; include `a/n` from a non-zero base; include `a-b/n` where `b` is not a multiple of `n` from `a`.

`lists_and_ranges`: include lists of literals, lists with ranges, lists with steps, and combinations.

`dom_dow_interaction`: 4 cases with both restricted (OR-rule fires); 2 with dom-only restricted; 2 with dow-only restricted; 2 with `?` in one field.

`l_and_w`: include `L` for Feb in a leap and a non-leap year; include `W` where `n` is a weekday, Saturday, Sunday, the 1st (Sunday → Monday, never December 31), the last day (Saturday → Friday, never the 1st of next month).

`calendar_edges`: month rollover, year rollover, leap-day fires, leap-day-on-non-leap-year (`29 2 * * *` should skip non-leap years), large `n` requesting many fires across a year boundary.

`timezone_dst`: include both spring-forward (skipped) and fall-back (duplicated) cases for `America/Los_Angeles`, `Europe/London`, `Australia/Sydney`. Include one case where `tz="UTC"` so DST is irrelevant.

`errors`: each well-known error type gets at least one case — wrong number of fields, out-of-range literals, bad step values, bad ranges, double-`?`, naive datetime, `n=0`, `n<0`, unknown tz, garbage chars.

### Reference implementation

`hidden/reference_impl.py` contains a known-good `next_fires` implementation that the test suite passes 100/100 against. This serves two purposes:

- During fixture authoring, you compute `expected` by running the reference impl, eyeballing the result, then committing it.
- During CI / pre-deploy validation of the benchmark itself, you can run `python hidden/reference_impl.py --self-check` (or equivalent) which loads every fixture and asserts the reference impl matches `expected`. This catches "I authored the fixture wrong" before any model run.

The reference impl is **not exposed to the model** — it is in `hidden/`. The harness does not copy `hidden/` into the worktree.

## 6. Validation script (`run_checks.py`)

Inputs (positional CLI args, matching the policy-engine pattern):

1. `run_dir` — where the validator writes outputs
2. `workspace` — the model's worktree
3. `hidden_dir` — where the harness placed `hidden/` content

Behavior:

1. Import the model's `cron_eval` module from `<workspace>/cron_eval.py`. If the import fails, write a `score.json` with score 0 and a single `import_error` validation record, then exit 0 (the run must complete; a 0 score is a valid result).
2. Load every JSON fixture from `<hidden_dir>/conformance/`.
3. For each fixture:
   - Parse `input.after` into a tz-aware datetime.
   - Call `cron_eval.next_fires(**input)` inside a try/except.
   - Compare actual to expected:
     - For `expected.kind == "fires"`: actual must be a list of timezone-aware datetimes equal to the expected list, element-by-element. Equality is on `(year, month, day, hour, minute, utcoffset)`.
     - For `expected.kind == "raises"`: actual must be an `InvalidCronExpr` (or subclass) — verify by `type(exc).__name__` and matching the model's `cron_eval.InvalidCronExpr` class. A different exception type is a fail. No exception raised is a fail.
4. Tally points per category and total.

Outputs:

- `<run_dir>/score.json`:
  ```json
  {
    "score": 87,
    "max_score": 100,
    "category_breakdown": {
      "field_validity_basic": {"earned": 20, "max": 20},
      "step_alignment": {"earned": 12, "max": 15},
      ...
    },
    "import_ok": true
  }
  ```
- `<run_dir>/category_breakdown.json` — same content as the `category_breakdown` key, top-level.
- `<run_dir>/validation_summary.json`:
  ```json
  {
    "total_cases": 100,
    "passed_cases": 87,
    "failed_cases": [
      {
        "id": "042_dst_fallback_repeat_handled_once",
        "category": "timezone_dst",
        "weight": 2,
        "expected": {"kind": "fires", "value": [...]},
        "actual": {"kind": "fires", "value": [...]},
        "diff_summary": "expected 5 fires, got 6; second 02:30 was emitted in addition to the first"
      },
      {
        "id": "099_invalid_expr_negative_step",
        "category": "errors",
        "weight": 1,
        "expected": {"kind": "raises", "value": "InvalidCronExpr"},
        "actual": {"kind": "fires", "value": ["2026-01-01T00:01:00+00:00"]},
        "diff_summary": "expected InvalidCronExpr; got fires list (length 1)"
      }
    ],
    "per_category": {
      "field_validity_basic": {"passed": 20, "failed": 0},
      ...
    }
  }
  ```
- A `commands.jsonl`-compatible record via the harness; the script itself just writes the three JSON files above.

`run_checks.sh` is a thin wrapper that activates the venv (created by `prepare.sh`) and runs `python scripts/run_checks.py "$@"`.

The validator must **never** modify model code, never install missing packages on its own (that's `prepare.sh`'s job), and never re-run failed cases with adjustments. Each fixture is one shot, deterministic.

`diff_summary` is generated by the validator (deterministic prose like the examples above) — not by an LLM. It exists so the adjudicator does not have to re-derive what failed. Keep it short and factual.

## 7. Adjudication wiring

Three files compose the adjudication step:

### `scripts/render_adjudication_prompt.py`

Renders `<run_dir>/adjudication_prompt.txt` from a template plus three inputs:

- `<run_dir>/score.json`
- `<run_dir>/category_breakdown.json`
- `<run_dir>/validation_summary.json`
- The model's source from the workspace (read `cron_eval.py` and any other `.py` files at the workspace root, up to a documented size cap — say 10 KB total — to avoid blowing the adjudicator's context).

The template lives at `hidden/adjudicator_prompt.md` and contains the rules below.

### `hidden/adjudicator_prompt.md`

> **Verbatim content in Section 14.E.** The summary below describes the prompt's design; do not derive the prompt content from this summary — copy 14.E.

The adjudicator is told:

- The score is **fixed** at the value in `score.json`. It must not propose adjustments.
- Its job is to produce `report.md` with header table, score breakdown, failure analysis, likely root causes, concrete fix suggestions, and strengths.
- Output is markdown. No JSON envelope. No score adjustments. No "what could be a different reasonable score."

The prompt explicitly says: **"You may not change the score. The score is `<score>/100`. State it as given. Your job is to explain the failures, not relitigate them."**

### `scripts/adjudicate.sh`

Bash. Steps:

1. Run `render_adjudication_prompt.py`.
2. Resolve the adjudicator binary, model, and extra args from env vars:
   - `bin = ${BENCH_CRON_EVAL_ADJUDICATOR_BIN:-cx}`
   - `model_arg = ${BENCH_CRON_EVAL_ADJUDICATOR_MODEL:+--model $BENCH_CRON_EVAL_ADJUDICATOR_MODEL}`
   - `extra_args = ${BENCH_CRON_EVAL_ADJUDICATOR_ARGS:-}`
3. Compose the command. For `cx` and `codex`, the canonical form is `<bin> exec $model_arg $extra_args` and the prompt is fed on stdin.
4. Invoke through `zsh -lic '<command>'` so shell-defined wrappers from `~/.zshrc` resolve.
5. Pipe stdout into `<run_dir>/report.md`. Capture stderr into `<run_dir>/adjudication.stderr.log`.
6. If the adjudicator fails (non-zero exit, empty output), still write a minimal `report.md` from the deterministic data so the run is not blocked. The score is already in `score.json` regardless.

Include a comment block at the top of `adjudicate.sh` showing the three override patterns:

```bash
# Use a different adjudicator binary:
#   BENCH_CRON_EVAL_ADJUDICATOR_BIN=cc bench run examples/cron-eval ...
#
# Pin a specific model:
#   BENCH_CRON_EVAL_ADJUDICATOR_MODEL=openrouter/anthropic/claude-opus-4-7 bench run ...
#
# Switch to higher-reasoning mode:
#   BENCH_CRON_EVAL_ADJUDICATOR_ARGS='--reasoning-effort high' bench run ...
```

The adjudicator is a separate benchmark step (named `adjudicate`); it can use the same or different model than the one being benchmarked, exactly like policy-engine.

## 8. `bench.yaml` manifest

```yaml
type: repo_task
id: cron-eval
runs: 3
run_order: breadth
output_dir: ${BENCH_CRON_EVAL_OUTPUT_DIR:-~/Documents/benchmark-llm/cron-eval}

workspace:
  kind: git_worktree
  source_repo: ${BENCH_CRON_EVAL_SOURCE_REPO}
  commit_outputs: true

visibility:
  expose:
    - visible/**
    - prompt.txt
  hide:
    - hidden/**

executor:
  kind: cli
  command: ./scripts/invoke_model.sh

execution_defaults:
  timeout_sec: 3600
  inactivity_timeout_sec: 900
  retries:
    max_attempts: 2
    backoff_sec: 20

steps:
  - name: prepare
    run: ./scripts/prepare.sh
  - name: execute
    use_executor: true
  - name: validate
    run: ./scripts/run_checks.sh
  - name: adjudicate
    run: ./scripts/adjudicate.sh

scoring:
  output: score.json
```

Notes:

- No `mutation_probe` step. The 100-case conformance suite is more rigorous than mutation testing for this domain, and adding mutation introduces noise.
- `output_dir` defaults are inline so the benchmark works without env vars (handy for smoke tests), but the documented run-command sets `BENCH_CRON_EVAL_OUTPUT_DIR` explicitly.

## 9. `prompt.txt` (model-facing)

> **Verbatim content:** The exact `prompt.txt` to write is in **Section 14.A**. Do not paraphrase, condense, or expand it. The notes below explain what the prompt is doing so plan readers understand the design; they are not authoring instructions.

The prompt should:

- State that the model is implementing a single Python module.
- State the function signature exactly (copy from `visible/spec.md`).
- Tell the model to read `spec.md` for the dialect and `examples.md` for worked examples.
- Mention that `starter_test.py` runs locally with `pytest` if the model wants a sanity check, but is not the grading suite.
- State the file the model must produce: `cron_eval.py` at the workspace root.
- State the error class name and that it must subclass `ValueError`.
- State that no third-party dependencies are required; standard library only. The `zoneinfo` module is available (Python 3.9+).
- State scope discipline: implement only the documented dialect. Year fields, seconds, `H`, `#`, month/day names, and `@macro` shortcuts are out of scope.
- Be neutral on internal structure. Helpers, dataclasses, multiple files are fine.
- Tell the model that grading is automated and deterministic — no "be readable" pleas. The spec is the contract.

The prompt should NOT:

- Mention output directories, JSON output, or stdout tables. There are none.
- Tell the model to write extensive tests. (`starter_test.py` is provided as a sanity check; the model can extend it but is not graded on it.)
- Reveal the conformance categories or per-category weights. The model should infer coverage from the spec.

## 10. `visible/` content

> **Verbatim content:** Every file under `visible/` (except `.gitignore`, specified below) has authoritative content in Section 14. Use those sections as the source of truth.

### `spec.md`

The full dialect spec. **Verbatim content in Section 14.B.** This is the contract.

### `examples.md`

Eight worked examples covering a basic minute schedule, a step expression, a list, a DOM/DOW OR case, an `L` case, a `W` case, a DST fall-back case, and an invalid-expression case. **Verbatim content in Section 14.C.**

### `starter_test.py`

A pytest file the model can run locally to confirm import and signature. **Verbatim content in Section 14.D.** The starter cases overlap with the hidden suite intentionally — it is a smoke test, not an independent set.

### `.gitignore`

Standard Python gitignore: `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.venv/`, `venv/`, `*.egg-info/`. Do NOT ignore `cron_eval.py` or `*.py` at the root.

## 11. Test-of-the-test plan

Before running this benchmark against any real model, verify the benchmark itself is internally consistent.

### Step 1: Reference impl self-check

Run `python hidden/reference_impl.py --self-check` (or equivalent script). Loads every fixture, computes `actual` via the reference impl, asserts `actual == expected`. If anything fails, the fixture is wrong, not the impl. Fix the fixture.

### Step 2: Validator end-to-end with reference impl

In a temp directory:

1. Create a fake "model output" by copying `hidden/reference_impl.py` to `cron_eval.py` (same module name the validator imports).
2. Run `python scripts/run_checks.py <run_dir> <workspace> <hidden_dir>`.
3. Assert `score.json` reports 100/100.
4. Assert `validation_summary.json` reports 0 failed cases.

### Step 3: Validator end-to-end with intentional mutations

Create three more "fake models," each a mutated copy of the reference impl that introduces one specific bug. **Exact mutation diffs are in Section 14.J.** The expected score impacts below are derived from the verbatim fixture weights in Sections 14.F/G/H:

- Mutation A: drop the POSIX OR-rule (use AND instead). Assert `score.json` shows in the range 88–92 and `dom_dow_interaction` earned 5/15. (The four both-restricted cases at 2.5 each = 10 points lost.)
- Mutation B: skip the DST fall-back duplicate handling. Assert `timezone_dst` earned 6/10. (The three fall-back cases tz_01/tz_04/tz_07 fail; the spring-forward and baseline cases pass.)
- Mutation C: raise `ValueError` instead of `InvalidCronExpr`. Assert `errors` is 0/5.

This confirms the conformance suite actually catches the bugs it is supposed to catch, in the categories it is supposed to attribute them to.

### Step 4: Adjudicator smoke

Run the full benchmark once with the reference impl as the "model." Adjudicator should produce a `report.md` that:

- States score 100/100.
- Lists no failure analysis (because nothing failed).
- Notes strengths across all categories.

Then run with Mutation A. Adjudicator should produce a report that:

- States score ~85/100, **does not invent a different score**.
- Identifies DOM/DOW OR-rule as the failure pattern.
- Suggests checking the dom/dow combine logic in the source.

This validates the adjudicator prompt's "explain, don't relitigate" constraint.

### Step 5: Cross-run summary smoke

Run the benchmark with three "models": reference impl, Mutation A, Mutation B. Confirm `summary.md` correctly aggregates the three runs and identifies the per-mutation pattern.

Only after Step 5 passes is the benchmark ready for real model runs.

## 12. Sequencing

Recommended build order for the executor agent. **Section 14 supplies authoritative content for several of these steps; copy it verbatim where indicated rather than re-deriving it.**

1. Bootstrap `cron-eval-beta` repo (Section 2).
2. Author `hidden/reference_impl.py` from the algorithmic spec in **Section 14.I**. The reference impl is the authority on what `expected` should be.
3. Write `visible/spec.md` from **Section 14.B verbatim**. Then verify the reference impl behavior matches the spec — if they disagree, fix the impl.
4. Write `visible/examples.md` from **Section 14.C verbatim** and `visible/starter_test.py` from **Section 14.D verbatim**. Run the starter tests against the reference impl and confirm they pass.
5. Author the 43 inlined fixtures from **Sections 14.F, 14.G, 14.H verbatim**. Run the Step 1 self-check (Section 11) — any disagreement is either an authoring error in 14 or a reference-impl bug. Prefer the reference impl; correct fixture `expected.value` to match.
6. Author the remaining 57 fixtures in the other five categories using the reference impl to compute `expected`. Run Step 1 self-check after each batch of ~20.
7. Write `scripts/run_checks.py` and verify Section 11 Step 2 passes.
8. Write the three mutation copies from **Section 14.J verbatim** and verify Section 11 Step 3 passes.
9. Write `hidden/adjudicator_prompt.md` from **Section 14.E verbatim**, plus `scripts/render_adjudication_prompt.py` and `scripts/adjudicate.sh`.
10. Verify Section 11 Step 4 passes.
11. Author `scripts/render_final_summary_prompt.py` (adapt from policy-engine's version).
12. Verify Section 11 Step 5 passes.
13. Write `prompt.txt` from **Section 14.A verbatim**. Author `bench.yaml` (Section 8 already has it verbatim), `README.md`, `report_template.md`.
14. Final smoke: run with `-m demo-model` and a stub executor script that emits the reference impl. Confirm artifacts land where expected.

## 13. Out of scope for v1

Deferred — call out explicitly if the executor wants to add them:

- Performance grading (e.g., "must compute 1000 fires in under 100 ms"). Real, but adds noise from machine variation.
- Property-based testing inside the conformance suite. Hypothesis-style tests would inflate fixture authoring effort and add nondeterminism.
- Cross-language support. Python only.
- Custom dialect knobs (e.g., a benchmark variant that uses Quartz semantics instead of POSIX). Worth considering as a v2 to differentiate models that train heavily on one variant.
- "No future fires" handling. The spec explicitly says schedules are assumed to keep firing indefinitely (e.g., `0 0 30 2 *` is out of scope). The reference impl raises `InvalidCronExpr` after iterating ~50 years without a fire as a safety guard against infinite loops, but no fixture exercises this branch and no behavior is contractually required for never-firing combos. If v2 wants to test this, the spec must first specify the expected behavior (raise vs return `[]` vs other) and a fixture must enforce it.

---

## 14. Authoritative artifacts

This section contains verbatim content for files where wording is load-bearing or where pattern-following has a high risk of judgment leak. Copy these into the named files exactly. Where a file is "verbatim," do not paraphrase, condense, expand, or reformat.

### 14.A `prompt.txt` (verbatim)

```
You are implementing a cron expression evaluator in Python.

Build the project in the current directory.

Goal
Implement a single function that returns the next N times a cron expression will fire after a given datetime, in a specified timezone. The function must follow the dialect spec in spec.md exactly.

Required artifact
- A Python module `cron_eval.py` at the workspace root.
- The module must expose a function with this exact signature:

  def next_fires(expr: str, after: datetime, n: int = 1, tz: str = "UTC") -> list[datetime]:
      ...

- The module must expose an exception class with this exact name and base:

  class InvalidCronExpr(ValueError):
      """Raised for any malformed expression or invalid argument."""

- `datetime` is `datetime.datetime` from the standard library. `n` is `int`. `tz` is an IANA timezone name (string).

Where the contract lives
- spec.md is the contract. Read it carefully. It defines the dialect, the DOM/DOW interaction rule, the L and W operators, DST handling, and the error class.
- examples.md shows worked examples for the most subtle cases. Use them to confirm your understanding.
- starter_test.py is a small pytest file you can run locally as a sanity check. It is NOT the grading suite. Passing it does not imply your implementation is correct.

Output
- Return a list of timezone-aware `datetime` objects in the requested `tz`, in ascending order, strictly after `after`. Do not include `after` itself in the result.
- Do not print anything. Do not write any files. Do not invoke any external commands.

Dependencies
- Standard library only. The `zoneinfo` module is available (Python 3.9+).
- No third-party packages.

Scope discipline
- Implement only the dialect documented in spec.md.
- Year fields, seconds fields, Jenkins `H`, Quartz `#`, month or day name aliases (JAN, MON, etc.), and `@yearly`/`@daily`/`@reboot` style macros are NOT part of the dialect. Do not implement them. They will not be tested and they increase the surface for accidentally breaking the spec'd behavior.

Internal structure
- Internal structure of the module is up to you. Helper functions, dataclasses, or splitting into additional modules in the workspace root are all fine, as long as `cron_eval.py` exposes the required `next_fires` function and `InvalidCronExpr` class.

Errors
- For any malformed expression, out-of-range field, invalid step or range, naive `after` datetime, `n < 1`, unknown timezone, or simultaneous `?` in both DOM and DOW, raise `InvalidCronExpr`.
- Do not raise `ValueError`, `TypeError`, or any other exception type at the API boundary. `InvalidCronExpr` subclasses `ValueError`, so callers can still catch `ValueError` if they want.

Grading
- Grading is automated and deterministic. There is no human review of code style or readability. The contract is the contract; clear code is welcome but not graded.
```

### 14.B `visible/spec.md` (verbatim)

```markdown
# Cron Expression Dialect

This is the authoritative spec for the cron dialect this benchmark uses. The grading suite enforces it exactly. Do not assume any other dialect.

## Function

```python
def next_fires(
    expr: str,
    after: datetime,
    n: int = 1,
    tz: str = "UTC",
) -> list[datetime]:
    ...
```

- `expr`: a five-field cron expression (see "Fields" below).
- `after`: a timezone-aware `datetime`. A naive datetime raises `InvalidCronExpr`.
- `n`: number of fire times to return; must be `>= 1`. Otherwise `InvalidCronExpr`.
- `tz`: an IANA timezone name (string). Default `"UTC"`.

Returns a list of `n` timezone-aware `datetime` objects in `tz`, in ascending order, all strictly after `after`. The list is exactly length `n` (the schedule is assumed to keep firing indefinitely; you do not need to handle "no more fires ever").

## Error class

```python
class InvalidCronExpr(ValueError):
    """Raised for any malformed expression or invalid argument."""
```

This is the only exception type the function may raise. Any malformed input, invalid argument, unknown timezone, or other usage error must raise `InvalidCronExpr`.

## Fields

Five space-separated fields, in this order:

| Field | Range | Notes |
| --- | --- | --- |
| minute | 0–59 | |
| hour | 0–23 | |
| dom (day of month) | 1–31 | |
| month | 1–12 | Numeric only. Names like `JAN` are NOT accepted. |
| dow (day of week) | 0–6 | 0 = Sunday. `7` is NOT accepted as Sunday. Names like `MON` are NOT accepted. |

A wrong number of fields raises `InvalidCronExpr`.

## Field grammar

Each field is one of:

- `*` — any value in range.
- A literal integer in range.
- A range `a-b` where `a <= b`, both in range.
- A list of any of the above, comma-separated, e.g. `1,5,10-15`.
- A step expression `<base>/<step>` where:
  - `<base>` is `*`, a single integer, or a range `a-b`.
  - `<step>` is a positive integer.
  - When `<base>` is a single integer `n`, the resulting set is `{n, n+step, n+2*step, ...}` ∩ `[n, field_max]`.
  - When `<base>` is `*`, the set is `{field_min, field_min+step, field_min+2*step, ...}` ∩ `[field_min, field_max]`.
  - When `<base>` is a range `a-b`, the set is `{a, a+step, a+2*step, ...}` ∩ `[a, b]`.
- `?` — only valid in `dom` and `dow`. Means "no opinion." See "DOM/DOW interaction" below.
- `L` — only valid in `dom`. Means "last day of the given month."
- `W` — only valid in `dom`, immediately following an integer `n`, e.g. `15W`. Means "weekday (Mon–Fri) nearest to day `n` of the month, without crossing month boundaries." If `n` falls on a weekday, that's the day. If on Saturday, use the Friday before it (unless that would land in the previous month, in which case use the Monday after). If on Sunday, use the Monday after (unless that would land in the next month, in which case use the Friday before).

The following are invalid and raise `InvalidCronExpr`:
- Steps with non-positive values.
- Ranges with `a > b`.
- Out-of-range literals.
- Unknown characters.
- `L` or `W` in fields other than `dom`.
- `?` in fields other than `dom`/`dow`.
- A `?` in both `dom` and `dow` simultaneously.

## DOM/DOW interaction (POSIX OR-rule)

This is the most-violated rule in cron implementations. Be precise:

- If **both** `dom` and `dow` are restricted (neither is `*` and neither is `?`), a date matches if it satisfies **either** field. (POSIX semantics.)
- If `dom` is `*` or `?`, only `dow` matters.
- If `dow` is `*` or `?`, only `dom` matters.
- If both are `*`, both effectively any.
- `?` is identical in match semantics to `*` for these purposes; it exists only to make "the other field is the one I care about" intent explicit. `?` may not be used in both DOM and DOW simultaneously.

## Timezone & DST

The schedule is wall-clock in `tz`. Fire times are returned as timezone-aware datetimes in `tz`.

During DST transitions:

- **Spring-forward (skipped hour):** if a scheduled fire falls in the skipped local interval, the fire is silently skipped. Do not retro-fire and do not slide it forward.
- **Fall-back (duplicated hour):** if a scheduled fire falls during the duplicated hour, fire **once** at the first occurrence (the pre-transition wall-clock instant, `fold=0`) and not again at the second occurrence (`fold=1`).

For schedules that fire every minute or every few minutes, the duplicated hour appears once in the result list and the skipped hour appears not at all.

An unknown timezone name (`zoneinfo.ZoneInfoNotFoundError` or equivalent) raises `InvalidCronExpr`.

## Strictly-after semantics

`after` is exclusive. If `after` is itself a fire time, it is not included in the result; the result starts at the next subsequent fire time.

## Out of scope

These are NOT part of this dialect:

- Year field (six-field cron).
- Seconds field (six-field cron).
- Jenkins `H` (hash) operator.
- Quartz `#` operator (Nth weekday of month).
- Quartz `L-N` (last day minus N).
- Month names (`JAN`–`DEC`) or day names (`SUN`–`SAT`).
- `@yearly` / `@monthly` / `@weekly` / `@daily` / `@hourly` / `@reboot` macros.

The grading suite does not test these. Do not implement them.
```

### 14.C `visible/examples.md` (verbatim)

```markdown
# Worked Examples

Each example shows the input arguments to `next_fires` and the expected return value. Times are shown in the requested timezone. All examples assume the dialect in `spec.md`.

## Example 1 — every minute, UTC

```python
next_fires("* * * * *", datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC")), n=3, tz="UTC")
# returns:
# [datetime(2026, 1, 1, 0, 1, tzinfo=ZoneInfo("UTC")),
#  datetime(2026, 1, 1, 0, 2, tzinfo=ZoneInfo("UTC")),
#  datetime(2026, 1, 1, 0, 3, tzinfo=ZoneInfo("UTC"))]
```

`after` is exclusive, so `00:00` is not included.

## Example 2 — every 15 minutes, alignment from `*`

```python
next_fires("*/15 * * * *", datetime(2026, 1, 1, 0, 7, tzinfo=ZoneInfo("UTC")), n=3, tz="UTC")
# returns: 00:15, 00:30, 00:45 on 2026-01-01
```

Step from `*` aligns to `field_min` (here, minute 0).

## Example 3 — list expression in hour

```python
next_fires("0 8,12,17 * * *", datetime(2026, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC")), n=3, tz="UTC")
# returns: 12:00 and 17:00 on 2026-01-01, then 08:00 on 2026-01-02
```

## Example 4 — DOM/DOW OR-rule

```python
next_fires("0 12 1 * 1", datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC")), n=3, tz="UTC")
# returns: noon on the 1st of the month OR any Monday
```

When both `dom` (1) and `dow` (Monday) are restricted, a date matches if EITHER condition is true. The first three fires after midnight on 2026-01-01 (a Thursday) are: noon on 2026-01-01 (matches "1st"), then the next two Mondays at noon.

## Example 5 — last day of month with `L`

```python
next_fires("0 12 L * *", datetime(2026, 2, 1, 0, 0, tzinfo=ZoneInfo("UTC")), n=2, tz="UTC")
# returns: noon on the last day of February 2026, then noon on the last day of March 2026
```

`L` resolves to the actual last day of each month, accounting for leap years for February.

## Example 6 — weekday-nearest with `W`

```python
next_fires("0 9 15W * *", datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC")), n=2, tz="UTC")
# returns: 09:00 on the weekday closest to the 15th of January 2026, then the same in February
```

If the 15th is Saturday, fire on Friday the 14th. If Sunday, fire on Monday the 16th. Without crossing month boundaries.

## Example 7 — DST fall-back, fires once during duplicated hour

```python
next_fires(
    "30 * * * *",
    datetime(2026, 11, 1, 5, 0, tzinfo=ZoneInfo("UTC")),
    n=5,
    tz="America/Los_Angeles",
)
# returns 5 times, with the duplicated 01:30 local appearing exactly once.
```

On 2026-11-01, Los Angeles falls back from 01:59:59 PDT to 01:00:00 PST. The schedule fires at minute 30 of each local hour. The 01:30 instant occurs twice in wall-clock time; the function fires exactly once for it (at the first occurrence, `fold=0`). The skipped hour on the spring-forward equivalent would not appear in the result at all.

## Example 8 — invalid expression raises `InvalidCronExpr`

```python
next_fires("*/0 * * * *", datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC")))
# raises InvalidCronExpr (step must be a positive integer)
```

A step of zero is not a valid expression. Any malformed input raises `InvalidCronExpr` (a subclass of `ValueError`), not `ValueError` directly, not `TypeError`, not a generic crash.
```

### 14.D `visible/starter_test.py` (verbatim)

```python
"""Sanity-check tests for cron_eval.

Run with: pytest -q starter_test.py

These tests are NOT the grading suite. Passing them only confirms that your
module imports, that the function signature is right, and that a handful of
trivial cases work. The hidden conformance suite is much larger and more
demanding.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from cron_eval import InvalidCronExpr, next_fires


UTC = ZoneInfo("UTC")


def test_every_minute_returns_n_fires_in_order():
    after = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    fires = next_fires("* * * * *", after, n=3, tz="UTC")
    assert fires == [
        datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
        datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
        datetime(2026, 1, 1, 0, 3, tzinfo=UTC),
    ]


def test_after_is_exclusive():
    after = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    fires = next_fires("0 12 * * *", after, n=1, tz="UTC")
    assert fires == [datetime(2026, 1, 2, 12, 0, tzinfo=UTC)]


def test_step_aligns_from_field_min():
    after = datetime(2026, 1, 1, 0, 7, tzinfo=UTC)
    fires = next_fires("*/15 * * * *", after, n=3, tz="UTC")
    assert fires == [
        datetime(2026, 1, 1, 0, 15, tzinfo=UTC),
        datetime(2026, 1, 1, 0, 30, tzinfo=UTC),
        datetime(2026, 1, 1, 0, 45, tzinfo=UTC),
    ]


def test_list_in_hour_field():
    after = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    fires = next_fires("0 8,12,17 * * *", after, n=3, tz="UTC")
    assert fires == [
        datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        datetime(2026, 1, 1, 17, 0, tzinfo=UTC),
        datetime(2026, 1, 2, 8, 0, tzinfo=UTC),
    ]


def test_returns_tz_aware_datetimes_in_requested_zone():
    after = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    fires = next_fires("0 0 * * *", after, n=1, tz="America/Los_Angeles")
    assert fires[0].tzinfo is not None
    assert str(fires[0].tzinfo) == "America/Los_Angeles"


def test_invalid_step_raises_invalid_cron_expr():
    after = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    with pytest.raises(InvalidCronExpr):
        next_fires("*/0 * * * *", after, n=1, tz="UTC")


def test_naive_after_raises_invalid_cron_expr():
    naive = datetime(2026, 1, 1, 0, 0)
    with pytest.raises(InvalidCronExpr):
        next_fires("* * * * *", naive, n=1, tz="UTC")


def test_invalid_cron_expr_is_value_error_subclass():
    assert issubclass(InvalidCronExpr, ValueError)
```

### 14.E `hidden/adjudicator_prompt.md` (verbatim)

The render script will substitute `{{ ... }}` placeholders with the corresponding file contents before invoking the adjudicator.

```markdown
You are adjudicating a model-produced implementation of the `cron-eval` task.

# Hard rules

The score is fixed. It is `{{ score }}/{{ max_score }}`. You may not change it. You may not propose adjustments. You may not say "could be argued differently" or "a stricter reading would yield." You may not invent additional grading criteria. You may not subtract or add points based on code style, readability, or any other factor.

Your only job is to explain what failed and why, in a way that is concrete enough for a reader to act on without rerunning the validator.

If the implementation failed to import (`import_ok` is `false` in the score JSON), state that, give the import error if it is in the validation summary, and stop. Do not write the rest of the report.

# Required output

Produce a single markdown document, written to stdout. No JSON wrapper. No preamble before the first heading. No closing remarks after the last section.

Use this exact structure and these exact heading levels:

# Cron-Eval Run Report

| Field | Value |
| --- | --- |
| Model | {{ model }} |
| Provider | {{ provider }} |
| Date | {{ date }} |
| Time started | {{ time_started }} |
| Time ended | {{ time_ended }} |
| Elapsed minutes | {{ elapsed_minutes }} |
| Cost | {{ cost }} |
| Final score | {{ score }}/{{ max_score }} |

## Score Breakdown

| Category | Earned | Max |
| --- | ---: | ---: |
| Field validity (basic) | (from category_breakdown.json) | 20 |
| Step alignment | (from category_breakdown.json) | 15 |
| Lists and ranges | (from category_breakdown.json) | 10 |
| DOM/DOW interaction | (from category_breakdown.json) | 15 |
| L and W | (from category_breakdown.json) | 10 |
| Calendar edges | (from category_breakdown.json) | 15 |
| Timezone & DST | (from category_breakdown.json) | 10 |
| Errors | (from category_breakdown.json) | 5 |

Fill the "Earned" column with integers from `category_breakdown.json`.

## Failure Analysis

For each category that lost points, write one short paragraph (3–6 sentences) identifying the failure pattern. Group failed cases by symptom, not case-by-case enumeration. Reference specific case ids only when one case stands out for a reason the others do not.

If a category lost 0 points, do NOT mention it here.

If every category is at full points, write a single line: "All categories clean. No failures to analyze." Then move on.

## Likely Root Causes

Cross-category pattern recognition. When several categories fail in a way consistent with a single bug, name it. Reference function or method names from the source code when supportable.

If failures look unrelated, say so explicitly: "These failures do not share an obvious common root."

## Concrete Fix Suggestions

Pointed suggestions. Each fix names a function or location in the source and the change to make. Do not propose rewrites. If the source is too short, too monolithic, or too sparse to localize a fix, say "Source structure does not allow a localized fix; broader rewrite would be required" and stop.

## Strengths

If any non-trivial category was clean (DOM/DOW interaction, Timezone & DST, L and W, or Calendar edges), list it here in a short bullet list. Skip this section entirely if the score is below 50/100 — there are no meaningful strengths to highlight at that level.

# Inputs

Score:
{{ score_json }}

Category breakdown:
{{ category_breakdown_json }}

Validation summary:
{{ validation_summary_json }}

Source code (truncated to 10 KB):
{{ source_code }}
```

### 14.F `hidden/conformance/` — `errors` fixtures (25 verbatim)

> **Authoring note:** All 25 fixtures use `after = "2026-01-15T00:00:00+00:00"` and `n = 1` and `tz = "UTC"` because the input details do not affect error detection — these only need a valid envelope so the malformed `expr` (or invalid arg) is what triggers the failure. Each is weighted 0.2 points (5 / 25 = 0.2). The validator should round per-case earned points to integer points only at the category total to avoid fractional drift.

Each fixture is one JSON file under `hidden/conformance/`. Filenames are `<id>.json`.

```json
{"id": "err_01_empty_string", "category": "errors", "weight": 0.2, "input": {"expr": "", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_02_garbage_chars", "category": "errors", "weight": 0.2, "input": {"expr": "@@@@@", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_03_only_four_fields", "category": "errors", "weight": 0.2, "input": {"expr": "* * * *", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_04_six_fields", "category": "errors", "weight": 0.2, "input": {"expr": "* * * * * *", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_05_minute_too_high", "category": "errors", "weight": 0.2, "input": {"expr": "60 * * * *", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_06_minute_negative", "category": "errors", "weight": 0.2, "input": {"expr": "-1 * * * *", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_07_hour_too_high", "category": "errors", "weight": 0.2, "input": {"expr": "0 24 * * *", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_08_hour_negative", "category": "errors", "weight": 0.2, "input": {"expr": "0 -1 * * *", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_09_dom_zero", "category": "errors", "weight": 0.2, "input": {"expr": "0 0 0 * *", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_10_dom_too_high", "category": "errors", "weight": 0.2, "input": {"expr": "0 0 32 * *", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_11_month_zero", "category": "errors", "weight": 0.2, "input": {"expr": "0 0 1 0 *", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_12_month_too_high", "category": "errors", "weight": 0.2, "input": {"expr": "0 0 1 13 *", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_13_dow_seven_rejected", "category": "errors", "weight": 0.2, "input": {"expr": "0 0 * * 7", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_14_dow_negative", "category": "errors", "weight": 0.2, "input": {"expr": "0 0 * * -1", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_15_step_zero", "category": "errors", "weight": 0.2, "input": {"expr": "*/0 * * * *", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_16_step_negative", "category": "errors", "weight": 0.2, "input": {"expr": "*/-5 * * * *", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_17_range_reversed", "category": "errors", "weight": 0.2, "input": {"expr": "10-5 * * * *", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_18_range_out_of_bounds", "category": "errors", "weight": 0.2, "input": {"expr": "0 0 1-50 * *", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_19_question_in_both_dom_and_dow", "category": "errors", "weight": 0.2, "input": {"expr": "0 12 ? * ?", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_20_question_in_minute", "category": "errors", "weight": 0.2, "input": {"expr": "? * * * *", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_21_l_in_hour", "category": "errors", "weight": 0.2, "input": {"expr": "0 L * * *", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_22_w_in_dow", "category": "errors", "weight": 0.2, "input": {"expr": "0 12 * * 1W", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_23_naive_after_datetime", "category": "errors", "weight": 0.2, "input": {"expr": "* * * * *", "after": "2026-01-15T00:00:00", "n": 1, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_24_n_zero", "category": "errors", "weight": 0.2, "input": {"expr": "* * * * *", "after": "2026-01-15T00:00:00+00:00", "n": 0, "tz": "UTC"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
{"id": "err_25_unknown_tz", "category": "errors", "weight": 0.2, "input": {"expr": "* * * * *", "after": "2026-01-15T00:00:00+00:00", "n": 1, "tz": "Mars/Olympus"}, "expected": {"kind": "raises", "value": "InvalidCronExpr"}}
```

> **JSON shape note:** Each fixture is one JSON file (one object per file, not JSON Lines). The block above is shown without per-line file separation for plan readability; when writing to disk, save each line as `<id>.json`.

> **Coverage of "naive after" detection:** Note that `err_23` uses an ISO string with no offset. The validator must parse it explicitly as a naive `datetime` (no tz attached) before passing it to `next_fires` — otherwise the test does not exercise the naive-datetime guard. See Section 6's parsing notes.

### 14.G `hidden/conformance/` — `dom_dow_interaction` fixtures (10 verbatim)

> **Cross-check requirement:** The dates and weekdays in the `expected.value` lists below are best-effort by the planning author. Before committing these fixtures, run them through the reference impl. If the reference impl produces a different result on any case, **trust the reference impl and update the fixture** — the impl is the source of truth, the planning author may have miscounted weekdays. The intent description above each case is the test's purpose; that intent is the invariant.

Total weight: 15 points across 10 cases. **Weights are deliberately uneven:** the four both-restricted cases (ddi_01–04) carry 10 of the 15 category points because the POSIX OR-rule is the most-violated rule in cron implementations and gets disproportionate testing weight. The single-restricted cases (ddi_05–08) carry 1 point each, and the `?`-synonym cases (ddi_09–10) carry 0.5 each since `?` is just syntactic sugar for `*`. This weighting is what makes Mutation A (Section 14.J) drop the category to 5/15.

```json
{"id": "ddi_01_or_rule_first_and_mondays", "category": "dom_dow_interaction", "weight": 2.5, "input": {"expr": "0 12 1 * 1", "after": "2026-01-01T00:00:00+00:00", "n": 5, "tz": "UTC"}, "expected": {"kind": "fires", "value": ["2026-01-01T12:00:00+00:00", "2026-01-05T12:00:00+00:00", "2026-01-12T12:00:00+00:00", "2026-01-19T12:00:00+00:00", "2026-01-26T12:00:00+00:00"]}, "intent": "Both DOM (1) and DOW (Monday) restricted; OR-rule fires on either."}

{"id": "ddi_02_or_rule_15th_or_fridays", "category": "dom_dow_interaction", "weight": 2.5, "input": {"expr": "0 0 15 * 5", "after": "2026-01-01T00:00:00+00:00", "n": 5, "tz": "UTC"}, "expected": {"kind": "fires", "value": ["2026-01-02T00:00:00+00:00", "2026-01-09T00:00:00+00:00", "2026-01-15T00:00:00+00:00", "2026-01-16T00:00:00+00:00", "2026-01-23T00:00:00+00:00"]}, "intent": "OR-rule between DOM=15 and DOW=Fri."}

{"id": "ddi_03_or_rule_lists_in_both", "category": "dom_dow_interaction", "weight": 2.5, "input": {"expr": "0 9 1,15 * 0,6", "after": "2026-01-01T00:00:00+00:00", "n": 6, "tz": "UTC"}, "expected": {"kind": "fires", "value": ["2026-01-01T09:00:00+00:00", "2026-01-03T09:00:00+00:00", "2026-01-04T09:00:00+00:00", "2026-01-10T09:00:00+00:00", "2026-01-11T09:00:00+00:00", "2026-01-15T09:00:00+00:00"]}, "intent": "Lists in both DOM (1,15) and DOW (Sat,Sun); OR-rule unions."}

{"id": "ddi_04_or_rule_31st_or_sundays", "category": "dom_dow_interaction", "weight": 2.5, "input": {"expr": "0 12 31 * 0", "after": "2026-01-01T00:00:00+00:00", "n": 5, "tz": "UTC"}, "expected": {"kind": "fires", "value": ["2026-01-04T12:00:00+00:00", "2026-01-11T12:00:00+00:00", "2026-01-18T12:00:00+00:00", "2026-01-25T12:00:00+00:00", "2026-01-31T12:00:00+00:00"]}, "intent": "DOM=31 only matches in months that have a 31st; OR-rule pulls in Sundays."}

{"id": "ddi_05_dom_only_first_of_month", "category": "dom_dow_interaction", "weight": 1.0, "input": {"expr": "0 12 1 * *", "after": "2026-01-01T00:00:00+00:00", "n": 4, "tz": "UTC"}, "expected": {"kind": "fires", "value": ["2026-01-01T12:00:00+00:00", "2026-02-01T12:00:00+00:00", "2026-03-01T12:00:00+00:00", "2026-04-01T12:00:00+00:00"]}, "intent": "DOW=*; DOM-only restriction. No OR-rule because DOW is unrestricted."}

{"id": "ddi_06_dom_range_first_week", "category": "dom_dow_interaction", "weight": 1.0, "input": {"expr": "0 12 1-7 * *", "after": "2026-01-01T00:00:00+00:00", "n": 4, "tz": "UTC"}, "expected": {"kind": "fires", "value": ["2026-01-01T12:00:00+00:00", "2026-01-02T12:00:00+00:00", "2026-01-03T12:00:00+00:00", "2026-01-04T12:00:00+00:00"]}, "intent": "DOM range (1-7), DOW=*. Should fire every day in the range, regardless of weekday."}

{"id": "ddi_07_dow_only_mondays", "category": "dom_dow_interaction", "weight": 1.0, "input": {"expr": "0 12 * * 1", "after": "2026-01-01T00:00:00+00:00", "n": 4, "tz": "UTC"}, "expected": {"kind": "fires", "value": ["2026-01-05T12:00:00+00:00", "2026-01-12T12:00:00+00:00", "2026-01-19T12:00:00+00:00", "2026-01-26T12:00:00+00:00"]}, "intent": "DOM=*; DOW-only restriction. Mondays only."}

{"id": "ddi_08_dow_range_weekdays", "category": "dom_dow_interaction", "weight": 1.0, "input": {"expr": "0 12 * * 1-5", "after": "2026-01-01T00:00:00+00:00", "n": 5, "tz": "UTC"}, "expected": {"kind": "fires", "value": ["2026-01-01T12:00:00+00:00", "2026-01-02T12:00:00+00:00", "2026-01-05T12:00:00+00:00", "2026-01-06T12:00:00+00:00", "2026-01-07T12:00:00+00:00"]}, "intent": "DOW range (Mon-Fri), DOM=*. Fires only on weekdays."}

{"id": "ddi_09_question_in_dom_with_dow_restricted", "category": "dom_dow_interaction", "weight": 0.5, "input": {"expr": "0 12 ? * 1", "after": "2026-01-01T00:00:00+00:00", "n": 4, "tz": "UTC"}, "expected": {"kind": "fires", "value": ["2026-01-05T12:00:00+00:00", "2026-01-12T12:00:00+00:00", "2026-01-19T12:00:00+00:00", "2026-01-26T12:00:00+00:00"]}, "intent": "`?` in DOM is identical to `*`; behaves like ddi_07."}

{"id": "ddi_10_question_in_dow_with_dom_restricted", "category": "dom_dow_interaction", "weight": 0.5, "input": {"expr": "0 12 15 * ?", "after": "2026-01-01T00:00:00+00:00", "n": 4, "tz": "UTC"}, "expected": {"kind": "fires", "value": ["2026-01-15T12:00:00+00:00", "2026-02-15T12:00:00+00:00", "2026-03-15T12:00:00+00:00", "2026-04-15T12:00:00+00:00"]}, "intent": "`?` in DOW is identical to `*`; fires on the 15th of every month."}
```

### 14.H `hidden/conformance/` — `timezone_dst` fixtures (8 verbatim)

> **Cross-check requirement (critical for this category):** DST transition dates and offsets are computed by the IANA tz database, which can change. Before committing these fixtures, run each through the reference impl with current `zoneinfo` data. If the reference impl produces a different `expected.value`, trust the reference impl. The `intent` line is the invariant; the literal datetimes are best-effort. The transition dates assumed are: US 2026 spring-forward 2026-03-08, fall-back 2026-11-01; UK 2026 spring-forward 2026-03-29, fall-back 2026-10-25; Sydney 2026 spring-forward 2026-10-04, fall-back 2026-04-05.

Total weight: 10 points across 8 cases.

```json
{"id": "tz_01_la_fallback_duplicate_fires_once", "category": "timezone_dst", "weight": 1.5, "input": {"expr": "30 * * * *", "after": "2026-11-01T05:00:00+00:00", "n": 5, "tz": "America/Los_Angeles"}, "expected": {"kind": "fires", "value": ["2026-10-31T22:30:00-07:00", "2026-10-31T23:30:00-07:00", "2026-11-01T00:30:00-07:00", "2026-11-01T01:30:00-07:00", "2026-11-01T02:30:00-08:00"]}, "intent": "LA fall-back: 01:30 wall-clock occurs twice; fire once at the first (PDT) occurrence and skip the second (PST)."}

{"id": "tz_02_la_springforward_skipped_hour_omitted", "category": "timezone_dst", "weight": 1.5, "input": {"expr": "30 * * * *", "after": "2026-03-08T08:00:00+00:00", "n": 4, "tz": "America/Los_Angeles"}, "expected": {"kind": "fires", "value": ["2026-03-08T00:30:00-08:00", "2026-03-08T01:30:00-08:00", "2026-03-08T03:30:00-07:00", "2026-03-08T04:30:00-07:00"]}, "intent": "LA spring-forward: 02:30 wall-clock does not exist; skip it entirely."}

{"id": "tz_03_utc_no_dst_baseline", "category": "timezone_dst", "weight": 1.0, "input": {"expr": "0 0 * * *", "after": "2026-01-01T00:00:00+00:00", "n": 3, "tz": "UTC"}, "expected": {"kind": "fires", "value": ["2026-01-02T00:00:00+00:00", "2026-01-03T00:00:00+00:00", "2026-01-04T00:00:00+00:00"]}, "intent": "UTC has no DST; baseline that tz handling does not perturb non-DST zones."}

{"id": "tz_04_london_fallback", "category": "timezone_dst", "weight": 1.5, "input": {"expr": "15 * * * *", "after": "2026-10-25T00:00:00+00:00", "n": 5, "tz": "Europe/London"}, "expected": {"kind": "fires", "value": ["2026-10-25T01:15:00+01:00", "2026-10-25T02:15:00+00:00", "2026-10-25T03:15:00+00:00", "2026-10-25T04:15:00+00:00", "2026-10-25T05:15:00+00:00"]}, "intent": "London fall-back at 02:00 BST → 01:00 GMT; the duplicated 01:15 wall-clock fires once at first occurrence (BST)."}

{"id": "tz_05_london_springforward", "category": "timezone_dst", "weight": 1.0, "input": {"expr": "15 * * * *", "after": "2026-03-29T00:00:00+00:00", "n": 4, "tz": "Europe/London"}, "expected": {"kind": "fires", "value": ["2026-03-29T00:15:00+00:00", "2026-03-29T02:15:00+01:00", "2026-03-29T03:15:00+01:00", "2026-03-29T04:15:00+01:00"]}, "intent": "London spring-forward at 01:00 GMT → 02:00 BST; 01:15 wall-clock does not exist; skip."}

{"id": "tz_06_sydney_springforward", "category": "timezone_dst", "weight": 1.0, "input": {"expr": "0 * * * *", "after": "2026-10-03T13:00:00+00:00", "n": 4, "tz": "Australia/Sydney"}, "expected": {"kind": "fires", "value": ["2026-10-04T00:00:00+10:00", "2026-10-04T01:00:00+10:00", "2026-10-04T03:00:00+11:00", "2026-10-04T04:00:00+11:00"]}, "intent": "Sydney spring-forward at 02:00 AEST → 03:00 AEDT; 02:00 wall-clock skipped."}

{"id": "tz_07_sydney_fallback", "category": "timezone_dst", "weight": 1.5, "input": {"expr": "30 * * * *", "after": "2026-04-04T14:00:00+00:00", "n": 5, "tz": "Australia/Sydney"}, "expected": {"kind": "fires", "value": ["2026-04-05T01:30:00+11:00", "2026-04-05T02:30:00+11:00", "2026-04-05T03:30:00+10:00", "2026-04-05T04:30:00+10:00", "2026-04-05T05:30:00+10:00"]}, "intent": "Sydney fall-back at 03:00 AEDT → 02:00 AEST; the duplicated 02:30 wall-clock fires once at first occurrence (AEDT)."}

{"id": "tz_08_eastern_no_transition_window", "category": "timezone_dst", "weight": 1.0, "input": {"expr": "0 12 * * *", "after": "2026-06-01T00:00:00+00:00", "n": 3, "tz": "America/New_York"}, "expected": {"kind": "fires", "value": ["2026-06-01T12:00:00-04:00", "2026-06-02T12:00:00-04:00", "2026-06-03T12:00:00-04:00"]}, "intent": "Mid-summer Eastern, no transition; baseline that DST-aware impls do not corrupt off-transition behavior."}
```

### 14.I Reference impl algorithmic spec

The reference impl is the source of truth for `expected` values across all 100 fixtures. It must be correct on every dialect rule. Build it before authoring fixtures.

**Constraints on the reference impl:**

- Standard library only. `zoneinfo` (Python 3.9+) is the timezone provider.
- Single file: `hidden/reference_impl.py`. Other helpers may live in the same file.
- Must expose `next_fires` and `InvalidCronExpr` with the exact signatures from the spec.
- Must NOT import from `cron_eval` or any non-stdlib package. The reference impl is a peer to the model's implementation, not a wrapper around it.

**Required algorithm (high level):**

1. **Parse** the `expr` into a `ParsedCron` structure with: `minute_set`, `hour_set`, `dom_kind`, `dom_set` (or `L` / `(n, "W")` markers), `month_set`, `dow_kind`, `dow_set`. `dom_kind` and `dow_kind` are one of `{"any", "restricted", "question"}` to make the OR-rule decision unambiguous.
2. **Validate `after`:** if `after.tzinfo is None`, raise `InvalidCronExpr`. If `n < 1`, raise `InvalidCronExpr`. If `tz` is not loadable via `ZoneInfo(tz)` (catches `ZoneInfoNotFoundError`), raise `InvalidCronExpr`.
3. **Convert `after` to `tz`:** the schedule operates in wall-clock time of `tz`. Internally walk in wall-clock minutes within `tz`, but be careful: the wall clock skips an hour at spring-forward and repeats an hour at fall-back.
4. **Iteration strategy:** start from `after` converted to `tz`, then walk forward minute-by-minute. For each candidate minute, ask:
   - Does the candidate's `(minute, hour, dom, month, dow)` match the parsed cron?
   - For DOM/DOW: apply the OR-rule (Section 14.B "DOM/DOW interaction"). If both restricted, match if either matches. If one is `*`/`?`, only the other matters.
   - For `L` in DOM: compute the actual last day of the candidate's `(year, month)`. Match only if `candidate.day == that_last_day`.
   - For `nW` in DOM: compute the weekday-nearest-to-`n` for `(candidate.year, candidate.month)`. Match only if `candidate.day == that_resolved_day`.
5. **Generation strategy** (faster than minute-by-minute, but produce identical results): given the parsed `minute_set`, `hour_set`, etc., generate candidates by:
   - For each year ≥ `after.year`:
     - For each month in `month_set`:
       - For each day 1..31 (filtered by month length and DOM/DOW match):
         - For each hour in `hour_set`:
           - For each minute in `minute_set`: yield the candidate datetime
   - The "minute-by-minute walk" and "generate-and-filter" approaches must produce the same output. Pick whichever you can verify; the test-of-the-test (Section 11 Step 1) catches discrepancies.
6. **Localize candidates:** each candidate is a wall-clock `(year, month, day, hour, minute)` tuple in `tz`. Use `datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(tz))` to localize.
7. **DST handling:**
   - For each localized candidate, check whether the wall-clock instant is **valid** in `tz`. The cleanest stdlib check: convert the candidate to UTC via `.utctimetuple()` or `.timestamp()`, then convert back. If the round-tripped wall-clock differs, the original was in a skipped or duplicated interval.
     - **Skipped interval:** `localized.utcoffset()` equals the *post-transition* offset, but `localized.replace(fold=0)` and `localized.replace(fold=1)` produce the same UTC instant — the wall-clock did not exist. **Action: skip this candidate entirely.**
     - **Duplicated interval (fall-back):** `localized.replace(fold=0)` and `localized.replace(fold=1)` produce *different* UTC instants. The candidate is ambiguous. **Action: emit only the `fold=0` instant; do NOT emit the `fold=1` instant for the same wall-clock.**
   - The simplest correct implementation: for each wall-clock candidate, build it with `fold=0`, convert to UTC, and emit. When the next minute's wall-clock is < the previous emitted UTC instant (because we fell back), we naturally skip emitting the duplicated wall-clock again — IF iteration is over wall-clock and we de-dup by emitted UTC. Or: explicitly check fold and skip `fold=1` candidates whose `fold=0` peer was already emitted.
8. **Strictly-after:** every emitted datetime must satisfy `emitted > after` (in UTC instant comparison, not wall-clock). Reject candidates whose UTC instant is `<= after`.
9. **Stop after `n` emissions.** Return the list.

**Cross-checks the reference impl must pass before being trusted:**

- `next_fires("* * * * *", t, n=5, "UTC")` produces 5 consecutive minutes after `t`.
- `next_fires("0 0 29 2 *", datetime(2025, 1, 1, ..., tz=UTC), n=3, "UTC")` skips non-leap years; first fire is 2028-02-29.
- `next_fires("0 12 1 * 1", ...)` (the OR-rule case) produces fires for both DOMs and DOWs, not the intersection.
- All eight DST cases in 14.H produce the listed outputs.
- All 25 error cases in 14.F raise `InvalidCronExpr`.
- 1000 random `(expr, after, n)` calls do not crash.

If any cross-check fails, fix the reference impl. Do not adjust the fixture to match a buggy impl.

### 14.J Mutation diffs (Section 11 Step 3)

Each mutation is a one-place change in `hidden/reference_impl.py`. After applying a mutation, copy the mutated file to a temp `cron_eval.py` and run `scripts/run_checks.py` against it. The assertions in Section 11 Step 3 should hold.

> **How to apply:** these are described as logical changes against the reference impl, since the reference impl source is not in this plan. The executor authors the reference impl per Section 14.I, then introduces these specific bugs into copies for the test-of-the-test.

**Mutation A — DOM/DOW becomes AND instead of OR:**

In whatever function decides "does this candidate match the cron's DOM and DOW combined" (likely named `_match_dom_dow`, `_date_matches`, or similar), find the OR-rule branch:

```python
# Original (correct, POSIX OR-rule):
if dom_restricted and dow_restricted:
    return dom_match or dow_match
```

Change to:

```python
# Mutation A (incorrect, AND instead of OR):
if dom_restricted and dow_restricted:
    return dom_match and dow_match
```

Leave all other branches untouched. The unrestricted-DOM and unrestricted-DOW cases remain correct.

Expected impact: every `dom_dow_interaction` case where both are restricted now fires only on the intersection. Cases ddi_01–ddi_04 (both restricted, weight 2.5 each = 10 points total) lose their fires; cases ddi_05–ddi_10 (only one restricted, or `?`) are unaffected. Score impact: `dom_dow_interaction` should earn 5/15 (rounded to integer from 5.0); overall score lands in the 88–92 range. The weighting in 14.G is intentional: the OR-rule is the most-violated rule in cron, so a model that gets it wrong loses two thirds of the category.

**Mutation B — DST fall-back duplicated hour fires twice:**

In whatever logic suppresses the second occurrence of a fall-back duplicated wall-clock (likely a `fold=1` skip or a UTC-instant de-dup), remove that suppression. For example:

```python
# Original (correct):
if instant_already_emitted(utc_instant):
    continue
emit(localized)
```

Change to:

```python
# Mutation B (incorrect, no fall-back de-dup):
emit(localized)
```

Or, if the suppression takes the form of a `fold=0` only emission:

```python
# Original:
candidate = wall_clock.replace(fold=0)
# Mutation B: emit both folds
for fold_val in (0, 1):
    candidate = wall_clock.replace(fold=fold_val)
    emit(candidate)  # but only if fold=1 produces a different UTC instant
```

Expected impact: the LA fall-back, London fall-back, and Sydney fall-back cases each emit one extra fire during the duplicated hour. Spring-forward cases unaffected. Score impact: `timezone_dst` should earn ≤ 6/10 (the three fall-back cases fail; the spring-forward and baseline cases pass).

**Mutation C — `InvalidCronExpr` becomes plain `ValueError`:**

At the top of the file, find:

```python
class InvalidCronExpr(ValueError):
    """Raised for any malformed expression or invalid argument."""
```

Replace every `raise InvalidCronExpr(...)` site with `raise ValueError(...)`. Also remove the class definition (or leave it but never raise it).

Expected impact: every `errors` fixture's expectation is `{"kind": "raises", "value": "InvalidCronExpr"}`. The validator checks `isinstance(exc, InvalidCronExpr)` (using the model's `cron_eval.InvalidCronExpr` import). When the model raises `ValueError`, the check fails. All 25 error cases fail. Score impact: `errors` should earn 0/5.

> **Note on Mutation C and the validator:** the validator must not relax its check to accept any `ValueError`. The point of the test is to catch impls that use the wrong exception type. If the validator says "any subclass of `ValueError` is fine," the mutation passes and the test does not fail correctly. See Section 6's "exception type matching" requirement.

---

## 15. Constraints on delegated work

These constraints apply to whatever agent (subagent or human) executes this plan. They exist to prevent judgment-call drift in places that look innocuous but materially change what the benchmark measures.

### 15.1 Verbatim-only sections

The following content is **verbatim** in Section 14 and must be copied unchanged into the named files:

- **`prompt.txt`** — Section 14.A
- **`visible/spec.md`** — Section 14.B
- **`visible/examples.md`** — Section 14.C
- **`visible/starter_test.py`** — Section 14.D
- **`hidden/adjudicator_prompt.md`** — Section 14.E
- **The 25 `errors` fixtures** — Section 14.F
- **The 10 `dom_dow_interaction` fixtures** — Section 14.G
- **The 8 `timezone_dst` fixtures** — Section 14.H
- **The three mutation diffs (test-of-the-test)** — Section 14.J

Do not paraphrase. Do not condense. Do not "improve clarity." Do not reformat tables to bullet lists or vice versa. Do not add or remove headings. Do not add explanatory comments to fixtures. Do not change file extensions or filenames.

The single allowed deviation is correcting an `expected.value` field in 14.G or 14.H if the reference impl computes a different result during Section 11 Step 1 self-check (and only that field; the `intent` line documents the invariant the case is testing).

### 15.2 Schema constraints on delegated fixtures

When authoring the 57 non-inlined fixtures in `field_validity_basic`, `step_alignment`, `lists_and_ranges`, `l_and_w`, and `calendar_edges`:

- Use exactly these JSON keys: `id`, `category`, `weight`, `input`, `expected`. No additional top-level keys.
- `input` keys: exactly `expr`, `after`, `n`, `tz`. No additional keys.
- `expected.kind` is exactly one of `"fires"` or `"raises"`.
- `expected.value` is a list of ISO datetime strings (for `fires`) or the string `"InvalidCronExpr"` (for `raises`).
- Do not add `notes`, `rationale`, `description`, `comment`, `expected_behavior`, or any other field. The `intent` line in 14.G/14.H is for plan readers; it is **not** part of the fixture file. Strip it before writing the JSON to disk.
- `id` follows the pattern `<category_short>_<NN>_<short_slug>` matching the inlined examples (e.g., `fvb_01_minute_literal_zero`, `step_03_step_from_range`).
- `weight` per fixture matches the per-category target average in Section 5's table. Per-category totals must sum to the rubric values exactly.

### 15.3 Categories are exhaustive

The eight categories listed in Section 5's table are the complete category list. Do not invent additional categories. Do not split or merge them.

### 15.4 `visible/` surface is complete

The four files listed in Section 10 (`spec.md`, `examples.md`, `starter_test.py`, `.gitignore`) are the complete visible surface. Do not add `HINTS.md`, `CONTRIBUTING.md`, `expected_behavior.md`, or any other file under `visible/`. Anything else under `visible/` would expose information the model is not supposed to have.

### 15.5 `prepare.sh` and the venv

`prepare.sh` may install Python dependencies and create directories. It must NOT:

- Pre-create a `cron_eval.py` stub (the model must produce it).
- Run any test against the model's code (validation is the validator's job).
- Modify any file under `visible/` or `hidden/` after they are copied into the worktree.

### 15.6 Adjudicator may not rescore

The adjudicator prompt in 14.E forbids rescoring. The implementation of `scripts/adjudicate.sh` and `scripts/render_adjudication_prompt.py` must:

- Pass the score from `score.json` into the prompt as a substituted value.
- Not pass the conformance fixtures themselves into the prompt (the adjudicator does not need them and they would dramatically inflate context cost).
- Pass the validation summary, category breakdown, and (truncated) source code only.

If the adjudicator returns text that contains the strings `"adjusted score"`, `"revised score"`, `"different score would"`, or any score value other than the one in `score.json`, the validator should still trust `score.json` — the adjudicator's output is narrative only and never overwrites `score.json`.

### 15.7 No silent scope expansion

If during execution the executor agent discovers that some part of this plan is missing or contradictory, the correct action is to stop and report the gap, not silently fill it in with a judgment call. Examples of gaps that warrant stopping:

- A fixture in 14.F/G/H produces results from the reference impl that disagree with the `expected.value` AND with the `intent` line.
- The dialect spec is silent on a corner case that one of the 57 delegated fixtures depends on.
- The harness machinery in `benchmark-llm` rejects a step shape that the manifest in Section 8 specifies.

In all such cases, write a note to `docs/cron_eval_open_questions.md` and pause execution until the planning author resolves it.

