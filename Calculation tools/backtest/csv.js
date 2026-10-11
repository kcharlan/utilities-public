'use strict';

/*
 * CSV serialization and download for Market Atlas.
 *
 * The four row-shaping functions and the serializer are pure data transforms.
 * Only the download itself needs browser APIs, so it lives behind a factory that
 * takes Blob, URL, and document as arguments rather than reaching for them.
 *
 * That split is deliberate: this block used to be tested by slicing it out of the
 * application source with comment markers and evaluating it in a VM sandbox with
 * a hand-built global environment. As a module with injected collaborators the
 * tests just require it and pass fakes.
 *
 * Dual-loadable: a plain <script> in the browser (exposing `MarketAtlasCsv`) and
 * require()-able from Node.
 */
(function (root, factory) {
  const stats = (typeof module !== 'undefined' && module.exports)
    ? require('./stats.js')
    : root.MarketAtlasStats;
  if (!stats) throw new Error('csv.js requires stats.js to be loaded first');
  const api = factory(stats);
  root.MarketAtlasCsv = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function (stats) {
  const { needProfile } = stats;

  function failureNote(row) {
    return row.settlement === 'yearEnd'
      ? 'Portfolio depleted after returns were applied'
      : 'Portfolio depleted before returns were applied';
  }

  function serializeCsv(rows) {
    if (!Array.isArray(rows)) throw new TypeError('CSV rows must be an array.');
    if (!rows.length) return '';
    if (!rows.every((row) => row && typeof row === 'object' && !Array.isArray(row))) {
      throw new TypeError('Each CSV row must be an object.');
    }
    const headers = Object.keys(rows[0]);
    if (!headers.length) return '';
    const encode = (value) => {
      if (value === null || value === undefined) return '';
      let text = typeof value === 'number' ? String(value)
        : typeof value === 'boolean' ? (value ? 'true' : 'false')
          : String(value);
      if (typeof value === 'string' && /^[\x00-\x20]*[=+\-@]/.test(text)) text = `'${text}`;
      return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
    };
    return [
      headers.map(encode).join(','),
      ...rows.map((row) => headers.map((header) => encode(row[header])).join(',')),
    ].join('\r\n');
  }

  function windowExportRows(rows, spending = null, needDollars = null) {
    const need = Number.isFinite(needDollars) && needDollars >= 0 ? needDollars : null;
    // Delivered and unfunded years share one builder: the serializer takes both
    // its header order and complete column set from the first row.
    const buildRow = (row, year) => ({
      year,
      stock_return_nominal: row?.returnRates.stock ?? null,
      bond_return_nominal: row?.returnRates.bond ?? null,
      bill_return_nominal: row?.returnRates.bill ?? null,
      withdrawal_nominal: row ? row.withdrawalNominal : 0,
      withdrawal_real: row ? row.withdrawalReal : 0,
      gross_withdrawal_nominal: row?.grossWithdrawal ?? null,
      tax_nominal: row?.taxPaid ?? null,
      stock_balance_nominal: row?.endBalances.stock ?? null,
      bond_balance_nominal: row?.endBalances.bond ?? null,
      bill_balance_nominal: row?.endBalances.bill ?? null,
      total_balance_nominal: row?.endTotal ?? null,
      total_balance_real: row?.endTotalReal ?? null,
      notes: row
        ? [row.failed ? failureNote(row) : '', row.notes || ''].filter(Boolean).join(' · ')
        : 'unfunded',
      status: row ? (row.failed ? 'failed' : 'completed') : 'unfunded',
      quality: row?.quality || '',
      withdrawal_real_pct_of_year1: spending?.baseline > 0 ? (row ? row.withdrawalReal : 0) / spending.baseline : null,
      need_real: need,
    });
    const exported = rows.map(row => buildRow(row, row.year));
    if (spending?.failed) {
      for (let index = rows.length; index < spending.path.length; index++) {
        exported.push(buildRow(null, spending.startYear + index));
      }
    }
    return exported;
  }

  function sweepCurveExportRows(series, needDollars = null) {
    const need = Number.isFinite(needDollars) && needDollars >= 0 ? needDollars : null;
    return series.flatMap((item) => item.results.map((result) => {
      const metrics = result.metrics || {};
      const partial = Boolean(result.partial || metrics.partial);
      const spending = metrics.spending;
      const needMetrics = spending ? needProfile(spending, need) : null;
      return {
        configuration_label: item.label,
        configuration_id: item.configuration.id,
        strategy_id: item.configuration.strategyId,
        start_year: result.startYear,
        status: partial ? 'partial' : metrics.success ? 'survived' : 'failed',
        partial,
        success: partial ? null : metrics.success === true,
        failure_year: Number.isSafeInteger(metrics.failureYear) ? metrics.failureYear : null,
        years_complete: metrics.yearsCompleted,
        horizon: metrics.horizon,
        terminal_wealth_real: metrics.terminalWealthReal,
        spending_volatility: Number.isFinite(metrics.spendingVolatility) ? metrics.spendingVolatility : null,
        max_safe_rate: Number.isFinite(result.maxSafeRate) ? result.maxSafeRate : null,
        year1_spending_real: spending?.baseline ?? null,
        spending_floor_real: spending?.floor ?? null,
        spending_floor_pct_of_year1: spending?.floorRatio ?? null,
        funded_floor_real: spending?.fundedFloor ?? null,
        last_partial_real: spending?.lastPartial ?? null,
        spending_ceiling_real: spending?.ceiling ?? null,
        spending_median_real: spending?.median ?? null,
        deepest_cut: spending?.deepestCut ?? null,
        need_real: need,
        years_below_need: needMetrics?.yearsBelow ?? null,
        longest_run_below_need: needMetrics?.longestBelowRun ?? null,
        shortfall_years: needMetrics?.shortfallYears ?? null,
      };
    }));
  }

  function heatmapExportRows(model) {
    return model.cells.map((cell) => ({
      start_year: cell.startYear,
      horizon: cell.horizon,
      metric: model.metric,
      status: cell.kind === 'no-rate' ? 'no_rate' : cell.kind,
      partial: Boolean(cell.partial || cell.kind === 'partial'),
      value: cell.kind === 'no-rate' || cell.kind === 'partial' ? null : cell.value,
    }));
  }

  /* The download side, isolated behind its dependencies. `Blob`, `URL`, and
     `document` arrive as arguments so this stays testable without a DOM and
     without a sandbox. */
  function createCsvDownloader(deps) {
    for (const name of ['Blob', 'URL', 'document']) {
      if (deps == null || deps[name] === undefined) {
        throw new TypeError(`createCsvDownloader requires ${name}`);
      }
    }
    const { Blob, URL, document } = deps;

    function exportCsv(rows, filename) {
      const blob = new Blob([serializeCsv(rows)], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      try {
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = filename;
        anchor.click();
      } finally {
        URL.revokeObjectURL(url);
      }
    }

    return exportCsv;
  }

  return Object.freeze({
    serializeCsv,
    failureNote,
    windowExportRows,
    sweepCurveExportRows,
    heatmapExportRows,
    createCsvDownloader,
  });
}));
