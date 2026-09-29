# Drawdown UI lessons learned

- **Script extraction is position-sensitive.** `tests/helpers/load_drawdown.js` and `tests/drawdown_dates.test.js` each extract the first bare `<script>`. Keep the application as the single classic inline script; a new earlier bare script would feed the loaders the wrong code.
- **`init()` has a sentinel ordering constraint.** `tests/drawdown_dates.test.js` expects the date stamp lookup first and its sentinel failure from the existing input listener loop. Put new DOM wiring after that loop.
- **SVG color sources have different precedence.** CSS rules override SVG presentation attributes such as `stroke`, but not an inline `style` declaration. Keep theme-controlled colors in CSS.
- **`light-dark()` resolves where a custom property is used.** Set `color-scheme` on the root for Auto and explicit theme overrides; token values then resolve in the consuming element's scheme. Force light for print.
- **Filtered banding changes selector specificity.** The `of S` argument in `:nth-child(of S)` contributes `S`'s specificity. Wrap the banding selector in `:where()` so pinned and failure row states can win.
- **Sticky ledger cells need full backgrounds.** Use opaque layered backgrounds and `border-collapse: separate` to prevent scrolled content and collapsed borders from showing through sticky cells.
- **A full-width editor can live inside the table scroller.** `100cqw` sizes the editor to the scroll container while a sticky row keeps it visible during horizontal scrolling.
- **Replacing rows removes keyboard focus.** Before a rerender, set one-shot `pendingFocus` for the editor opener or a stable fallback; restore it after the new DOM is in place.
- **Markup is part of the test contract.** `tests/drawdown_sales.test.js` asserts exact tax-label/input markup, the `inputs` array, the Gross sold header, the table scroll wrapper, the stats count, and pin field attributes. `tests/drawdown_dates.test.js` asserts the date stamp. `tests/drawdown.browser.spec.js` exercises the pin field chain, chart series paths, and editor, status, and table selectors. Inspect those locations before changing markup.
