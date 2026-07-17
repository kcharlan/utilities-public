<!-- Curated from reference/work/execution/RESOLUTION.md -->
# Dependency Resolution Report

## Constraints

| Plan | DEPENDS_ON | ANTI_AFFINITY | EXEC_ORDER |
|------|------------|---------------|------------|
| 039  | none       | 043           | 1          |
| 043  | none       | 039           | 1          |

## Parallel Opportunities

- Independent: none in this minimal slice
- Anti-affinity group: 039 and 043 cannot run together
