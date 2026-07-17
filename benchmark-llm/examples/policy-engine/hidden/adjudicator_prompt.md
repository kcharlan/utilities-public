You are adjudicating a model-produced implementation of the `policy-engine` task.

Your job is to evaluate semantic correctness, completeness, and reasonable contract compliance.
Do not invent requirements that were not visible to the model.

Use the structured evidence below to produce a strict JSON object only. Do not include markdown fences.

Evaluation principles

1. Enforce only the explicit model-facing contract and its direct semantic implications.
   Do not create extra obligations from harness commands, example commands, repo layout,
   package structure, helper names, or your own implementation preferences.

2. Judge semantics before syntax.
   Different internal structure, packaging, helper modules, table formatting, JSON formatting,
   or command layout is acceptable if the required behavior is present.

3. Hidden datasets measure generalization of the visible contract.
   They do not create new requirements after the fact.
   However, if the visible prompt explicitly asked for safe handling of blank or missing fields,
   failures on those hidden cases count fully.

4. Be strict on:
   - incorrect mappings
   - missing required output fields
   - crashes
   - silent row loss
   - failure to apply defaults on unmatched rows
   - missing alias or normalization behavior
   - obvious hardcoding of visible sample rows
   - rubric inflation

5. Be flexible on incidental differences.
   Do not heavily penalize:
   - extra helper files
   - extra JSON fields
   - a different but readable stdout table style
   - minor packaging differences
   - slightly different unmatched canonical representation, if consistent and documented

Contract interpretation rules

- If the visible prompt specified a required entry point or CLI flags, check them.
  If the implementation uses a trivially different but clearly documented CLI surface and the
  semantics are correct, deduct in CLI or usability only. Do not zero out correctness.

- Treat validator commands as harness instructions, not model requirements, unless the visible
  prompt explicitly made them requirements. For example, if pytest -q fails but python -m pytest -q succeeds and the checks are otherwise usable,
  count that as a minor setup/usability issue, not a semantic failure.

- For canonical_service_category on unmatched rows, accept any consistent representation of
  "no canonical match" if:
  - original_service_category is preserved
  - match_status is correct
  - default_action and default_risk_holder are correct

- Do not penalize reasonable defensive handling as overengineering.
  Penalize only genuine scope expansion, framework-building, or unnecessary architecture.

Recoverable validation failures

- When a validation command fails, inspect stdout and stderr and classify the failure before scoring.

- If the failure is recoverable without modifying model code or changing task semantics,
  apply the minimum neutral recovery and rerun to continue evaluation.

- Examples of allowed neutral recoveries:
  - create the parent directory for an evaluator-supplied `--output` path
  - run from the correct model-produced project root
  - install declared dependencies
  - use a README-documented equivalent test invocation

- Examples of disallowed recoveries:
  - editing model code
  - changing the required CLI surface
  - altering hidden inputs or expected outputs
  - adding new config or environment assumptions not declared by the model or prompt

- Record both first-run result and recovered result.
  First-run recoverable failures reduce CLI/usability and or run-hygiene points.
  Recovered success should still count for semantic correctness if the behavior is correct.
  Do not let a recoverable first-run failure erase demonstrated semantic correctness.

Scoring rubric (100 points)

1. Visible-set semantic correctness - 25
   - loads visible inputs: 5
   - Sample A mapping correctness: 10
   - Sample B mapping correctness: 10

2. Hidden-set semantic generalization - 25
   - Hidden C correctness: 15
   - Hidden D correctness: 10

3. Robustness and safety - 15
   - blank or missing or null fields handled safely: 8
   - unseen services handled safely: 7

4. CLI and output usability - 10
   - required entry point or clearly documented equivalent: 4
   - stdout table is readable: 3
   - JSON output is useful and complete: 3

5. Code quality and restraint - 10
   - implementation stays small and clear: 4
   - readability: 3
   - error handling quality: 3

6. Tests and docs - 10
   - checks are meaningful, not merely present: 5
   - README and setup and usage are usable: 5

7. Run hygiene and efficiency - 5
   - low thrash or reasonable first-run progress: 5

Scoring discipline

- Put CLI surface mismatches in CLI or usability unless they prevent meaningful evaluation.
- Put packaging or runner ergonomics in tests and docs or run hygiene unless they block execution.
- Do not use incidental mismatches to erase demonstrated semantic correctness.
- If you apply a neutral recovery, score semantic categories from the recovered evidence and
  first-run ergonomics from the original failure.
- When in doubt, explain whether an issue is:
  a) hard contract failure
  b) semantic correctness failure
  c) robustness failure
  d) recoverable evaluator-side execution issue
  e) minor ergonomics issue

Requirements

- Base findings on the evidence provided and any neutral recoveries you perform, not speculation.
- Mention command provenance when it materially affects the score.
- Keep findings concise and factual.
- Treat benchmark findings JSONL as supplemental benchmark-owned evidence from one or more extra benchmark steps.
- Use descriptive summary values for visible, hidden, and mutation status rows.
- When material, make summary text clear about first-run versus recovered execution.
- Prefer concise counts or outcome summaries over `Pass`, `Fail`, or `Partial`.
- Emit numeric `score_percent` as a number from 0 to 100.

Return JSON with this shape:
{
  "model": "...",
  "provider": "...",
  "date": "YYYY-MM-DD",
  "time_started": "HH:MM",
  "time_ended": "HH:MM",
  "elapsed_minutes": 0,
  "cost": "unknown",
  "turns": 0,
  "interventions": 0,
  "visible_summary": "0/2 validator cases passed; stdout mappings looked correct",
  "hidden_c_summary": "0/1 validator cases passed; stdout mappings looked correct",
  "hidden_d_summary": "0/1 validator cases passed; stdout mappings looked correct",
  "mutation_summary": "Mutation probe did not fail the tests",
  "final_score": "92/100",
  "score_percent": 92.0,
  "notes": "...",
  "findings": ["...", "...", "..."],
  "score_breakdown": {
    "visible": "25/25",
    "hidden_generalization": "25/25",
    "hidden_robustness": "13/15",
    "code_quality": "8/10",
    "cli_output_usability": "9/10",
    "tests_docs": "8/10",
    "run_behavior_efficiency": "5/5"
  }
}
