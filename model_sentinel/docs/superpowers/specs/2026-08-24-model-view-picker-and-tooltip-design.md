# Model View Picker and Tooltip Design

Date: 2026-08-24
Status: Approved design

## Problem

The Models view has two usability defects.

1. The **Add model** search results are absolutely positioned inside
   `.model-controls`, whose `overflow-y: auto` clips descendants. When no model
   is pinned, the controls are short and only the first result is visible. A
   pin makes the aspect list taller, which enlarges the scrollport and merely
   masks the defect.
2. Numeric uPlot timelines draw points and a synchronized cursor but disable
   the built-in legend and provide no replacement value readout. Hovering a
   point therefore cannot reveal the exact observation behind the rounded
   axis position.

The fixes are frontend-only. The existing `/api/models` and `/api/series`
contracts already contain all required data.

## Goals

- Show the complete model result list without clipping, regardless of how many
  models are already pinned or how tall the aspect controls are.
- Keep the result list anchored to the Add model input and bounded by the
  viewport.
- On numeric timeline hover, show the observation timestamp and exact values
  for every visible model for that aspect.
- Make small differences discoverable even when the chart axis visually
  compresses them.
- Preserve existing selection, zoom, synchronized-cursor, theming, offline,
  and read-only behavior.

## Non-goals

- No database, API, aspect-catalog, or stored-value changes.
- No redesign of boolean, list, or scalar state strips; they already expose
  per-observation tooltips.
- No change to the eight-model or twelve-aspect limits.
- No new frontend framework, build step, CDN dependency, or vendored library.
- No standalone deployment from the feature branch. Rebuild only after merge
  to `main` and explicit deployment authorization.

## Model Search Overlay

### Rendering boundary

The result list will be rendered in a temporary overlay host attached to
`document.body`, outside `.model-controls`. A small Preact portal helper will
create the host while results are open, render the existing typeahead content
into it with the already-vendored Preact `render` primitive, and remove the
host on close or component unmount.

Moving only the overlay boundary fixes the clipping at its source. The sticky,
bounded sidebar and its existing scrolling behavior remain unchanged.

### Placement

When the query is non-empty, placement is derived from the Add model input's
`getBoundingClientRect()`:

- align with the input's left edge when space permits;
- use at least the input width and allow a wider desktop list for long model
  identifiers, capped to the viewport minus a small edge margin;
- prefer placement below the input; flip above when the usable space above is
  greater and the space below cannot show a practical list;
- cap list height to the chosen viewport space and scroll the results inside
  the overlay;
- clamp horizontal placement so neither edge can leave the viewport.

Recompute placement while open on window resize, captured scrolling, and input
size changes. Coalesce repeated geometry updates with
`requestAnimationFrame`. The overlay sits above normal panels but below modal
drawers and global notifications.

### Interaction and accessibility

Preserve the current loading, error, no-results, item rendering, click-to-pin,
Escape-to-clear, and input Arrow Down behavior. The input exposes
`aria-expanded` and `aria-controls`; the overlaid list retains `role=listbox`
and its result buttons retain `role=option`. Selecting a result clears the
query and removes the overlay.

## Numeric Timeline Tooltip

### Data and activation

Each `TimelinePanel` will install a lightweight tooltip element/plugin in its
own uPlot root. While the pointer is over that plot, uPlot's cursor index is
the single source of truth for the nearest saved observation. The tooltip
reads:

- the corresponding `axis[index].completed_at` timestamp; and
- `item.values[index]` for every series in that panel.

The synchronized vertical cursor continues to move across plots, but only the
plot actually under the pointer shows a tooltip. Event-rail cursor movement
does not open chart tooltips. Leaving the plot or losing a valid cursor index
hides the tooltip.

### Content

The tooltip has a fixed two-column value grid:

- left: series color and model name;
- right: the exact JSON-decoded API value;
- header: localized observation date and time;
- footer: the aspect unit and the meaning of the missing marker.

Use `String(value)` for finite numeric values so the readout reflects the API
number rather than a rounded axis tick. Do not apply fixed decimal rounding
that could collapse distinct values. A `null` or non-finite value is shown as
`—` and described as **no observation**. Long model names may ellipsize, but
the value column must remain visible.

### Positioning and presentation

Position the tooltip beside the cursor inside the plot. Flip it horizontally
and clamp it vertically near chart edges. Its width is capped for narrow
screens, and its two-column grid must never discard or clip the value column.
Use existing theme tokens, series colors, typography, borders, and shadows.
The tooltip is non-interactive (`pointer-events: none`) and carries
`role=tooltip`.

The chart's current point markers, drag-to-zoom, resize observer, legend hover
focus, and URL date-range writes remain unchanged.

## Failure and Edge Cases

- Empty, loading, failed, and no-match model searches remain visible in the
  overlay rather than falling back inside the clipped sidebar.
- Overlay geometry is recalculated after responsive layout changes and when a
  sticky sidebar moves during document scrolling.
- A timeline with no axis or no valid cursor index shows no tooltip.
- Missing values remain listed so comparisons do not silently omit models.
- One-model timelines use the same tooltip layout as multi-model timelines.
- At eight models, values remain right-aligned and visible; the tooltip body
  may grow vertically but stays within the plot/viewport constraints.
- Values at the first and last observations remain readable through edge-aware
  horizontal flipping.

## Testing and Validation

Follow test-driven development.

Automated coverage will verify:

- overlay content is mounted outside the sidebar clipping boundary;
- placement accounts for above/below space, horizontal clamping, and maximum
  height;
- opening, clearing, and selecting remove or retain the overlay as specified;
- tooltip rows are built from one axis index for every visible model;
- exact numeric strings and missing markers are rendered without axis-style
  rounding;
- tooltip lifecycle hooks coexist with cursor synchronization, zoom, resize,
  and plot cleanup;
- offline/CSP checks still reject external runtime dependencies;
- all existing browser and project tests continue to pass.

Because the repository intentionally has no browser-test dependency, complete
the automated source/contract coverage with a live local-browser validation at
both narrow and wide viewport sizes. Reproduce the previously clipped empty-pin
state, verify multiple search results remain visible, and hover first, middle,
and last chart observations to verify timestamp, all model rows, exact values,
missing markers, and edge placement.

Run the complete pytest suite before completion. The installed standalone
remains untouched until the change is merged to `main` and explicitly
deployed.
