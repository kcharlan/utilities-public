# Tax2 Built-Page Migration Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task by task after the user explicitly authorizes implementation. Checkboxes track independently reviewable work; they are not instructions to start implementation now.

**Goal:** Replace Tax2's server and CDN UI with a private, self-contained, offline HTML page; preserve annual calculations exactly; round tax toward the safe side; provide QIF, Markdown schedule and CSV lookup downloads; remove the retired md-autotax project.

**Architecture:** Python discovers, loads, validates and normalizes rules, reads preferences, and atomically builds the page. One browser JavaScript engine owns calculations, rounding, QIF and both exports. Vendored Preact, hooks and htm render the existing design without a server, CDN, JSX or build tool.

**Tech stack:** Python >=3.12, uv PEP 723 launcher, pydantic, pyyaml; Preact/hooks 10.29.8, htm 3.1.1, plain CSS; pytest and Playwright Chromium.

## 1. Authority, scope and current baseline

**Implementation authorization (2026-10-08):** The user instructed implementation using subagent-driven development on a new branch, with this plan as its first commit. The user also approved this exact file, `tax2/docs/tax2-built-page-migration-implementation-plan.md`, as a fourth historical exception to every retired-project/contract reference check below. Add the same exact-path exception to the design specification during implementation. References here are historical implementation guidance; live code and maintained operating instructions must still be cleaned. This approval supersedes the planning-only/start-authorization statements retained below and the three-path exception lists; it does not authorize private-file deletion or live deployment.

The binding source is `tax2/docs/tax2_built_page_design_spec.md` at `191ae33`, especially D1–D7, S1–S7, F1–F6 and §§6–13, plus the approved income-basis amendment and P1–P4 below. This revision incorporates a user-supplied plan-hardening prompt (not part of the repository) and the user's subsequent approval: **“I approve all four P1, P2, P3, and P4 inclusion in this plan and in the follow-on implementation effort.”** Only this plan is edited. The four requirements are authorized for follow-on implementation; this plan revision does not start application implementation, commits, branch changes, deletion, deployment, or private runtime inspection.

**Authority categories:** **Approved requirement** means the spec, the supplied income-basis amendment, or the explicitly approved P1–P4 contract changes; **implementation decision/assumption** means guidance consistent with those contracts. P1–P4 are binding follow-on requirements, not pending proposals. Preserve engine semantics and bundled rule values; reject newly invalid rules at the loader/build boundary rather than changing the engine.

Work from the repository root. Paths below are repository-relative unless explicitly identified otherwise. Execute shell commands from the directory specified for each gate; quote paths containing spaces. The requested private plan destination is outside the repository.

Rechecked for this revision: HEAD is `191ae338f959560cd004948efa8db59b00939d47` (`Add the tax2 built-page migration design spec`), preceded by `7fe9b7bd51203194dfa5c191f498860a467b05c6` (`Genericize the Pennsylvania local EIT label`). `git status --porcelain=v1` was empty, and `git diff 191ae33 -- tax2/docs/tax2_built_page_design_spec.md` reported no live-spec differences. The source therefore does not yet contain the approved basis or P1–P4 amendments; Tasks 3 and 7 record them during implementation. §11's committed-spec/PA-label prerequisites are satisfied; its uncommitted description is historical. Recheck before implementation; deployed revision and ignored/private inventories remain unverified in this revision.

The current launcher defines `compute_taxes`, `_discover_states`, `_validate_state_selections`, `testing_mode_enabled`, `HTML_TEMPLATE`, and `main`. Annual semantics come from `taxkit.engine.compute_tax` and `apply_brackets`; QIF byte layout comes from `taxkit.qif.build_qif_entries`. The embedded UI's `Sidebar`, `MoneyInput`, `MainPanel`, `ExportPanel` and `App` are the behavior and wording references. Preserve their visual hierarchy, income ordering, summary note, light/dark color tokens, selected-state order and single-state QIF wording, with the specified fixes.

Prior project decisions loaded from PKM:

- Entry 242: built-page default and Python/JavaScript ownership boundary; Tax2 is the first deliberate port.
- Entry 243: consequence-based rounding; taxes and displayed tax rates round up, gross is exact cents, net is exact gross minus rounded tax.
- Entry 152: implementation uses a normal `codex/` feature branch in this checkout. Do not create a worktree unless the user specifically requests one.

Read `tax2/README.md` and its documentation chain, including `tax2/docs/Usage.md`, `tax2/docs/multi_state_design.md`, the spec, `colophon/colophon`'s page/file helpers, vendor provenance, `tools/testkit.py`, and root `docs/local_deployment_sync.md`. Keep the existing tax limitations and multi-state invariants unless the spec or approved amendment explicitly changes them. The HTML visual reference remains unchanged.

### 1.1 Approved amendment and read-only evidence

**Approved S4 amendment, verbatim:**

> A file is also invalid if any component's `applies_to` is empty or lists an income class more than once. The allowed values are `[earned]`, `[unearned]`, or both in either order; an omitted `applies_to` still defaults to both. This keeps every component on exactly one of the three bases §7 exports, and prevents double-counted income and silent zero-tax components.

Apply it to disabled components as well. Reject malformed lists rather than repairing them; preserve the order of both valid two-class lists. Task 3 will update the specification during authorized implementation; the specification is not edited by this revision.

Read-only in-memory probes used `PYTHONDONTWRITEBYTECODE=1 tax2/.venv/bin/python -B` (CPython 3.12.15), current `TaxRules`/`TaxComponent`/`Credit`, `taxkit.rules_loader._load_components`, `compute_tax`, `apply_brackets` and `normalize_config`. They wrote no fixtures or runtime config and ran no application tests. Results:

- Earned-only 10%, deduction zero, annual earned 12,000, credit amount 1,000/cap −120: calculator annual **1,320**, credit-omitting export annual **1,200** (monthly 110 versus 100 before any rounding difference).
- `components: []`, an empty bracket list for each status, and a nonempty list with all components disabled each currently produce annual zero when no credits apply. The loader/model allow these structures; intentional disabling is a separate supported case.
- Caps `[-100, null]`, both rates 10%: tax is **0** at taxable zero and **10.001000000000001** at taxable 0.01. Strict ascending order alone does not establish continuity.
- The current loader preserves empty/duplicate `applies_to`, preserves `[unearned, earned]` order, and defaults an omitted list to `[earned, unearned]`. The approved amendment must add rejection, not deduplication.
- `normalize_config` currently retains non-string override leaves and arbitrary nested fields. The embedded override projection requires its own nested validation.

These schema gaps were identified by the supplied independent-review findings and reproduced during hardening. They are not attributed to the original plan's review. The user subsequently approved P1–P3's corresponding schema amendments and P4's output restriction; approval changes the accepted-input contract, not the observed historical engine behavior.

### 1.2 Approved requirements register

| ID / status | Binding contract | Minimal evidence/test and owning work |
| --- | --- | --- |
| P1 — **approved by user** | Add S4 rejection of negative `Credit.refundable_cap`; absent/null, zero and positive caps remain valid subject to existing finite-data checks. Do not change `min(effective, cap)` in the engine. | The 12,000/10%/1,000/−120 example above proves unsafe credit omission. Task 3: negative caps fail with the rules filename; absent/null/zero/positive caps pass. Task 5 tests conservative omission for valid caps. |
| P2 — **approved by user** | Reject `components: []` and every empty per-status bracket list, including disabled components. Express intentional zero tax with a nonempty, enabled component using a zero-rate open bracket and valid status data, or a nonempty list of intentionally disabled, otherwise valid components. | Task 3: empty components and each status's empty brackets fail with filename; zero-rate/all-disabled successful roots remain valid. Missing required status keys remain separately invalid. Tasks 8/10 document and verify the approved policy. |
| P3 — **approved by user** | Require every non-null `Bracket.up_to` to be nonnegative and finite. Preserve ascending order and null-last rules. Add no deduction restrictions. | Task 3: reject −100 and non-finite thresholds with filename; accept zero/positive thresholds and null only last. Task 5 verifies the supported continuous curves while retaining falling-rate/interpolation caveats. |
| P4 — **approved by user** | Reject an output publication destination inside a verified utilities-public source checkout. This deliberately narrows `--output PATH`; warning-only behavior is not the selected policy. Add no flags or hardcoded private source path. | Task 7: relative/normalized/symlink-parent source destinations fail before publication; synthetic Git/source/deployment tests verify identity, failure handling, unchanged config/page and valid standalone deployment destinations. |

**P4 source identity — planner's implementation decision:** protect this Git worktree of utilities-public and any other worktree/clone identified by the same tracked-source signature, wherever Tax2 is launched. A directory containing only a deployed Tax2 copy is not a source checkout. Normalize the output publication entry as in §3, then inspect its physical parent and ancestors for `.git` entries (directory or worktree/submodule indirection file); do not recursively scan the filesystem. Detect entries with `lstat`: only a missing entry is absent; permission errors or broken metadata links are unclassifiable, not evidence of safety. For each candidate, use bounded read-only Git subprocesses with argument arrays, no shell, and Git repository/index override environment variables removed. Resolve `git -C <candidate> rev-parse --show-toplevel`, and query the resulting root with `git -C <root> ls-files --cached -z -- tax2/tax2 tools/check_uv_headers.py`. Both exact paths must be in the tracked set to identify a utilities-public source root. Check every candidate ancestor, so a nested unrelated repository cannot hide an outer protected source checkout. Use path ancestry, not string-prefix comparisons. Resolve symlinked parents, but do not follow the output's final symlink; atomic replacement writes that directory entry.

No `.git` candidate means the destination is outside this Git-source boundary, including a standalone `~/tax2` deployment copy. A successfully inspected unrelated repository is also permitted. If Git is missing, times out, returns an execution error, or cannot classify a Git-marked candidate, fail closed with exit 1 and a clear destination-safety message before loading/creating config or writing output; choosing a destination outside Git-marked trees remains available without Git. Do not silently replace enforcement with a warning, use repository directory names as identity, hardcode the planning path, or inspect the real deployment. Git is a conditional identity-check prerequisite only for destinations under Git metadata; help and default home output outside Git-marked trees need no Git invocation. Tests inject command results for failure cases and use tiny synthetic Git repositories outside the checkout for positive identity cases. This bounds the policy to the local single-user publication model; parent stability is assumed as in §3.

P1–P4 need no further approval for inclusion or implementation. Implement their validation, destination enforcement and acceptance tests when the migration is explicitly started. Approval of these requirements does not itself start implementation or authorize live deletion/deployment. All agent-run commands continue to use synthetic state and output outside the checkout.

### Working and validation rules

- Tax2 Python commands use `tax2/.venv/bin/python` (or `.venv/bin/python` from `tax2/`). The current interpreter was exercised and reports CPython 3.12.15; installation/dependency/browser readiness still must be checked during implementation. If the venv is missing, create it with `/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv .venv` from `tax2/`, then install documented requirements through it. Never overwrite an existing venv. Shared root-tooling tests use the utility venv under the global environment policy; do not borrow Tax2's venv for them (§6).
- No implementation is performed by this planning deliverable. No project tests were run. Read-only calculation/schema/config probes used Tax2's venv; these are evidence about current code, not application-test success.
- Every migration command/test uses synthetic config and a temporary output/runtime directory outside the canonical source checkout. Assert that boundary in test setup; `tmp_path` alone is not proof if pytest's base directory was overridden. Tracked synthetic rule fixtures may live in the repository, but built pages, operational preferences and mutable outputs may not. These execution safeguards supplement the independently approved P4 product enforcement.
- For an executable change, first add meaningful failing coverage, implement, and run the full affected Tax2 suite and applicable launcher acceptance before committing. During migration, retain the old tests and runtime dependencies until their replacement passes; §6 includes the required interim server smoke gate. A failed test blocks the commit and next task: investigate and fix it, or report every failed name and output to the user.
- Do not modify shared `tools/testkit.py` or other projects to support this port. Copy only the specified vendor assets; Model Sentinel remains unchanged. The tax2-specific uv manifest-policy edit requires the guard and its tests. It does not change other launchers' behavior.
- Before every commit, inspect `git diff --cached --name-only` and the entire `git diff --cached` for sensitive data. Use only unmistakably synthetic test values and generic labels. Every commit needs an imperative subject and a non-empty body explaining changes, reasons and validation. Verify all branch-only commit bodies before publication.

## 2. File and responsibility map

| Path | Action and responsibility |
| --- | --- |
| `tax2/tax2` | Retain uv launcher; replace server, embedded template and API models with argument parsing and build/write/open orchestration. |
| `tax2/taxkit/page.py` | Add rules-root discovery, payload construction and static asset rendering. No tax calculation or YAML normalization here. |
| `tax2/taxkit/config.py` | Retain config parsing/default normalization; create missing config privately and atomically without replacing existing config. Own `runtime_home`, `ensure_runtime_home`, and atomic file primitives used by the launcher. Keep the old alias/save API until their callers are removed in Task 7. |
| `tax2/taxkit/models.py` | Retain normalized rules types; retire `TaxInput` at cutover if no callers remain. |
| `tax2/taxkit/rules_loader.py` | Retain `load_rules` and v1 normalization; add the build-validity checks with filename-bearing errors. |
| `tax2/taxkit/utils.py` | Retain year/path discovery; retire `resolve_year` and unused imports at cutover. |
| `tax2/taxkit/__init__.py` | Remove imports of retired modules at cutover. |
| `tax2/web/template.html` | Add HTML skeleton, application root, embedded schema-1 payload, inline styles/scripts and license notices. |
| `tax2/web/styles.css` | Extract current plain CSS; replace fonts/utilities; fix responsive export panel. |
| `tax2/web/engine.js` | Add pure calculation, validation, cents formatting, date/QIF, rate-schedule and CSV builders. Expose `window.Tax2Engine`. |
| `tax2/web/app.js` | Add Preact/htm UI, synchronous derived results, storage, field state and Blob downloads. |
| `tax2/web/vendor/` | Copy `preact.umd.js`, `hooks.umd.js`, `htm.umd.js`, `preact.LICENSE`, `htm.LICENSE`, and matching provenance rows. |
| `tax2/tests/fixtures/parity/bundled/rules/` | Freeze current bundled rules, preserving values and structure. |
| `tax2/tests/fixtures/parity/synthetic/rules/` | Freeze separate federal/PA-enabled/XU/XC root with synthetic component/credit coverage. |
| `tax2/tests/fixtures/parity/python_parity.json` | Commit immutable Python expectations, source metadata, raw annual doubles, safe-rounded cents, error text and QIF strings. |
| `tax2/tests/capture_python_parity.py` | Temporary oracle generator; commit before capture and delete with Python engine retirement. |
| `tax2/tests/conftest.py` | Extend with reusable built-file/Chromium helpers while retaining `UTILITIES_TESTING`; isolate runtime homes and browser storage. |
| `tax2/tests/test_built_browser.py` | Transitional built-page UI coverage alongside the retained server smoke tests; consolidate into `test_browser_smoke.py` at cutover. |
| `tax2/tests/test_page_build.py` | Add payload, rendering and vendor/probe tests. |
| `tax2/tests/test_launcher.py` | Add actual argument, output, permissions, failure and browser-open tests using testkit. |
| `tax2/tests/test_engine_parity.py` | Add exact frozen-fixture comparisons and error parity. |
| `tax2/tests/test_engine_components.py`, `tax2/tests/test_golden_baselines.py`, `tax2/tests/test_qif_multistate.py` | Port coverage to `page.evaluate` at cutover, preserving meaningful assertions. |
| `tax2/tests/test_exports.py` | Replace `tax2/tests/test_cli_tables.py` with both export builders and download coverage. |
| `tax2/tests/test_bundled_rules.py` | Add deliberately maintained, hand-verifiable expectations for live bundled rules. |
| `tax2/tests/test_config.py`, `tax2/tests/test_rules_v2.py`, `tax2/tests/test_browser_smoke.py` | Keep/extend config and rules coverage; rewrite browser coverage for file URLs. |
| `tax2/tests/test_api.py` | Delete only after every scenario is covered by payload/engine/page tests. |
| `tax2/cli.py`, `tax2/taxkit/engine.py`, `tax2/taxkit/tablegen.py`, `tax2/taxkit/qif.py`, `tax2/tables/` | Retire only after oracle capture and built-page parity. |
| `tax2/requirements-dev.txt` | Final dependencies: pydantic, pyyaml, pytest and Playwright, retaining documented compatible test version ranges. |
| `tax2/requirements.txt` | Remove at cutover; runtime requirements are the launcher header, development requirements are standalone. |
| `tax2/.gitignore` | Remove table-output and `.tax2_venv/` rules after inventory; keep `.venv`, caches and existing unrelated ignores. |
| `tools/check_uv_headers.py` | Change only Tax2 manifest-only extras to `playwright` and `pytest`. |
| `tax2/docs/tax2_built_page_design_spec.md` | During authorized implementation, record the approved basis/P1–P3 amendments in S4 and matching tests/acceptance; record P4 in §3's output/exit contract and matching launcher acceptance. |
| Project/root docs and `agents.md` | Update exactly the sections specified in spec §§8 and 10. |
| `md-autotax/` | Remove tracked project and approved leftovers in its own complete retirement commit. |

## 3. Binding implementation interfaces

These names and shapes are the plan's integration contracts. Routine implementation choices within them belong to the executor.

### Python boundary

- `load_rules(path: str) -> TaxRules`: existing normalized model boundary. Reject S4-invalid files, approved income-basis violations and P1–P3 violations, including disabled-component structure. Preserve valid `applies_to` order and omitted defaults. Require nonempty components and each required status's brackets; reject negative refundable caps and negative/non-finite non-null thresholds. Errors include the offending path. Validate JSON serializability with finite numeric values while that filename is known; the final serializer also uses `allow_nan=False`.
- `build_payload(rules_root: Path, *, rules_source: str, built_at: str | None = None) -> dict`: in `tax2/taxkit/page.py`; builds exactly spec §4 schema 1. Enumerate and validate every discovered numeric-year `.yaml`/`.yml` file, not only latest or selected files. If both extensions exist for one year, validate both, then select `.yaml` as `get_rule_path` does today. Emit each year once. States are sorted by code; years are ascending and unique; latest-year display name and QIF defaults populate discovery metadata. `federal` and per-state `rules` use string year keys. Serialize each `TaxRules` with `model_dump(mode="json")`.
- `render_page(payload: dict) -> bytes`: in `tax2/taxkit/page.py`; reads tracked assets beside the installed project, validates all inlined source assets before assembly/escaping, separately escapes JSON, and inlines all assets. The surrounding template is excluded from the closing-script scan. Python never embeds source paths, environment dumps or runtime-directory metadata.
- `runtime_home() -> Path`, `ensure_runtime_home(path: Path) -> Path`, `atomic_write_bytes(path: Path, data: bytes, mode: int = 0o600) -> None`: in `tax2/taxkit/config.py`; use Colophon's filesystem pattern without importing Colophon.
- `load_config() -> dict`: existing API; its final output contains only `default_states` and `qif_overrides`. Add `create_config_if_missing(cfg: dict) -> None` in Task 3 for no-clobber initial creation, but retain `save_config` and the legacy alias for old server/CLI callers until Task 7. The new payload projects only the two final keys throughout the transition. At cutover remove `save_config` and ignore the alias on input. Missing-config creation never replaces an existing file, even if corrupt or legacy-key-bearing; final built-page execution never writes existing config.
- `normalize_qif_overrides(raw: object) -> dict[str, dict[str, str]]`: in `tax2/taxkit/config.py`; embedded shape is a string-state-code mapping to per-state mappings containing only string-valued `state_expense`/`state_transfer`. Project known fields; never coerce non-strings. Compatibility-preserving **implementation assumption**: warn/ignore malformed containers, entries or fields, retain valid siblings and use the fallback chain; this agrees with the existing corrupt-config fallback and no fatal override policy was found. A future policy requiring fatal failure needs user resolution.
- Launcher `parse_args(argv=None)` and `main(argv=None) -> int`: make direct tests straightforward; normal execution exits with `main()`'s return code. Keep `testing_mode_enabled()` semantics: empty, `0`, `false`, `no` are false case-insensitively; other values suppress browser opening.
- `validate_output_destination(output: Path, config_path: Path) -> None`: in `tax2/taxkit/config.py`; enforce the existing config-entry/target protection and approved P4 before config creation/loading or output writes. It uses the physical publication entry and §1.2's Git-source identity decision, raises a user-readable fatal error for unsafe/unclassifiable destinations, and has no write side effects. Rule/config/page publication follows only after this gate succeeds.

Override normalization is explicit: accept mappings only; require string state keys, strip surrounding whitespace and uppercase them, ignore empty keys without coercion, and retain every nonempty normalized string key, including unknown custom codes. Add no length, character-format or known-jurisdiction restriction: current discovery accepts custom directory names, including `XTEST`. Preserve existing `default_states` normalization without unrelated changes. Recognized fields keep string values including empty strings; missing/empty values trigger fallback at use time. Invalid state mappings are ignored; an invalid field does not erase valid siblings. Ignore unknown fields without embedding nested content. If normalized keys collide, process file order, merge recognized fields, and let the last **valid** field win; invalid later data does not destroy an earlier valid field. Warnings name recognized fields and a stable entry index, not arbitrary keys, values or whole objects. The plan treats this as an explicit config-normalization assumption, not a new fatal accepted-input rule. Disk bytes and `mtime_ns` remain unchanged.

Rules discovery uses the year/path conventions of `get_available_years` and `get_rule_path`, supporting `.yaml` and `.yml`, with per-file enumeration before selecting the file for a year. The helpers alone are insufficient for complete validation when one extension shadows the other. A missing federal root/year inventory, any invalid discovered rules file, or no state directory with a valid rules year is fatal. A state directory with no years may retain a discovered entry with `years: []` and no rules, matching existing discovery and the specified `Available years: none` error; it cannot satisfy the minimum-valid-state requirement. Do not substitute a year for missing federal/state rules.

**Spec-consistent federal-only-year decision:** a federal year with no state rules in that year remains available when valid state rules exist elsewhere in the root. The selected-state calculator still requires at least one state and reports the exact missing-year error; QIF is disabled and cards are replaced. Schedule/CSV for that federal year stay enabled and contain only federal sections/columns. Do not drop that year, substitute another one or enable federal-only calculator success. Keep local-opening-year selection and stored-state precedence.

**Existing config-destination protection, explicit matching decision:** atomic publication replaces a directory entry, so compare `output.expanduser().parent.resolve(strict=False) / output.name` against the resolved-parent config entry before creating/replacing output. Also protect the resolved target of an existing config symlink, because that target is the configuration read by the loader. Normalize relative paths against the build's actual cwd and resolve symlinked parent directories. Do not resolve/follow the output's final symlink when writing: an unrelated final symlink is replaced by the ordinary `os.replace` operation, not written through. Do not switch to truncating writes. Test equivalence/parent links/config-target links and verify failed checks preserve config/page bytes and timestamps. This protects the actual configuration; P4 is a separate source-checkout policy. Assume publication parents are stable for the local single-user build, without introducing an adversarial filesystem framework.

### JavaScript boundary

The `rules` argument below is the complete schema-1 payload; functions look up normalized jurisdiction rules within it. Income passed to `computeTax` is annual dollars; `computeAnnual` inputs are monthly dollar doubles; `computeMonthly` inputs are integer monthly cents.

```text
StateSelection = {code: string, allocation_pct: number}
MonthlyInput = {earnedCents: integer, unearnedCents: integer,
                filingStatus: "single" | "married_joint", year: integer,
                states: StateSelection[]}

applyBrackets(taxable, brackets) -> raw annual number
computeTax({earned_income, unearned_income}, taxRules, filingStatus) -> raw annual number
computeAnnual(earned, unearned, filingStatus, year, states, rules) ->
  {federal_annual, states: [{code, display_name, allocation_pct, annual}]}
computeMonthly(input, rules) ->
  {federal_cents, states: [{code, display_name, allocation_pct, state_cents}],
   total_monthly_cents, gross_cents, net_cents, effective_rate}

ceilScaled(x, scale) -> integer
ceilCents(x) -> integer
formatCents(cents, {grouping = false} = {}) -> decimal text (signed when needed)
parseMoneyInput(text, previousCents) -> {cents, error, inProgress}
parseAllocation(text) -> {value, error}
resolveStateQifDefaults(code, rules) -> {expense, transfer}
parseQifDate(text) -> validated local calendar parts
buildQif(result, qifConfig, qifStates, rules) -> string
buildRateSchedule(year, rules) -> Markdown string
buildLookupCsv(year, filingStatus, rules) -> CSV string
```

`state_cents` belongs to each ordered `states` entry. Do not add a competing parallel state-amount map. `effective_rate` is the rounded-up numeric percentage, formatted without trailing zeros by the UI. Annual results exclude a float-summed annual total, which the new page does not need.

Use a shared component evaluator and credit evaluator beneath `computeTax` if helpful. There must be one bracket loop, one credit loop and one rounding helper; export code calls these same evaluators rather than reimplementing tax logic. `engine.js` has no DOM, storage, download or network operations. `app.js` owns those browser operations.

## 4. Ordering and reviewable tasks

Main dependency chain: **preflight → oracle capture → inline-stack probe → payload/builder → JS engine parity → exports → UI → cutover → final validation**. Documentation follows final interfaces. Task 9's md-autotax retirement is independent after preflight; schedule it before Task 8's README rewrite by default so its complete removal/reference cleanup, including the Tax2 compatibility sentence, lands in one commit. If its private-file confirmation is still pending, other approved migration work can continue, but Task 8 must reserve that sentence's removal for Task 9. No deployment audit runs while retirement is staged but uncommitted. Deployment follows merge and separate live authorization.

### Task 1 — Confirm baseline and freeze the Python oracle

**Files:** add `tax2/tests/fixtures/parity/bundled/rules/`, `tax2/tests/fixtures/parity/synthetic/rules/`, `tax2/tests/capture_python_parity.py`, and `tax2/tests/fixtures/parity/python_parity.json`; retain all existing engine/QIF/API code and tests.

- [ ] Recheck clean checkout and committed prerequisites. Create a normal `codex/tax2-built-page` feature branch when implementation is authorized. Preserve any new user edits rather than overwriting them.
- [ ] Run the full existing Tax2 suite from `tax2/`, with a private temporary `TAX2_HOME`: `.venv/bin/python -m pytest`. Expected: all existing test categories pass, with no skips. This establishes the old oracle and browser baseline without reading real runtime preferences. Run the interim launcher gate in §6 too.
- [ ] Copy bundled rules exactly into the frozen bundled root. Do not rewrite numeric values, component structure, generic labels or comments.
- [ ] Create the separate synthetic root with federal 2026, PA 2026 with local EIT enabled, XU with an unearned-only component, and XC with a total-income component and credit covering phaseout and refundable cap. Use conspicuously synthetic names, round inputs and generic QIF labels. Include both filing statuses in every component. Keep credit `amount_per_child` coverage in targeted evaluator tests as well.
- [ ] Implement the temporary generator using `load_launcher`. Set `_base_dir` to each frozen root's parent of `rules/`; isolate `TAX2_HOME` in a temporary directory. Call `compute_taxes` with `TaxRequest` and rules mode, including its async handling, and call `build_qif_entries` for expected QIF. Do not build a second tax engine in the generator.
- [ ] Commit the generator and frozen roots first, with a body explaining the parity boundary. Then capture with `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B tests/capture_python_parity.py` from `tax2/`. Record that committed generator's `git rev-parse HEAD`, exact `sys.version`, fixture schema, root identifier, inputs and expected outputs. This makes the recorded generator SHA reproducible rather than pointing to a commit that does not contain it.
- [ ] Make fixture compute cases cover every federal year/status, valid state combinations, all-unearned/all-earned/mixed splits, zero/below-deduction/boundary±$1/large incomes, and allocations named in spec §9.1. PA 2025 is an error case, not a successful calculation. At federal boundaries, derive monthly dollars as annual income divided by 12; retain these non-cent inputs for `computeAnnual`.
- [ ] Store raw annual doubles directly, without `round(x, 10)`. Existing golden literals were rounded for comparison; validate their agreement with the oracle using their original ten-decimal comparison only during capture. New parity assertions compare the captured raw doubles exactly.
- [ ] Calculate expected monthly cents with the spec's Python reference: `(annual / 12.0) * 100.0`, snap within `1e-6` of the nearest integer, otherwise ceil. Assert `cents >= nearest_cent_cents` and `-1e-6 <= cents - c < 1` in every case. Assert the fixture contains whole-cent, changed-nearest-rounding and float-noise cases; add explicit compute cases until each assertion is met.
- [ ] Include the exact missing-state-year `detail` message and QIF cases for income-derived GA, GA+PA, zero state, custom fields, plus the fixed-amount GA golden. Generate safe-rounded QIF expectations with the old builder using cents divided by 100; retain `T-0.00`.
- [ ] Inspect generated JSON and frozen roots for privacy, rerun the complete current suite, and commit the fixture before continuing. Repeating capture at the same generator commit/interpreter must reproduce expected values. Do not regenerate this fixture from the new engine or from subsequently corrected bundled rules.

**Acceptance:** committed, reproducible oracle covers §9.1; current Python modules remain available; old suite passes. Test fixtures never use real runtime preferences or income.

### Task 2 — Prove the inline Preact/htm stack

**Files:** `tax2/web/vendor/`, a focused probe in `tax2/tests/test_page_build.py`; add only the minimal template/harness needed for this probe.

- [ ] Copy the three UMD files and two licenses byte-for-byte from `model_sentinel/model_sentinel/browse/assets/vendor/`. Copy only their corresponding `VERSIONS.md` rows. Verify SHA-256 values with `shasum -a 256`; do not fetch replacements or include uPlot.
- [ ] Create a file-URL probe containing classic inline scripts in this order: Preact, hooks, htm, then a component using `htm.bind(preact.h)` and a hooks state update. Verify the actual UMD hooks global from the probe rather than assuming ESM usage.
- [ ] Open it in Playwright Chromium. Attach `guard_browser_errors`, collect/abort every non-`file:` request, and assert the collection remains empty. Render a component and click a button that changes its state; verify both render and hooks behavior.
- [ ] If the probe fails, diagnose this integration before building the engine/UI; do not accumulate alternate stacks or runtime workarounds. The proposed stack is already fixed by the spec, so a needed change requires user resolution.
- [ ] Verify copied licenses are available for inline page notices, and run the full Tax2 suite with the new probe before committing.

**Acceptance:** an inlined hooks-based htm component works from `file://` with zero network requests and no browser errors. This gate precedes all UI investment.

### Task 3 — Build normalized payloads and private page files

**Files:** `tax2/taxkit/page.py`, `tax2/taxkit/config.py`, `tax2/taxkit/rules_loader.py`, `tax2/web/template.html`, initial `tax2/web/` assets, `tax2/tests/test_page_build.py`, `tax2/tests/test_config.py`, `tax2/tests/test_rules_v2.py`, and the approved amendment in `tax2/docs/tax2_built_page_design_spec.md`.

- [ ] Add failure tests before changes: YAML parse/schema failure; missing either offered status; missing deduction/brackets for either status on enabled and disabled components; negative bracket/phaseout rates; duplicate or descending caps; null cap before the last bracket; missing federal inventory; no valid state; non-finite JSON values. Every per-file failure names its source file. Test an invalid older year and a valid `2026.yaml` alongside an invalid `2026.yml`, so latest-only or preferred-extension-only validation cannot pass. For two valid extensions, test YAML precedence and unique year metadata.
- [ ] Extend `load_rules`' normalized-model validation for approved S4 requirements while preserving v1/v2 ambiguity rejection and component semantics. Require offered statuses in both `filing_statuses` and each component's data; do not supply a missing deduction or bracket key. Implement P1–P3 on the normalized model: reject negative non-null refundable caps, empty component lists, any required status's empty brackets (including disabled components), and negative/non-finite non-null thresholds. Test failures through `load_rules` and the builder with filenames, including v1 normalization and v2 components; test absent/null/zero/positive refundable caps, zero/positive caps with valid ordering, an intentional zero-rate open bracket, and nonempty all-disabled otherwise-valid components as successes. Confirm bundled rules still normalize identically. Add no deduction constraints or engine arithmetic changes.
- [ ] Implement the approved income-basis amendment on every component, including disabled ones. Reject `[]`, `[earned, earned]`, `[unearned, unearned]`, and mixed repetitions such as `[earned, unearned, earned]`. Accept `[earned]`, `[unearned]`, `[earned, unearned]`, `[unearned, earned]`, and omission/default. Assert exact normalized order for both valid mixed lists; do not use a deduplicating/reordering set as the normalization result. Extend `tax2/tests/test_rules_v2.py` and build-failure tests so each rejection names the file. During authorized implementation, amend S4 and matching test/acceptance wording in `tax2/docs/tax2_built_page_design_spec.md` for both this basis amendment and approved P1–P3; keep all bundled YAML values unchanged.
- [ ] Build schema-1 payloads using the resolved custom/default root. Preserve latest-year discovery metadata, all normalized years, config preferences, version `3.0`, UTC ISO build time and `rules_source` as `bundled` or `custom`. Use an injected timestamp in deterministic tests. No absolute paths appear in the payload.
- [ ] Add private create-if-missing behavior while retaining `legacy_combined_alias`, `save_config`, existing round-trip coverage and old config-write callers until Task 7. Preserve uppercase state normalization, QIF overrides and corrupt-file warnings/default fallback. New payloads project only `default_states` and `qif_overrides`. Add synthetic no-clobber/load tests now; defer alias-removal assertions and retirement of old save tests to cutover.
- [ ] Apply the §3 nested override boundary to the **embedded projection** now, without prematurely removing the old config API. Test list/scalar/null containers, non-string/empty state keys, non-mapping state entries, number/bool/null/list/object leaves, unknown nested fields, missing/empty strings, valid overrides, valid siblings beside invalid ones, key-case normalization and collisions. Include `" xtest "` normalizing to `XTEST` and an unknown nonempty key surviving projection; impose no two-letter/format/known-state filter. Assert the page payload contains only recognized string fields; warnings expose no supplied values or arbitrary keys. Use synthetic hand-written config outside the checkout and assert bytes/`mtime_ns` unchanged after load and build. At cutover use the same normalizer in the final config path, with no duplicate policy.
- [ ] Enforce runtime-home mode `0700` on every run. For generated HTML, use a same-directory temporary file, `fchmod(0600)`, flush/fsync, and `os.replace`; remove temporary files on failure. Existing successful HTML must survive a failed write.
- [ ] Make missing-config creation atomic **and no-clobber**. A separate `exists()` check followed by `os.replace` is insufficient: it could overwrite a file created meanwhile. Write/fsync/chmod a same-directory temporary file, publish with `os.link(temp, config_path)` (exclusive creation), treat `FileExistsError` as an existing config, and always unlink the temporary name. Reload the existing winner through `load_config`; never normalize/rewrite its bytes. Test publication racing with an existing config, using a narrowly injected filesystem operation rather than nondeterministic timing.
- [ ] Embed the payload in a `type="application/json"` script with a fixed ID such as `tax2-data`. Use the Python serialization below. The generated JSON contains **one backslash followed by `u003c`** for each literal `<`; the Python source string uses two backslashes to represent that one character. Insert payload after assembling template/assets, so placeholder-looking user strings cannot trigger a subsequent replacement pass. Test `</script>`, non-ASCII text and placeholder-looking strings round-trip as data.

```python
data = json.dumps(payload, ensure_ascii=True, allow_nan=False)
data = data.replace("<", "\\u003c")
```

- [ ] Reject `</script` case-insensitively in **every inlined source asset**: all vendor JS, engine/app JS, CSS and raw license text, before assembly or license escaping. Exclude the surrounding template, which has legitimate closing tags, and the JSON payload, whose separate `<` escaping handles harmless hostile-looking data. Add separate JavaScript/CSS/license rejection tests, including mixed-case `</ScRiPt`. Through the cutover launcher, a copied temporary project with an unsafe asset must exit 1 before replacing an existing successful page; record this launcher test in Task 7. Keep JSON/placeholder round-trip tests. No external script/src/stylesheet/font references or local fetches; inert notice URLs do not load resources.
- [ ] Add a synthetic two-year root with federal 2025/2026 and state XF only in 2025. Global state validity succeeds; federal years remain `[2025, 2026]` and no 2026 state rule is invented. Payload/build tests prove the root is accepted. Its UI/export checks are in Tasks 5–6; use temporary roots/pages/config outside the checkout.
- [ ] Add tests for schema shape, normalized enum strings, discovery ordering, custom root, missing-year inventory, and build error filenames. Keep the server launcher intact until the UI is ready; new tests call builder functions directly to build temporary file-URL harnesses.
- [ ] Run the full Tax2 suite and §6's interim direct-launcher/server smoke gate, then commit the builder/config/validation work. Old state-selection persistence and CLI table generation must still work at this intermediate commit.

**Acceptance:** deterministic payload, all approved S4/basis/P1–P3 checks including disabled components, projected override schema and conservative fallback, all-asset guarding distinct from JSON escaping, private atomic HTML/no-clobber config, and old server/CLI compatibility. Intentional zero-rate/all-disabled rules and synthetic negative-net cases remain supported; no bundled YAML value changes.

### Task 4 — Port annual calculation and safe rounding

**Files:** `tax2/web/engine.js`, `tax2/tests/test_engine_parity.py`, focused browser-evaluated tests in `tax2/tests/test_page_build.py` or `tax2/tests/test_engine_parity.py`.

- [ ] Add fixture-driven tests against file-URL engine harnesses before implementation. Use the frozen root named by each fixture case. Compare every annual value, monthly integer, total, missing-year message and QIF value when its builder becomes available. Capture separate direct annual and monthly surfaces; boundary cases are not rounded to cents before annual comparison.
- [ ] Port `apply_brackets` line-for-line in operation order. In particular, update `prev_cap` only inside `taxable > prev_cap`, add only positive slices, and break for an open bracket or a reached cap. Do not simplify to a rearranged equivalent formula.
- [ ] Port enabled-component evaluation, `applies_to` iteration order, deductions, additive credit loop, max-of-amount/one-child behavior, phaseout on this call's annual earned+unearned total, cap and final zero floor. Validate finite nonnegative inputs, allocations and status data; errors never become silent zero.
- [ ] Preserve the Python credit/bracket algorithms even where §1.1's now-rejected historical examples have surprising results. Approved P1/P3 validation rejects those inputs at build time; do not clamp negative caps, revise bracket arithmetic, or recapture the immutable oracle to conceal the original semantics. Preserve intentional negative-net cases using conspicuously synthetic rules, such as a rate above 100% or a deduction generating tax at zero income; no new deduction restriction is authorized.
- [ ] `computeAnnual` validates nonempty known-state selections and preserves their order. Federal receives `earned * 12`, `unearned * 12`; states receive `earned * 12 * (allocation_pct / 100)` and unearned likewise, left-to-right. Keep raw annual doubles. State name fallback is selected-year `display_name`, discovered name, then code.
- [ ] Implement the single load-bearing rounding helper exactly:

```javascript
function ceilScaled(x, scale) {
  if (!Number.isFinite(x) || x < 0) throw new Error('Invalid rounding input');
  const c = x * scale;
  const r = Math.round(c);
  return Math.abs(c - r) <= 1e-6 ? r : Math.ceil(c);
}
```

Only scales 10 and 100 are used. `ceilCents(x)` delegates with 100. Test all §6.4 money and percentage vectors, including `1.1`, `0.07`, `1e-9`, `100/3` and non-finite/negative failures. Preserve the documented tolerance and large-income tradeoff rather than substituting an epsilon formula.

- [ ] Implement `computeMonthly` by validating whole integer cents, calling `computeAnnual(cents / 100, ...)`, converting each jurisdiction's `annual / 12` through `ceilCents` once, and summing cents. Compute exact gross and net in cents. Combined rate is `ceilScaled(total / gross * 100, 100) / 100`, or zero for zero gross.
- [ ] Format integer cents by sign, whole-dollar quotient and two-digit remainder. Group dollar digits only for UI/schedule; CSV/QIF are ungrouped. Do not format money using float division and `toFixed`. Card rates use the same helper at scale 10 and exactly one displayed decimal.
- [ ] Test earned-only/unearned-only/multiple/disabled components and all credit branches directly through `window.Tax2Engine`; verify state-credit phaseout receives allocated income. No state-specific engine branches.
- [ ] Run exact annual/monthly fixture parity and the full Tax2 suite before committing. Any floating mismatch requires explaining and correcting the operation-order difference; widening tolerances or recapturing expectations is not a fix.

**Acceptance:** exact annual and safe-rounded monthly parity before UI implementation; one engine and rounding helper; annual surface accepts the fixture's non-cent boundary inputs.

### Task 5 — Implement QIF and both export builders

**Files:** `tax2/web/engine.js`, `tax2/tests/test_exports.py`, new browser QIF coverage; old Python QIF and CLI remain until cutover.

- [ ] Port QIF line order/text to `buildQif`, using integer amounts. Federal pair first, then states in result order; one `!Type:Bank`; `D`, `T`, `P`, `M`, `L`, `^`; newline joins without trailing newline; local date parts; generic state memo for one state, code-bearing memos for multiple states; `T-0.00`/`T0.00` at zero.
- [ ] Centralize each state's default chain: nonempty config override, latest-year payload QIF default, hard-coded generic fallback. The app uses this on first initialization even for a later-checked state; `buildQif` uses it again for an empty edited field. Keep federal defaults and payee wording from the existing UI. Test fixed-amount and income-derived fixture text exactly.
- [ ] Parse QIF date as `YYYY-MM-DD` calendar parts; validate actual month/day and leap-year validity without UTC conversion. Invalid/empty dates must throw from the builder and disable QIF in the UI. Export builders have no DOM or Blob side effects.
- [ ] Build rate-schedule Markdown for selected year and **both** filing statuses, federal first and all eligible states alphabetically. Include header/build time/year/not-tax-advice, the manual procedure and every §7 caveat. For each enabled component/status show basis, deduction, and Over/But not over/formula rows. Each lower-bound base comes from `applyBrackets(lower, brackets)` and `ceilCents`; list disabled components and credits explicitly.
- [ ] Implement exact rule-number formatting using shortest decimal strings: expand any exponent, move the decimal point two positions for percent text, and group the integer portion without rounding thresholds/deductions. Test `0.0307 → 3.07%`, fractional thresholds, and exponent notation. Do not use float multiplication by 100 for rule-rate presentation.
- [ ] CSV row count is **10,001 data rows**, 0 through 500,000 inclusive in $50 increments. Format every number with two decimals and no grouping. Columns are `MonthlyIncome`, then federal/state groups in total/earned-only/unearned-only order, only when an enabled component exists. Use all states with selected-year rules, regardless of selection/allocation/input errors.
- [ ] To avoid duplicating computation, construct a non-mutating view of each jurisdiction's rules containing the components for one basis; call the shared evaluator at annual `MonthlyIncome * 12`. For total basis pass the annual amount as unearned and zero earned; for earned-only pass earned; for unearned-only pass unearned. Retain credits only for the total group. Floor that group's annual result before its monthly rounding. Disabled components never create columns.
- [ ] Preserve the prescribed credit treatment: subtract once in the total-income group/section with phaseout at total jurisdiction income; floor that group at zero; do not subtract from other groups. Without an enabled total-income group, omit credits and state their omission. Mark credited jurisdictions' lookups approximate. Schedule guidance describes credit calculation/phaseout/cap and total-group subtraction. P1 makes the negative-cap counterexample invalid at build time; test that credit-omitting export tax is at least the corresponding calculator tax after valid nonnegative effective credits, retaining shared engine arithmetic. P3 rejects negative-threshold jumps; test continuity at representative valid zero/positive thresholds. Retain all existing approximation, falling-rate-bend, next-row-up and above-range caveats: these amendments do not make interpolation exact or eliminate those limits.
- [ ] Test bundled and synthetic CSV header/order/count/sample cells, PA enabled EIT, XU unearned-only, XC phaseout/cap, zero-floor behavior, multiple components per basis, omitted credits without total group, and missing-state-year exclusion. Compare cells with shared engine results, and retain independent hand-verifiable expectations for at least representative rows. Assert input rules are not mutated.
- [ ] Test the two-year federal-only root's 2026 schedule and CSV: federal sections for both statuses, only the federal enabled-basis columns, 10,001 data rows and no state section/column. Those exports do not require a successful selected-state calculator result. Cover the ordinary partial-missing-year case separately.
- [ ] Verify schedule bases and exact rule text, both statuses, all jurisdictions, disabled labels, credit warnings, allocation procedure, interpolation caveats, next-row-up advice and >500,000 boundary. Preserve the warning that interpolation across a falling-rate bend may understate tax.
- [ ] Finish exact QIF fixture parity; run the full Tax2 suite and commit.

**Acceptance:** QIF parity and export content/scope/grouping are covered, including a federal-only export year; no parallel engine or selected-input dependency. Conservative credit omission and threshold continuity are tested within approved valid inputs; interpolation/credited-lookup caveats remain explicit. P1/P3 counterexamples fail build validation rather than altering the engine or frozen oracle.

### Task 6 — Port the UI and apply F1–F6

**Files:** `tax2/web/app.js`, `tax2/web/styles.css`, `tax2/web/template.html`, `tax2/tests/test_built_browser.py`. Keep `tax2/tests/test_browser_smoke.py` and the old launcher runnable until Task 7; consolidate coverage at cutover.

- [ ] Extract CSS and port existing components to htm/Preact. Bind `const html = htm.bind(preact.h)`; use the proved hooks UMD API. Replace Google Fonts with system display/body/monospace stacks; replace remaining Tailwind utility classes with named plain CSS. Drop the unused Lucide component and bracket UI remnants if unused. Keep existing color tokens, cards and summary wording.
- [ ] Initialize the app from embedded payload exactly once. Default filing status is `single`, monthly unearned is `1250000` cents and earned is `0` cents; default theme is light absent a stored preference, matching the existing UI. Available federal years are newest first; choose current **local opening year** if present, otherwise latest. Show build time. Initial state selection uses first valid nonempty browser list, filtered config defaults, then first discovered state. Preserve list order, remove duplicate codes from stored lists, and refuse unchecking the last state.
- [ ] Store state selection under `tax2:selected-states` and theme under `tax2:theme`. Catch storage reads, parsing and writes individually. Malformed/non-list/unknown-only storage falls back; blocked storage must leave a working page. No origin migration from `tax2-dark-mode`, and no config writes.
- [ ] Keep money field text, last-valid cents, focus state and validation separately. Validate against the exact spec regex before stripping commas; parse digits/padded fractional part into integer cents. Empty/whitespace means zero; lone `.` keeps previous cents with no error. Invalid input retains its text, including on blur, and shows `Enter a dollar amount, up to 2 decimal places`. Valid blur formats cents with grouping; valid focus shows an ungrouped raw amount. Test every accepted/rejected §6.2 vector and 12-digit limit.

```javascript
/^\s*(?:(?:\d{1,3}(?:,\d{3}){1,3}|\d{1,12})(?:\.\d{0,2})?|\.\d{1,2})\s*$/
```

Handle empty/whitespace and trimmed lone-dot cases before applying this regex. Parse the fractional digits by right-padding to two digits and use the integer dollar digits times 100; never use `parseFloat` for money.

- [ ] Allocation controls are visible for every selected state, even one. Maintain editable text plus validation; clamp finite numeric input to 0–100, report empty/non-numeric as `Enter 0–100`. Preserve allocations and QIF edits across uncheck/recheck. Newly checked states default to 100 and initialize QIF fields through the common fallback chain.
- [ ] Compute results synchronously from current render inputs, using `computeMonthly` and a caught error. Do not publish calculations through delayed effects, fetch, debounce, request keys or a loading state. If any input is invalid, render `Error: Fix the highlighted inputs.` instead of cards and disable QIF. A missing-year error replaces cards and disabling applies immediately; correcting inputs recovers without console errors.
- [ ] End-to-end two-year test: freeze a local opening date in 2026; with federal 2025/2026 and XF only in 2025, preserve 2026 selection and persisted XF precedence. Show `State XF has no rules for 2026. Available years: [2025]`, no calculation cards, QIF disabled, and both export buttons enabled. Download/inspect both federal-only artifacts, choose 2025 and verify current results/QIF recover, then return to 2026 and verify cards are cleared again. Retain GA+PA/2025-style coverage where one selected state lacks the year but another has it; do not normalize away that selection.
- [ ] With projected overrides, test later-selected state defaults, including a custom `XTEST` rules directory and its normalized override; valid siblings beside ignored malformed fields; missing/empty config strings falling through the chain; an emptied edited field falling back during QIF build; and retained edits across uncheck/recheck. Confirm resulting QIF uses strings and contains no coerced object/list/number text.
- [ ] Render only monthly federal/state cards, rounded-up one-decimal sublabels, total and net. Net is signed integer cents; combined rate has up to two decimals without trailing zeros. Gross monthly/annual summary is based on exact input cents. Every card/QIF value comes from the same current result object.
- [ ] Initialize QIF date using local year/month/day getters, not `toISOString`. Test a frozen UTC instant that lies on the previous local date with an explicit browser timezone. Invalid dates disable QIF independently of tax errors.
- [ ] Add QIF/Markdown/CSV Blob downloads in the panel, using the prescribed filenames and QIF MIME `application/qif`. Both table buttons remain enabled during money/allocation/missing-state-year errors; their builders depend only on the valid chosen year/status. Revoke object URLs after download activation without interfering with browser consumption.
- [ ] At widths 1200px and below, keep the export panel visible and stack it under the main panel; at narrow mobile widths stack the sidebar too. Avoid fixed viewport-height/scroll rules that trap the lower panel. Preserve two summary columns above 768px, one below, and the net accent in both themes. Verify at widths 1440, 1280, 1201, 1200, 900, 768, 390 and a 720×500 zoom-equivalent viewport, with large valid income text.
- [ ] Built-page tests attach `guard_browser_errors` and a request collector before navigation; abort and fail every non-file request and assert no requests occurred. Test all F1–F6, selection/theme reload, storage failure, current-input/QIF reconciliation, proper rate rounding, negative/zero net with synthetic rules, export downloads and recovery. Use real local engine failures such as missing state-year rather than intercepted server responses.
- [ ] Run exact fixture parity and the complete Tax2 suite; inspect both themes and narrow-width rendering in Chromium before committing.

**Acceptance:** UI behavior matches §6, all specified fixes work, all downloads remain reachable, current inputs and outputs always agree, and the built page is entirely offline.

### Task 7 — Cut over the launcher, tests and dependencies together

**Files:** `tax2/tax2`; `tax2/taxkit/__init__.py`, `tax2/taxkit/models.py`, `tax2/taxkit/utils.py`, `tax2/taxkit/config.py`; Tax2 test ports/removals and retired modules/CLI/tables; Tax2 manifests/`.gitignore`; Tax2 policy in `tools/check_uv_headers.py`; P4 output/exit/launcher acceptance amendment in `tax2/docs/tax2_built_page_design_spec.md`.

- [ ] Add launcher tests with `load_launcher`, `run_launcher` and `assert_launcher_help`: flags/env/files documented; no output/config side effects on help; default bundled root and honored custom root; relative output file URI; output/home modes; corrupt/existing config preservation; fatal rule/output errors; argparse exit 2; browser returns false or throws yet written page yields exit 0 with warning; `UTILITIES_TESTING` suppression.
- [ ] Replace the launcher only after the built UI passes. Header retains `pydantic`, `pyyaml` and Python >=3.12. Parse `--no-browser`, `--output`, `--rules-dir`; drop positional rules root and `--port`. Default rules root is beside the launcher; default output is `runtime_home() / "tax2.html"`. Derive output/config paths without writes, run `validate_output_destination` first, then create runtime home/load config/build/validate/render, atomically write, print written path, and open `output.resolve().as_uri()` unless suppressed. Return 1 for fatal destination/build/write errors without a traceback; return 2 for argparse usage. Warn rather than fail on browser-open failure after successful write.
- [ ] Implement §3's config-destination protection before output creation/replacement. Test direct, relative, `.`/`..`-equivalent and symlinked-parent matches, plus the actual target of a symlinked config. Reject with exit 1 while preserving existing config/page bytes and `mtime_ns`. Test an unrelated output leaf symlink is replaced as a directory entry rather than written through; its target remains untouched. Test JS/CSS/license unsafe-asset failures through a temporary copied launcher before replacement. Keep atomic writes and output mode 0600; never chmod arbitrary existing output parents.
- [ ] Implement approved P4 using §1.2's destination-ancestor Git identity algorithm, separately from the config guard. Test a tiny synthetic tracked source repo, relative/normalized/symlink-parent paths, nonexistent output subdirectories, a worktree `.git` indirection file, and an unrelated nested repository inside a protected outer source checkout. All protected destinations exit 1 before config loading/creation or output publication; verify existing config/page bytes and `mtime_ns` remain unchanged and no new private file appears. A standalone deployment copy, a successfully inspected unrelated Git repo and a sibling with a shared name prefix remain valid. An output leaf symlink outside source that points into source is replaced without modifying its target; a leaf entry inside source pointing outside is still rejected. Inject metadata permission/broken-link and Git-missing/timeout/execution-error results under a candidate and require fatal no-write behavior; help and destinations with no Git-marked ancestry work with Git unavailable. Add no flags, private hardcoded paths or warning-only bypass. Update the specification's §3 `--output`, exit-1 and launcher acceptance contracts for this approved restriction and conditional identity-check prerequisite.
- [ ] Port current golden/component/QIF tests to direct engine browser evaluation, retaining the fixed QIF golden. Replace each API scenario: state/QIF inventory → payload, GA golden → parity, GA+PA100 and PA50 → engine/page, state validation → engine/UI, QIF request → builder/download. Replace CLI-table scenarios with export content/missing-year filtering. Keep rules/config tests and bundled-rules checks.
- [ ] Retire server-response race, table-mode and CDN-resource tests only after equivalent current-input/error-recovery/offline/style tests exist. Replace the `100.005` accepted-income case with explicit rejection; keep negative-net and zero-gross rendering coverage using conspicuously synthetic rules. Apply every numeric disposition in §5 below.
- [ ] Inventory ignored/generated `tax2/tables/` contents before deleting the working directory; do not silently delete unknown private files. In this same coherent cutover commit, delete tracked table fixtures and remove their corresponding table ignore rules; remove only approved generated leftovers and the `.tax2_venv/` ignore pattern. Preserve the existing project venv; recheck its actual path/readiness rather than relying on the planning snapshot.
- [ ] Delete `cli.py`, Python engine/tablegen/QIF and temporary oracle generator. Remove their package imports, `resolve_year`, unused `TaxInput`, old API/CLI tests and all executable imports of retired modules. The immutable oracle JSON and both frozen roots remain.
- [ ] With the last server/CLI config-write callers removed, delete `save_config`, remove the alias from config defaults/output and explicitly ignore it on input. Replace old save/round-trip coverage with hand-edited config loading and final no-rewrite/legacy-key compatibility assertions. No earlier commit removes members still required by the old runtime.
- [ ] Remove `requirements.txt`; make `requirements-dev.txt` standalone with pydantic, pyyaml, pytest and Playwright. Drop FastAPI, uvicorn, pandas, pyarrow, python-dateutil, typer and httpx from tracked Tax2 manifests. Do not uninstall anything from an existing venv to prove dependency removal. Change only Tax2's guard extras to `frozenset({"playwright", "pytest"})`.
- [ ] Run the complete post-port Tax2 suite and repository guard/tests listed in §6 before this cutover commit. Verify the launcher works with only declared runtime dependencies via uv rather than relying on packages left in the development venv. Keep every commit testable; launcher deletion, package import cleanup and test ports form one coherent cutover.

**Acceptance:** no server/table input/retired Python logic remains; direct launcher builds and exits; all post-port tests pass; fixture retained; dependencies and guard agree. Approved P4 rejects verified source and unclassifiable Git-marked destinations before private state reads/writes, while standalone deployed output remains supported.

### Task 8 — Update operating and repository documentation

**Files:** `tax2/README.md`, `tax2/docs/Usage.md`, `tax2/docs/multi_state_design.md`; root `README.md`, `agents.md`, `docs/local_deployment_sync.md`; approved specification amendments in `tax2/docs/tax2_built_page_design_spec.md`.

- [ ] Rewrite README/Usage around flags, built page, manual rebuild, UTC build timestamp, local opening year/date, warm-cache offline boundary, private runtime home and read-only hand-edited config, storage precedence, input validation, safe rounding and unchanged tax limitations.
- [ ] Task 9 owns removal of every maintained md-autotax reference, including Tax2's QIF compatibility sentence, in its single retirement commit. Prefer completing Task 9 before this rewrite. If documentation work lands first, preserve that existing sentence verbatim until Task 9 instead of removing the name in a separate commit; do not scatter retirement changes across the documentation commits.
- [ ] Document QIF and both exports with exact filenames/scope, independent state allocations, earned/unearned bases, credit approximations/omissions, conservative component rounding, interpolation and falling-rate-bend caveats, next-row-up recommendation and schedule use above 500,000. No server-start or CLI table-generation instructions remain.
- [ ] Include federal-only-year error/export behavior, nested override fallback/schema, approved basis/P1–P3 validation and approved P4 output rejection. Document intentional zero tax, retained negative-net test support, source-versus-deployment identity, fail-closed handling of unclassifiable Git-marked destinations, conditional Git prerequisite, and the unchanged export caveats. Verify that Task 3's S4 and Task 7's output/exit/acceptance spec amendments are present. Label malformed-override warning/fallback as the stated compatibility assumption.
- [ ] Keep instructions for generic locality labels and disabled-by-default PA EIT; explain rebuilding after locally changing rules. Do not change bundled rules or the visual reference.
- [ ] Update multi-state architecture and compatibility invariants from API/table input/config writes to payload/JavaScript/export/storage contracts. Preserve federal-once and allocated-before-compute behavior, selected-state QIF order, and fixed-amount GA golden compatibility. Remove only the obsolete three-column CSV invariant.
- [ ] Replace both root README Tax2 descriptions. Update the Tax2 Validation Matrix to the commands in §6 and keep the fleet-header guard requirement. Remove port/server/API/table-generation instructions.
- [ ] Correct the deployment doc's Tax2 local-state examples to `~/.tax2/config.yaml` and `~/.tax2/tax2.html`. For Tax2's deployed suite, document its own venv interpreter plus canonical-root `PYTHONPATH`; the docs' generic uv command must not be copied literally in this Homebrew agent environment. Keep unrelated deployment sections unchanged.
- [ ] Verify docs against actual help/generated payload/downloads and final test names. Run executable checks only when this task changes test-relevant behavior; prose edits alone do not warrant unrelated tests. Review changed instruction rules under the applicable deliverable-review policy before presenting them.

**Acceptance:** maintained docs describe the final implementation and its limits; dated audits and HTML design reference remain unchanged.

### Task 9 — Retire md-autotax in a complete independent commit

**Files:** all 13 tracked `md-autotax/` files; root `.gitignore`, `README.md`, `agents.md`, `docs/privacy_scrub_design.md`; QIF compatibility sentence in `tax2/README.md`.

- [ ] Inventory tracked, untracked and ignored files before any deletion. This revision did not inspect private/untracked inventory or contents; the earlier `.zshrc`/venv/cache observation is not proof of current state. Establish a fresh path inventory separately from tracked-source reference checks. Do not recursively grep private runtime trees or ignored environments.
- [ ] Inspect the ignored `.zshrc` locally for sensitivity, show its reviewable content to the user safely, and obtain the confirmation required by spec §10 before deleting it. If a private config/table/export appears, stop and ask for handling instructions. Never put its contents in a public diff, fixture, commit or report. Preserve `~/.md-autotax/`; it is the user's private runtime folder and theirs to delete.
- [ ] Remove tracked project via `git rm -r md-autotax`, then only approved leftovers. Remove the five root-ignore entries, at-a-glance README line, `agents.md` repo-shape/setup examples and md-autotax Streamlit validation text, and its private-runtime bullet from `docs/privacy_scrub_design.md`.
- [ ] In the same commit, remove md-autotax's name from Tax2's QIF compatibility sentence without changing the single-state wording compatibility promise. This remains necessary if retirement lands before Task 8.
- [ ] Run §6's tracked-source `git grep`, which includes hidden tracked files such as root/project `.gitignore` and excludes only the explicitly named spec/audit paths. Expected no live matches (exit 1 means no match; exit 2 or other errors are failures). Check the complete permitted-match listing too. Keep only `tax2/docs/tax2_built_page_design_spec.md`, `docs/dependency_modernization_audit_2026_09_16.md` and `docs/cleanup_audit_20260916.md` as exceptions; no blanket dated-doc exemption.
- [ ] Inspect the entire staged deletion/reference diff for privacy and commit all retirement changes together with a meaningful body. Do not run `tools/check_local_deployments.zsh` during the staged-uncommitted `.gitignore` deletion; its indexed-source audit deliberately rejects this intermediate state. Deployment checks may run after commit.

**Acceptance:** retired source and maintained references are gone; permitted history remains; unknown/private leftovers receive explicit handling rather than automatic deletion.

### Task 10 — Validate final source and prepare handoff

- [ ] Execute §6's full source gates after all executable changes. Confirm no skips or failure dismissal. Preserve named failures and output if any cannot be fixed; do not commit or publish a broken result.
- [ ] Check rule files against the baseline; bundled rules must be byte-identical. Check vendor bytes/provenance, generated payload escaping/permissions, and absence of requests in all browser flows. No real user config or built runtime artifact enters Git.
- [ ] Run tracked-file-aware leftover checks (§6), including hidden ignores, for server/table input/CLI contracts, retired imports/dependencies and `legacy_combined_alias`. Alias matches are limited to the config ignore path, its compatibility test and spec; legacy table/generate-combined/combined-file contracts are limited to the spec and the two specifically named audits. Modern export-download terminology is intentional. Private/untracked inventory is separate.
- [ ] Map each spec acceptance criterion to passing tests or an explicitly authorized manual gate. Record baseline expectation changes, fixture metadata, test results, and any deployment still awaiting authorization.
- [ ] Verify every approved P1–P4 requirement against its implementation, spec amendment and acceptance coverage before claiming the affected work complete. Their approval is recorded in §1.2; a clean plan review is validation, not the source of authorization. Do not broaden schema restrictions or CLI flags beyond the approved requirements and stated implementation decisions.
- [ ] Inspect every branch-only commit body before pushing or creating a PR. Do not merge, deploy or delete deployed files solely because implementation tests pass; follow the user's requested integration scope.

### Task 11 — Deploy only after merge and live authorization

**Target:** `~/tax2`, the maintained home-project directory copy. This is an operational follow-up, not authorization from this plan.

- [ ] Resolve the actual deployed baseline commit by evidence; do not assume current checkout HEAD was deployed. Derive deleted tracked paths from Git with rename detection disabled, e.g. `git diff --no-renames --diff-filter=D --name-only <deployed-commit>..HEAD -- tax2`. Review the list, including renamed/ported tests, not just runtime modules.
- [ ] Prepare private backups and a concrete tracked-copy/deletion list. Obtain the user's approval for live updates and retired-file deletions. Follow `docs/local_deployment_sync.md`: copy only tracked files, back up replaced/deleted files first, preserve local state/venvs, never mirror a whole directory or use `rsync --delete`.
- [ ] Sync new/changed tracked source, remove approved retired tracked files from the deployed tree, and leave generated local `tables/*.csv` for the user's decision. Stale test files must be removed along with stale runtime modules; otherwise the installed suite can still import retired code.
- [ ] Run `zsh tools/check_local_deployments.zsh` after the removal commit and deployment changes. Address its Tax2 stale/drift findings with backups and the granted approval; it may report other deployed utilities, which must be reported honestly and handled within authorized scope.
- [ ] From the deployed directory run `UV_PYTHON_DOWNLOADS=never ./tax2 --help` and a build using a private temporary `TAX2_HOME` and output. Confirm modes and open the deployed built page from `file://` if live browser acceptance is authorized.
- [ ] Run the complete copied suite with that deployment's own `.venv/bin/python` and `PYTHONPATH="<repository root>"`; do not borrow the source venv. Preserve the existing deployed venv; install declared requirements through it only if needed. If none exists, create one according to the environment rules. Compare deployed tracked bytes/modes with source.

**Acceptance:** authorized deployed copy matches source, no stale tracked code/tests remain, complete deployed suite passes, local-only state survives, and backups are retained.

## 5. Existing numeric expectations: required dispositions

These were calculated from the current Python engine using its actual operation order and the spec's safe-rounding rule. Values are synthetic test inputs, not user financial data. 2026/single, unearned 5,000 monthly and earned zero unless stated otherwise:

| Current location/scenario | Old expectation | New expectation |
| --- | --- | --- |
| `test_api.py::test_compute_single_ga_matches_golden`, federal monthly | 418.33 | 418.34 (`41834` cents); raw annual remains `5020.0` |
| Same, GA monthly | 203.6 | 203.60 (`20360` cents), unchanged |
| Same, total monthly | 621.93 | 621.94 (`62194` cents) |
| `test_compute_ga_pa_both_100_are_independent`, GA/PA monthly | 203.6 / 153.5 | 203.60 / 153.50, unchanged |
| Same, total monthly | 775.43 | 775.44 (`77544` cents) |
| `test_compute_pa_half_allocation_uses_half_income`, PA monthly | 76.75 | 76.75 (`7675` cents), unchanged |
| Browser real GA scenario, total / net | 621.93 / 4,378.07 | 621.94 / 4,378.06 |
| Browser adds PA100, net (total implicit) | 4,224.57 (775.43) | 4,224.56 (775.44) |
| Browser PA50, total / net | 698.68 / 4,301.32 | 698.69 / 4,301.31 |
| Browser then adds earned 250 (gross 5,250), derived total / net | 745.25 / 4,504.75 | 745.26 / 4,504.74 |
| That mixed scenario, fed / GA / PA monthly | 448.33 / 216.33 / 80.59 | 448.34 / 216.33 / 80.59 |
| Browser zero-income net | 0.00 | 0.00, unchanged; no NaN |

All hard-coded amount expectations in the API tests are listed above; fixed API-QIF amounts 100/20/30 remain identical, expressed as 10000/2000/3000 cents. `test_golden_baselines.py`'s fixed QIF 2345.67/512.34 remains byte-identical, expressed as 234567/51234 cents. Its annual expectation arrays stay as historical comparisons against the frozen rules; new exact tests use unrounded oracle values instead of the old ten-decimal truncation.

Browser synthetic table/race fixtures have these dispositions, not rounding migrations:

- Gross `100.005`, old net `$90.01` and summary `$100.01`: replace with F6 rejection and disabled QIF; do not invent a new rounded gross expectation.
- Gross/tax `100/125 → -$25.00` and `0/10 → -$10.00`: retain negative-net formatting assertions via synthetic rules/current engine results, without table/API stubs. Zero-gross effective rate stays zero.
- Obsolete async tax/net `30/4,970` and `40/7,960`, discarded `888`/`999`, and request counts: replace with synchronous successive-input assertions and recovery tests using the real engine. These arbitrary server responses have no new tax expectation.
- Responsive layout input `987654321`: remains a valid large, whole-dollar synthetic input. No hard-coded tax value was present; retain geometric/style assertions and add export reachability.

## 6. Verification commands and expected results

All application/browser/engine/config/rules/export/launcher tests belong to one maintained Tax2 project and run through pytest. Focused test runs during development supplement, not replace, the full suite before executable commits.

### Interim acceptance while the server remains

For every intermediate commit affecting the old runtime, including Task 3's config/rules changes, run the **current** Validation Matrix lifecycle as well as the full suite. From `tax2/`, use a private temporary `TAX2_HOME` and select a free localhost port (verify availability with `lsof`). Run:

```sh
UV_PYTHON_DOWNLOADS=never ./tax2 --help
UV_PYTHON_DOWNLOADS=never TAX2_HOME="$tax2_interim_home" ./tax2 \
  --no-browser --port "$tax2_interim_port"
```

Keep the server process/PID under control. While it is running, request `http://127.0.0.1:$tax2_interim_port/` and `/api/status` with `curl -fsS`; expected HTTP 200, the existing UI HTML, and status JSON with version `2.0`. Terminate that exact FastAPI process cleanly and reap it; verify it no longer listens on the port. Do not treat pytest's imported-ASGI tests as a substitute for this real launcher lifecycle. If tax-rule/table-generation behavior changes before cutover, also run the current documented `generate-combined` command through the venv or permitted uv requirements invocation, directing tables and runtime config to temporary paths. Remove only the synthetic smoke output afterward.

### Complete suite and final acceptance

From `tax2/`:

```sh
.venv/bin/python -m pytest
```

Expected: all tests pass with no skips. Browser tests open temporary built files from `file://`, reject non-file requests and enforce `guard_browser_errors`. During Tasks 1–6 the old server tests also remain required; after cutover all their retained scenarios have file-page replacements.

Give baseline and intermediate test invocations a private temporary `TAX2_HOME`; new test helpers likewise isolate it per test. Do not let imported old API tests fall back to real home configuration while adding the new fixtures.

From repository root after launcher/header/policy changes, use the root-tooling environment rather than another independently maintained project's venv. This revision found no root `.venv`, no `tools/.venv` and no root-tooling dependency manifest. The shared guard/test modules import stdlib code; pytest is the test runner. Under the global no-borrowing/utility-venv rule, run:

```sh
uv run --no-python-downloads --script tools/check_uv_headers.py
~/.claude/shared/agent-tools.sh ensure
~/.venvs/agent-tools/bin/python -m pytest tools/tests/test_check_uv_headers.py
```

Allow at least 600 seconds for the helper command (including lock waits); rerun it after a timeout, and report rather than bypass an ensure failure. Verify this environment and Python >=3.12 before execution. If pytest is absent, use `~/.claude/shared/agent-tools.sh add --reason "Run the repository uv-header guard tests" pytest`; never pip/uv-install into the shared utility venv directly. Do not run these setup commands during planning. If an owned root-tooling environment has since been established, inspect its actual instructions instead of assuming this snapshot is permanent.

Expected: guard exits 0 with no drift and every guard test passes. Tax2 policy permits only its two test extras. No audit-runner implementation is changed, so static-audit and Market Atlas suites are outside this port's affected test scope.

Launcher acceptance from `tax2/`, after cutover (same-shell variables are task-specific; never replace HOME/CODEX_HOME):

```sh
UV_PYTHON_DOWNLOADS=never ./tax2 --help
tax2_acceptance_dir=$(mktemp -d)
chmod 700 "$tax2_acceptance_dir"
UV_PYTHON_DOWNLOADS=never TAX2_HOME="$tax2_acceptance_dir/runtime" ./tax2 \
  --no-browser --output "$tax2_acceptance_dir/tax2.html"
stat -f '%Lp' "$tax2_acceptance_dir/runtime" \
  "$tax2_acceptance_dir/runtime/config.yaml" "$tax2_acceptance_dir/tax2.html"
```

Expected: help describes flags, `TAX2_HOME`, `config.yaml` and `tax2.html`; build exits 0 and prints output path; modes are `700`, `600`, `600`. Repeat the build with `UV_OFFLINE=1` after this exact launcher header/environment has been warmed; expected success without dependency resolution network access. Independently open an already built file in an offline Chromium context and exercise calculator/QIF/both downloads; opening the file does not require uv. The acceptance directory contains only synthetic/default data and is removed after inspection.

Launcher tests cover relative `--output`, explicit custom root, browser failure, usage exit 2, fatal exit 1 and file-preservation cases; these are not replaced by the single smoke build. Bundled-rules tests retain independent current-rule expectations. Suitable small hand-checks at 2026/single are federal annual `0` for monthly 1,000, `1240` at annual 28,500 (monthly 2,375), and `5020` at monthly 5,000; pair these with 2025/both-status examples derived deliberately from the bundled tables, not from the parity fixture generator.

After staging the complete retirement, and again after its commit, check the current tracked source rather than recursively scanning private/ignored trees. From root:

```sh
git grep -n -E 'md-autotax|md_autotax' -- . \
  ':!tax2/docs/tax2_built_page_design_spec.md' \
  ':!tax2/docs/tax2-built-page-migration-implementation-plan.md' \
  ':!docs/dependency_modernization_audit_2026_09_16.md' \
  ':!docs/cleanup_audit_20260916.md'
git grep -n -E 'md-autotax|md_autotax'
git grep -n -E 'legacy_combined_alias|generate-combined|combined_.*\.csv' -- .
git diff --name-only 191ae338f959560cd004948efa8db59b00939d47 -- tax2/rules
```

The first command must produce no matches: git-grep exit 1 means that expected result; exit 0 means live references remain; exit 2/other execution errors must be reported and fixed. The second lists allowed md-autotax references, whose paths must be exactly the three named exceptions. The third requires reviewing every result: the alias is permitted only in the config ignore path, its compatibility test and spec; retired table contracts only in the spec and those two named audits. Confirm no bundled-rule changes. `git grep` covers hidden tracked files and does not traverse `.git`, untracked private state or ignored venvs. After staging, optionally repeat with `--cached` to inspect the exact publishable snapshot. Keep these source checks separate from Task 9's private/untracked inventory.

Broaden tracked searches for retired imports/compute-mode controls; scoped Tax2 checks must distinguish the unchanged visual reference from live runtime contracts, while `/api/` elsewhere in the monorepo is not a Tax2 leftover. Do not generalize exceptions to every dated document. Deploy-audit results remain a separate live gate.

## 7. Acceptance map

| Spec requirement | Owning work and proof |
| --- | --- |
| D1–D3, §§3–5 built-page shape and payload | Tasks 2–3/7; probe, builder/launcher tests, real uv build, offline browser request assertions |
| D4 retired table input/engine/CLI | Task 7; scenario ports, dependency guard, retired-import/contract searches |
| D5/S6/§7 both exports | Tasks 3/5–6; P1/P3 invalid-input rejection, valid-rule omission/continuity tests, unchanged export caveats, federal-only-year artifacts and Blob downloads |
| D6/§6.4 amounts/rates/net | Task 4; exact fixture cents, rounding vectors, rate-sublabel and net UI tests, §5 dispositions |
| F1 local date | Task 5–6; explicit timezone/frozen-instant test, calendar validation and exact QIF |
| F2 defaults for later states and empty edits | Task 5–6; common resolver plus late-check/recheck/download tests |
| F3 allocation visible with one state | Task 6; select two/set allocation/uncheck one regression |
| F4 narrow export panel | Task 6; both themes, boundary/mobile widths and reachable downloads |
| F5 state display fallback | Task 4/6; GA 2025 card and custom selected-year-name tests |
| F6 input/engine validation | Task 3/4/6; exact money vectors, allocation/status/finite-input failures and recovery |
| S4 + approved basis/P1–P3 amendments | Task 3; every-file/old-year/status/bracket/phaseout/basis/disabled-component/root tests, negative cap/threshold and empty-structure failures, valid zero-rate/all-disabled roots |
| S5 storage/config boundary | Tasks 3/6; nested override projection/fallback, no-clobber/disk preservation and state-precedence/blocked-storage tests |
| Inlined-source guard | Tasks 3/7; raw JS/CSS/license mixed-case rejection, launcher preserves prior page, template exclusion and hostile JSON round-trip |
| Federal-only year with states elsewhere | Tasks 3/5/6; year retained, selected-state error/no stale cards/QIF disabled, federal-only downloads, supported-year recovery |
| Output/config destination + approved P4 | Task 7; physical parent/equivalent-path/config-target tests, verified source/worktree/nested-source rejection, Git identity failure/no-write coverage and valid deployed output |
| §9 parity and replacement accountability | Task 1/4/5/7; immutable two-root fixture and old-to-new scenario mapping |
| §8 maintained docs | Task 8, review against final interfaces and output |
| D7/§10 retirement | Task 9; complete committed removal, privacy gates, hidden-tracked git-grep and only named exceptions |
| §12 deployment | Task 11; authorized backups/deletions, audit, deployed help/build/full suite |

## 8. Plan review record

This exact approval-incorporation revision completed **one full review round**, using separate fresh clean-context adversarial and sanity reviewers. Both verified the complete artifact against the latest user approval, hardening request, baseline spec, current source/tests and repository instructions, including P1–P4 propagation, P4 identity/failure/symlink decisions, and preserved engine/oracle/transition contracts. Both reported **no material or polish findings**. The final sanity reviewer answered **no** to another adversarial round.

**Review disposition:** 0 material findings to fix; 0 findings rejected; 0 unresolved review findings or P1–P4 approval decisions. Separate implementation-start, private-file handling and live-operation authorization gates remain as documented. No material changes were made after final sanity; this record was completed and §10 clarified that the synthetic probes belong to earlier hardening. Both reviews were read-only, without conversation history, file edits, probes, application tests/builds or private runtime inspection. Earlier revision reviews are historical and are not proof for this approved artifact.

## 9. Change and disposition summary

| Correction | Status | Owning task / acceptance proof |
| --- | --- | --- |
| Income-basis nonempty/unique classes; valid order/default preserved; future spec amendment | **Approved requirement** | Task 3: enabled/disabled malformed lists rejected with filename; singleton/two-order/default success and unchanged YAML values |
| Closing-script guard covers raw JS, CSS and license assets; JSON/template handled separately | **Approved requirement** | Tasks 3/7: three asset-type rejection cases with mixed case; launcher preserves prior file; hostile data round-trips |
| Retirement checks include hidden tracked files with precise exceptions | **Implementation decision enforcing approved requirement** | Tasks 9–10/§6: tracked git-grep, root `.gitignore` covered, only named spec/audits permitted; private inventory separate |
| Federal-only valid year retained, calculator errors but exports work | **Spec-consistent implementation decision** | Tasks 3/5/6: two-year synthetic root, exact error/no stale cards, both federal-only downloads, recovery; ordinary partially missing state retained |
| Nested override string schema and known-field projection | **Required shape hardening; warn/ignore-valid-siblings policy is a stated assumption** | Tasks 3/6: malformed/container/leaf/unknown-field tests, key normalization, fallback for later-selected/empty edits, bytes/mtime preserved |
| Runtime config output protection matches physical publication destinations | **Implementation decision enforcing existing no-rewrite requirement** | Task 7: relative/normalized/parent-symlink/config-target cases, leaf replacement semantics, no config/page changes on failure |
| Prevent source-checkout private page writes in product CLI | **P4 approved by user**; Git identity/failure handling is a stated implementation decision | Task 7/§1.2: enforce rejection; synthetic source/worktree/nested/deployment and Git-failure tests; pre-config/pre-publication no-write gate |
| Negative credit cap, empty structures, negative finite thresholds | **P1–P3 approved by user**, reproduced rather than assumed | Task 3 required schema failures/successes and spec amendments; Task 5 valid-rule omission/continuity tests; preserve engine, oracle and intentional negative-net coverage |
| Shared guard test environment uses utility venv; Tax2 keeps its own | **Existing global environment requirement** | Task 7/§6: helper ensure/add policy and correct absolute interpreter, no borrowed venv |
| Oracle/probe/parity/config transition/cutover/deployment sequencing | **Approved requirements preserved** | Tasks 1–11: no new engine, no blanket source copy/deletion, fresh operational inventories and explicit live approvals |

## 10. Readiness and remaining authorization

This is a planning-only revision. Read-only source checks were performed for approval incorporation; §1.1's synthetic in-memory probes were performed during the earlier hardening revision. No application suites, builds, deployment checks or private runtime inspection were performed in either planning revision. Only this plan is edited. Approved work has concrete tasks/tests; implementation still requires the user's separate instruction.

The income-basis amendment and **all four P1–P4 requirements are approved for this plan and follow-on implementation**; none remains an open approval question. P4 selects enforced source-checkout rejection, with §1.2's explicit identity/failure decision. Warning/fallback for malformed overrides remains the explicit compatibility assumption; seek a decision only if a governing fatal-config policy is discovered. The plan is ready for an explicit instruction to start implementation. Private-file handling and live deletion/deployment approvals remain the separate execution gates in Tasks 9 and 11.
