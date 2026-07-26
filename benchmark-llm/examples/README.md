# Examples

This folder holds runnable and reference benchmark packages for each authoring rail.

- `logic-mini/` is the lowest-ceremony prompt-batch example.
- `cron-eval/` is a deterministic repo-task benchmark with a 100-case hidden conformance suite and narrative adjudication.
- `policy-engine/` is a repo-task reference benchmark adapted from the policy-engine evaluation package and report shape.
- `plugin-advanced/` is a small Python plugin benchmark that shows the escape hatch for custom orchestration.

Both repo-task examples are configured for three breadth-ordered runs per model. Before running one, follow its README to configure a source repository and a writable output directory.
