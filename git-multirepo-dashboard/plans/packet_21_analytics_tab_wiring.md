# Packet 21: Analytics Tab Wiring

## Why This Packet Exists

All three analytics components (Heatmap, TimeAllocation, DepOverlap) are fully implemented and tested but unreachable — the Analytics tab in ContentArea renders a "coming soon" placeholder instead of the actual components. This packet wires them together into a single Analytics tab view.

## Scope

- Create an `AnalyticsTab` React component that renders all three analytics sections stacked vertically
- Each section has a styled header (18px `var(--font-heading)` weight 600, `var(--text-primary)`, `margin-bottom: 16px`)
- Sections separated by `32px` vertical gap (per spec §5.6)
- Section headers: "Activity Heatmap", "Time Allocation", "Dependency Overlap"
- Replace the "Analytics — coming soon" placeholder in `ContentArea` with `<AnalyticsTab />`
- All three child components already self-fetch their own data — no new data fetching logic needed

## Non-Goals

- No new API endpoints (all three analytics endpoints already exist and are tested)
- No new CSS custom properties (all needed vars already exist)
- No changes to existing Heatmap, TimeAllocation, or DepOverlap component internals
- Not wiring the top-level "Dependencies" tab (that placeholder remains as-is)
- No time range coordination across sections (each section manages its own time range independently)
- No loading orchestration across sections (each component handles its own loading state)

## Relevant Design Doc Sections

- §5.6 "Analytics Tab" — layout, section headers, gap spacing, and the three analytics sections

## Allowed Files

- `git_dashboard.py` — add AnalyticsTab component, update ContentArea
- `tests/test_analytics_tab_wiring.py` — new test file

## Tests to Write First

1. **test_analytics_tab_component_in_html**: Verify `GET /` response contains the string `AnalyticsTab` (the component is defined in the HTML template).

2. **test_analytics_section_headers_in_html**: Verify `GET /` response contains all three section header strings: "Activity Heatmap", "Time Allocation", "Dependency Overlap".

3. **test_analytics_tab_renders_child_components**: Verify `GET /` response contains references to all three child components (`Heatmap`, `TimeAllocation`, `DepOverlap`) within or near the AnalyticsTab definition.

4. **test_content_area_no_coming_soon**: Verify `GET /` response does NOT contain the string "Analytics — coming soon" (the placeholder has been replaced).

5. **test_analytics_section_layout_gap**: Verify the AnalyticsTab component applies `gap: '32px'` or equivalent `32px` spacing between sections in its style.

6. **test_analytics_heatmap_endpoint_still_works**: `GET /api/analytics/heatmap?days=365` returns 200 with `data` and `max_count` keys (regression guard).

7. **test_analytics_allocation_endpoint_still_works**: `GET /api/analytics/allocation?days=90` returns 200 with `series` key (regression guard).

8. **test_analytics_dep_overlap_endpoint_still_works**: `GET /api/analytics/dep-overlap` returns 200 with `packages` key (regression guard).

## Implementation Notes

### AnalyticsTab Component Structure

```jsx
function AnalyticsTab() {
  const sectionHeaderStyle = {
    fontFamily: 'var(--font-heading)',
    fontSize: '18px',
    fontWeight: 600,
    color: 'var(--text-primary)',
    marginBottom: '16px',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
      <section>
        <h2 style={sectionHeaderStyle}>Activity Heatmap</h2>
        <Heatmap />
      </section>
      <section>
        <h2 style={sectionHeaderStyle}>Time Allocation</h2>
        <TimeAllocation />
      </section>
      <section>
        <h2 style={sectionHeaderStyle}>Dependency Overlap</h2>
        <DepOverlap />
      </section>
    </div>
  );
}
```

### ContentArea Change

Replace the analytics placeholder block (lines ~4658-4665):
```jsx
// Before:
} else if (tab === 'analytics') {
  content = (<div style={...}>Analytics — coming soon</div>);

// After:
} else if (tab === 'analytics') {
  content = <AnalyticsTab />;
```

### Key Details

- `Heatmap` accepts optional `{ data, maxCount, loading }` props. When called with no props (`<Heatmap />`), it self-fetches from `/api/analytics/heatmap?days=365`.
- `TimeAllocation` takes no props and self-fetches from `/api/analytics/allocation?days=N`.
- `DepOverlap` takes no props and self-fetches from `/api/analytics/dep-overlap`.
- All three components have their own internal loading states — no orchestration needed.

## Acceptance Criteria

1. The `AnalyticsTab` function is defined in the HTML template inside `git_dashboard.py`.
2. `ContentArea` renders `<AnalyticsTab />` when `tab === 'analytics'`.
3. The "Analytics — coming soon" placeholder text is removed.
4. AnalyticsTab renders three `<section>` elements with headers "Activity Heatmap", "Time Allocation", "Dependency Overlap".
5. Section headers use 18px `var(--font-heading)`, weight 600, `var(--text-primary)`, `margin-bottom: 16px`.
6. Sections are separated by 32px gap (via flexbox `gap: '32px'` or equivalent).
7. Heatmap is rendered with no props (self-fetching mode).
8. TimeAllocation is rendered with no props.
9. DepOverlap is rendered with no props.
10. `GET /api/analytics/heatmap?days=365` still returns 200 with correct shape.
11. `GET /api/analytics/allocation?days=90` still returns 200 with correct shape.
12. `GET /api/analytics/dep-overlap` still returns 200 with correct shape.
13. All existing tests pass (no regressions).
14. `python git_dashboard.py --help` exits cleanly.

## Validation Focus Areas

- Verify the three analytics components actually render (not just defined) when navigating to `#/analytics`.
- Verify no console errors when the analytics tab loads.
- Verify each section fetches its data independently on tab activation.
- Verify the placeholder text is completely removed, not just hidden.
- Run the full test suite to confirm no regressions in the existing 394 tests.
