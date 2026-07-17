# Packet 04: HTML Shell & Design System

## Why This Packet Exists

Every UI packet depends on the HTML template, CSS design system, React shell, and hash-based routing infrastructure. This packet delivers the frontend skeleton — the empty frame that subsequent packets fill with live data.

## Scope

- Replace the placeholder `GET /` response with the full `HTML_TEMPLATE` string
- Complete CSS custom properties on `:root` (all color, typography, sizing, and transition tokens from spec §5.2)
- CDN script/link tags for React 18, ReactDOM 18, Babel Standalone, Recharts, JetBrains Mono, Geist Sans (per spec §5.1, pinned versions)
- Header bar: "Git Fleet" title, placeholder "Scan Dir" (secondary) and "Full Scan" (primary) buttons, settings gear icon — all styled per spec §5.3
- Navigation tabs: "Fleet Overview", "Analytics", "Dependencies" — underline style with animated sliding indicator per spec §5.3
- Hash routing via `window.onhashchange`: routes `#/fleet`, `#/analytics`, `#/deps`, `#/repo/{id}` — per spec §5.8
- Content area with placeholder text per active tab (e.g., "Fleet Overview — coming in packet 05")
- View transition animations: fade-in with translateY on tab switches per spec §5.8
- React `ErrorBoundary` component wrapping the app
- `<div id="root">` mount point

## Non-Goals

- Fetching any data from `/api/fleet` or any other API endpoint — that is packet 05
- KPI cards, project grid, or card rendering — packet 05
- Charts of any kind — packets 09, 10, 18, 19
- Project detail view — packet 10
- Dark mode toggle (the design is dark-only; there is no light theme in the spec)
- Settings panel functionality — later packets
- Scan Dir / Full Scan button click handlers (wiring to real APIs) — packet 05+
- Loading skeletons or progress indicators — packets 09, 23
- Focus states and keyboard navigation — packet 23

## Relevant Design Doc Sections

- **§5.1** Technology — CDN URLs, library versions, font loading note
- **§5.2** Design System — all CSS custom properties (colors, typography, sizing, transitions)
- **§5.3** Layout — header bar (56px), nav tabs (44px), content area, button styling
- **§5.8** Interactions, Routing, and Accessibility — hash fragment routes, view transition animations

## Allowed Files

- `git_dashboard.py`
- `tests/test_html_shell.py` (new)

## Tests to Write First

All tests go in `tests/test_html_shell.py`. Use TestClient from Starlette (same as packet 00/02 tests).

### 1. `test_get_root_returns_html`
- GET /
- Assert 200 status
- Assert content-type contains `text/html`

### 2. `test_html_includes_react_cdn`
- GET /
- Assert response body contains React 18 CDN URL (`react/18.2.0`)
- Assert response body contains ReactDOM 18 CDN URL (`react-dom/18.2.0`)
- Assert response body contains Babel Standalone CDN URL (`babel-standalone/7.23.9`)

### 3. `test_html_includes_recharts_cdn`
- GET /
- Assert response body contains Recharts CDN URL (`recharts/2.12.7`)

### 4. `test_html_includes_font_links`
- GET /
- Assert response body contains `JetBrains+Mono` font link
- Assert response body contains `Geist` font link

### 5. `test_html_includes_css_custom_properties`
- GET /
- Assert response body contains `--bg-primary`
- Assert response body contains `--text-primary`
- Assert response body contains `--accent-blue`
- Assert response body contains `--font-heading`
- Assert response body contains `--radius-md`
- Assert response body contains `--transition-normal`

### 6. `test_html_includes_root_div`
- GET /
- Assert response body contains `id="root"`

### 7. `test_html_includes_hash_routing`
- GET /
- Assert response body contains `onhashchange` or `hashchange`
- Assert response body contains `#/fleet`
- Assert response body contains `#/analytics`

### 8. `test_html_includes_nav_tabs`
- GET /
- Assert response body contains `Fleet Overview`
- Assert response body contains `Analytics`
- Assert response body contains `Dependencies`

### 9. `test_html_includes_header`
- GET /
- Assert response body contains `Git Fleet`
- Assert response body contains `Scan Dir` (button text)
- Assert response body contains `Full Scan` (button text)

### 10. `test_html_includes_error_boundary`
- GET /
- Assert response body contains `ErrorBoundary`

## Implementation Notes

### HTML_TEMPLATE structure

The `HTML_TEMPLATE` is a Python string (triple-quoted) assigned at module level. It contains a complete HTML document. Use `f-string` or `.format()` only if dynamic values are needed (e.g., version number); otherwise a plain string is fine.

Approximate structure:
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Git Fleet</title>
  <!-- Google Fonts -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Geist:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    /* CSS Reset + Custom Properties + Base Styles */
  </style>
</head>
<body>
  <div id="root"></div>
  <!-- CDN Scripts -->
  <script crossorigin src="...react.production.min.js"></script>
  <script crossorigin src="...react-dom.production.min.js"></script>
  <script crossorigin src="...babel.min.js"></script>
  <script crossorigin src="...Recharts.min.js"></script>
  <script type="text/babel">
    // React app code here
  </script>
</body>
</html>
```

### CSS custom properties

Copy all properties from spec §5.2 verbatim onto `:root`. Include:
- Base backgrounds (5 vars)
- Borders (2 vars)
- Text (3 vars)
- Accent (2 vars)
- Status colors + backgrounds (8 vars)
- Freshness backgrounds + borders (8 vars)
- Runtime colors (9 vars)
- Typography (3 vars)
- Sizing (3 vars)
- Transitions (3 vars)

Also add a minimal CSS reset:
```css
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg-primary); color: var(--text-primary); font-family: var(--font-body); }
```

### React component tree

```
<ErrorBoundary>
  <App>
    <Header />
    <NavTabs activeTab={activeTab} onTabChange={setActiveTab} />
    <ContentArea activeTab={activeTab} />
  </App>
</ErrorBoundary>
```

### Hash routing

Use a simple `useState` + `useEffect` pattern:

```javascript
function useHashRoute() {
  const [route, setRoute] = React.useState(window.location.hash || '#/fleet');
  React.useEffect(() => {
    const handler = () => setRoute(window.location.hash || '#/fleet');
    window.addEventListener('hashchange', handler);
    return () => window.removeEventListener('hashchange', handler);
  }, []);
  return route;
}
```

Route parsing:
- `#/fleet` or `#/` or empty → Fleet Overview tab
- `#/analytics` → Analytics tab
- `#/deps` → Dependencies tab
- `#/repo/{id}` → Project Detail (render placeholder for now)

### Navigation tabs

The tabs are text-only with an underline indicator. The active tab has a 3px `var(--accent-blue)` bottom border that slides to the active tab position. Use a `useRef` + `useLayoutEffect` to measure tab element positions and animate the underline bar via CSS `transition: left var(--transition-normal), width var(--transition-normal)`.

### Header buttons

- "Scan Dir": `onClick` does nothing yet (wired in packet 05)
- "Full Scan": `onClick` does nothing yet (wired in packet 08/05)
- Settings gear: `onClick` does nothing yet

### Content area placeholders

Each tab route renders a styled placeholder div:
```jsx
<div style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)' }}>
  <p style={{ fontFamily: 'var(--font-heading)', fontSize: '16px' }}>
    {tabName} — coming soon
  </p>
</div>
```

### ErrorBoundary

Standard React class component with `componentDidCatch` and `getDerivedStateFromError`. Renders a styled error message with the error text when caught.

### GET / handler update

Replace the current placeholder HTML response with:
```python
@app.get("/", response_class=HTMLResponse)
async def root():
    return HTML_TEMPLATE
```

The existing `GET /` handler in packet 00 already returns HTML — this replaces its content entirely.

## Acceptance Criteria

1. `GET /` returns 200 with a complete HTML document containing the full design system.
2. HTML includes pinned CDN tags for React 18.2.0, ReactDOM 18.2.0, Babel Standalone 7.23.9, and Recharts 2.12.7.
3. HTML includes Google Fonts links for JetBrains Mono and Geist with correct weights.
4. `:root` CSS block contains all custom properties from spec §5.2 (at minimum: `--bg-primary`, `--bg-secondary`, `--bg-card`, `--text-primary`, `--text-secondary`, `--accent-blue`, `--status-green/yellow/orange/red`, all `--runtime-*` colors, `--font-heading`, `--font-body`, `--font-mono`, `--radius-sm/md/lg`, `--transition-fast/normal/slow`).
5. Header bar displays "Git Fleet" title, "Scan Dir" button (secondary style), "Full Scan" button (primary style), and settings gear icon.
6. Three navigation tabs ("Fleet Overview", "Analytics", "Dependencies") render with underline-style active indicator.
7. Hash routing works: navigating to `#/fleet`, `#/analytics`, `#/deps` switches the active tab and content area.
8. Default route (empty hash or `#/`) resolves to Fleet Overview.
9. `#/repo/{id}` route renders a project detail placeholder (content filled in packet 10).
10. React `ErrorBoundary` wraps the entire app and renders a fallback on error.
11. Content area shows placeholder text for each tab.
12. All new tests pass. All existing tests (78+) continue to pass with no regressions.
13. `python git_dashboard.py --help` does not crash.

## Validation Focus Areas

- **CSS completeness**: Every custom property from §5.2 must be present. Later UI packets will reference these directly — missing vars cause silent rendering failures.
- **CDN version pinning**: Exact versions matter. Recharts 2.12.7 is required for the API surface later packets use.
- **Hash routing correctness**: Test all routes, including edge cases (empty hash, unknown hash, `#/repo/abc123`).
- **No API calls**: This packet must not fetch from any `/api/*` endpoint. The template is pure skeleton.
- **Babel JSX compilation**: Verify the `<script type="text/babel">` block compiles and renders without console errors.
- **Font fallback**: The CSS `font-family` stacks must include system fallbacks so the UI works if CDN fonts are unreachable.
