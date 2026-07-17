# Packet 24: Keyboard Accessibility

## Why This Packet Exists

Interactive elements (project cards, nav tabs, KPI cards, header buttons) lack visible focus indicators and keyboard interaction handlers. This packet makes the dashboard fully keyboard-navigable per spec §5.8.

## Scope

- **`:focus-visible` styles for all interactive elements**: buttons, tabs, cards, inputs, table rows. The spec requires `outline: 2px solid var(--accent-blue); outline-offset: 2px` on `:focus-visible`. Three rules already exist (`.detail-back-btn`, `.sub-tab-btn`, `.time-range-btn`); extend coverage to all remaining interactive elements.
- **Keyboard navigation handlers**:
  - Tab through KPI cards, sort/filter controls, project cards.
  - Enter/Space on a project card navigates to its detail view.
  - Escape in project detail view returns to fleet overview.
- **ARIA attributes**: `tabIndex`, `role="button"`, `aria-label` on project cards to make them keyboard-accessible and screen-reader-friendly.
- **Card focus visual treatment**: On `:focus-visible`, apply the same background + border change as hover (per spec §5.8).

## Non-Goals

- Loading skeletons, scrollbar styling, tool-status banner (packet 23).
- Screen reader support beyond basic ARIA attributes (not in spec §10 exclusions, but out of scope).
- Mobile/touch accessibility (spec §10: "No mobile responsive design").
- Settings panel or any new UI features.

## Relevant Design Doc Sections

- §5.8 Interactions, Routing, and Accessibility — focus states, keyboard navigation, `:focus-visible` spec
- §5.4 Fleet Overview Tab — card hover behavior (which focus should mirror)
- §5.5 Project Detail View — Escape to return to fleet

## Allowed Files

- `git_dashboard.py`
- `tests/test_keyboard_accessibility.py` (new)

## Tests to Write First

1. **test_focus_visible_on_nav_tabs**: Confirm `.nav-tab-btn:focus-visible` (or equivalent class) has `outline: 2px solid var(--accent-blue)` in CSS.
2. **test_focus_visible_on_project_card**: Confirm `.project-card:focus-visible` has outline and background change in CSS.
3. **test_focus_visible_on_header_buttons**: Confirm header button classes have `:focus-visible` styles in CSS.
4. **test_focus_visible_on_sort_dropdown**: Confirm sort dropdown trigger has `:focus-visible` styles.
5. **test_focus_visible_on_filter_input**: Confirm filter input has `:focus-visible` styles.
6. **test_focus_visible_on_kpi_cards**: Confirm KPI card elements have `:focus-visible` styles (if made focusable).
7. **test_project_card_has_tabindex**: Confirm `ProjectCard` renders with `tabIndex` attribute (value `0`).
8. **test_project_card_has_role_button**: Confirm `ProjectCard` renders with `role="button"` or wraps content in a button/link.
9. **test_project_card_has_keyboard_handler**: Confirm `ProjectCard` has an `onKeyDown` handler that checks for Enter or Space.
10. **test_escape_handler_in_detail_view**: Confirm `ProjectDetail` registers a `keydown` event listener that navigates back on Escape.
11. **test_no_focus_ring_on_click**: Confirm the CSS uses `:focus-visible` (not `:focus`) so mouse clicks don't show the outline.
12. **test_existing_focus_rules_preserved**: Confirm `.detail-back-btn:focus-visible`, `.sub-tab-btn:focus-visible`, `.time-range-btn:focus-visible` still exist (no regressions).

## Implementation Notes

### Focus-Visible CSS Rules

Add `:focus-visible` rules for every interactive element class. The spec requires:

```css
outline: 2px solid var(--accent-blue);
outline-offset: 2px;
```

Elements needing `:focus-visible` rules (check the existing class names in the codebase):

| Element | Likely CSS class | Extra on focus |
|---|---|---|
| Nav tabs | `.nav-tab-btn` | outline only |
| Project cards | `.project-card` | outline + `background: var(--bg-card-hover)` + `border-color: var(--border-hover)` |
| Header buttons (Scan Dir, Full Scan, Settings) | inspect inline styles — may need a class | outline only |
| Sort dropdown trigger | inspect — likely custom component | outline only |
| Filter input | inspect — likely inline styles | outline only (already has blue border on focus per §5.4) |
| KPI cards | inspect — if they're not interactive, no need | skip if not clickable |
| Pagination buttons (Prev/Next) | inspect class | outline only |
| "Check Now" button | inspect class | outline only |
| Expand/collapse chevron in DepOverlap | inspect | outline only |

For elements using inline styles (no CSS class), the implementer has two options:
1. Add a CSS class and use it in the JSX.
2. Use a global rule like `button:focus-visible, [role="button"]:focus-visible` as a catch-all.

Option 2 is simpler. A global catch-all rule plus specific overrides for cards is recommended:

```css
button:focus-visible,
[role="button"]:focus-visible,
input:focus-visible {
  outline: 2px solid var(--accent-blue);
  outline-offset: 2px;
}
```

Then add the card-specific rule:

```css
.project-card:focus-visible {
  outline: 2px solid var(--accent-blue);
  outline-offset: 2px;
  background: var(--bg-card-hover);
  border-color: var(--border-hover);
}
```

### Keyboard Navigation — Project Cards

In `ProjectCard`, add:
- `tabIndex={0}` to the outer div.
- `role="button"` for screen reader semantics.
- `aria-label` with the project name (e.g., `aria-label="View routerview details"`).
- `onKeyDown` handler:

```jsx
onKeyDown={(e) => {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    window.location.hash = `#/repo/${repo.id}`;
  }
}}
```

The `e.preventDefault()` on Space prevents the page from scrolling.

### Keyboard Navigation — Escape in Detail View

In `ProjectDetail`, add a `useEffect` that registers a global `keydown` listener for Escape:

```jsx
useEffect(() => {
  const handler = (e) => {
    if (e.key === 'Escape') {
      window.location.hash = '#/fleet';
    }
  };
  document.addEventListener('keydown', handler);
  return () => document.removeEventListener('keydown', handler);
}, []);
```

**Edge case**: If a modal/dropdown is open, Escape should close it first, not navigate away. Currently there are no modals, so this is safe. If modals are added later, the handler should check `e.defaultPrevented`.

### Nav Tabs Keyboard Support

Nav tabs already use `<button>` elements (via `.nav-tab-btn` class), which are natively keyboard-accessible. Adding `:focus-visible` CSS is sufficient. No extra `onKeyDown` needed — buttons respond to Enter/Space by default.

## Acceptance Criteria

1. All `<button>` and `<input>` elements have a visible `:focus-visible` outline (`2px solid var(--accent-blue)`, `offset: 2px`).
2. `.project-card:focus-visible` shows both the outline and hover-like background/border change.
3. `:focus-visible` is used (not `:focus`), so mouse clicks do not show the ring.
4. Project cards have `tabIndex={0}` and are reachable via Tab key.
5. Project cards have `role="button"` for accessibility.
6. Pressing Enter or Space on a focused project card navigates to its detail view (`#/repo/{id}`).
7. Pressing Escape while in project detail view navigates back to fleet overview (`#/fleet`).
8. The three pre-existing `:focus-visible` rules (`.detail-back-btn`, `.sub-tab-btn`, `.time-range-btn`) are preserved.
9. Tab order follows visual layout: header buttons → nav tabs → content area controls → cards.
10. All existing tests still pass (no regressions).
11. `python git_dashboard.py --help` does not crash.

## Validation Focus Areas

- Test keyboard flow end-to-end: Tab from header → nav → cards → Enter to open detail → Escape to return.
- Verify focus ring does NOT appear on mouse click (only on keyboard Tab navigation).
- Verify the Escape handler doesn't interfere with typing in the filter input (Escape in an input should blur it, not navigate away — check if `e.target` is an input).
- Check that the global `button:focus-visible` rule doesn't conflict with existing button hover/active states.
- Verify no duplicate `:focus-visible` rules (the 3 existing rules should still work and not be overridden incorrectly).
