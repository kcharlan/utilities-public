# Maintenance to-do

This list holds real repairs and features only. Anything that needs the owner goes
here with its reason, not in a plan or the PKM. Sign-offs, acceptance checks and
evidence gaps are not tracked; breakage found in use gets fixed then.

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
