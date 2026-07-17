<!-- Curated from reference/work/execution/done/001_clean_acr_loop.plan.md -->
---
PLAN_ID: 001
DEPENDS_ON: none
EXEC_ORDER: 1
---

# Plan: Loop back to repository selection after deletion in clean-acr.zsh

## Overview

Wrap the repository-selection-through-deletion flow in a loop so the user can clean multiple repos in one session.

## Testing

- `zsh -n deploy/azure/clean-acr.zsh`
