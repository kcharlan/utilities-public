# Examples

This folder holds runnable and reference benchmark packages for each authoring rail.

- `logic-mini/` is the lowest-ceremony prompt-batch example.
- `policy-engine/` is a repo-task reference benchmark adapted from the policy-engine evaluation package and report shape. Its `bench.yaml` is preconfigured with `runs: 3`, `run_order: breadth`, and `output_dir: ~/Downloads/benchmark-llm`.
- `plugin-advanced/` is a small Python plugin benchmark that shows the escape hatch for custom orchestration.
