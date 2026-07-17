# Packet 12 - Embedded React SPA Monitor

## Why This Packet Exists

Packet `11` establishes the backend transport seam, but the operator still has no live monitor, setup flow, DAG view, history browser, or settings editor. The design deliberately keeps UI work out of the backend packet so the transport contracts can stabilize before layout, styling, and client-side state management are introduced.

This packet uses the packet-`11` REST and WebSocket surface to build the single-file embedded React SPA that turns Cognitive Switchyard into an interactive local dashboard.

## Scope

- Add the embedded single-file React 18 SPA document served from `GET /`.
- Implement the design-specified view set on top of the packet-`11` transport contracts:
  - Setup View
  - Main Monitor View
  - Task Detail View
  - DAG View
  - History View
  - Settings View
- Implement the client-side REST and WebSocket data flow needed for:
  - initial state/bootstrap loading
  - live pipeline-count updates
  - worker-card progress/detail/log-tail updates
  - task-detail log streaming
  - session controls and setup actions
  - history and settings editing
- Render the exact design-token, typography, color, spacing, and animation direction defined in the design doc, including the required Google Fonts import and pinned CDN-loaded libraries.
- Keep the SPA architecture embedded and dependency-light:
  - React 18 UMD
  - ReactDOM 18 UMD
  - Babel Standalone
  - Tailwind CSS
  - Lucide Icons
  - React Flow v11 UMD

## Non-Goals

- No new REST endpoints, WebSocket message types, or backend orchestration semantics unless packet `11` is missing a transport field already required by its own accepted contract.
- No npm toolchain, `node_modules`, bundler, compiled asset pipeline, or separate frontend project directory.
- No pack-author tooling, release-notes workflows, or packet `13` operator documentation work.
- No redesign of the packet `11` backend contract to accommodate UI convenience fields that can be derived client-side.
- No second UI framework or Streamlit fallback.

## Relevant Design Sections

- `6.1 Technology Stack`
- `6.2 Aesthetic Direction: Industrial Command Center`
- `6.3 UI Implementation Specification`
- `6.3.1 Views (Functional Specification)`
- `6.4 Navigation`
- `6.5 WebSocket Protocol`
- `6.6 REST API Endpoints` only as the client contract to consume
- `7.1 Module Structure` entry for `html_template.py`
- `1466 React 18 / UMD Lifecycle Risk`

## Allowed Files

- `README.md`
- `cognitive_switchyard/server.py`
- `cognitive_switchyard/html_template.py`
- `tests/test_server.py`
- `tests/test_html_template.py`
- `tests/fixtures/ui/`

## Tests To Write First

- `tests/test_html_template.py::test_render_app_html_pins_required_react18_tailwind_lucide_and_reactflow_cdns`
- `tests/test_html_template.py::test_render_app_html_includes_required_google_fonts_import_and_design_token_block`
- `tests/test_html_template.py::test_render_app_html_escapes_bootstrap_json_for_inline_use`
- `tests/test_server.py::test_root_serves_embedded_spa_document_while_preserving_packet11_api_routes`
- `tests/test_server.py::test_root_bootstrap_payload_supports_setup_monitor_history_and_settings_views_without_extra_requests`

## Implementation Notes

- Keep the frontend in a single embedded HTML template module. Do not create a parallel asset tree or introduce a build step.
- Pin CDN URLs to exact versions compatible with React 18 UMD and React Flow v11. Do not use `@latest`.
- Follow the design tokens exactly. Packet `12` should treat the CSS custom-property block in the design doc as a contract, not inspiration.
- The server root should inject only the minimum bootstrap JSON needed to avoid an empty shell on first paint. Ongoing state changes should come from the packet-`11` API and WebSocket surface rather than server-side HTML regeneration.
- Use client-side routing/state transitions only. Navigation between Monitor, Setup, History, Settings, DAG, and Task Detail should not cause full page reloads.
- Keep client logic explicit and readable. Prefer a small number of focused React components over a generic component framework abstraction.
- If packet `11` already supplies all required data, keep `server.py` changes limited to wiring `GET /` to the HTML template and serving any bootstrap payload the template needs.
- Treat WebSocket updates as incremental patches over the last fetched state, especially for worker detail text and log tails.

## Acceptance Criteria

- `GET /` serves a single embedded HTML document that includes the required Google Fonts import, exact design-token CSS block, and pinned React 18/Tailwind/Lucide/React Flow CDN dependencies.
- The SPA renders the Setup, Monitor, Task Detail, DAG, History, and Settings views with client-side navigation and without requiring a separate frontend build step.
- The Setup view can list packs, show defaults/settings, display intake contents and preflight results, and start a session using the packet-`11` backend.
- The Monitor view renders the top bar, pipeline strip, worker cards, and task feed from backend data, then updates them live via WebSocket without page reloads.
- The Task Detail and DAG views consume existing packet-`11` task/log/DAG endpoints and react to live updates while preserving the design's layout and interaction rules.
- The History and Settings views consume the packet-`11` session/settings endpoints without introducing new backend semantics.
- The repository still contains no npm workspace, bundled frontend assets, or generated UI build output after this packet lands.

## Validation Focus

- Exact compliance with the design-token, typography, and CDN-loading constraints.
- Root-route integration without regressing packet `11` API behavior.
- Safe bootstrap-data embedding into the HTML document.
- SPA initialization with and without an active session present.
- Live WebSocket-driven updates for pipeline counts, worker details, and log tails.
- Regression coverage that the packet `11` REST and WebSocket contracts remain unchanged while the UI is added.
