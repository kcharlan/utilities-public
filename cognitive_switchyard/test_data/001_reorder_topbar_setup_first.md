# Move Setup to be the leftmost top-level menu item

The top-level navigation bar currently orders menu items as: Monitor, Setup, History, Settings. This is confusing because the app defaults to the Setup view on load (when no session exists or when a session has status "created"), yet Monitor appears first in the menu bar. The visual ordering should match the workflow — Setup is the first thing users do, so it should be the first (leftmost) menu item.

Additionally, after landing on Setup, the app should stay on the Setup view until the user explicitly clicks another menu item (e.g., Monitor). The current default-view logic already does this correctly for most cases, but the menu ordering creates a mismatch between what the user sees in the nav bar and where they actually are.

## Context
- **Navigation bar component:** `cognitive_switchyard/html_template.py` — `TopBar` function, lines ~1593–1633
- **Menu item order defined at:** lines ~1616–1618, currently: Monitor → Setup → History
- **Default view logic:** lines ~909–913, defaults to `"setup"` when no session or session status is `"created"`
- **Nav link CSS:** lines ~256–286 in the same file (`.nav-link` class)
- The menu bar uses simple `<button>` elements inside a `<nav>` with class `topbar-nav`

## Acceptance criteria
- The top-level menu bar renders items in this order: **Setup**, **Monitor**, **History**, **Settings** (icon button remains rightmost)
- When the app loads with no session or a session with status "created", the user lands on Setup and the Setup nav link shows the active state
- The user remains on the Setup view until they explicitly click another menu item — no automatic redirect to Monitor
- No changes to the default-view logic (it already defaults to Setup correctly)

## Notes
- This is a one-line reorder — swap lines 1616 and 1617 so the Setup button comes before the Monitor button
- The active-link highlighting (if any CSS class toggles based on current view) should continue to work correctly after the reorder — verify the active state styling applies to whichever link matches the current view
- Scope: ~10 minutes of implementation work
