# Cron Eval Open Questions

## Mutation A assertion mismatch — RESOLVED 2026-05-01

The original Section 14.G weighted all 10 `dom_dow_interaction` cases at 1.5 points each. With the mutation only affecting the four both-restricted cases, the maximum loss was 6 points (9/15 retained), making the plan's `≤5/15` target mathematically unreachable.

Resolution: Section 14.G fixture weights were rebalanced to reflect the disproportionate importance of the POSIX OR-rule:

- `ddi_01`–`ddi_04` (both restricted): 2.5 each = 10 points
- `ddi_05`–`ddi_08` (single restricted): 1.0 each = 4 points
- `ddi_09`–`ddi_10` (`?` synonym): 0.5 each = 1 point
- Total: 15 points (unchanged)

Verified validator results after fix:

```text
mutation_a_and_dom_dow score=89  dom_dow_interaction=5/15
mutation_b_duplicate_fallback   timezone_dst=6/10
mutation_c_value_error          errors=0/5
```

All three mutations now match Section 11 Step 3 targets.

The plan's Section 11 Step 3, Section 14.G, and Section 14.J have been updated. The on-disk fixtures `ddi_01.json`–`ddi_10.json` carry the new weights.
