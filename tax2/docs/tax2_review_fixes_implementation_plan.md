# Tax2 Built-Page Review Fixes — Implementation Plan

Status: approved scope, ready to execute · Date: 2026-10-08

## 0. Context and authority

The post-implementation review of branch `codex/tax2-built-page` (head
`b596582`) found defects, specification gaps, documentation drift and test
gaps. The user asked for every finding to be fixed except one (§1, Out of
scope). This plan is the work order.

The binding sources are:
- `tax2/docs/tax2_built_page_design_spec.md` (the spec);
- `agents.md` → UI Shapes;
- this plan.

Where this plan defines behaviour the spec leaves open, record it in the spec
(Task 9).

**Rules for every task:**
- Work on branch `codex/tax2-built-page`. **Do not push it, and do not rewrite
  its history.** See §11.
- **Public repository:** no personal paths, names, localities or private file
  references in code, tests, docs or commit messages. Fixtures stay
  conspicuously synthetic.
- **No real runtime state:** never read or write the real `~/.tax2`. Every
  test, capture and manual run uses a temporary `TAX2_HOME` (§2a).
- **Python only through `tax2/.venv/bin/python`.** Repo-root tooling tests use
  the utility venv `~/.venvs/agent-tools/bin/python`, per the global
  environment rules.
- **No duplicate logic:** each behaviour lives in one function, and every call
  site uses it.
- **Test-first where practical.** Write each task's acceptance tests, watch
  them fail on current code where the defect is behavioural, then fix. Every
  named test must exist and pass at the end.
- **Commits:** one commit per task, or per tightly related group. Each has an
  imperative subject and a meaningful body. Inspect the staged diff for
  sensitive data before every commit.

## 1. Scope

**In scope:** Tasks 1–10.

**Out of scope (user decision):** `formatCents` throwing for amounts at or
above `Number.MAX_SAFE_INTEGER` cents (about $90 trillion) under absurd rules.
Leave it unchanged.

**Do not change:** tax arithmetic, the rounding direction (D6), the parity
fixture, the frozen rules, bundled rule values, or the vendored libraries.

## 2. Baseline gates (run first and record)

From `tax2/`:
- `TAX2_HOME="$(mktemp -d)" .venv/bin/python -m pytest -q -p no:cacheprovider`
  (the review run showed `352 passed`, 0 skipped).
- Export a temporary `TAX2_HOME` for every pytest run until the §2a conftest
  fixture lands. Some current tests call `build_payload` without setting one.

From the repository root:
- `uv run --no-python-downloads --script tools/check_uv_headers.py`, which
  should print `OK`.
- `~/.claude/shared/agent-tools.sh ensure`, then
  `~/.venvs/agent-tools/bin/python -m pytest -q -p no:cacheprovider tools/tests/test_check_uv_headers.py`.
- `zsh tools/tests/test_check_local_deployments.zsh`, which should print
  `PASS`.
- `node --test tools/tests/check_static_deployments.test.mjs`.

**Recording results.** Record the actual counts.
- If a count differs from the review numbers but every test passes, record the
  difference; it is not a failure.
- If any baseline test fails, stop and report before changing code.

## 2a. Test conventions

**Runtime home**
- Add an autouse fixture in `tax2/tests/conftest.py` that points `TAX2_HOME`
  at a fresh `tmp_path / "tax2-home"` for every test, unless a test sets its
  own. Land it in the first commit.
- Existing tests that set `TAX2_HOME` themselves keep working.

**Where tests go**
- **Built-page browser tests:** extend the existing fixtures and helpers in
  `tests/test_browser_smoke.py`. Each test opens the page from `file://` in
  offline Chromium, uses `guard_browser_errors`, and fails on any non-`file:`
  request.
- **Engine tests:** use the existing `engine_page` fixture. Extend existing
  tests where one already covers the function, for example the parser tests at
  `tests/test_browser_smoke.py:86`.
- **Synthetic rules roots:** build them in `tmp_path`, as
  `tests/test_page_build.py::synthetic_root` does.

**Expected values**
- Write expected values into the test, derived by hand or from the fixture.
  Never compute them with the code under test.
- Compare colours after normalizing both sides to the browser's computed
  `rgb(...)` form. For example, read the computed colour of a probe element
  styled with `var(--accent-tax)`.

---

## Task 1 — The page can never replace config (must fix)

### Defect
On macOS's case-insensitive APFS, `--output <home>/CONFIG.yaml` passes the
guard, and the page replaces `config.yaml`. This was reproduced: exit 0, and
`config.yaml` became HTML. `validate_output_destination` (`taxkit/config.py:51-56`)
compares `Path` objects case-sensitively.

### Required behaviour
Page publication (`os.replace` onto the output entry) must never replace any
of these entries met while resolving the config path. Plain directories on the
path are not listed, because `os.replace` cannot put a file over a
directory.
- the config entry itself;
- every symlink entry met while resolving it, including directory symlinks in
  its path and in link text, and a symlinked `TAX2_HOME`;
- the final target, whether or not it exists.

This must hold regardless of letter case. It must also hold whether or not
config, its target or the runtime home exists when the command starts.

A config symlink loop or unresolvable chain must **not** fail builds whose
output aliases nothing in the protected set. Such builds warn through the
existing config read, use the defaults, and build.

**This is new behaviour on some interpreters.** Today a looping config fails
even default builds on Python 3.12, which `tax2/.venv` uses:
`validate_output_destination` calls `config.resolve(strict=False)`, which
raises `RuntimeError` on Python 3.12 (not `OSError`). The loop test below
therefore fails before the fix there.

**Avoid `Path.resolve()` in these helpers.** Do not call it on the config
chain, on `TAX2_HOME`, or on name-rule parents. The output entry itself may
keep coming from `_publication_entry`. A loop in the output's own parent
already exits 1 through the launcher's error handling. Use `os.lstat`, `os.readlink`
and `os.path.realpath`, and catch their errors as described below.

### Approach (load-bearing)
Put all of this in `taxkit/config.py`, in two helpers used by both call
points.

1. **`config_resolution_entries(config_entry) -> list[Path]`**
   - Resolve the config path component by component, the way `realpath`
     does.
     - Start from its absolute form, built with `Path.absolute()` or a join
       onto the current directory. Never use `os.path.abspath` or `normpath`:
       they collapse `link/..` lexically.
     - "Appending" a component below means appending it to the path being
       resolved, not to the recorded entries.
   - Record the absolute path of every entry visited that is a symlink (the
     link entry itself, not its target), then the final resolved path, which
     may not exist.
   - For each symlink, read its text with `os.readlink`. Resolve relative text
     against the link's own parent, then continue resolving the remaining
     components.
   - Stop after 40 symlink expansions. On a loop, or on that limit, return the
     entries recorded so far plus the original config entry; never raise. The
     loop itself is handled by the existing config read, which warns and uses
     the defaults.
   - Treat any `OSError` from `os.lstat` or `os.readlink` (for example ENOENT,
     ENOTDIR or EACCES) as meaning *this component is not a link*. Append it
     and keep joining the remaining components, exactly as
     `os.path.realpath(strict=False)` does. The final entry is always the full
     remaining path, so a missing directory or a non-directory component never
     shortens the protected set. Never let such an error escape the helper.
2. **`entry_matches(a: Path, b: Path) -> bool`**, comparing two
   directory-entry paths without following a final symlink.
   - **Existence:** an entry exists when `os.lstat` succeeds. Any `OSError`
     from `lstat`, `samefile` or `realpath` means "does not exist / not the
     same", as `os.path.lexists` behaves. None of these errors may escape the
     helper.
   - **Identity:** if both exist, compare `(st_dev, st_ino)`. This catches case
     variants and other aliases of existing entries.
   - **Name rule:** otherwise, if the two entries' parents are the same
     directory, compare
     `unicodedata.normalize("NFC", name).casefold()` of the two leaf names.
     - The parents count as the same directory when both exist and
       `os.path.samefile` is true.
     - When either parent does not exist, they count as the same when the
       NFC-casefolded `os.path.realpath(parent)` strings are equal. Without
       the casefold, a missing case-variant parent directory slips through:
       config → `<tmp>/other/real.yaml` with output
       `<tmp>/OTHER/real.yaml` on APFS.
   - **Conservative cases.** Document all three in the README's output rules:
     - On case-sensitive volumes the name rule rejects a case-variant name or
       parent unless both entries exist. Only when both exist does the
       identity rule decide; then an existing, distinct `CONFIG.yaml` is
       allowed.
     - `casefold` maps `ß` to `ss`.
     - The identity rule also rejects other hard links of config or its
       target, even though replacing such a link would not change config.
3. **`config_conflict(output, config)`** is true when the output entry (its
   physical parent plus the leaf name, as `_publication_entry` computes)
   matches any path from `config_resolution_entries` under `entry_matches`.
4. **Call points**
   - **Early:** at the existing call in `validate_output_destination`, before
     any private state is accessed. This replaces the current equality test.
     The Git ancestry checks are unchanged and run only here.
   - **Pre-publish:** call `config_conflict` again in the launcher, after
     `build_payload` (which creates or loads config) and before
     `atomic_write_bytes`. Do not put it inside the generic
     `atomic_write_bytes` helper, and do not run the Git checks again here.
   - The pre-publish call is defence in depth. The casefolded missing-parent
     rule makes the early check cover the known cases. The re-check guards
     against whatever the build itself creates between the two checks.
   - **On conflict, at either point:** exit 1 with
     `Tax2: Output destination would replace config.yaml`. Write no page, and
     leave existing config bytes and `mtime_ns` unchanged.

### Acceptance tests
All in `tests/test_launcher.py`, run through the launcher with a temporary
`TAX2_HOME`.

**Existing config**
- `test_case_variant_config_output_rejected`: with an existing config,
  `--output <home>/CONFIG.yaml` and `--output <home>/Config.YAML` each exit 1
  with the message above. Config bytes and `mtime_ns` are unchanged, and the
  home contains only `config.yaml`.

**First run**
- `test_case_variant_config_output_rejected_on_first_run`: try two starting
  states, (a) the home exists without config, and (b) the home does not exist.
  In both, `--output <home>/CONFIG.yaml` exits 1 at the early check. No
  `config.yaml` and no page are created, and in (b) no runtime home directory
  is created either. This matches `test_config_destination_rejected_before_creation`.

**Case-variant parent**
- `test_case_variant_missing_parent_rejected_early`: use
  `TAX2_HOME=<tmp>/runtime`, which does not exist, and
  `--output <tmp>/RUNTIME/config.yaml`. The build exits 1 on every volume
  type, and no runtime home, config or page is created.
- `test_case_variant_missing_target_parent_rejected`: `config.yaml` points at
  `<tmp>/other/real.yaml`, and `<tmp>/other` does not exist.
  `--output <tmp>/OTHER/real.yaml` exits 1, and neither directory is created.
- `test_prepublish_recheck_rejects_conflict`: disable only the early check. For
  example, patch `taxkit.config.validate_output_destination`'s conflict step,
  or inject a stub through a parameter. Do it so the launcher's pre-publish
  call still reaches the real `config_conflict`; state the mechanism in the
  test's docstring. Then run the launcher's
  main with `--output <home>/CONFIG.yaml` against an existing config. The
  pre-publish check exits 1, no page is written, and config bytes are
  unchanged.

**Symlinks**
- `test_dangling_config_symlink_target_rejected`: `config.yaml` points at a
  missing synthetic `target.yaml`. `--output <path to target.yaml>` exits 1,
  and `target.yaml` is not created. This is a regression guard: it already
  passes today, and must still pass after the change.
- `test_unresolvable_config_chain_still_builds`: `config.yaml` points at
  `<regular file>/child`. A default build exits 0, writes `tax2.html`, and
  logs the existing config-read warning.
- `test_intermediate_config_symlink_rejected`:
  - Set up `config.yaml → link_a → link_b → real.yaml`.
  - `--output link_a` and `--output link_b` each exit 1.
  - `real.yaml` bytes are unchanged, and every link still points where it did.
- `test_directory_symlink_in_config_path_rejected`:
  - `config.yaml → dirlink/real.yaml`, where `dirlink` is a directory symlink.
    `--output <home>/dirlink` exits 1, and `dirlink` is still a symlink to the
    same target.
  - A symlinked `TAX2_HOME`, with `--output` naming that symlink entry, exits
    1.
- `test_config_symlink_loop_still_builds_default_output`:
  - `config.yaml` is part of a symlink loop. A default build (no `--output`)
    exits 0, writes `tax2.html`, and logs the existing config-read warning.
    This fails before the fix on Python 3.12.
  - `--output` naming a loop member exits 1.

**Regression**
- Every existing P4 and config protection test passes unchanged.

**Done when:** all of the above pass, and a manual run with a synthetic
`TAX2_HOME` and `--output <home>/CONFIG.yaml` exits 1 with config unchanged.

---

## Task 2 — One rules-discovery implementation; strict year-file inventory (must fix)

### Defect
- `taxkit/page.py:_inventory` (lines 15–25) reimplements the numeric-year
  `.yaml`/`.yml` discovery and the `.yaml`-preferred rule.
- `taxkit/utils.py` `get_available_years` and `get_rule_path` are unused in
  production; only `tests/test_rules_v2.py` imports `get_available_years`.
- `path.is_file()` silently skips a broken symlink or a non-regular entry
  named like `2025.yaml`, but spec S4 says to validate every numeric-year
  file.

### Required behaviour
**One discovery function.** Add it to `taxkit/utils.py`, for example
`discover_year_files(directory: Path) -> dict[int, list[Path]]`.
- It returns every entry whose name fully matches
  `^[0-9]+\.(yaml|yml)$` (ASCII digits only), including non-regular entries,
  grouped by year in a deterministic order.
- `page.py` uses it.
- Delete `get_rule_path` and `get_available_years`. Tests that need a year
  list derive it from the new function.

**Every discovered entry must be a regular file or a symlink to one.**
- A broken symlink, directory, FIFO or other non-regular entry fails the build
  with exit 1.
- The message names the entry the same way existing rule-validation messages
  name files (they include the path; `test_launcher.py:404` asserts
  `str(bad)`).

**Order of checks.** Validate every candidate before choosing the winner for a
year.
- Preserve today's selection predicate exactly. Iterate candidates in sorted
  name order and keep a candidate when
  `year not in validated or path.suffix == ".yaml"`.
- So `.yaml` beats `.yml`. Among same-year `.yaml` duplicates (for example
  `02026.yaml` and `2026.yaml`) the last in sorted order wins. Among `.yml`
  duplicates the first wins.

**Payload unchanged.** For valid roots the payload is unchanged, apart from
`built_at`.

### Capture the payload before refactoring (load-bearing ordering)
Do this before changing `page.py` or `utils.py`.
1. With a temporary `TAX2_HOME` containing the synthetic config
   `default_states: [GA]` and `qif_overrides: {}`, call
   `build_payload(Path("tests/fixtures/parity/bundled/rules"), rules_source="custom", built_at="2026-01-01T00:00:00+00:00")`
   from `tax2/`.
2. Write the JSON with `sort_keys=True` to
   `tests/fixtures/payload_bundled_baseline.json`.
3. Commit it in its own commit. The body states it was captured with
   `page.py`, `utils.py` and config loading unchanged from `b596582`, using
   the frozen bundled rules and synthetic config.

### Acceptance tests
- **`tests/test_rules_v2.py::test_discovery_single_implementation`**
  - `taxkit.utils` exposes the new function and no longer defines
    `get_rule_path` or `get_available_years`.
  - A source check finds no `.suffix in (` or `stem.isdigit()` in `page.py`.
- **`tests/test_page_build.py::test_broken_year_symlink_fails_build`**
  - A broken `states/XB/2026.yaml` symlink in a synthetic root makes the build
    exit 1, and the message names that entry.
  - No page is written.
- **`tests/test_page_build.py::test_non_regular_year_entry_fails_build`**
  - A directory named `federal/2027.yml` fails the same way.
- **`tests/test_page_build.py::test_non_ascii_digit_year_ignored`**
  - An entry named with non-ASCII digits (for example Arabic-Indic digits
    followed by `.yaml`) is not treated as a year. The build behaves as if it
    were absent.
- **`tests/test_page_build.py::test_bundled_payload_unchanged_by_discovery_refactor`**
  - Rebuilding with the same inputs as the capture (frozen root, synthetic
    config, fixed `built_at`) equals `payload_bundled_baseline.json`.
- **Regression:** existing discovery and shadowing tests pass.

---

## Task 3 — UI behaviour

### 3a. Allocation input accepts only decimal numbers (should fix)

**Defect.** `parseAllocation` (`web/engine.js:152-156`) uses `Number(text)`,
so `0x10`, `0b11`, `0o7` and `1e1` are accepted. `0x10` shows as "16%" while
the field still says `0x10`.

**Required behaviour**
- Accept only text that fully matches
  `^\s*[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\s*$`.
- Clamp numbers outside 0–100, as today: `-5` → 0, `150` → 100. The field
  shows the clamped value, as today.
- Anything else shows "Enter 0–100" and makes the inputs invalid.

**Acceptance tests**
- **Engine:** extend the existing allocation-parser test, the one in
  `tests/test_browser_smoke.py` that uses `engine_page`.
  - Accepted: `50`, ` 50 `, `33.33`, `.5`, `5.`, `+7`, `-5` (→ 0), `150`
    (→ 100).
  - Rejected with `Enter 0–100`: `0x10`, `0b11`, `0o7`, `1e1`, `Infinity`,
    `NaN`, empty, `5%`, `1,000`.
- **Browser:** entering `0x10` shows the field error and the error card,
  shows no "16%" card, and disables the QIF download.

### 3b. Arrow-key stepping on allocation fields (low; restore the old number-input behaviour)

**Required behaviour**
- In an allocation field:
  - ArrowUp sets the value to `Math.floor(v) + 1`;
  - ArrowDown sets it to `Math.ceil(v) - 1`;
  - both clamp to 0–100.
- This matches the old `type="number" step="1"` snapping: 33.3 → 34 up, 33.3
  → 33 down.
- **Starting value.** `v` is the current valid value. If the field is invalid,
  `v` is the last valid value, which needs a new state field such as
  `lastValid`, because invalid state stores `value: null`.
- The key's default caret movement is prevented.

**Acceptance tests (browser)**
- 50 → ArrowUp → 51.
- 33.3 → ArrowUp → 34.
- 33.3 → ArrowDown → 33.
- 100 → ArrowUp → 100.
- 0 → ArrowDown → 0.
- After typing `abc` over 40, ArrowUp → 41.

### 3c. Total line is never stale (should fix)

**Defect.** `Total $X monthly = $Y annually` (`web/app.js:127,175`) uses the
last valid cents while an income field is invalid.

**Required behaviour.** While either income field is invalid, the line reads
`Total unavailable — fix the highlighted inputs.` Otherwise it shows the
current gross, as today.

**Acceptance test (browser).** With earned set to `1e5`, the line reads
exactly that text. After the input is fixed, it shows the new gross.

### 3d. Rate display uses one engine function, and its round-up direction is tested (should fix)

**Defect**
- The rate arithmetic exists twice: in `engine.js:129` (scale 100) and in
  `app.js:128` (scale 10, which also recomputes gross).
- No test uses a value where rounding up and rounding to nearest differ.

**Required behaviour**
- Add one engine function, for example
  `ratePercent(taxCents, grossCents, decimals)`. It returns
  `ceilScaled(taxCents / grossCents * 100, 10 ** decimals) / 10 ** decimals`,
  or 0 when gross is 0.
- Both `computeMonthly`'s `effective_rate` and the card sublabels call it.
  Sublabels pass `result.gross_cents`.
- Display formatting stays as today: sublabels use `.toFixed(1)`, and the
  combined rate prints without trailing zeros.

**Acceptance tests**
- **Engine:** one value at one decimal place and one at two decimal places
  where `Math.round` would give a lower figure. Assert the rounded-up result,
  and assert that the nearest-rounded figure differs. Example: the default
  2026 single Georgia scenario has a combined rate of 21.172…%. It displays
  `21.18`; nearest rounding gives 21.17.
- **Browser:**
  - Built with the fixed instant `2026-10-08T12:00:00Z`, as other tests use,
    so the default year is 2026, the default page shows `21.18% combined`.
    The builder's default instant, `2026-01-01T02:30:00Z`, is still
    2025-12-31 in America/New_York. It selects 2025, which computes 21.73%.
  - A scenario the executor chooses shows a card sublabel whose
    nearest-rounded value is lower. Assert the rounded-up string.
- **Source test:** `app.js` contains no `* 100` rate arithmetic.

### 3e. Invalid fields are visibly highlighted (should fix)

**Defect.** The error card says "Fix the highlighted inputs", but nothing is
highlighted:
- `[aria-invalid="true"] { border-color }` (`styles.css:556`) loses to the
  more specific rules at `:418` and `:547`;
- money inputs have `border: 0`;
- the `:focus` rules (around `:274` and `:432`) also override the colour.

**Required behaviour.** Every input with `aria-invalid="true"` shows an
`--accent-tax`-coloured indicator, whether focused or not, in both themes.
- **Bordered inputs** (allocation, date, payee and category text): use a
  border.
- **Money inputs:** use an outline or underline, for example
  `outline: 2px solid var(--accent-tax)`, because they have no border.

Valid inputs look exactly as they do today, focused and unfocused.

**Acceptance test (browser, both themes).** Check one money input, one
allocation input and the date input in two states:
- after an invalid `fill`, while still focused;
- after blurring.

In both states the computed border or outline colour must equal the
normalized `--accent-tax` (§2a), with a non-zero width. After the input is
fixed, the computed style matches the valid baseline captured before the
test.

**Avoid timing races.** Inputs animate with `transition: all 0.2s`. Either
assert with retrying checks (Playwright `expect(locator).to_have_css(...)` or
`expect.poll`), or inject `* { transition: none !important; }` into the test
page. Do this for the valid-baseline comparison too.

### 3f. Accessibility, parity and layout details (low)

**Required behaviour**
- Date and allocation field errors are linked to their inputs through
  `aria-describedby`, as money-input errors already are.
- The page `<title>` is `Tax2 - Professional Tax Calculator`.
- Focusing a money field whose value is 0 shows an empty box (the old
  behaviour), not `0`.
- **Wider than 1200 px:** restore independent column scrolling.
  `.app-container` is the viewport height, and the sidebar, main panel and
  export panel each scroll vertically on their own.
- **1200 px and narrower:** keep today's whole-page scrolling and the stacked
  export panel (F4).
- **769–1200 px:** remove the empty grid area under the sidebar, for example
  by making the sidebar span both grid rows.

**Acceptance tests (browser)**
- When the date and allocation inputs are invalid, their `aria-describedby`
  refers to the visible error element.
- `page.title()` equals the string above.
- Focusing the earned field at $0 gives `input_value() == ''`.
- **At 1440 wide, with a viewport short enough that the export panel
  overflows** (for example 1440×600 with both states selected):
  - all three columns have computed `overflow-y` of `auto` or `scroll`;
  - the `.app-container` height equals the viewport height;
  - first assert `scrollHeight > clientHeight` for the export panel;
  - then scroll the export panel and assert that its `scrollTop` increased,
    the main panel's `scrollTop` is unchanged, and `window.scrollY` is still
    0.
- **At 1024 px:** the sidebar's bounding-box bottom is at or below the export
  panel's bounding-box bottom, within 1 px. On today's layout it stops at the
  export panel's top, so this test must fail before the fix.
- **At 390 px:** the existing F4 checks still pass.

---

## Task 4 — Rate schedule procedure order and Markdown escaping

### 4a. Procedure steps are consistent for credited jurisdictions (should fix)

**Defect.** `web/engine.js:278-279` says, in step 6, to apply credits "before
dividing by 12", but step 5 already divided. `docs/Usage.md:139-142` repeats
the same contradiction.

**Required behaviour.** Replace the schedule's procedure with these seven
steps. They are consistent with spec §7.1 and §7 Credits.
1. Multiply monthly income by 12.
2. For a state, multiply earned and unearned income by its allocation first.
   Federal uses unallocated total income.
3. Use each component's income basis. Subtract its standard deduction,
   flooring taxable income at 0.
4. Find the bracket and apply its formula.
5. For a jurisdiction with credits, subtract them once from the annual tax of
   its total-income components, flooring at zero (see Credits).
6. Divide each component's annual tax (or the credited total-income section's)
   by 12 and round up to the next cent.
7. Add the results.

Keep the existing caveat lines. Keep the per-jurisdiction Credits text
consistent with these steps.

**Acceptance test (`test_exports.py`)**
- The schedule's procedure section equals the seven steps, in order.
- In a synthetic credited jurisdiction's schedule, no "before dividing"
  instruction appears after a divide step.

### 4b. Markdown escaping covers `&`, `~` and `#` (low)

**Required behaviour.** `markdownText` (`engine.js:266-268`) also
backslash-escapes `&`, `~` and `#`. The same helper still handles every
user-supplied string in the schedule.

**Acceptance test (`test_exports.py`)**
- Use a synthetic component labelled `A & B ~~x~~ #` and a synthetic credit
  named `C #1 ~`.
- The component heading is exactly `#### A \& B \~\~x\~\~ \#`.
- The credit line contains `C \#1 \~`.
- No unescaped `~~` or trailing ` #` remains anywhere in the schedule.

---

## Task 5 — Duplicate helpers in `engine.js` (low)

**Required behaviour**
- The digit-grouping regex `/\B(?=(\d{3})+(?!\d))/g` exists once, as a helper
  such as `groupDigits(text)`. Both `formatCents` and `exactNumber` call it.
- The Task 3d rate function is the only rate arithmetic.

**Acceptance.** A source test asserts that the grouping regex literal appears
exactly once in `web/engine.js`. All existing formatting tests pass unchanged.

---

## Task 6 — Config that isn't a mapping warns (should fix)

**Defect.** `normalize_config` (`taxkit/config.py:167-168`) silently returns
defaults when the YAML parses to a list, a scalar or null.

**Required behaviour**
- An existing config that parses to anything other than a mapping, including
  `null` from an empty file, logs one warning:
  `config.yaml is not a mapping; using defaults`.
- The warning never includes file content.
- The build uses the defaults and leaves the file untouched.
- A missing file is still created as today, with no warning.

**Acceptance tests (`tests/test_config.py`)**
- `test_non_mapping_config_warns`, parameterized over four configs:
  - `- GA\n`;
  - `just text\n`;
  - `42\n`;
  - an empty file.
- For each case:
  - exactly that message is logged at WARNING;
  - the defaults are used;
  - the file's bytes and `mtime_ns` are unchanged.
- Document the warning in the "Hand-edit preferences" section of
  `docs/Usage.md`.

---

## Task 7 — Test hygiene and coverage gaps

1. **Pin engine error messages.** The invalid-call test in
   `test_engine_parity.py` (around line 194) must assert the exact message for
   each call, in order, rather than "some non-empty string". Take the expected
   messages from the current guards after checking each names its cause, and
   list them in the test.
2. **No fixed `/tmp` paths.** The screenshot step in
   `test_browser_smoke.py:427-430` writes into `tmp_path` or
   `tmp_path_factory`. Add a source test that no test file other than itself
   contains `Path('/tmp')` or `'/tmp/'`. Build the searched strings at runtime
   so the test does not match itself.
3. **Two-year error format:** add `test_available_years_multi_year_format`.
   - Build a synthetic root with federal 2024, 2025 and 2026, and a synthetic
     state with 2025 and 2026 only. Select 2024 with that state.
   - The engine error is exactly
     `State <CODE> has no rules for 2024. Available years: [2025, 2026]`.
   - The page shows that text in its error card.
4. **Golden test uses the engine.** `test_golden_baselines.py` also runs
   `window.Tax2Engine.computeAnnual` against the frozen bundled root for every
   legacy `MONTHLY_INCOMES` case:
   - federal and GA;
   - both years;
   - both statuses.

   It compares the results with the fixture's unrounded annual values
   exactly. The existing fixture-versus-legacy-array check stays.
5. **Retired alias key only where §13 allows.**
   - Remove the retired table-alias config key from the synthetic config at
     `tests/test_page_build.py:46`. Its compatibility case already lives in
     `tests/test_config.py`.
   - Add a source test that walks the project's own files on disk. It must not
     use Git, because the deployed copy is not a Git repository.
     - Walk everything under the `tax2/` project directory. Exclude `.venv`,
       `__pycache__`, `.pytest_cache` and every other dot-directory.
     - **In a deployed copy:** spec §12 requires removing retired tracked files
       when deploying. A correctly deployed copy therefore passes, and a
       failure there correctly flags stale retired files such as an old
       `cli.py`.
     - Assert that the set of files containing the retired key equals exactly
       `{taxkit/config.py, tests/test_config.py, docs/tax2_built_page_design_spec.md, docs/tax2-built-page-migration-implementation-plan.md}`.
       Use set equality, not a subset check.
   - Build the key string at runtime (for example
     `"legacy_combined" + "_alias"`) so the test file does not match itself.
6. **Display-name fallback.** When the latest year's rules lack
   `display_name`, the payload uses the state directory's own name, as before
   the migration, not the uppercased code. Add
   `test_display_name_falls_back_to_directory_name`:
   - use a synthetic lowercase directory `xn/2026.yaml` without
     `display_name`;
   - expect `display_name == "xn"` and `code == "XN"`.

   Record the rule in spec §4 (Task 9).
7. **Stale bytecode.**
   - Delete every `__pycache__` directory under `tax2/` outside `.venv/`.
     They are ignored, generated files.
   - Verify with `find tax2 -path tax2/.venv -prune -o -name '*.pyc' -print`.
     After one full test run, it lists no `.pyc` for `cli`, `engine`, `qif`,
     `tablegen`, `test_api`, `test_cli_tables`, `test_built_browser` or
     `test_placeholder`.

---

## Task 8 — Documentation brought into line with the spec

### 1. `tax2/README.md` (spec §7, §8)
The README becomes the single home for the CSV manual-lookup procedure and its
caveats.

**Add a "Manual lookup" section.**
- Build it from `docs/Usage.md:134-160`. Correct that text as follows, rather
  than copying it as is:
  - the schedule procedure matches Task 4a's seven steps exactly, which fixes
    the "before dividing" contradiction;
  - say "the rate schedule discloses omitted credits", not "reference exports
    disclose omitted credits";
  - include the bend formula `(standard deduction + up_to) / 12`.
- Replace the Usage section with a one-line link to the README section, so the
  text exists once.

The section must cover:
- applying allocation first, with federal on unallocated income;
- choosing columns by income basis, then adding them;
- interpolating, then rounding up;
- where the tax curve bends: the bend formula, deduction thresholds, phaseouts
  and caps;
- that interpolating across a bend where the rate drops can underestimate;
- using the next row up, and using the schedule above 500,000;
- the nearest-row error of $25 × the marginal rate per month per column;
- the rounding caveat;
- credits;
- what is not modelled: qualified dividends and long-term capital gains,
  NIIT, FICA and self-employment tax.

**Restore the single-state Georgia compatibility sentence**, without naming
the retired version-1 tool. For example: "A single-state Georgia export keeps
the transaction text of earlier versions; multi-state memos include the state
code."

**Add the launcher contract**
- Exit codes 0, 1 and 2.
- The `--output` destination rules:
  - an output that would replace the config entry, its symlink chain or its
    target is rejected, including case variants (Task 1);
  - the name rule is conservative on case-sensitive volumes;
  - utilities-public source checkouts are rejected;
  - a Git-marked ancestry that cannot be classified fails closed.
- The config warning (Task 6).

**Extend the offline-boundary text.** The network may be needed again after
the uv cache is cleared or dependencies change. The dependencies are pydantic
and pyyaml.

**Add a short operations note:** rerun after updating rules or hand-editing
config. No server restart is involved. This replaces the paragraph removed
from `docs/local_deployment_sync.md` in item 4.

### 2. `tax2/docs/Usage.md`
After item 1, its manual-lookup section is only the link. Its "Hand-edit
preferences" section documents the Task 6 warning.

### 3. `tax2/docs/multi_state_design.md`
Add a "Goals and boundaries" section, which spec §1 refers to by name. It
states:
- what is not modelled (matching Usage's tax limitations);
- that runtime config never contains tax rates or locality rules;
- that allocations are the caller's choice and are not normalized;
- that federal tax depends on total income, not the earned/unearned split.

### 4. `docs/local_deployment_sync.md` (spec §8 asked for only the local-only bullet)
Restore the pre-branch text around the tax2 deployed-test example:
- the command, which differs from the original only by the
  `--no-python-downloads` flag that agents.md requires:
  `PYTHONPATH="$HOME/source/utilities-public" uv run --no-python-downloads --with-requirements requirements-dev.txt python -m pytest -q`;
- the sentence "The same pattern applies to `~/mls-tracker`.";
- the updated local-only bullet, kept.

Delete the paragraph this branch added about deployed `.venv`s and rebuilding;
its rebuild note moves to the README (item 1).

Prove the command once from the source checkout's `tax2/` directory. That is
allowed under agents.md, because there is no `pyproject.toml` in `tax2/` or
its parents.

If it fails because the Playwright browser version is missing or mismatched,
report the failure. Do not install browsers.

### 5. `agents.md` Validation Matrix, `tax2` entry (spec §8)
- Add the explicit-output step:
  ```text
  TAX2_HOME="$tax2_acceptance_home" UV_PYTHON_DOWNLOADS=never ./tax2 --no-browser --output "$tax2_acceptance_home/explicit.html"
  ```
  then confirm `explicit.html` exists with mode `0600`.
- Add a final cleanup step: remove the run's `$tax2_acceptance_home`
  directory.

### 6. `tax2/docs/tax2-built-page-migration-implementation-plan.md` (public repo; must fix)
- Replace every absolute personal path (lines 15, 19, 365, 372, and any others
  found) with a repository-relative or generic form:
  - the repository root becomes "the repository root";
  - the deployed home-project copy becomes `~/tax2`.
- Replace the reference to the private prompt file with "a user-supplied
  plan-hardening prompt (not part of the repository)". Remove the private plan
  destination path the same way.

### Acceptance checks
- `git grep -n -I -E "/Users/[^/]+/(source|Downloads|tax2)" -- tax2 docs agents.md README.md ':!tax2/docs/tax2_review_fixes_implementation_plan.md'`
  returns nothing.
- `git grep -n -I "Downloads/" -- tax2 ':!tax2/docs/tax2_review_fixes_implementation_plan.md'`
  returns nothing.
- Read the README and confirm it contains every item listed in item 1, the
  exit codes, the output rules and the Georgia sentence. Grep alone is not
  enough.
- Usage.md's manual-lookup section is only a link.
- This plan file still contains none of the retired names that spec §13 lists.
  Check with a grep that assembles each name from two quoted halves, as Task
  7.5 does.
- `git diff 191ae33 -- docs/local_deployment_sync.md` shows only the
  local-only bullet change and the added `--no-python-downloads` flag.

---

## Task 9 — Record the decisions in the spec

Amend `tax2/docs/tax2_built_page_design_spec.md` so it states what this plan
decided, keeping each addition short.
- **§3:**
  - the config conflict model: resolution entries, identity and name rules,
    the early and pre-publish checks, and loop behaviour;
  - the non-mapping config warning.
- **§4:**
  - the pipeline step that named `get_available_years` now names the single
    discovery function;
  - non-regular year entries fail the build;
  - years use ASCII digits only;
  - the display-name falls back to the directory name.
- **§6.1:**
  - the Total line's unavailable state;
  - an empty box when focusing a $0 field;
  - arrow-key stepping;
  - the title;
  - column scrolling at each width.
- **§6.2:**
  - the allocation grammar;
  - invalid fields visibly highlighted, focused and unfocused.
- **§6.4:** the single rate function.
- **§7.1:**
  - the seven-step procedure;
  - the escaped characters.
- **§9.2:** the new tests listed in this plan.
- **§10.10 and §13:** do **not** change the user-approved historical-document
  exceptions. This plan contains no retired names, and it must stay that way.
  Task 8's acceptance checks include a check that it contains none.

**Acceptance:** a reviewer can trace every behaviour change in Tasks 1–7 to a
spec sentence.

---

## Task 10 — Final gates and review

### 1. Full gates (all must pass)
- From `tax2/`: `.venv/bin/python -m pytest -q -p no:cacheprovider`, with
  0 failed and 0 skipped.
- The uv header guard prints `OK`.
- The guard tests pass.
- The fleet zsh test prints `PASS`.
- The static node test passes.

### 2. Validation Matrix acceptance for tax2 (the updated agents.md entry)
- `--help` works.
- A private build writes the home 0700 and the files 0600.
- The `--output` build writes a 0600 file.
- A `UV_OFFLINE=1` rebuild succeeds.
- In offline Chromium, the `file://` page:
  - accepts calculator inputs, including a multi-state allocation;
  - shows an invalid input with its highlight and error;
  - produces all three downloads, each verified;
  - makes zero external requests and logs zero page or console errors.
- Remove the acceptance home afterwards.

### 3. Manual reproductions (synthetic `TAX2_HOME`), re-run
- `--output <home>/CONFIG.yaml` exits 1 and leaves config unchanged.
- `0x10` in an allocation is rejected.
- The Total line shows the unavailable text while an input is invalid.

### 4. Review
Run the repository's normal clean-context review on the whole diff
(`b596582..HEAD`). Fix the findings and record them.

### 5. Report
- List every test added, by name, with its pass status.
- Give test counts before and after.

---

## 11. Publication note (for the user; the executor must not push)

Commit `96ba091`'s copy of the migration plan still contains the old personal
paths. As of the last fetch, no remote-tracking ref contains `96ba091`.

Both options below have the same provenance effect. The parity fixture records
`generator_commit` `abb2b1088e485a735ba861f0b5da04ed2f6d7315`, which exists
only on this local branch, so after either option that hash is not in public
history.

- **Recommended:** squash-merge the branch into `main` locally
  (`git merge --squash`), commit, and push only `main`. Keep the local branch
  if you want the generator commit to stay resolvable for yourself.
- **Alternative:** rewrite the branch history to remove the paths from
  `96ba091`.
  - Every later hash changes, including `abb2b10`. The fixture's recorded hash
    would then not exist even locally unless that field is updated.
  - Commit messages that quote old hashes also go stale.
