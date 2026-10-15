# Dependency Report Remediation Implementation Plan

**Goal:** Update the dependencies in **Dependency targets**, repair the block-validation and temporal-conversion defects, and validate the affected projects and authorized deployments.

This is an implementation plan, not authorization to implement, commit, merge, change existing environments, or deploy. Apply Kevin's session instructions and [repository instructions](../agents.md). Paths below are relative to the repository root unless a task explicitly defines another base.

## Scope and sources

The earlier draft cited an external Git Fleet export, planning conversation, and previous reviews without providing their locations. Do not infer approval from those citations. Confirm any necessary prior authorization from the actual conversation, or obtain it before the gated action.

Read the affected project's README and its linked documents before execution. Use the following sources directly rather than the earlier draft's descriptions:

| Area | Source |
|---|---|
| Validation | [Validation Matrix](../agents.md#validation-matrix) and each project's test documentation |
| Deployment, backups, recovery | [Local Deployment Synchronization](local_deployment_sync.md) |
| Release source | PKM project `utilities-public`, knowledge entry `250`; resolve this checkout before retrieving it |
| Block reconstruction | `reversible-skew/rs.py:transform`, `reversible-skew/rs-big.py:transform` |
| Converter dispatch and serialization | `data_format_converter/src/data_convert.py:dump_data` and `data_format_converter/src/converters/` |
| Git Fleet report accuracy | `git-multirepo-dashboard/git_dashboard.py`: `parse_deps_for_repo`, `parse_requirements_txt`, `detect_dep_files`, `check_python_vulns`, and dependency persistence/rendering |
| YAML migration API | [Pinned upstream migration guide](https://github.com/nodeca/js-yaml/blob/5.4.3/docs/migrate_v4_to_v5.md) |
| TOON migration | `toon-format/toon-python` documentation at the release selected in **Dependency targets** |
| Market Atlas recipe and reproduction | `Calculation tools/backtest/tools/data_contract.mjs:RECIPE_FILES`, `Calculation tools/backtest/data/test_retained_reproduction.py`, and [test guide](../Calculation%20tools/backtest/tests/README.md) |

Exclude `docker/llm_proxy/uv.lock`, `benchmark-llm/uv.lock`, replacement of the browser TOML library, and the unmanaged webroot copy `utilities/LLM_token_analyzer_and_format_converter.html`. A sentinel-correct BWT redesign is also outside this plan.

## Dependency targets

This table is the authoritative target list; task names, documentation instructions, and commit subjects should refer to it rather than duplicate release numbers. Current pins come from the manifests being edited. Before installing, query the relevant public registry for target availability and yanked status. Use a newer non-yanked patch on the selected minor line if available and record that selection here. A failed compatibility check requires a decision before changing the target or accepting additional behavior changes.

| Task | Dependency or release | Target |
|---|---|---|
| Reversible Skew dependencies | numba | `0.68.0` |
| Scene detection | numpy | `2.5.4` |
| Scene detection | scenedetect | `0.7.2` |
| Scene detection | platformdirs, replacing appdirs | `4.13.0` |
| Transcription | streamlit | `1.66.0`; proposed fallback minor line `1.65`, requiring confirmation before use |
| Transcription; Market Atlas compiler | pandas | `3.0.6` |
| Transcription optional graph | openai | `3.31.0` |
| Released TOON package | toon-format, replacing the Git URL | `1.1.0` |
| Browser YAML | js-yaml | `5.4.3` |
| npm browser tooling | @playwright/test | `1.64.1` |
| Colophon browser tooling | playwright | `1.64.0` |
| Video Compiler test tooling | pytest | `9.1.1` |
| Market Atlas release | package.json and package-lock.json release fields | `1.0.1` |
| Webserver Python graph | requirements.lock | Regenerate from its existing input with `--upgrade` |

Preserve manifest entries outside these changes. Exact Python pins apply to the dependencies selected here. If resolution requires another direct dependency change, explain it before expanding scope.

## Execution and release gates

- Set `REPO=$(git rev-parse --show-toplevel)` for command examples; follow the session's **Git** instructions for checkout and branch selection.
- Apply Kevin's Python environment rules. Use each project's documented interpreter for its canonical suite. Scratch runtime checks supplement that suite. Obtain explicit approval before changing an existing environment; do not recreate it to resolve a failed install.
- Apply [Colophon's development setup](../colophon/docs/development.md) for its offline-first installation and download permissions. Apply the session's approval rules to lock compilation and browser downloads. Confirm authorization before downloading Whisper's model. Owner data preparation belongs in **Market Atlas compiler**, not an agent workaround.
- Keep fixtures and evidence outside the public checkout, except suite-owned fixtures under their existing lifecycle. Retain freezes, registry responses, audit results, baseline comparison outputs, and deployment backups privately until handoff.
- After dependency resolution, run `pip check`, freeze the validated graph, and audit that freeze with `uvx --no-python-downloads pip-audit --strict --no-deps --disable-pip -r "$FREEZE"`. For hashed locks, audit the lock instead. Run `npm audit` for the changed npm projects. Expected: successful checks with no unsuppressed advisory. Report a failure without weakening its check.
- For validation, commit, and release checkpoints, follow the session's **Tests**, **Git**, and **Release Versions** instructions and the validation source in **Scope and sources**.
- Follow **Scope and sources → Release source** for deployment checkout selection. Reconcile task evidence with the selected release source and rerun affected validation if integration changes it. Test-environment updates belong to task validation under their environment approval; runtime deployment uses the following **Deployment gate**.

### Deployment gate

Use the maintained procedures in **Local Deployment Synchronization**, including its project inventory, backup, verification, and recovery sections. Use the approved task's explicit file inventory and reviewed base-to-main diff; do not assume the last commit contains the deployment inventory.

For source-copy projects, preserve local state and destination metadata as that guide requires. If a runtime venv must change, obtain environment-replacement approval, retain its rollback copy, install the privately retained audited freeze, and compare the resulting freeze with that evidence before acceptance. Stop on an unplanned destination or graph difference.

Run `zsh tools/check_local_deployments.zsh` from the validated repository and exercise the changed deployed application using the task's synthetic acceptance checks. Expected: the selected deployment matches validated source and passes its acceptance checks. Report other fleet drift separately. Keep backups until Kevin removes them.

## Reversible Skew block validation

**Files:** `reversible-skew/rs-big.py`, `reversible-skew/README.md`, root `docs/lessons_learned.md`.

- [ ] Add `selftest()` and a CLI parser/dispatch entry following the `# --- CLI ---` section of `reversible-skew/rs.py`. Have `transform` return `(passed, total)` after its existing summary. The regression below is specified here because it does not yet exist:

```python
def selftest():
    import os, tempfile
    unit = b"synthetic reversible skew line\n"
    cases = {
        "random": os.urandom(1 << 20),
        "periodic": (unit * ((1 << 20) // len(unit) + 1))[:1 << 20],
        "varied": b"".join(f"synthetic line {i:06d} value {i * 7 % 1000}\n".encode() for i in range(60000))[:1 << 20],
    }
    with tempfile.TemporaryDirectory() as d:
        for name, data in cases.items():
            src, enc, dec = (os.path.join(d, f"{name}.{ext}") for ext in ("in", "rsbwt", "out"))
            with open(src, "wb") as f:
                f.write(data)
            passed, total = transform(src, enc, 64 * 1024, 255)
            if name == "varied" and passed == total:
                print("SELFTEST FAILED: varied (no block took the transformed path)")
                sys.exit(1)
            inverse(enc, dec)
            with open(dec, "rb") as f:
                if f.read() != data:
                    print(f"SELFTEST FAILED: {name}")
                    sys.exit(1)
    print("SELFTEST PASSED!")
```

- [ ] Run `PYTHONDONTWRITEBYTECODE=1 "$REPO/reversible-skew/venv/bin/python" "$REPO/reversible-skew/rs-big.py" selftest` before the fix. Expected: a reconstruction failure from the new regression; retain its case and exit status.
- [ ] Make the transformed-block acceptance behave as `rs.py:transform` does, using the variant's existing JIT functions:

```python
            bad = payload >= len(block)
            if not bad:
                rec_block = bwt_inverse(mtf_decode_jit(rle_decode_jit(rle)), primary)
                bad = rec_block != block
            if bad:
```

Keep the existing write branches, stream format, and inverse implementation. Run the new selftest and the reference script's selftest; expected: successful exits and satisfied assertions.
- [ ] Cross-decode generated periodic, varied, and random fixtures between the scripts and use `cmp` against the originals. Also decode a retained valid pre-change synthetic stream with the changed script. Expected: byte equality.
- [ ] Update README's Scripts and Usage sections to refer to the guard in `rs.py:transform` and the named selftests. Add a root lesson referencing the regression and the need to retain the reference guard in optimized variants. Use [Reversible Skew's guide](../reversible-skew/README.md) for project validation.

## Reversible Skew dependencies

**Files:** `reversible-skew/requirements.txt`.

- [ ] Apply the matching **Dependency targets** entry. In a new external scratch directory, create a venv using `/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv "$S/venv"`; install this project's requirements there.
- [ ] Run the selftests named in **Reversible Skew block validation** using that scratch interpreter, then the canonical project checks. Complete **Execution and release gates**. Expected: successful checks against the selected graph. No runtime deployment is planned for this task.

## Scene detection

**Files:** `video-scenes/requirements.txt`, `video-scenes/README.md`.

- [ ] Before changing pins, generate and detect a synthetic clip with a baseline scratch graph:

```bash
S=$(mktemp -d "${TMPDIR:-/tmp}/vs-deps.XXXXXX")
P="$REPO/video-scenes"
ffmpeg -v error -f lavfi -i testsrc=size=320x240:rate=25:duration=3 \
  -f lavfi -i color=c=red:size=320x240:rate=25:duration=3 \
  -filter_complex '[0:v][1:v]concat=n=2:v=1[v]' -map '[v]' -pix_fmt yuv420p "$S/cut.mp4"
detect() {
  "$1/bin/scenedetect" -i "$S/cut.mp4" -o "$2" detect-content list-scenes
}
/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv "$S/old"
"$S/old/bin/python" -m pip install -r "$P/requirements.txt"
detect "$S/old" "$S/baseline"
```

Expected: the reported boundary matches the fixture's concatenation boundary. Retain the baseline scene table, not timing-dependent logs.
- [ ] Apply the matching **Dependency targets** entries. Confirm the selected SceneDetect release's registry metadata before removing `appdirs`. Resolve a fresh scratch graph, repeat `detect` into a separate output directory, and compare scene boundaries with the baseline. Run the README's help check and **Execution and release gates**.
- [ ] In README Setup, link to `requirements.txt` rather than restating its graph. In validation, name the synthetic detection check and its acceptance criterion.
- [ ] After the **Deployment gate**, update the maintained home copy and its runtime graph, then repeat the retained synthetic detection check with the deployed interpreter.

## Transcription

**Files:** `transcription/requirements.txt`, `transcription/requirements-optional.txt`, `transcription/README.md`.

- [ ] Build a baseline scratch graph before edits. Use this new scratch harness because the README does not contain the AppTest acceptance check:

```python
import sys
from streamlit.testing.v1 import AppTest
for script in sys.argv[1:]:
    at = AppTest.from_file(script, default_timeout=120).run()
    assert not at.exception, f"{script}: {at.exception}"
```

Run it from the scratch directory with `CUMULATIVE_JSON_PATH` and `LIFETIME_TXT_PATH` set inside that directory, passing the absolute paths of `app.py` and `transcribe.py`. Expected: no assertion failure. Consult `transcription/README.md#counters-and-local-state` for the state contract.
- [ ] Apply the matching **Dependency targets** entries. Create separate scratch environments for the core and optional manifests; run the harness against the changed graphs. Smoke-run the Streamlit entrypoints as required by the Validation Matrix, with scratch working directory and counters, and shut each server down cleanly. Expected: successful health/page requests and AppTest execution.
- [ ] Generate synthetic speech with `say`, convert it to mono audio with FFmpeg, and assert Whisper transcription and nonempty word timings through the core graph. Use the model download permission in **Execution and release gates**. In the optional graph, exercise `librosa.load` on that audio and construct the OpenAI client with a conspicuously synthetic key to check `audio.transcriptions.create` without sending a request. Expected: audio duration is positive and the client method is callable. Audit the core and optional freezes separately.
- [ ] Extend README Validation to name the harness and synthetic audio checks; link counter isolation instructions to its Counters section. Use the Validation Matrix for canonical checks.
- [ ] After the **Deployment gate**, deploy the core graph only. Repeat the harness and audio acceptance against deployed scripts with scratch state. Compare pre/post file metadata and hashes of deployed counter files without printing their contents; expected: unchanged.

## Released TOON package

**Files:** `data_format_converter/requirements.txt`, `data_format_converter/src/converters/toon_conv.py`, `data_format_converter/tests/test_toon_conv.py`, `data_format_converter/tests/test_cli.py`, `data_format_converter/README.md`.

- [ ] Add the proposed tests named `test_dump_temporal_as_iso_string`, `test_load_comment_only_is_empty_object`, and `test_yaml_binary_to_toon_is_a_structured_error`. Parameterize the temporal test over `date`, `datetime`, and `time`, using `isoformat()` for its expected value. In the CLI test assert the existing structured conversion-error contract from `src/data_convert.py:exit_with_error`. These new tests, rather than an unprovided historical comparison, define acceptance.
- [ ] Run the added tests on the current graph and record actual outcomes before replacing the Git URL with the matching **Dependency targets** package. Change the import-failure messages in `toon_conv.py` to name the selected distribution. Test a fresh scratch graph, complete its audit, then update the canonical test venv under its environment approval.
- [ ] Run the complete Python and browser suites from the Validation Matrix. Expected: the proposed tests and retained tests pass. An unexpected compatibility change returns to the target-selection decision gate.
- [ ] Replace README's installation-history paragraph with a reference to `requirements.txt`. Document changed behavior by linking the named regressions.

## Browser YAML

**Files:** `data_format_converter/web/index.html`, `data_format_converter/tests/browser.spec.js`, `data_format_converter/README.md`.

The following proposed tests are the acceptance contract because they are not yet present. Put these fixture definitions in the browser test module rather than duplicating them in README or commit prose:

```javascript
const implicitNumberCase = {
  source: 'bin: 0b101\nsep: 1_000\nplain: 1000\n',
  expected: { bin: '0b101', sep: '1_000', plain: 1000 },
};
const explicitNumberCases = [
  { source: 'n: !!int 1_000\n', expected: { n: 1000 } },
  { source: 'n: !!float 1_000.5\n', expected: { n: 1000.5 } },
];
const malformedExplicitNumber = 'n: !!int synthetic\n';
const multilineDumpCases = ['a\n\n', { text: 'a\n\n' }, 'a\n', 'a\n\n\n'];
const whitespaceQuoteCase = '   ';
```

| Proposed test | Required assertions |
|---|---|
| `yaml_load_preserves_legacy_collections_and_timestamps` | Capture current results for merge keys, timestamps, complex keys, binary, sets, ordered mappings, pairs, YAML boolean-looking words, and comment-only documents; assert the same parsed values after migration. |
| `yaml_implicit_legacy_numbers_use_core_strings` | Assert `implicitNumberCase`'s expected mapping. |
| `yaml_explicit_numeric_tags_keep_baseline_values` | Assert `explicitNumberCases`' mappings and retain rejection of `malformedExplicitNumber`. |
| `yaml_dump_keeps_baseline_multiline_output` | Compare retained dump bytes for `multilineDumpCases` and parse the output back to verify values. |
| `yaml_dump_accepts_whitespace_quote_change` | Limit the quotation-style exception to `whitespaceQuoteCase` and verify the parsed value. |

- [ ] Record baseline results from the current page/library before changing the pin. The implicit-number regression describes the proposed changed behavior and should fail on the baseline; preservation tests should pass.
- [ ] Apply the browser **Dependency targets** entry using its `dist/browser/js-yaml.umd.min.js` build and update the existing browser test's pinned URL assertion. Use the pinned upstream migration guide's public schema/tag APIs to make `jsonFromYaml` satisfy the named load tests. Preserve explicit numeric handling even where implicit handling intentionally changes; use tag `resolve(source, isExplicit)` rather than assuming built-in schema selection proves impossibility.
- [ ] Make `yamlFromJson` satisfy the named dump tests. Do not silently accept the added document-end marker found during review. If public APIs cannot meet a preservation assertion, present the exact measured test diff and obtain a separate compatibility decision before continuing. Approval to execute this plan alone does not accept further deltas.
- [ ] Run the complete converter Python and browser suites. Expected: all retained and proposed assertions pass, including the browser error/privacy guards. Update README's dependency reference to the pinned script tag and link conversion limits to the named tests.

## npm browser tooling

**Files:** `package.json` and `package-lock.json` under `Calculation tools/`, `Calculation tools/backtest/`, `data_format_converter/`, and `web_games/multibody_sim/`.

- [ ] Set `PLAYWRIGHT_TARGET` from the matching **Dependency targets** entry. In `web_games/multibody_sim/`, run `npm install --save-dev --save-exact=false --save-prefix='^' "@playwright/test@$PLAYWRIGHT_TARGET"`. In the other projects listed under **Files**, run `npm install --save-dev --save-exact "@playwright/test@$PLAYWRIGHT_TARGET"`. Then run `npm ci`, inspect the saved ranges and resolved package versions, and run `npx playwright install --dry-run chromium`. Use the selected driver's browser metadata, not a hardcoded cache revision. Obtain download permission if the required browser is absent.
- [ ] Run each project's complete validation by following its README and the root Validation Matrix, including Market Atlas's independently required root audit commands from its test guide. Use a prepared external compiler interpreter for Market Atlas. Expected: required tests run successfully without skips; npm audits meet **Execution and release gates**.

## Colophon browser tooling

**Files:** `colophon/requirements-dev.txt`, `colophon/docs/development.md`.

- [ ] Apply the matching **Dependency targets** entry. Install into the canonical project test environment following its development guide and environment approval. Inspect the selected driver's `browsers.json` to confirm its required browser is cached; follow the same guide if it is absent.
- [ ] Run the Colophon commands in the root Validation Matrix. Expected: required categories and guards pass. In the development guide, refer to `requirements-dev.txt` rather than repeat tool versions.
- [ ] Check `tools/deploy_colophon.mjs:buildInput` against the changed inventory. No native deployment is intended for this development-tool task; an unexpected native-input change requires a scope decision.

## Video Compiler test tooling

**Files:** `vid-compiler/requirements-dev.txt`.

- [ ] Apply the matching **Dependency targets** entry and install into the canonical test environment under its environment approval. Follow [Video Compiler validation](../vid-compiler/README.md#development-and-validation), translating Python commands according to the session rules. Expected: pytest succeeds and launcher help succeeds.
- [ ] After the **Deployment gate**, copy the changed manifest into the maintained home project. This task does not update its runtime venv.

## Market Atlas compiler

**Paths in this section are relative to `Calculation tools/backtest/`, except explicitly repository-root paths.**

**Files:** `data/requirements.txt`, `data/requirements.lock`, `tools/setup_data.mjs`, `tests/setup-data.test.js`, `package.json`, `package-lock.json`, `data/README.md`, `README.md`.

- [ ] Establish a passing baseline with [Complete acceptance and Root audit checks](../Calculation%20tools/backtest/tests/README.md). Record selected identity and reproduction metadata:

```bash
MA="$REPO/Calculation tools/backtest"
DATA="${MARKET_ATLAS_DATA_HOME:-$HOME/.cache/market-atlas}"
S=$(mktemp -d "$HOME/.cache/ma-pandas3.XXXXXX")
cp "$DATA/current.json" "$S/baseline-selector.json"
BUNDLE=$(jq -r .bundleId "$S/baseline-selector.json")
jq -r .generatedDate "$DATA/datasets/$BUNDLE/provenance.json" > "$S/generated-date.txt"
```

Use `tests/helpers/runner.cjs:validatePython` and the data guide when preparing the external scratch compiler environment. Missing real inputs or a failed baseline leave the acceptance gate unmet.
- [ ] Add the regression to `tests/setup-data.test.js` using its existing fixture/hooks:

```javascript
test('compiler venv below Python 3.11 is refused because pandas 3 requires it',async t=>{
 const f=await fixture(t),{setupData}=await api;await setupData(f.options);
 const hooks={...f.hooks,run:async(command,args,options)=>args[0]==='-c'?JSON.stringify({version:'3.10.14',platform:'darwin',machine:'arm64',ready:true,isolated:true}):f.hooks.run(command,args,options)};
 await assert.rejects(setupData({...f.options,refresh:true,hooks}),/Python 3\.11 or newer/);
});
```

Run it before the floor change; expected: failure of the rejection assertion. In `environment()`, change the version regex to `/^3\.(?:1[1-9]|[2-9][0-9])\.\d+$/` and the message to `'Compiler requires Python 3.11 or newer'`. Run the named regression and the entire setup-data test module; expected: success.
- [ ] Apply the matching compiler **Dependency targets** entry. Create the scratch graph with `/opt/homebrew/opt/python@3.14/bin/python3.14 -m venv --copies "$S/venv"` and `"$S/venv/bin/python" -m pip --isolated install --index-url https://pypi.org/simple -r "$MA/data/requirements.txt"`. Run `pip check` and record/audit its freeze. Populate `data/requirements.lock` from that freeze. Its comment should record the actual interpreter and install method, without inferring source-build history from a separate wheel-availability check. Update environment guidance to refer to the selected dependency's `Requires-Python` and the guard in `environment()`; keep source-syntax requirements separate.
- [ ] Apply the matching release entry to maintained release fields. Run `MARKET_ATLAS_TEST_PYTHON="$S/venv/bin/python" npm run test:synthetic` from the project. Expected: the invented suites succeed. **Do not commit yet.**
- [ ] Prepare the owner recompilation command, using the retained date from `data/test_retained_reproduction.py`'s reproduction pattern:

```bash
printf 'npm run setup:data -- --generated-date %s\n' "$(cat "$S/generated-date.txt")"
```

Kevin runs it from the project against the edited recipe. Before that operation, preserve the existing external compiler freeze and an environment backup restorable at its original path; establish approval for that environment update. If cleanup of packages outside the new lock is necessary, review the exact removal list against that freeze before an authorized removal; never remove packages solely because an unreviewed diff lists them. Compare the resulting freeze with the audited lock and run `pip check`.
- [ ] Compare `dataId` and `recipeId` from `$DATA/current.json` against `$S/baseline-selector.json`. Expected: data bytes retain their identity and the recipe identity changes. A different data identity is a stop condition for commit and deployment. Retain the old bundle; after setup has stopped, restore the saved selector atomically using a fresh mode-0600 temporary file inside `$DATA`, and restore the backed-up compiler environment at its original path under its recovery authorization. Report the unchanged source recipe edits as pending investigation. Do not infer the cause solely from the hash difference.
- [ ] Run **Complete acceptance** and **Root audit checks** from the test guide against the newly selected recipe and graph, then run `npm run build -- --offline` and audit the final compiler freeze. Expected: required suites pass without skips, the build succeeds, and the audit meets **Execution and release gates**. This is the task's commit-candidate checkpoint under those gates.
- [ ] After the **Deployment gate**, use the deployment guide's Market Atlas dry-run/install procedure with the validated build. Follow the test guide's separately authorized **Installed acceptance**, including response-byte comparisons. Compare the built inventory with the installed inventory before deciding no deployment is necessary; do not use a glob that overlooks extra installed files. Expected: installed acceptance matches merged source and selected data.

## Webserver Python graph

**Files:** `docker/webserver/app_py/requirements.lock`.

- [ ] With lock-compilation authorization, follow `docker/webserver/app_py/README.md`'s compile command, adding `--upgrade`, and audit the resulting lock through **Execution and release gates**. Review the dependency and hash diff against the selected registry metadata.
- [ ] Validate the lock's hash-enforced install in an isolated disposable environment using the Dockerfile's target Python/platform and exercise `main.py`'s endpoint. Follow the webserver README's documented validation; expected: install and synthetic API checks succeed. Obtain any required image/network permission before this validation.
- [ ] After the **Deployment gate** and explicit live-stack authorization, follow [Docker-specific state and maintenance](local_deployment_sync.md#docker-specific-state) and the deployed `~/docker/webserver/update.sh`.
- [ ] Verify the installed API package versions against the selected lock and the webserver README's routing contracts using response contents as well as status. Follow Market Atlas's separately authorized installed acceptance if the maintenance affects that site. Run the fleet audit. Expected: endpoint, routing, and deployment checks succeed. For state preservation and recovery, apply the linked maintenance guide.

## Converter temporal values

Run this task after the dependency tasks. **Paths are repository-root-relative.**

**Files:** create `data_format_converter/src/converters/temporal.py`; modify `data_format_converter/src/converters/json_conv.py`, `data_format_converter/src/converters/xml_conv.py`, `data_format_converter/src/converters/yaml_conv.py`, their corresponding test modules under `data_format_converter/tests/`, `data_format_converter/tests/test_cli.py`, `data_format_converter/README.md`, and root `docs/lessons_learned.md`.

The proposed tests below define the conversion policy. They are specified here because no existing regression captures this cross-format contract:

- [ ] Add `test_dump_temporal_as_iso` to JSON tests, parameterizing supported temporal objects and pretty/compact writers, and `test_dump_xml_temporal_as_iso` to XML tests for the same objects, including nested mappings/lists. Add unknown-type rejection tests for the changed writers. Expected before implementation: the new serialization cases fail and rejection tests retain existing behavior.
- [ ] Add `test_yaml_temporal_policy`: retain native date/datetime values after dump/load, encode `datetime.time` as its `isoformat()` string, and retain ordinary strings unchanged. Add a TOML regression asserting preservation of native temporal values and ordinary strings without modifying its writer. Expected before implementation: the YAML time case fails; native-type preservation passes.
- [ ] Add `test_temporal_cli_matrix` to `data_format_converter/tests/test_cli.py`, using its `run_cli` helper and external `tmp_path`. Parameterize the source format and the target values from `src/data_convert.py:SUPPORTED_FORMATS`. Use these fixtures in the test code:

```python
sources = {
    "toml": 'when = 2030-01-02T03:04:05Z\nday = 2030-01-02\nt = 03:04:05\nname = "synthetic"\n',
    "yaml": 'when: 2030-01-02T03:04:05Z\nday: 2030-01-02\nt: "03:04:05"\nname: synthetic\n',
}
```

Load each source fixture to establish its typed input mapping. Parse each actual CLI output using its target loader; unwrap the CLI's XML root according to `dump_data`. Compare the complete mapping, including field set, marker, temporal values, and types: JSON, JSONC, XML, and TOON expect temporal `isoformat()` strings; YAML follows `test_yaml_temporal_policy`; TOML preserves the input's supported native values. Do not coerce a YAML string into a TOML time. Include nested temporal values in the direct writer regressions. Expected before implementation: unsupported CLI conversions fail; after implementation every matrix assertion passes. Substring presence is not an acceptance check.
- [ ] Implement the shared serializer hook:

```python
import datetime
from typing import Any

def iso_temporal(value: Any) -> str:
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not serializable")
```

Import it relatively in the changed converter modules. Pass it as `default` to JSON serialization. Use it in XML's final unsupported-value branch while retaining the existing error for other types. In YAML's `_normalize`, apply it only to `datetime.time`. Reuse the released TOON writer; leave TOML's native writer unchanged.
- [ ] Run the converter's complete Python and browser suites through the Validation Matrix. Expected: retained assertions and the named temporal regressions pass. Update README conversion behavior by linking these policy tests rather than promising string normalization across formats. Add the lesson to the explicitly root-qualified file in **Files**, referencing the regression matrix. Use the conversion-policy test names when describing the task's change.

## Git Fleet report accuracy

Keep scanner/report remediation in [its separate implementation plan](../git-multirepo-dashboard/docs/git_fleet_dependency_accuracy_implementation_plan.md). Use the code symbols in **Scope and sources** and that project's README/test instructions rather than the earlier draft's scanner-behavior summary. After that work is validated and integrated, rescan this repository to obtain report evidence from the repaired implementation.
