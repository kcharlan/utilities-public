# Orchestrator model evaluation

This plugin is a public-safe harness for a future, explicitly approved comparison of
orchestrator and worker model candidates. It does not select an executor, candidate,
or live model by default. Its checked-in tasks and expected outputs are conspicuously
synthetic.

Do not run a paid model merely to smoke-test this example. The automated tests use a
local fake executor. Any live run belongs to the separate approval phase: first present
the exact candidates, fixed corpus, thresholds, projected invocation count, retry cap,
and cost controls, then wait for explicit approval.

## Safety boundary

Set `BENCH_RUNTIME_HOME` to a private directory outside this source checkout before
invoking `bench`. The plugin resolves real paths and symlinks and refuses a runtime
home or disposable-workspace root inside the canonical checkout. It creates one fresh,
minimal Git repository per scheduled trial under:

```text
$BENCH_RUNTIME_HOME/runs/<run-id>/workspaces/
```

It never creates a worktree and never changes the source checkout. Plugin mode also
writes the framework's SQLite index, manifest, report, score, and `commands.jsonl`
beneath `BENCH_RUNTIME_HOME`; unlike repo-task mode, it has no `output_dir` setting.

Raw run artifacts are private by design. They can contain exact working directories,
absolute paths, stdout and stderr, failed attempts, executor commands, metrics, and raw
model output. Do not commit them. `commit-eligible-summary.json` is separately generated
without raw output or absolute paths and is the only artifact intended to be eligible
for review and possible commit after an independent sensitive-data inspection.

## Fixed paired corpus

The checked-in corpus has one task for each independent decision cell:

- `design_orch.orchestration`
- `switchyard.planning`
- `switchyard.resolution`
- `switchyard.auto_fix`
- `codex.worker_execution`
- `codex_hybrid.worker_execution`

The direct and hybrid worker tasks deliberately use different synthetic contexts. Every
candidate receives the same task and prompt in each paired trial. The schedule rotates
the six task positions and rotates candidate order within each task, so candidates are
interleaved rather than evaluated in model-sized blocks.

Six paired trials per cell and candidate are the minimum and default. Trial counts must
be multiples of both six and the candidate count to keep every position balanced. The
report includes mean, population standard deviation, minimum, median, and maximum scores
and elapsed times, plus paired per-task results. These repetitions provide descriptive
dispersion; the harness does not
claim that an arbitrary three trials—or its default six—constitute statistical proof.

The first candidate is the declared baseline. Before any live run, every cell uses these
fixed non-regression thresholds:

- correctness rate at least `1.0`;
- mean verification score at least `100.0`;
- paired correctness-rate drop from baseline at most `0.0`;
- paired mean-score drop from baseline at most `0.0`.

## Executor contract

The plugin requires these explicit environment variables:

- `BENCH_RUNTIME_HOME`: private external runtime directory;
- `BENCH_ORCHESTRATOR_EVAL_CANDIDATES`: comma-separated exact model identifiers, with
  the baseline first and at least one comparison candidate;
- `BENCH_ORCHESTRATOR_EVAL_EXECUTOR`: a wrapper command that implements the protocol
  below;
- `BENCH_ORCHESTRATOR_CODEX_COMMAND`: the command whose `--version` output identifies
  the Codex CLI used by the wrapper.

Optional controls are:

- `BENCH_ORCHESTRATOR_EVAL_TRIALS` (default `6`, minimum `6`, and a multiple of both
  `6` and the candidate count);
- `BENCH_ORCHESTRATOR_EVAL_REASONING_EFFORT` (default `high`);
- `BENCH_ORCHESTRATOR_EVAL_MAX_ATTEMPTS` (default `2`, including the first attempt).

For each scheduled trial, the plugin invokes the wrapper without a shell and appends:

```text
--model <exact-id>
--reasoning-effort <effort>
--task-id <synthetic-task-id>
--prompt-file <external-path>
--workspace <external-path>
--metrics-file <external-path>
```

The wrapper must make its changes inside `--workspace`. A zero exit status ends retries.
When available, it writes a JSON object to `--metrics-file` containing any of
`cost_usd`, `input_tokens`, `output_tokens`, `total_tokens`, `provider_latency_ms`, and
`turns`. A wrapper for a live run is responsible for mapping these inputs to the exact
approved Codex invocation and enforcing the approved per-call cost or token ceiling.

The wrapper receives benchmark-llm's scrubbed model-command environment, not the
framework process environment. Provider credentials and basic process settings allowed
by a provider-prefix allowlist layered over `build_model_command_env` are preserved,
while generic suffix matches such as `DATABASE_URL`, `GITHUB_TOKEN`, and `NPM_TOKEN`,
plus `PWD`, `BENCH_*`, pytest/framework variables, and unrelated values are removed.
Neutral `MODEL_ID`, `TASK_ID`,
`TASK_PROMPT_PATH`, `WORKSPACE_ROOT`, `TASK_METRICS_PATH`, and `REASONING_EFFORT`
values are supplied explicitly. No source-fixture or hidden-answer path is exposed.

Workspace Git initialization uses a separate minimal environment and isolated empty
Git configuration. Incoming `GIT_*` controls cannot redirect the repository or inject
hooks/configuration. A retry deletes and recreates the disposable repository, prompt,
and Git metadata from the checked-in synthetic fixture before invoking the executor;
prior raw logs and reported usage remain preserved outside the workspace.

The required outer `bench` model is only the plugin-run label because the plugin owns
the interleaved candidate matrix. A future approved invocation therefore has this shape:

```bash
BENCH_RUNTIME_HOME="$EXTERNAL_BENCH_HOME" \
BENCH_ORCHESTRATOR_EVAL_CANDIDATES='baseline-id,candidate-id' \
BENCH_ORCHESTRATOR_EVAL_EXECUTOR="$EXTERNAL_EXECUTOR_WRAPPER" \
BENCH_ORCHESTRATOR_CODEX_COMMAND='codex' \
./bench run examples/orchestrator-model-eval -m paired-matrix
```

The paths above are placeholders, not recommended literal values. Do not run that shape
with a live executor until the paid-run gate has been approved.

## Provenance and scoring

`evaluation-results.json` records the execution date, exact candidate identifiers,
`codex --version`, reasoning effort, prompt SHA-256 hashes, full scheduled task order,
correctness, verification score, attempt and retry metadata, elapsed time, and reported
usage/cost metrics. `score.json` contains the predeclared thresholds, candidate-level
dispersion, paired comparisons, per-trial checks, and usage totals across every attempt,
including failed attempts that reported metrics. Its usage blocks distinguish trial
count, attempt count, and attempts reporting usage. Raw attempt logs remain beside those
files under the external run directory. Reported metrics must be finite and nonnegative;
token and turn counts must also be integer-valued.

The commit-eligible summary replaces exact free-form candidate identifiers with stable
run-local aliases plus SHA-256 digests and replaces the free-form Codex version with its
SHA-256 digest. This keeps exact identifiers and version output in private raw provenance
while preventing an embedded absolute path from crossing the commit boundary. Financial
usage such as `cost_usd` remains only in private raw results and is removed recursively
from the commit-eligible summary.

For safe local validation, run the complete project suite; it supplies only fake
executors and never invokes a paid model:

```bash
cd benchmark-llm
.venv/bin/python -m pytest -q
```
