# Dependency Modernization Audit — 2026-09-16

## Scope and method

This is a source and validation snapshot of the repository's 54 independently
maintained project boundaries as of 2026-09-16. Grouping directories are not
counted as projects: `coding/` is represented by `coding/design_orch` and
`coding/task_orch`, `docker/` by its eight deployable projects, and
`web_games/` by its three games.

The audit followed each project's README and directly referenced design or
testing documentation, inspected package manifests, lockfiles, PEP 723
metadata, setup commands, CDN URLs, container images, and system-tool
requirements, and then used the project's documented full suite or the safest
available help, dry-run, sample, health, or browser smoke. Python resolution
and execution used uv or a project virtual environment. Browser applications
were checked for page and console errors with Playwright where applicable.
Package versions described as "resolved" are the fresh resolver result used by
validation, not necessarily exact source pins; uv launchers retain the
repository policy of floating compatible direct dependencies unless a safety
range is required. Conventional legacy virtual-environment requirements are
exactly pinned where this modernization replaced setup-only dependency lists;
Apple Health instead uses current-compatible lower bounds.

Status meanings:

- **Changed** — dependency, lock, test, or dependency documentation changed in
  this modernization.
- **Audited/current** — the dependency surface was current or intentionally
  retained, so no dependency source change was needed.
- **No dependency change** — the project is standard-library/system-tool only
  or otherwise has no third-party package pin to modernize.

## Project matrix

| # | Independent project boundary | Status | Dependency result and validation evidence |
|---:|---|---|---|
| 1 | `Calculation tools` | Changed | Chart.js 4.5.1; Playwright 1.63.0 and `http-server` 14.1.1 tracked for browser validation. Full suite: 33 passed; npm audit clean. |
| 2 | `Claude_plugin_converter` | Changed | Modernized the standard-library Gemini converter to validate current Agent Skills naming, preserve source plugins and conflicting destinations, link compliant names, and emit TOML-safe commands. Three regression tests passed, along with usage and compile smokes. Gemini CLI 0.60.0 was registry-current, but no authenticated live Gemini session was available; generated TOML and link behavior were verified locally. |
| 3 | `abacus usage` | Audited/current | Standard-library `de-abacus.py` help, compile, and a one-row synthetic JSON-to-CSV conversion passed with the exact row `2030-01-02,1.23,synthetic-model`. The account-only bookmarklets call the private, unversioned authenticated endpoint `/api/_getOrganizationComputePointLog`; it could not be live-tested without private account data and remains an upstream-change risk. |
| 4 | `anduril_steps` | No dependency change | Standard-library Python 3.10+ calculator/solver. Help, compile, the documented `1..130` seven-step calculation, and the step-3/level-65 solver sample passed on Python 3.12.14; the upstream Anduril ramp source remained available. |
| 5 | `apple-health-extract` | Changed | Added tracked compatible floors `pandas>=3.0` and `tqdm>=4.70` plus a matching dev manifest; this is a current-compatible input, not a frozen reproducible lock. Fresh resolution produced pandas 3.0.5, tqdm 4.70.1, NumPy 2.5.3, python-dateutil 2.9.0.post0, and six 1.17.0. Setup/run syntax, the complete wrapper suite, a disposable real setup, and a fully synthetic extraction (`summary=1 detail=1 bouts=1`) passed; pip audit clean. pandas 3 makes Python 3.11+ the effective runtime floor. |
| 6 | `benchmark-llm` | Changed | Lock refreshed to packaging 26.3, Pygments 2.21.0, pytest 9.1.1, and PyYAML 6.0.3. The policy-engine example now pins its harness-owned pytest/PyYAML versions while still installing the target repository's own requirements. Full suite: 55 passed; audit clean. |
| 7 | `coding/design_orch` | Changed | zsh orchestration plus a standard-library Python 3.10+ progress parser; no package graph. Both shell files passed `zsh -n`, orchestration help and parser help passed, and the parser compiled. Current Codex CLI 0.154.0 and Claude Code 2.1.273 expose the flags the scripts use. The intentional, overrideable `gpt-5.4` default is documented as a behavior/cost hold rather than a dependency lag. |
| 8 | `coding/task_orch` | Audited/current | System-only Bash/Git/Claude scaffold. All four shell entrypoints passed Bash 3.2 syntax checks. In a disposable initialized copy, empty-queue `plan.sh` and `stage.sh` exited cleanly; the source snapshot correctly requires the README's queue-directory initialization first. Current Claude Code 2.1.273 supports the used flags and floating `opus`/`sonnet` aliases. |
| 9 | `cognitive_switchyard` | Changed | Embedded React/ReactDOM 18.3.1, Babel 7.29.8, Tailwind 3.4.17, Lucide 1.46.0, and ReactFlow 11.11.4. Full suite: 476 passed; package audits clean. |
| 10 | `data_format_converter` | Changed | Git-pinned TOON dependency at `e475c82e9da03dfaf88c0b277dee6b5d17100b13`, js-yaml 4.1.1, and TOML 3.0.0 via jsDelivr; Playwright browser coverage added. The unsafe legacy browser OpenAI Completions/key path was removed: the browser contract now requires local token labels and no external model request. Validation: 62 Python tests and 1 browser privacy/conversion test passed; audits clean. |
| 11 | `div_conv` | Audited/current | Runtime remains a standard-library uv launcher with `dependencies = []`; the fresh dev graph resolved pytest 9.1.1, iniconfig 2.3.0, packaging 26.3, pluggy 1.6.0, and Pygments 2.21.0. Complete suite: 70 passed in 2.03 seconds; help passed and pip audit was clean. |
| 12 | `dloc` | No dependency change | Standard-library Python plus Git. Compile and a real safe repository smoke passed on Python 3.12.14, producing the expected Markdown header and dated rows with Git 2.55.0. |
| 13 | `doc_linearizer` | Audited/current | BeautifulSoup and html2text requirements retained after current-version audit. Documented help smoke passed; included in the clean Python-audit batch. |
| 14 | `docker/actual-data` | Audited/current | Intentional moving `actualbudget/actual-server:latest` channel pulled and isolated load smoke passed. |
| 15 | `docker/docker-disk-compact` | No dependency change | Shell/Docker system-tool utility; help and safe dry-run passed. |
| 16 | `docker/excalidraw` | Audited/current | Intentional moving `excalidraw/excalidraw:latest` channel pulled and isolated load smoke passed. |
| 17 | `docker/llm_collector` | Changed | Container moved to Python 3.14 and gunicorn 26.2.0; the image no longer performs an unpinned pip self-upgrade before installing its exact application requirements. Validation: 5 pytest tests, shell suite PASS, 7 Node tests, and isolated health check; pip/npm audits clean. |
| 18 | `docker/llm_proxy` | Changed | Container moved to Python 3.14 and now installs the refreshed frozen `uv.lock` with uv 0.12.15 rather than resolving project ranges through pip. The lock advanced FastAPI to 0.141.1, Uvicorn to 0.53.0, Pydantic to 2.13.5, Pydantic Settings to 2.15.0, and other transitive packages. Full suite: 74 passed; the rebuilt image reported the locked versions and passed an isolated health check; pip audit clean. |
| 19 | `docker/mermaid` | Audited/current | Intentional moving Mermaid Live Editor `latest` channel pulled and isolated load smoke passed. |
| 20 | `docker/n8n-poc` | Changed | n8n updated from 2.0.2 to 2.39.6. Isolated container reached healthy `/healthz`. |
| 21 | `docker/webserver` | Changed | Python service moved to Python 3.14 and now installs a fully frozen universal graph from `requirements.lock` with pip `--require-hashes`; Node services resolved Fastify 5.12.5, `@fastify/reply-from` 12.6.5, Cheerio 1.2.0, and current Express on Node 24 LTS. Both Node images copy audited locks and use `npm ci --omit=dev`. A clean isolated rebuild passed service health, API/config, static-first, and nginx routing checks; locked Python and Node audits were clean. |
| 22 | `docpipe` | Audited/current | Existing document-processing requirements retained. Full suite: 4 passed; included in the clean Python-audit batch. |
| 23 | `editdb` | Changed | Embedded React 18 stack modernized and browser coverage added. The obsolete pre-uv installer was converted into a non-installing compatibility shim that checks uv resolution and points users to the direct launcher, removing its stale `src/editdb.py` and manual-pip surface. Validation: 3 Python tests plus 2 browser tests passed; Python graph audit clean. |
| 24 | `etf_montecarlo` | Audited/current | NumPy, pandas, yfinance, and pytest graph retained after current-version resolution. Full suite: 45 passed; Python audit clean. |
| 25 | `expense_dock` | Changed | Embedded React 18/Babel 7/Tailwind 3/Lucide stack modernized with browser coverage. Full suite: 8 passed; Python graph audit clean. |
| 26 | `git-multirepo-dashboard` | Changed | React/ReactDOM 18.3.1, Babel 7.29.8, PropTypes 15.8.1, and Recharts 2.15.4 CDN surface modernized with browser coverage. Validation: 469 core tests plus 64 browser tests passed; Python graph audit clean. |
| 27 | `harscope` | Changed | Embedded React 18/Babel 7/Tailwind 3/Lucide stack modernized with browser coverage. Full suite: 164 passed; Python graph audit clean. |
| 28 | `hysa-excel` | Audited/current | XlsxWriter, openpyxl, and pytest graph retained after current-version resolution. Full suite: 20 passed; Python audit clean. |
| 29 | `jtree` | Changed | Embedded React 18.3.1, Babel 7.29.8, Tailwind 3.4.17, and Lucide 1.46.0 modernized with browser coverage. Full suite: 158 passed; Python graph audit clean. |
| 30 | `launchmaster` | Changed | Embedded React/ReactDOM 18.3.1, Babel 7.29.8, and Lucide 1.46.0 modernized with browser coverage. Full suite: 89 passed; Python graph audit clean. |
| 31 | `md-autotax` | Changed | Added tracked exact requirements for pandas 3.0.5 and Streamlit 1.64.0; `setup.sh` now recreates the disposable environment and installs that script-relative manifest so orphaned transitive packages cannot survive upgrades. This removed a stale vulnerable GitPython left by the prior reused environment. Validation: 7 Python tests plus the shell-wrapper smoke passed; the clean graph audit passed. |
| 32 | `md-json` | Audited/current | Standard-library converter with an environment-only setup script; documented help smoke passed. |
| 33 | `media-dater` | No dependency change | Bash plus ExifTool/system utilities. `--help` and a synthetic-file `--dry-run --ext jpg` passed without renaming data. |
| 34 | `mem_snapshots` | No dependency change | macOS `vm_stat` and `top` commands only. Both documented commands produced nonempty output in a temporary directory. |
| 35 | `mls-tracker` | Changed | Resolved FastAPI 0.141.1, Uvicorn 0.53.0, Requests 2.34.2, pytest 9.1.1, HTTPX 0.28.1, and Playwright 1.63.0; embedded React 18.3.1/Babel 7.29.8/Tailwind 3.4.17/Lucide 1.46.0. Full suite: 75 passed, including browser refresh path and page/console-error checks; pip audit clean. |
| 36 | `model_sentinel` | Changed | Test graph refreshed to pytest 9.1.1 and Playwright 1.63.0. Vendored Preact, HTM, and uPlot assets were already current and were not changed. Full suite: 1,352 passed; pip audit clean. |
| 37 | `moneydance backup rotation` | No dependency change | zsh/system utilities only. Complete synthetic shell suite: 720 passed, 0 failed. |
| 38 | `pdf-split` | No dependency change | zsh, qpdf, and BSD `stat`. A generated three-page synthetic PDF split into one valid three-page chunk and passed `qpdf --check`. |
| 39 | `reversible-skew` | Changed | Added exact legacy-environment requirements: pydivsufsort 0.0.20 and Numba 0.67.0; setup consumes the manifest. Built-in 1 MiB round-trip selftest passed; pip audit clean. |
| 40 | `router-log-analyzer` | Changed | Safety ranges retained for PyMuPDF 1.x and pypdf below 7; fresh validation resolved PyMuPDF 1.28.2, pypdf 6.19.0, and pytest 9.1.1. Full suite: 451 passed; pip audit clean. |
| 41 | `routerview` | Changed | Resolved FastAPI 0.141.1, Uvicorn 0.53.0, aiosqlite 0.22.1, python-multipart 0.0.32, pytest 9.1.1, HTTPX 0.28.1, and Playwright 1.63.0; embedded React 18.3.1/Babel 7.29.8/Tailwind 3.4.17/PropTypes 15.8.1/Recharts 2.15.4. Full suite: 21 passed, including keyboard-help browser path and page/console-error checks; pip audit clean. |
| 42 | `storage_monitor` | Changed | Resolved FastAPI 0.141.1, Uvicorn 0.53.0, pytest 9.1.1, and Playwright 1.63.0; embedded React 18.3.1/Babel 7.29.8/Tailwind 3.4.17/Lucide 1.46.0. Full suite: 25 passed, including theme-toggle browser path and page/console-error checks; pip audit clean. |
| 43 | `tax2` | Changed | Resolved FastAPI 0.141.1, Uvicorn 0.53.0, Pydantic 2.13.5, PyYAML 6.0.3, pandas 3.0.5, python-dateutil 2.9.0.post0, PyArrow 25.0.1, Typer 0.27.2, pytest 9.1.1, HTTPX 0.28.1, and Playwright 1.63.0; embedded React 18.3.1/Babel 7.29.8/Tailwind 3.4.17/Lucide 1.46.0. Full suite: 25 passed, including calculator browser path and page/console-error checks; pip audit clean. |
| 44 | `time_machine_snapshot_monitor` | No dependency change | POSIX shell/macOS system tools only. Complete shell suite: 80 passed, 0 failed. |
| 45 | `toggle_wifi` | No dependency change | Bash plus macOS `networksetup`; `bash -n` passed. Live Wi-Fi mutation was intentionally not used as a smoke. |
| 46 | `transcription` | Changed | Added exact legacy requirements for openai-whisper 20250625, Streamlit 1.64.0, and directly imported pandas 3.0.5; optional OpenAI 3.14.1 and librosa 1.0.0 remain separately installable. Import/version smoke and headless Streamlit health check passed; both required and optional graphs audit clean. |
| 47 | `trim_last` | No dependency change | zsh plus FFmpeg/ffprobe; documented `--help` smoke passed. |
| 48 | `usage-monthly-csv` | Changed | Replaced moving `ccusage@latest` invocations with registry-current `ccusage@20.0.20` throughout code, tests, and docs. Full Zsh harness passed; temporary npm graph audit clean. |
| 49 | `vid-compiler` | Changed | Added exact legacy requirements for immutable upstream MoviePy commit `211e4b15f6ce4f34a6a9efbfff40590e43a68f77`, Pillow 12.3.0, NumPy 2.5.3, and tqdm 4.70.1; setup consumes the manifest. This is a temporary security bridge past stable MoviePy 2.2.1's `pillow<12` bound. CLI help passed, a generated two-second synthetic video produced a valid one-second compilation, and pip audit is clean. |
| 50 | `video-scenes` | Changed | Added exact legacy requirements for OpenCV 5.0.0.93, NumPy 2.5.3, Click 8.5.0, tqdm 4.70.1, appdirs 1.4.4, and SceneDetect 0.7.1; removed the nonexistent `scenedetect[opencv]` extra. CLI dependency smoke passed; pip audit clean. |
| 51 | `web_games/gorilla` | Audited/current | Browser-first, dependency-free single-file app. JavaScript parse and browser page-error smoke passed. |
| 52 | `web_games/multibody_sim` | Changed | Playwright updated to 1.63.0. Complete browser suite: 10 passed; npm audit clean. |
| 53 | `web_games/rps_screen` | Audited/current | Browser-first, dependency-free app. JavaScript parse and browser page-error smoke passed. |
| 54 | `worktree-helper` | No dependency change | Standard-library Python plus Git/curses/system opener. Help, version, and repository-scoped prune dry-run passed through uv. |

The shared uv-header drift guard, which is repository tooling rather than a
55th project boundary, also passed its 9-test suite and verified all 17
registered launchers.

## Latest-compatible holds and follow-on migrations

Registry versions in this table were checked on the snapshot date.

| Retained surface | Newer line | Why it is retained and validation evidence | Follow-on migration |
|---|---|---|---|
| React and ReactDOM 18.3.1 UMD | React 19.3.0 | React 19 does not publish the same UMD-global artifacts used by the embedded, build-free SPAs. Project Playwright tests loaded and exercised the React 18 pages while rejecting page and console errors. | Adopt ESM/import maps or a bundler, update root/render integration, and rerun every browser path before moving to React 19. |
| Babel Standalone 7.29.8 | Babel 8.0.5 | Existing pages compile inline `text/babel` JSX in the browser. The browser suites prove the retained major-7 transform against the current application code. | Validate Babel 8 transform/plugin changes in every embedded SPA, or remove runtime transpilation in favor of a build step. |
| Tailwind classic Play CDN 3.4.17 | Tailwind 4.3.3 | The build-free apps depend on the classic `cdn.tailwindcss.com` configuration contract. Although a `3.4.19` endpoint responds, it emits the runtime console error `Unknown Tailwind version: 3.4.19`; 3.4.17 is the newest working classic artifact. Browser tests explicitly fail on console errors. | Move to Tailwind 4's browser package or compile CSS at build/release time, then adapt inline configuration and content discovery. |
| Recharts 2.15.4 UMD/global | Recharts 3.10.1 | RouterView and Git Fleet use the Recharts 2 global API in inline JSX. Their browser suites exercise the retained chart surface. | Introduce ESM/bundling, migrate Recharts 3 component/API changes, and add chart-specific assertions before removing the v2 UMD scripts. |
| ReactFlow 11.11.4 | `@xyflow/react` 12.11.6 | Cognitive Switchyard uses the legacy ReactFlow UMD/global package; its 476-test suite validates the retained integration. Version 12 is published under a new package/API surface. | Replace the global loader with `@xyflow/react`, migrate renamed imports, styles, and node/edge APIs, and extend browser interaction coverage. |
| Cognitive Switchyard test harness | Upcoming HTTPX 2 and AnyIO API removals | The current compatible FastAPI/Starlette/HTTPX/AnyIO graph passes all 476 tests, but emits one Starlette warning about the HTTPX 2 transport path and one AnyIO warning about the legacy `BlockingPortal` alias. These are test-harness deprecations, not runtime failures. | Track the upstream Starlette/FastAPI test-client migration and replace the deprecated AnyIO alias before either removal lands; keep the warnings visible so a future dependency refresh cannot silently cross the boundary. |
| Node 24 container base | Node 26.8.2 current | Node 24 is the active LTS line; Node 26 is current/non-LTS on the snapshot date. Docker Webserver's full isolated stack passed on Node 24. | Re-evaluate at the next LTS promotion, rebuild all Node services, rerun npm audits, and repeat nginx/API/health checks. |
| `coding/design_orch` default `gpt-5.4` | Newer available Codex models | The long-running packet loop intentionally retains an overrideable, supported, xhigh-capable model whose behavior and cost are understood. Current CLI help confirms the script's flags; changing the default would alter orchestration behavior and spend rather than merely update a package. | Run a deliberate representative packet-set evaluation comparing quality, retries, latency, and cost before changing `MODEL_NAME`; keep the environment override for opt-in trials. |
| Immutable unreleased MoviePy commit `211e4b…` | Stable MoviePy 2.2.1 | Stable MoviePy 2.2.1 declares `pillow<12`; that graph selects Pillow 11.3.0 and `pip-audit` reports 35 advisory records whose fixes culminate in Pillow 12.3.0. The immutable upstream [bridge commit](https://github.com/Zulko/moviepy/commit/211e4b15f6ce4f34a6a9efbfff40590e43a68f77) removes the upper bound, resolves Pillow 12.3.0, passes the full synthetic render, and audits clean. It is intentionally commit-pinned because the upstream code is unreleased and reports inconsistent package metadata. | Return to a stable MoviePy release as soon as one includes the relaxed Pillow bound; rerun setup, the synthetic render/probe, and `pip-audit`. If upstream does not release the fix promptly, replace MoviePy with a directly maintained FFmpeg integration. See the [stable 2.2.1 release](https://pypi.org/project/moviepy/2.2.1/). |

Lucide 1.46.0 and PropTypes 15.8.1 were current on the snapshot date and need
no hold entry. The remaining directly managed Python and JavaScript packages
were updated to or freshly resolved at their latest compatible stable releases.

## Adversarial review

The first independent review found four gaps: six browser suites did not prove
that `console.error` was captured, Docker Webserver's Python graph still floated,
Calculation Tools did not assert a known numeric result, and Apple Health's
lower-bound manifest was described too strongly. The browser suites now prove
their error listeners and pass in full, the webserver uses a hashed frozen lock,
the calculator covers default and recomputed numeric results, and the Apple
Health wording is precise. A second read-only review of the complete 54-project
diff found no remaining actionable correctness, security, reproducibility,
documentation, or generated-artifact issue.

## Security and reproducibility notes

- The Python and npm graphs audited in the completed scopes were clean. The 35
  Pillow advisory records initially found through stable MoviePy 2.2.1 were
  remediated by the immutable bridge described above; no advisory was
  suppressed or ignored.
- `ccusage` is now reproducibly versioned instead of using `@latest`.
- Embedded SPAs and Data Format Converter still load JavaScript and Google
  Fonts from public CDNs at runtime without Subresource Integrity metadata.
  The browser suites prove current reachability and API compatibility, not
  offline availability or immutable delivery. Follow-on options are vendored
  assets, a build pipeline with hashed artifacts, or SRI plus an explicit
  update process where the delivery mechanism supports it.
- Docker Webserver's Python build consumes a fully frozen, hashed pip lock, its
  Node builds consume checked-in locks with `npm ci --omit=dev`, and LLM Proxy
  consumes its frozen `uv.lock`. Their base image references remain mutable
  tags rather than digests:
  `python:3.14-slim`, `node:24-alpine`, `nginx:stable-alpine`, and the semantic
  `n8nio/n8n:2.39.6` tag. This intentionally accepts patched base refreshes at
  rebuild time; digest pinning plus an explicit scheduled refresh is the
  follow-on if byte-for-byte image reproducibility becomes the priority.
- The Abacus bookmarklet's authenticated
  `/api/_getOrganizationComputePointLog` endpoint is private and unversioned.
  Its standard-library converter was validated with synthetic data, but the
  capture call itself was not exercised against an account. Treat dashboard
  breakage as an upstream compatibility event and never use private exports as
  repository fixtures.
- Actual, Excalidraw, and Mermaid intentionally retain moving `latest` image
  channels. Their update scripts are operational update workflows: each pull
  deliberately accepts upstream change, then relies on isolated load/health
  validation. This favors convenient updates over byte-for-byte reproducible
  deployments. Digest pinning plus a scheduled refresh process is the
  follow-on when reproducibility becomes the higher priority.
- The local deployment-drift audit is separate from source correctness. It
  reported that installed user-home copies lag the modernized source, as
  expected before deployment; this audit did not mutate user-home deployments.
