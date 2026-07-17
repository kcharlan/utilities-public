# Evaluation Sheet

| Field | Value |
| --- | --- |
| Model | {{ model }} |
| Provider | {{ provider }} |
| Date | {{ date }} |
| Time started | {{ time_started }} |
| Time ended | {{ time_ended }} |
| Elapsed minutes | {{ elapsed_minutes }} |
| Cost | {{ cost }} |
| Turns/prompts | {{ turns }} |
| Human interventions | {{ interventions }} |
| Visible set summary | {{ visible_summary }} |
| Hidden C summary | {{ hidden_c_summary }} |
| Hidden D summary | {{ hidden_d_summary }} |
| Mutation summary | {{ mutation_summary }} |
| Final score | {{ final_score }} |
| Notes | {{ notes }} |

## Findings

- {{ finding_1 }}
- {{ finding_2 }}
- {{ finding_3 }}

## Score Breakdown

- Visible correctness: {{ score_visible }}
- Hidden generalization: {{ score_hidden_generalization }}
- Hidden robustness and safety: {{ score_hidden_robustness }}
- Code quality and restraint: {{ score_code_quality }}
- CLI and output usability: {{ score_cli }}
- Tests and docs: {{ score_tests_docs }}
- Run hygiene and efficiency: {{ score_run_behavior }}
