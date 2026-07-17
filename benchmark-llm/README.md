# benchmark-llm

`benchmark-llm` is a filesystem-first benchmark runner for LLM evaluation work. It keeps the core runtime small and pushes task-specific behavior to benchmark packages.

The project is built around one runtime with three authoring modes:

1. `prompt_batch` for JSONL prompt sets plus lightweight judging.
2. `repo_task` for coding and workflow benchmarks with linear shell/Python hooks.
3. `plugin` for advanced Python-defined benchmarks that need branching or custom orchestration.

## Status

The current implementation supports:

- `bench run <benchmark-dir> -m <model[,model...]>`
- `bench run <benchmark-dir> -m @models.txt`
- `bench run <benchmark-dir> --models-file models.txt`
- `bench list`
- `bench report <run-id|latest>`
- prompt-batch benchmarks with `exact_match`, `regex`, and command-backed `llm_judge`
- repo-task benchmarks with retained result branches, cleaned-up successful worktrees, and structured command provenance
- repo-task benchmark-level `runs`, `run_order`, and required `output_dir` settings in `bench.yaml`
- repo-task final synthesized summaries written to `summary.md` in the configured output root when the benchmark provides `scripts/render_final_summary_prompt.py`, with room for benchmark-run overview notes plus aggregated per-model commentary
- plugin benchmarks through a small `benchsdk` API
- filesystem artifacts plus a SQLite run index

## Runtime Model

The repo-local launcher is `./bench`. It runs via [uv](https://docs.astral.sh/uv/) (`brew install uv`) using a PEP 723 inline-metadata header; because benchmark-llm requires the repo checkout to run, the launcher adds the repo directory to `sys.path` and invokes the `benchmark_llm` package directly rather than installing it. On first run, uv resolves the dependency (PyYAML) into its shared cache.

Its runtime home holds only data (no venv):

```text
~/.benchmark_llm/
  index.sqlite3
  runs/
  worktrees/
```

Artifacts are kept by default. Repo-task runs keep their branches for inspection, clean up successful worktree checkouts automatically, and preserve failed attempts for debugging.
Prompt-batch and plugin runs still store artifacts under `~/.benchmark_llm/runs/`. Repo-task runs store artifacts under the benchmark's configured `output_dir`.

## Quick Start

```bash
cd benchmark-llm
./bench --help
```

Run the included prompt-batch example with the demo executor:

```bash
./bench run examples/logic-mini -m demo-model --executor-command ./examples/shared/demo_prompt_executor.py
```

Run the same benchmark against a reusable model set:

```bash
./bench run examples/logic-mini -m @models.txt --executor-command ./examples/shared/demo_prompt_executor.py
```

That shared demo executor reads `responses.jsonl` from the benchmark package by `id`. It is only a fixture runner for local smoke tests and examples, not the recommended authoring pattern for real benchmarks.

Then inspect results:

```bash
./bench list
./bench report latest
```

## Model Selection

You can supply models three ways:

- inline: `-m openrouter/gpt-5,openrouter/glm-5.1`
- inline file reference: `-m @models.txt`
- separate option: `--models-file models.txt`

`--models-file` may be passed more than once. Model files support one model per line or comma-separated entries, ignore blank lines and lines starting with `#`, and de-duplicate repeated entries within the file while preserving order.

Inline `-m` entries remain an explicit sequence. If you list the same model twice inline, the runtime will create two runs.

## Benchmark Package Shapes

### 1. Prompt-batch

```text
examples/logic-mini/
  cases.jsonl
  answers.jsonl
  judge.yaml
```

`cases.jsonl` contains prompt rows keyed by `id`. `answers.jsonl` contains hidden expected answers. `judge.yaml` defines the built-in judge.

Example:

```yaml
type: exact_match
normalize:
  - strip
  - lowercase
```

Supported built-in judges:

- `exact_match`
- `regex`
- `llm_judge` using `judge_command`

`llm_judge` keeps the simple authoring rail intact while still letting you call an external judge model:

```yaml
type: llm_judge
judge_command: ./judge_model.sh
rubric: |
  Grade semantic correctness, not formatting.
```

### 2. Repo-task

```text
examples/policy-engine/
  bench.yaml
  prompt.txt
  visible/
  hidden/
  scripts/
```

The runtime handles:

- run directory creation
- git worktree creation
- artifact capture
- command stdout/stderr capture
- elapsed timing capture for commands and runs
- `commands.jsonl` provenance
- markdown report generation
- SQLite indexing

The benchmark package handles:

- source repo selection
- visible asset injection
- model invocation
- hidden evaluation logic
- score production
- optional post-validation adjudication with the same or a separate CLI/model as an additional benchmark step

For model-execution steps, the runtime intentionally scrubs framework and test harness environment variables before invoking the executor. Use neutral task-oriented inputs such as `MODEL_ID`, `TASK_PROMPT_TEXT`, `TASK_PROMPT_PATH`, and `WORKSPACE_ROOT` inside model runner scripts.

## Metrics

The runtime always records:

- per-command `started_at`, `ended_at`, and `elapsed_ms`
- per-run `started_at`, `ended_at`, and `timing.elapsed_ms`

When a harness can provide richer usage data, it can optionally write a JSON sidecar and the runtime will ingest it automatically.

Model-facing commands receive:

- `TASK_METRICS_PATH`

Framework-owned non-model commands receive:

- `BENCH_COMMAND_METRICS_PATH`

If the file exists after the command finishes, the runtime reads it and attaches the parsed object to that command record in `commands.jsonl`. Known numeric keys are aggregated up to the run manifest and SQLite index:

- `cost_usd`
- `input_tokens`
- `output_tokens`
- `total_tokens`
- `provider_latency_ms`
- `turns`

If `total_tokens` is omitted but `input_tokens` and `output_tokens` are present, the runtime derives it automatically.

Example sidecar payload:

```json
{
  "cost_usd": 0.0042,
  "input_tokens": 812,
  "output_tokens": 146,
  "provider_latency_ms": 1280
}
```

### 3. Plugin

```text
examples/plugin-advanced/
  bench.py
```

Use `benchsdk.BenchmarkPlugin` when a benchmark needs custom control flow:

```python
from benchsdk import BenchmarkPlugin

class MyBenchmark(BenchmarkPlugin):
    def prepare(self, ctx):
        ...

    def execute(self, ctx, model):
        ...

    def judge(self, ctx):
        return {
            "summary": {"passed": 1, "total": 1, "score_percent": 100.0},
            "checks": [{"name": "example", "passed": True}],
        }
```

## Repo-task Manifest

Minimal example:

```yaml
type: repo_task
id: policy-engine
runs: 3
run_order: breadth
output_dir: ~/Downloads/benchmark-llm

workspace:
  kind: git_worktree
  source_repo: ${BENCH_POLICY_ENGINE_SOURCE_REPO}
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

steps:
  - name: prepare
    run: ./scripts/prepare.sh
  - name: execute
    use_executor: true
  - name: judge
    run: python ./scripts/judge.py

scoring:
  output: score.json
```

Repo-task settings at the top of `bench.yaml` control batch scheduling and artifact placement:

- `output_dir` is required. The runtime expands `~`, creates the directory tree if needed, and writes each run directory there instead of under `~/.benchmark_llm/runs/`.
- `runs` defaults to `1` when omitted.
- `run_order` defaults to `breadth` when omitted.
  - `breadth`: run each model once, then loop back through the model list for the next pass.
  - `depth`: run one model for all requested passes before moving to the next model.

If a repo-task benchmark includes `scripts/render_final_summary_prompt.py` and an `adjudicate` step, `bench run` also launches one final adjudicator pass after the batch completes and writes `summary.md` to the root of `output_dir`. That prompt can synthesize both successful reports and failed-run metadata, which lets the final report cover benchmark execution reliability as well as the model results themselves.

`executor.command` is authoritative for the model invocation step. You can reference it in two ways:

- preferred: a named step with `use_executor: true`
- shorthand: a plain string step whose command exactly matches `executor.command`

`steps` supports both strings and objects. String steps keep the manifest terse. Named steps preserve intent and become the phase names written into `commands.jsonl`.

Repo-task execution also supports harness-managed supervision and retries:

```yaml
execution_defaults:
  timeout_sec: 1800
  inactivity_timeout_sec: 300
  retries:
    max_attempts: 3
    backoff_sec: 20

steps:
  - name: execute
    use_executor: true
    retries:
      max_attempts: 4
```

Use `execution_defaults` for global timeout and retry policy, then override individual steps only when they need different limits.

Retries are whole-attempt retries for repo tasks. If a step is retried, the runtime creates a fresh git worktree and reruns the full workflow from the beginning rather than reusing a partially written workspace.

For supervised commands, the runtime writes stdout/stderr to per-step files, polls the child process, enforces wall-clock and inactivity timeouts, and preserves prior failed attempts under the run directory for troubleshooting.

## Artifacts

Prompt-batch and plugin runs are stored under `~/.benchmark_llm/runs/<run-id>/`.
Repo-task runs are stored under `<output_dir>/<run-id>/`, where `output_dir` comes from `bench.yaml`.

Common artifacts:

- `manifest.json`
- `score.json`
- `report.md`

Prompt-batch runs also write:

- `raw_responses.jsonl`
- `judged.jsonl`
- `commands.jsonl`

Repo-task and plugin runs also write:

- `commands.jsonl`

Repo-task batch roots may also include:

- `summary.md`
- `summary_runs.json`
- `summary_command.json`

For repo tasks, `commands.jsonl` captures the exact command string, cwd, exit code, stdout, stderr, and timestamps for each step. This is where command provenance such as `pytest -q` versus `python -m pytest -q` should live.

Repo-task runs with retries also keep attempt-scoped artifacts under:

- `attempts/01/`
- `attempts/02/`
- ...

The top-level `commands.jsonl`, `score.json`, and `report.md` reflect the final successful attempt. Earlier failed attempts are preserved beneath `attempts/` for debugging. Successful repo-task branches remain available in the source repository, but their worktree checkouts are removed after the run completes.

When available, command rows also include:

- `elapsed_ms`
- `metrics`
- `metrics_path`

For `visibility.expose` and `visibility.hide`, the runtime strips the static path prefix from each glob when copying files. For example:

- `visible/**` copies into the workspace root without a top-level `visible/` folder
- `evaluator-only/**` copies into `BENCH_HIDDEN_DIR` without a top-level `evaluator-only/` folder

## Examples

- [examples/logic-mini](./examples/logic-mini/README.md)
- [examples/policy-engine](./examples/policy-engine/README.md)
- [examples/plugin-advanced](./examples/plugin-advanced/README.md)

## Development

Create a local venv, install the project, and run the full test suite:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

As a quick uv-managed equivalent, run `uv run --extra dev pytest`.

## Current Constraints

- The built-in runtime supports `git_worktree` for repo tasks. Container isolation is intentionally deferred.
- There is no web UI. Reports are static files.
- Archiving and garbage-collection commands are not currently implemented.
