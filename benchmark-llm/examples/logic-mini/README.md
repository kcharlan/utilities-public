# logic-mini

Simple prompt-batch example with exact-match judging.

Run it with the included demo executor:

```bash
./bench run examples/logic-mini -m demo-model --executor-command ./examples/shared/demo_prompt_executor.py
```

To run the same benchmark against several models without shell scripting:

```bash
./bench run examples/logic-mini -m @models.txt --executor-command ./examples/shared/demo_prompt_executor.py
```

`models.txt` can contain one model per line, blank lines, and `#` comments.

The benchmark package itself stays low-ceremony:

```text
logic-mini/
  cases.jsonl
  answers.jsonl
  judge.yaml
  responses.jsonl
```

`responses.jsonl` exists only for the bundled fixture executor. It is not part of the benchmark runtime contract for real model runs.

Model executors in this rail receive neutral inputs such as `MODEL_ID`, `CASE_ID`, and `TASK_PROMPT_TEXT`. The runtime does not pass its internal `BENCH_*` variables into the model-execution environment.

If your executor wrapper can recover usage data from the underlying model provider, it can also write a JSON object to `TASK_METRICS_PATH`. The runtime will attach that payload to the command record and roll up known fields like `cost_usd` and token counts to the run manifest.
