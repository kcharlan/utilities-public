# Maintenance to-do

This list holds real repairs and features only. Anything that needs the owner goes
here with its reason, not in a plan or the PKM. Sign-offs, acceptance checks and
evidence gaps are not tracked; breakage found in use gets fixed then.

- [ ] Repair Model Sentinel's scheduled scan so it runs the deployed zipapp
  (`~/Library/Scripts/model-sentinel`) instead of the checkout. The runner generated
  by [`install_launchd.template.sh`](../model_sentinel/install_launchd.template.sh)
  changes into `PROJECT_DIR` and executes its `model-sentinel`, so scheduled scans run
  whatever the checkout holds. Change the template and
  [LAUNCHD.md](../model_sentinel/docs/LAUNCHD.md), then reseed and reinstall the job:
  `setup_launchd.sh` does not overwrite an existing runtime-home installer.
- [ ] Make deployers keep only the newest two rollback backups per tool, so
  `~/.utilities-deploy-backups` needs no manual pruning. They never prune today, and
  older copies are a restore hazard. Writers include `tools/deploy_*.mjs`,
  `tools/calculator_page_deployment.mjs` and `docker/propagate-updates.zsh`.
- [ ] Port the 14 CDN-backed tools to vendored assets so they work offline and an
  outage can't break them, as esm.sh did to Git Fleet and RouterView on 2026-10-30.
  Follow the front-end rules in [agents.md](../agents.md), with no exceptions.
  Verify each with external requests blocked.
  - Vendor or inline in place: `Calculation tools` `ai-model-timeline.html` (D3),
    `drawdown.html` (fonts), `early_loan_termination_calculator.html` (Chart.js),
    and `data_format_converter/web` (TOML parser, fonts).
  - Port to Preact and htm with plain CSS: EditDB, Expense Dock, Harscope, Jtree,
    Launchmaster, MLS Tracker, Storage Monitor, RouterView, Git Fleet and Cognitive
    Switchyard. They load React 19, which has no UMD build, plus runtime Babel and
    mostly runtime Tailwind, so vendoring alone can't meet the rules.
  - Replace the React-only libraries: Recharts in Git Fleet and RouterView (uPlot
    or SVG), and `@xyflow/react` in Cognitive Switchyard.
  - Remove the React and Recharts contracts from `tools/testkit.py` once the last
    app is ported.
- [ ] Move the two exact image tags onto the normal refresh: `ghcr.io/astral-sh/uv`
  in `docker/llm_proxy/Dockerfile` and `n8nio/n8n` in `docker/n8n-poc`. Neither
  receives updates today, and n8n-poc also needs an `update.sh` for propagation to
  refresh it.
- [ ] Add Colophon's Continue in CLI action for OpenCode sessions, which Codex and
  Claude rows already have. Try the command against a disposable database first:
  `opencode --session` creates a session when the ID isn't found, and `--standalone`
  may be needed for `OPENCODE_DB` to apply instead of the background service. The
  action needs a branch in `colophon/assets/page.js`, and `continue_in_cli` enabled in
  `colophon/src/out/session_payload.c`. Keep archived and subagent sessions ineligible.
