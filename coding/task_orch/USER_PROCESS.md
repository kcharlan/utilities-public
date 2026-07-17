# Agent Pipeline — User Process Guide

## What this is

A pipelined workflow where planning agents (cc-opus) convert work items into
implementation plans, and worker agents (cc-sonnet) execute those plans
sequentially. A bash orchestrator script coordinates the queue.

    You (write intake) → plan.sh → review? → stage.sh → orchestrate.sh
           ↓                 ↓         ↓          ↓            ↓
       intake/         staging/    you resolve   ready/    done/ or blocked/
                       + review/                          (parallel workers
                                                           with worktrees)

## Quick start

### 1. Write intake items

Create numbered markdown files in `task_orch/planning/intake/`:

```bash
cat > task_orch/planning/intake/001_add_export_api.md <<'EOF'
# Add CSV export endpoint

Add a GET /api/plans/:id/export/csv endpoint that exports the benefit
specification as a CSV file.

## Context
- Plan data is in Cosmos DB, accessed via src/backend/cosmos_client.py
- Existing endpoints are in src/backend/server.py
- See docs/Developer_Guide.md for routing patterns

## Acceptance criteria
- Returns CSV with headers matching the plan schema
- Returns 404 for nonexistent plan IDs
- Requires authentication (same as other /api/plans endpoints)

## Notes
- Keep it simple — no streaming needed for v1
- Add targeted tests in tests/test_server.py
EOF
```

Naming convention: `<NNN>_<short_slug>.md` where NNN is a zero-padded sequence
number. The orchestrator processes plans in numeric order.

### 2. Launch planner agents

```bash
# One planner (default)
task_orch/plan.sh

# Two planners in parallel (for larger intake batches)
task_orch/plan.sh 2
```

The script launches cc-opus agents that run autonomously. Each planner:
1. Claims intake items by moving them to `claimed/`
2. Reads relevant source code
3. Writes full implementation plans to `ready/` — or to `review/` if there
   are open questions that would materially affect the implementation
4. Continues until intake is empty, then stops

The script waits for all planners to finish and reports results: how many
plans are ready, how many need review, and whether any items are stuck in
`claimed/` (which indicates a planner failure). Logs are in
`task_orch/planning/planner_A.log` (and `planner_B.log` if running two).

You can also launch planners manually if you prefer interactive control:

```bash
cc-opus -p "Read task_orch/planning/PLANNER.md. You are Planner A. Begin."
```

### 3. Review plans (if any)

Check if any plans need your input before proceeding:

```bash
ls task_orch/planning/review/
```

If plans are in `review/`, you have two options (see section 7 for details):
- **Quick turnaround:** Add answers to the top of the file, move it back to
  `intake/`, and run `task_orch/plan.sh` again for the planner to revise it.
- **Deep dive:** Open an interactive cc-opus session to work through the
  questions, then move the finalized plan to `staging/`.

Or proceed to step 4 with whatever is already in `staging/` — reviewed
plans can be added later.

### 4. Resolve dependencies

Once plans are in `staging/`, run the dependency resolver before execution:

```bash
task_orch/stage.sh
```

This launches a cc-opus agent that reads ALL staged plans, identifies
cross-plan dependencies (file overlap, schema dependencies, logical
ordering), sets DEPENDS_ON and EXEC_ORDER in each plan's metadata, flags
conflicts, and moves resolved plans to `execution/ready/`.

Review the resolution report: `cat task_orch/execution/RESOLUTION.md`

If plans are left in `staging/` (conflicts or circular deps), resolve
them manually and re-run `task_orch/stage.sh`, or move them directly to
`execution/ready/` with DEPENDS_ON set by hand.

### 5. Start the orchestrator

```bash
# Default: 2 parallel workers, full test every 4 completed plans
task_orch/orchestrate.sh

# Custom: 3 workers, full test every 5 plans
MAX_WORKERS=3 FULL_TEST_INTERVAL=5 task_orch/orchestrate.sh
```

The orchestrator will:
1. **Guard:** Refuse to run if the current branch is `main`
2. **Recover:** Clean up any leftover worktrees/state from a prior crash
3. **Parse chains:** Read `RESOLUTION.md` for dependency chains
4. **Dispatch chains in parallel:** Each chain gets its own worker slot and
   git worktree. Independent chains run simultaneously.
5. **Merge on completion:** When a worker finishes its chain, the orchestrator
   merges the worktree branch back to the current branch
6. **Run full test suite** every N completed plans (pauses merges, waits for
   active workers to finish first)
7. **Halt** if full tests fail
8. **Exit** when all chains are processed

Workers within a chain execute plans sequentially (respecting dependencies).
Chains run in parallel (they touch independent files by construction).

### 6. Monitor progress

Check the auto-generated dashboard:

```bash
cat task_orch/DASHBOARD.md
```

Or watch it update:

```bash
watch -n 5 cat task_orch/DASHBOARD.md
```

The dashboard shows each worker slot's current chain assignment, PID, and
the plans in that chain.

### 7. Review plans that need human input (ongoing)

When a planner has questions that would materially affect the implementation,
it writes the plan to `review/` instead of `staging/`. These plans won't
enter the dependency resolver or the execution queue — they're parked
until you resolve them.

Check for plans awaiting review:

```bash
ls task_orch/planning/review/
```

Each plan in `review/` has a `## Questions for Review` section at the top
listing what the planner needs answered. The rest of the plan is drafted
using the planner's best-guess answers, with affected steps marked ⚠️.

**Path A — Quick turnaround** (you're busy herding processes):

Add your answers or directives at the top of the plan file and drop it back
into `intake/`. The next planner pass will pick it up, incorporate your
answers, and route the revised plan to `staging/`.

```bash
# Add answers to the top of the file
vim task_orch/planning/review/001_something.plan.md
# Drop it back into intake for the planner to revise
mv task_orch/planning/review/001_something.plan.md task_orch/planning/intake/
```

This is best when: answers are straightforward, you don't need to discuss,
and planners are still running (or you'll run `task_orch/plan.sh` again).

**Path B — Deep dive** (complex problem, needs discussion):

Open an interactive session to work through the questions with an agent:

```bash
cc-opus -p "Read task_orch/planning/review/001_something.plan.md. \
  Here are my answers: Q1: use JWT not sessions. Q2: yes, add pagination. \
  Update the plan accordingly and remove the Questions for Review section."
```

Or load the file and discuss interactively until the plan is solid. Then
move the finalized plan to `staging/` (for dependency resolution) or
directly to `execution/ready/` (if you're sure it has no cross-plan deps):

```bash
# Normal — goes through dependency resolution
mv task_orch/planning/review/001_something.plan.md task_orch/planning/staging/

# Skip resolver — you know this plan is independent
mv task_orch/planning/review/001_something.plan.md task_orch/execution/ready/
```

This is best when: the questions are complex, you want to explore tradeoffs,
or you need to make architectural decisions that benefit from discussion.

### 8. Handle blocked plans

Plans only land in `blocked/` after the orchestrator's auto-fix system has
been exhausted (2 attempts by default). Fixer logs are preserved in `blocked/`
alongside the plan (`*_fix_attempt_1.log`, `*_fix_attempt_2.log`). Review
these to understand what was tried before manual intervention.

When a plan lands in `blocked/`, the worker couldn't complete it. Check:

```bash
# See why it blocked
cat task_orch/execution/blocked/<plan_id>.status

# See the full worker log
cat task_orch/execution/blocked/<plan_id>.log
```

Your options:
- **Fix and retry:** Edit the plan if needed, then move it back to `ready/`:
  `mv task_orch/execution/blocked/<plan>.plan.md task_orch/execution/ready/`
- **Escalate:** Open the plan in an interactive cc-opus session to debug
- **Skip:** Leave it in `blocked/` and continue with other plans

### 9. Handle full test suite failures

When the full test suite fails, the orchestrator automatically launches a
fixer agent to diagnose and fix the failures (up to 2 attempts). The
orchestrator only halts if auto-fix is exhausted. Fixer logs are preserved
in `task_orch/execution/` for post-mortem.

If the orchestrator halts due to a full test failure:

1. Check which tests failed: `./scripts/test_all.sh`
2. Fix the failures (interactively or via a new intake item)
3. Restart the orchestrator: `task_orch/orchestrate.sh`

### 10. Restart after a crash

The orchestrator is safe to restart at any time. On startup it:
1. Removes any leftover `.worktrees/worker_*` directories
2. Moves any plans stuck in `workers/*/` back to `ready/`
3. Re-reads `RESOLUTION.md` for chain definitions
4. Skips chains whose plans are already in `done/`
5. Resumes with remaining chains

No manual cleanup needed — just re-run `task_orch/orchestrate.sh`.

## Directory structure reference

```
task_orch/
  SYSTEM.md              # Rules read by all agents
  USER_PROCESS.md        # This file (human documentation)
  DASHBOARD.md           # Auto-generated status (read-only)
  plan.sh                # Planner launcher script
  stage.sh               # Dependency resolver launcher
  orchestrate.sh         # Queue runner script

  planning/
    PLANNER.md           # Planner agent instructions
    planner_A.log        # Planner output logs (generated)
    intake/              # Raw work items you write
      001_something.md
      002_something.md
    claimed/             # Planner is working on these
    staging/             # Plans awaiting dependency resolution
    review/              # Plans needing human input

  execution/
    RESOLVER.md          # Dependency resolver instructions
    RESOLUTION.md        # Resolver output report (generated)
    resolver.log         # Resolver output log (generated)
    WORKER.md            # Worker agent instructions
    ready/               # Dependency-resolved, queued for execution
      001_something.plan.md
    workers/             # Per-worker slots (parallel mode)
      0/                 # Worker slot 0
        chain.id         # Chain ID assigned to this worker
        *.plan.md        # Plans in this chain
        *.status         # Status sidecars
        *.log            # Worker output
      1/                 # Worker slot 1
      ...
    active/              # (Legacy) single-worker execution
    done/                # Successfully completed
      001_something.plan.md
      001_something.status
      001_something.log
    blocked/             # Failed, needs human attention
```

## Configuration

Environment variables for the orchestrator:

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_WORKERS` | `2` | Parallel worker slots (1–4) |
| `FULL_TEST_INTERVAL` | `4` | Run full test suite every N completed plans |
| `POLL_INTERVAL` | `5` | Seconds between worker PID checks |
| `FIXER_MODEL` | `opus` | Model for auto-fix agents (e.g., opus, sonnet) |
| `MAX_FIX_ATTEMPTS` | `2` | Auto-fix attempts before blocking/halting |

Example:

```bash
MAX_WORKERS=3 FULL_TEST_INTERVAL=5 POLL_INTERVAL=3 task_orch/orchestrate.sh
```

## Intake item format

Keep intake items focused. Each should represent 30–120 minutes of
implementation work. If a task is larger, the planner will split it into
multiple plans with dependency links.

```markdown
# <Imperative title>

<1–3 paragraph description of what needs to happen>

## Context
- <relevant file paths>
- <relevant docs or prior plans>
- <architectural constraints>

## Acceptance criteria
- <specific, testable outcomes>

## Notes
- <risks, gotchas, things the planner should know>
```

## Testing cadence

| Event | What runs | Who triggers it |
|-------|-----------|-----------------|
| Worker starts a plan | Targeted component tests | Worker agent |
| Worker finishes a plan | Targeted component tests | Worker agent |
| Chain merge succeeds | Merge commit on target branch | Orchestrator |
| Every N completed plans | Full suite (test_all.sh) | Orchestrator |
| Full suite fails | Queue halts | Orchestrator |
| High-priority plan completes | Full suite (test_all.sh) | Orchestrator |

This is relaxed compared to the standard "full suite on every exit" policy.
The tradeoff: faster throughput, but integration bugs may survive 2–3 plans
before being caught. The circuit breaker (halt on full suite failure) limits
the blast radius.

## Tips

- **Start with one planner.** Get the flow working before adding a second.
- **Front-load intake.** Write 4–8 intake items before launching planners.
  This gives the pipeline something to chew on.
- **Review plans before they execute.** If you want a human gate, move plans
  from `ready/` to a `reviewed/` directory, then move approved ones back to
  `ready/`. Or just review them in `ready/` before starting the orchestrator.
- **Checkpoint your branch.** Before a long orchestrator run, tag or branch
  so you can reset if things go sideways:
  `git tag pipeline-start-$(date +%Y%m%d-%H%M)`
- **Watch the logs.** Worker output is captured in `.log` files alongside
  plans in `done/` and `blocked/`.
- **E2E coverage.** The full test suite (`test_all.sh`) now includes automated
  Playwright browser tests. Planners are required to specify e2e tests for any
  UI-facing change, and workers must write the Playwright specs. Manual
  container verification is only needed for exploratory/visual spot-checks
  beyond what automated e2e covers.
