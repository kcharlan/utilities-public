'use strict';

/*
 * Shared number formatting for Market Atlas.
 *
 * Every user-visible number in the app resolves through this module. It exists
 * because the sweep view previously carried its own hand-rolled money and
 * percent formatters — written that way only because the sweep-helper region was
 * evaluated in a sandbox without `Intl` — and they had drifted from the main
 * formatters. The same quantity rendered as "$1.2M" in the summary stat and
 * "$1.2m" in the heatmap legend beside it, and 1200 rendered as "$1.2K" or "$1k"
 * depending on which view you were looking at.
 *
 * Dual-loadable: a plain <script> in the browser (exposing `MarketAtlasFormat`)
 * and require()-able from Node. No DOM, no dependencies, no state.
 */
(function (root, factory) {
  const api = factory();
  /* Only the namespace is published. Spreading every export onto globalThis
     would make each new export a global, where a collision would silently shadow
     rather than fail; consumers destructure from the namespace instead. */
  root.MarketAtlasFormat = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const EM_DASH = '—';

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, (character) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
    })[character]);
  }

  function money(value, digits = 0) {
    if (!Number.isFinite(value)) return EM_DASH;
    return new Intl.NumberFormat('en-US', {
      style: 'currency', currency: 'USD', minimumFractionDigits: digits, maximumFractionDigits: digits,
    }).format(value);
  }

  function percent(value, digits = 1) {
    if (!Number.isFinite(value)) return EM_DASH;
    return new Intl.NumberFormat('en-US', {
      style: 'percent', minimumFractionDigits: digits, maximumFractionDigits: digits,
    }).format(value);
  }

  /* The single compact money format. Chosen over the sweep view's former
     lowercase variant because Intl handles locale and rounding consistently. */
  function moneyCompact(value) {
    if (!Number.isFinite(value)) return EM_DASH;
    return new Intl.NumberFormat('en-US', {
      style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1,
    }).format(value);
  }

  /* Percent with trailing zeros trimmed — "4%" rather than "4.00%". Used for
     configuration labels where a fixed decimal count is noise. */
  function percentConcise(value, digits = 2) {
    if (!Number.isFinite(value)) return EM_DASH;
    return `${Number((value * 100).toFixed(digits))}%`;
  }

  function count(value, digits = 0) {
    if (!Number.isFinite(value)) return EM_DASH;
    return new Intl.NumberFormat('en-US', { maximumFractionDigits: digits }).format(value);
  }

  return Object.freeze({
    escapeHtml,
    fmtMoney: money,
    fmtPct: percent,
    fmtMoneyCompact: moneyCompact,
    fmtPctConcise: percentConcise,
    fmtCount: count,
  });
}));
