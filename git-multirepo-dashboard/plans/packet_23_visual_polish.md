# Packet 23: Visual Polish

## Why This Packet Exists

The UI is functionally complete but lacks loading feedback, custom scrollbars, and a tool-status banner. These visual polish items reduce perceived latency and surface runtime tool availability to the user.

## Scope

- **Loading skeletons**: Animated skeleton cards shown in FleetOverview while the initial quick scan is in flight. Three placeholder cards with pulsing gray rectangles that mimic the 3-row card layout (header line 60%, commit line 80%, status line 50%).
- **Scrollbar styling**: Dark-themed scrollbars matching the design system. WebKit pseudo-elements (`::-webkit-scrollbar`) for Chrome/Edge/Safari plus Firefox `scrollbar-color`/`scrollbar-width` properties.
- **Tool-status banner**: A dismissible banner below the nav tabs that fetches `GET /api/status` on mount and displays which optional tools are missing (e.g., "npm not found — Node.js dependency checks disabled"). Shown only when at least one optional tool is unavailable. Dismissible via a close button; dismissal persisted in `sessionStorage`.

## Non-Goals

- Focus states and keyboard navigation (packet 24).
- Settings panel or settings persistence.
- View transitions — already implemented in ContentArea (opacity + translateY fade-in).
- Virtualization for >100 repos (not in the canonical ladder).
- Dependencies cross-view tab content (`#/deps` placeholder stays as-is).

## Relevant Design Doc Sections

- §5.2 Design System — CSS custom properties, transition vars
- §5.7 Empty / Loading / Error States — skeleton card spec, `@keyframes pulse` definition
- §11 Cross-Platform Requirements — scrollbar styling (`::-webkit-scrollbar` + Firefox `scrollbar-color`)
- §1 Project Structure — `TOOLS` dict, `/api/status` endpoint, startup preflight banner

## Allowed Files

- `git_dashboard.py`
- `tests/test_visual_polish.py` (new)

## Tests to Write First

1. **test_skeleton_keyframes_in_css**: Parse HTML_TEMPLATE, confirm `@keyframes pulse` is defined with `opacity` transitions at 0%/50%/100%.
2. **test_skeleton_component_exists**: Confirm `SkeletonCard` function is defined in HTML_TEMPLATE.
3. **test_skeleton_three_rows**: Confirm `SkeletonCard` renders 3 placeholder rows with distinct widths (the spec says 60%, 80%, 50%).
4. **test_scrollbar_webkit_styles**: Confirm `::-webkit-scrollbar`, `::-webkit-scrollbar-track`, `::-webkit-scrollbar-thumb` are defined in CSS.
5. **test_scrollbar_firefox_styles**: Confirm `scrollbar-color` and `scrollbar-width` properties are set on `html` or `*`.
6. **test_scrollbar_uses_design_tokens**: Confirm scrollbar styling references `--bg-secondary` or `--border-default` (dark theme colors).
7. **test_api_status_endpoint_shape**: `GET /api/status` returns `{"tools": {...}, "version": "..."}` — this test likely already passes (endpoint exists from packet 00); add a shape assertion if missing.
8. **test_tool_status_banner_component**: Confirm `ToolStatusBanner` function is defined in HTML_TEMPLATE.
9. **test_tool_status_banner_fetches_status**: Confirm `ToolStatusBanner` contains a `fetch('/api/status')` call.
10. **test_tool_status_banner_dismissible**: Confirm `ToolStatusBanner` references `sessionStorage` for dismiss persistence.
11. **test_fleet_overview_shows_skeletons**: Confirm `FleetOverview` renders `SkeletonCard` when data is not yet loaded (references SkeletonCard in its body).

## Implementation Notes

### Loading Skeletons

Add a `@keyframes pulse` animation to the CSS block (spec §5.7):

```css
@keyframes pulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 0.7; }
}
```

Create a `SkeletonCard` React component that renders a card-shaped div with three animated placeholder bars:
- Background: `var(--bg-card)`, border: `1px solid var(--border-default)`, radius: `var(--radius-md)`, padding: `14px 16px`.
- Each bar: `background: var(--border-default)`, `border-radius: 4px`, `animation: pulse 1.5s ease-in-out infinite`, `height: 14px`.
- Row 1 (header): width 60%. Row 2 (commit): width 80%. Row 3 (status): width 50%.
- Spacing between rows: same as the real ProjectCard (~8px gap).

In `FleetOverview`, show 3 `SkeletonCard` components while `fleet` data is `null` (before the first fetch resolves). Once data arrives, replace skeletons with real cards (or EmptyState if fleet is empty).

Currently, FleetOverview likely renders an empty grid or nothing while fetching. Wrap the loading state check around the existing grid rendering.

### Scrollbar Styling

Add to the CSS `<style>` block:

```css
/* Webkit (Chrome, Edge, Safari) */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: var(--bg-primary); }
::-webkit-scrollbar-thumb {
  background: var(--border-default);
  border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover { background: var(--border-hover); }

/* Firefox */
html {
  scrollbar-color: var(--border-default) var(--bg-primary);
  scrollbar-width: thin;
}
```

### Tool-Status Banner

Create a `ToolStatusBanner` component:
1. On mount, `fetch('/api/status')` and read the `tools` dict.
2. Collect keys where the value is `null` (tool not found).
3. If no missing tools, render nothing.
4. If `sessionStorage.getItem('toolBannerDismissed')` is set, render nothing.
5. Otherwise, render a banner div:
   - Background: `var(--status-yellow-bg)`, border-bottom: `1px solid var(--status-yellow)`, padding: `8px 16px`.
   - Text: 12px `var(--font-body)`, `var(--status-yellow)` color.
   - List missing tools with their impact (e.g., "npm not found — Node.js dependency checks disabled").
   - Close button (×) on the right that sets `sessionStorage.setItem('toolBannerDismissed', '1')` and hides.
6. Render `ToolStatusBanner` inside the `App` component, between NavTabs and ContentArea (but after ScanProgressBar).

Tool name → user-facing message mapping:
- `npm`: "npm not found — Node.js dependency checks disabled"
- `pip_audit`: "pip-audit not found — Python vulnerability scanning disabled"
- `go`: "go not found — Go dependency checks disabled"
- `govulncheck`: "govulncheck not found — Go vulnerability scanning disabled"
- `cargo`: "cargo not found — Rust dependency checks disabled"
- `cargo_audit`: "cargo-audit not found — Rust vulnerability scanning disabled"
- `cargo_outdated`: "cargo-outdated not found — Rust outdated checks disabled"
- `bundle`: "bundler not found — Ruby dependency checks disabled"
- `bundler_audit`: "bundler-audit not found — Ruby vulnerability scanning disabled"
- `composer`: "composer not found — PHP dependency checks disabled"

## Acceptance Criteria

1. `@keyframes pulse` is defined in the CSS block with opacity 0.4 → 0.7 → 0.4.
2. `SkeletonCard` component exists and renders 3 animated placeholder bars.
3. `FleetOverview` shows skeleton cards while fleet data is loading (before first fetch resolves).
4. Once fleet data loads, skeletons are replaced by real ProjectCard components (or EmptyState).
5. `::-webkit-scrollbar`, `::-webkit-scrollbar-track`, `::-webkit-scrollbar-thumb` are defined in CSS.
6. `scrollbar-color` and `scrollbar-width` are defined for Firefox.
7. Scrollbar styling uses design system tokens (`--bg-primary`, `--border-default`, `--border-hover`).
8. `GET /api/status` returns `{"tools": {...}, "version": "..."}` (pre-existing, verify shape).
9. `ToolStatusBanner` component exists and fetches `/api/status` on mount.
10. Banner is hidden when all tools are available (tools dict has no null values).
11. Banner shows a list of missing tools with their impact when tools are unavailable.
12. Banner has a close button that dismisses it via `sessionStorage`.
13. Banner renders between NavTabs/ScanProgressBar and ContentArea.
14. All existing tests still pass (no regressions).
15. `python git_dashboard.py --help` does not crash.

## Validation Focus Areas

- Verify skeleton cards have the correct visual layout (3 rows, varying widths) — inspect the rendered JSX structure.
- Verify scrollbar styles apply to both WebKit and Firefox targets (both CSS blocks present).
- Verify the tool-status banner doesn't flash briefly when all tools are available (check for loading state handling — the banner should not render until the fetch resolves).
- Verify `sessionStorage` dismiss persistence works (banner stays hidden after close across tab navigations but reappears in a new session).
- Check that skeleton → real card transition is smooth (no layout shift).
