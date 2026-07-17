# EditDB Past Issues

## 2026-02-13: Theme toggle ignored light override on dark systems

- Symptom:
  - System default dark mode correctly initialized the app in dark mode.
  - Switching to light mode only changed a small subset of styles (for example, active sidebar row), while most UI remained dark.
- Root cause:
  - Tailwind Play CDN was compiling `dark:*` utilities as media-query rules (`prefers-color-scheme: dark`) instead of class-based rules.
  - The theme config was set before the CDN script in a way that was not being applied by the current runtime.
- Fix:
  - Load `https://cdn.tailwindcss.com` first, then assign `tailwind.config = { darkMode: 'class', ... }`.
  - This ensures dark variants are tied to the `.dark` class so the app-level toggle can override OS preference.
- Validation:
  - `python3 -m py_compile editdb` passes.
  - Browser probe under forced dark media with `editdb_theme=light` now reports light container backgrounds and class-based dark selectors.

## 2026-02-13: SQL Console caused white-screen crash

- Symptom:
  - Opening the SQL Console intermittently blanked the UI.
  - Browser console showed React error:
    - `NotFoundError: Failed to execute 'removeChild' on 'Node': The node to be removed is not a child of this node.`
- Root cause:
  - The `Icon` component used imperative DOM mutation (`lucide.createIcons` + manual element replacement) inside React-managed nodes.
  - React reconciliation later attempted to remove/update nodes that had already been replaced outside React, causing the crash.
- Fix:
  - Replaced imperative icon DOM mutation with a React-rendered SVG component using Lucide icon data.
  - Added a top-level React `ErrorBoundary` so future frontend runtime failures render a recoverable error screen instead of a blank page.
- Validation:
  - `python3 -m py_compile editdb` passes.
  - SQL Console navigation no longer triggers the prior `removeChild` crash path.

## 2026-02-13: Action icons became invisible but buttons still worked

- Symptom:
  - Row edit icon (left pencil), index edit icon (right pencil), and index delete icon were clickable but not visible.
- Root cause:
  - Lucide UMD icon map uses PascalCase keys (example: `Edit3`), while component lookup used kebab-case names (example: `edit-3`), resulting in missing icon definitions.
- Fix:
  - Added kebab-case to PascalCase conversion before icon lookup.
  - Render now uses Lucide’s canonical tuple format (`[tag, attrs, children]`) to construct SVG children via React.
- Validation:
  - `python3 -m py_compile editdb` passes.
  - Icon controls render visually while preserving existing click behavior.

## 2026-02-13: Full white-screen on app load after frontend merge

- Symptom:
  - App loaded as a blank white page immediately.
  - No interactive UI rendered.
- Root cause:
  - A JSX parse error in the embedded frontend script: an extra `};` after the `App` component declaration in `editdb`.
  - Because the script is Babel-transpiled in-browser, this syntax error prevented the React app from mounting.
- Fix:
  - Removed the extra `};` token so the script parses and React mounts normally.
- Validation:
  - `python3 -m py_compile editdb` passes.
  - Smoke-run against `/` returned HTML containing valid app bootstrap markers (`const App = () =>` and `ReactDOM.createRoot(...)`), and the blank-screen failure path was eliminated.

## 2026-02-13: Duplicate backend table routes after merge

- Symptom:
  - Backend contained duplicate FastAPI route definitions for:
    - `POST /api/tables`
    - `DELETE /api/tables/{table_name}`
  - Risk of ambiguous behavior and harder maintenance/debugging.
- Root cause:
  - Merge left two copies of the same handlers in `editdb`.
- Fix:
  - Removed the later duplicate handler block and kept a single canonical definition for each route.
- Validation:
  - `python3 -m py_compile editdb` passes.
  - Live smoke test confirmed:
    - `POST /api/tables` returned `200` and created table `t1`.
    - `DELETE /api/tables/t1` returned `200` and removed `t1`.

## Notes

- The browser console message:
  - `A listener indicated an asynchronous response by returning true, but the message channel closed before a response was received`
  - was assessed as extension/background-script noise, not an EditDB application error.
