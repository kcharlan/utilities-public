# policy-engine repo-task example

This example adapts the policy-engine evaluation package into `benchmark-llm`'s repo-task shape.

It is meant to be both runnable and readable:

- the framework owns worktree creation, artifact capture, and structured command provenance
- the benchmark package owns repo prep, model invocation, deterministic validation, model-based adjudication, and the benchmark-specific scorecard

The bundled `bench.yaml` is configured to:

- write run artifacts to `~/Downloads/benchmark-llm`
- run each requested model `3` times
- use `breadth` ordering so the batch cycles across models before starting the next pass

## Required environment

Point the benchmark at the repo you want to evaluate:

```bash
export BENCH_POLICY_ENGINE_SOURCE_REPO=/absolute/path/to/policy-engine
```

The included invocation script is wired for `opencode`:

```bash
bench run examples/policy-engine -m openrouter/qwen/qwen3.6-plus
```

For repeated benchmark sweeps, you can use a model list file instead:

```bash
bench run examples/policy-engine -m @models.txt
```

Each successful run lands under `~/Downloads/benchmark-llm/<run-id>/`. After the batch finishes, the benchmark launches one final adjudicator pass and writes `~/Downloads/benchmark-llm/summary.md`.
That final report is structured for reading, not just archival: an executive summary first, then a benchmark-run overview, a synthesized narrative, model-level commentary aggregated across each model's runs, and the detailed per-run topline table at the end.

By default the adjudication step uses `cx` (your `codex` wrapper), but it is a separate shell step and can use the same or a different model:

```bash
export BENCH_POLICY_ENGINE_ADJUDICATOR_MODEL=openrouter/gpt-5
bench run examples/policy-engine -m openrouter/qwen/qwen3.6-plus
```

The default script invokes Codex non-interactively with `exec` and feeds the adjudication prompt on stdin. It launches the adjudicator through `zsh -lic` so shell-defined wrappers such as `cx` from your `~/.zshrc` resolve the same way they do in an interactive terminal. When the adjudicator bin is `cx` or `codex`, the script uses that wrapper's configured default model unless you explicitly set `BENCH_POLICY_ENGINE_ADJUDICATOR_MODEL`. To use a different CLI binary for adjudication, set `BENCH_POLICY_ENGINE_ADJUDICATOR_BIN` or edit `scripts/adjudicate.sh`. The framework keeps the result branch either way because adjudication is just another benchmark-owned step running after validation, and the same script also handles the final cross-run `summary.md` synthesis pass once the batch is complete. Successful worktree checkouts are cleaned up automatically once each run is recorded.

`scripts/adjudicate.sh` also includes a commented Claude Code example for your `cc` wrapper. That path uses Claude's non-interactive `--print` mode with JSON output, while the active default remains `cx exec`.

The model execution step itself receives a scrubbed environment with neutral task inputs such as `MODEL_ID`, `WORKSPACE_ROOT`, and `TASK_PROMPT_PATH`. Framework-owned `BENCH_*` variables stay available to the non-model steps like prepare, validate, and adjudicate.

If the `opencode` wrapper can recover usage data, it can write a JSON payload to `TASK_METRICS_PATH` during the execute step. The same pattern works for adjudication or validation steps through `BENCH_COMMAND_METRICS_PATH`.

## Layout

```text
policy-engine/
  bench.yaml
  prompt.txt
  report_template.md
  visible/
  hidden/
  scripts/
```

`report_template.md` is a reusable scorecard template derived from the original evaluation sheet, but with placeholders instead of baked-in results.

The manifest uses the recommended repo-task shape:

- `executor.command` is the authoritative model invocation
- the execute step references it with `use_executor: true`
- top-level `runs`, `run_order`, and `output_dir` control batch scheduling and artifact placement
- named steps become the phase names stored in `commands.jsonl`
- `execution_defaults` applies benchmark-wide timeout and retry policy, with fresh-worktree retries when a supervised step is retried
- validation is deterministic and writes `validation_summary.json`
- extra benchmark-owned probes can append adjudicator-facing records to `benchmark_findings.jsonl`
- adjudication is a second CLI/model invocation that turns those artifacts into `score.json` and `report.md`
- a final summary pass reads the generated run artifacts, writes `summary.md` at the root of `output_dir`, and includes both model-level synthesis and benchmark-run execution observations such as retries or failed completions

This example uses that pattern for a benchmark-specific `mutation_probe` step. It is not a framework feature or special harness hook; it is just another benchmark-owned step in `bench.yaml` that appends a JSONL finding record for adjudication.

## Prompt and validation contract

The model-facing prompt exposes the hard contract directly.
It now makes the required CLI entry point, output fields, and blank or missing field handling visible instead of relying on hidden evaluator expectations.

Primary CLI validation uses:

```bash
python policy_engine.py --policy ... --benefits ... --output ...
```

For automated checks:

- Prefer the README-documented command if present.
- Otherwise try `pytest -q`.
- Then try `python -m pytest -q`.
- If one works and the other does not, treat that as a minor setup/usability issue unless the visible prompt explicitly required a specific invocation.

Hidden validations are for generalization of the visible task.
They should confirm semantic behavior on unseen inputs, not invent new requirements after the fact.
