# Intake Document Generator — Session Prompt

> **Usage:** Start a Claude session and say:
>
> ```
> Read <pack_root>/prompts/intake.md and convert the following list of items
> into work intake documents:
>
> - <item 1 description>
> - <item 2 description>
> - ...
> ```
>
> Then drop the generated `.md` files into the session's `intake/` directory.

---

## What You Are Doing

You are converting a human's shorthand list of work items into fully specified
intake documents for Cognitive Switchyard's agent pipeline. Each intake document
will be picked up by a planning agent, which will read it and produce a detailed
implementation plan. The planner is smart but has no context beyond what you
write — each document must be self-contained with enough context for the planner
to find the right code and make good decisions.

## Before Writing Anything

1. **Read these files** (in this order):
   - `CLAUDE.md` (repo root) — project conventions, test commands, branch workflow
   - `docs/LESSONS_LEARNED.md` — avoid writing intake items that would lead the
     planner into known pitfalls

2. **Explore the codebase** for each item in the user's list:
   - Find the relevant source files (frontend components, backend routes, scripts,
     etc.) using Glob and Grep
   - Read enough of each file to understand current behavior, key function names,
     data structures, and file paths
   - If the item references external data files (e.g., sample data, schemas),
     read those too
   - Note the exact file paths — the planner needs them

3. **Ask material questions** before writing if:
   - An item is ambiguous enough that two reasonable interpretations would produce
     very different intake documents
   - You need to know the user's preference on UX, scope, or priority
   - An item references something you can't find in the codebase
   - Do NOT ask about things you can figure out by reading code

## Intake Document Format

Each intake document is a standalone markdown file (`.md`, not `.plan.md`).

**Filename:** `<NNN>_<short_snake_case_slug>.md`
- NNN = zero-padded sequence number (001, 002, ...)
- **Automatic numbering:** Read the integer from `NEXT_SEQUENCE` in the
  session's `intake/` directory. Use that number for the first document,
  increment for each subsequent document, then write the final next value
  back. If `NEXT_SEQUENCE` does not exist, create it starting at 1.
- As a defensive check, verify no file with that number already exists
  anywhere in the session. If a collision is found, increment until clear
  and update `NEXT_SEQUENCE` accordingly.

**Structure:**

```markdown
# <Imperative title — what to do, not what's wrong>

<1-3 paragraphs describing what needs to happen and why. Include enough
context that a reader unfamiliar with the codebase can understand the problem
and the desired outcome. Reference specific UI elements, user flows, or
system behaviors by name.>

## Context
- <exact file paths of relevant source files>
- <relevant docs, APIs, or data files>
- <architectural constraints or related systems>
- <current behavior summary — what happens today>

## Acceptance criteria
- <specific, testable outcome>
- <specific, testable outcome>
- <...>

## Notes
- <risks, gotchas, edge cases>
- <UX preferences or constraints>
- <anything the planner should know but isn't an acceptance criterion>
```

## Quality Standards

- **Be specific about current behavior.** Don't just say "it's broken" — say
  "the drawer shows status, created, started, and elapsed, but does not show
  snapshot_id, filename, or document_id, which are available in the API response."

- **Include file paths.** The planner will read these files. Give it:
  - Frontend files (components, views, JS modules)
  - Backend files (routes, models, services)
  - Scripts or tools being modified
  - Test files that exist for the affected code
  - Sample data or schema files that illustrate the problem

- **Describe the data.** If the issue involves data not being displayed, describe
  what data exists (field names, example values, where it comes from) and what
  the user currently sees vs. what they should see.

- **Acceptance criteria must be testable.** "Better UX" is not testable. "Each
  document in the documents list shows a colored status tag (Pending=yellow,
  Processing=blue, Complete=green, Failed=red) that updates without page refresh"
  is testable.

- **Scope each item to 30-120 minutes of implementation work.** If an item is
  clearly larger (touches many files, multiple subsystems, complex UI), note
  that in the document. The planner will split it into multiple plans.

- **Note when items are related.** If two intake items touch the same area or
  have a logical ordering dependency, mention it in the Notes section of both.
  The dependency resolver handles execution ordering, but the planner benefits
  from knowing the relationship upfront.

## After Writing All Documents

1. List the files you created with a summary table (number, filename, one-line
   description)
2. Call out any items where you had to make assumptions and what those were
3. Call out any items that are likely large enough for the planner to split
4. Report the total count and confirm the numbering is clean

## What NOT to Do

- Do not write implementation plans — that's the planner's job
- Do not write code — that's the worker's job
- Do not create `.plan.md` files — only `.md` files go in intake
- Do not modify existing intake documents unless the user asks you to revise one
- Do not guess at acceptance criteria when the user's intent is unclear — ask
