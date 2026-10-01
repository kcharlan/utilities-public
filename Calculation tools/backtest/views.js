'use strict';

/*
 * Pure view logic for Market Atlas — the model-building half of the two views,
 * with no DOM access and no application state.
 *
 * These three blocks previously lived inside index.html and were tested by
 * slicing them out of the HTML with string markers and evaluating them in a VM
 * sandbox. That worked, but it coupled the tests to comment placement, required
 * a hand-maintained export list inside each test, and meant the sandbox had to
 * whitelist every global the code touched. As real modules they are simply
 * require()-able.
 *
 * Depends on format.js for formatting and stats.js for shared statistics.
 *
 * Dual-loadable: a plain <script> in the browser (exposing `MarketAtlasViews`
 * and each helper as a global, matching how index.html used to see them) and
 * require()-able from Node.
 */
(function (root, factory) {
  const format = (typeof module !== 'undefined' && module.exports)
    ? require('./format.js')
    : root.MarketAtlasFormat;
  if (!format) throw new Error('views.js requires format.js to be loaded first');
  const stats = (typeof module !== 'undefined' && module.exports)
    ? require('./stats.js')
    : root.MarketAtlasStats;
  if (!stats) throw new Error('views.js requires stats.js to be loaded first');
  const api = factory(format, stats);
  /* Only the namespace is published. Spreading every export onto globalThis
     would make each new export a global, where a collision would silently shadow
     rather than fail; consumers destructure from the namespace instead. */
  root.MarketAtlasViews = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function (format, stats) {
  const { median, quantile, extremeBy, comparisonTolerance, needProfile } = stats;
  const { fmtMoney, fmtMoneyCompact, fmtPct, fmtPctConcise, fmtCount } = format;

  /* ===== Render coordination — latest request wins, predecessors abort ===== */
  function createRenderCoordinator(resetTransient = null) {
    if (resetTransient !== null && typeof resetTransient !== 'function') {
      throw new TypeError('Transient reset must be a function or null.');
    }
    let generation = 0;
    let current = null;
    function isCurrent(request) {
      return Boolean(
        request
        && current
        && request.requestId === current.requestId
        && request.signal === current.controller.signal
        && !request.signal.aborted,
      );
    }
    function commitTransient(request, commit) {
      if (typeof commit !== 'function') throw new TypeError('Transient commit must be a function.');
      if (!isCurrent(request)) return false;
      commit();
      return true;
    }
    function clearTransient(request) {
      if (!isCurrent(request) || !resetTransient) return false;
      resetTransient();
      return true;
    }
    return Object.freeze({
      begin() {
        if (current) current.controller.abort();
        const controller = new AbortController();
        current = { requestId: generation += 1, controller };
        const request = Object.freeze({ requestId: current.requestId, signal: controller.signal });
        clearTransient(request);
        return request;
      },
      cancelCurrent() {
        if (!current) return false;
        current.controller.abort();
        current = null;
        if (resetTransient) resetTransient();
        return true;
      },
      isCurrent,
      commitTransient,
      clearTransient,
    });
  }

  async function executeRendererRequest(coordinator, request, renderer, snapshot) {
    try {
      const product = await renderer(
        snapshot,
        Object.freeze({
          requestId: request.requestId,
          signal: request.signal,
          reportProgress: (commit) => coordinator.commitTransient(request, commit),
        }),
      );
      if (!coordinator.isCurrent(request)) return { stale: true };
      const commit = typeof product === 'function'
        ? product
        : product && typeof product.commit === 'function' ? () => product.commit() : null;
      if (!commit) throw new TypeError('Renderer must return a commit callback or an object with commit().');
      if (!coordinator.isCurrent(request)) return { stale: true };
      commit();
      return { committed: true, errorMessage: commit.errorMessage || null };
    } catch (error) {
      if (!coordinator.isCurrent(request)) return { stale: true };
      coordinator.clearTransient(request);
      throw error;
    }
  }

  function createLatestWinsScheduler(coordinator, run, scheduleFrame) {
    let framePending = false;
    let latestRequest = null;
    return function schedule() {
      latestRequest = coordinator.begin();
      if (!framePending) {
        framePending = true;
        scheduleFrame(async () => {
          framePending = false;
          const request = latestRequest;
          await run(request);
        });
      }
      return latestRequest;
    };
  }

  /* ===== Window view — selection, quality seam, per-year models ===== */
  function selectWindowRows(rows, startYear, horizon, lastYear) {
    if (!Array.isArray(rows) || !Number.isSafeInteger(startYear) || !Number.isInteger(horizon) || horizon < 1) return [];
    const byYear = new Map(rows.map((row) => [row.year, row]));
    const selected = [];
    const finalYear = Math.min(Number.isSafeInteger(lastYear) ? lastYear : Infinity, startYear + horizon - 1);
    for (let year = startYear; year <= finalYear; year += 1) {
      if (!byYear.has(year)) break;
      selected.push(byYear.get(year));
    }
    return selected;
  }

  function findQualitySeam(rows) {
    for (let index = 1; index < rows.length; index += 1) {
      if (rows[index - 1].quality === 'reconstructed' && rows[index].quality !== 'reconstructed') {
        return { index, year: rows[index].year };
      }
    }
    return null;
  }

  function classifyWindowOutcome(metrics) {
    if (!metrics || metrics.success === false) {
      return {
        kind: 'failed',
        label: `Failed${Number.isSafeInteger(metrics && metrics.failureYear) ? ` · ${metrics.failureYear}` : ''}`,
        detail: 'portfolio depleted during withdrawal',
      };
    }
    if (metrics.partial) {
      return {
        kind: 'partial',
        label: `Solvent through ${metrics.yearsCompleted} of ${metrics.horizon}`,
        detail: 'recent window · outcome incomplete',
      };
    }
    return { kind: 'survived', label: 'Survived', detail: `complete ${metrics.horizon}-year passage` };
  }

  function displayBalance(value, row, display) {
    if (!Number.isFinite(value)) return NaN;
    if (display !== 'real') return value;
    if (value === 0) return 0;
    return Number.isFinite(row.endCpiIndex) && row.endCpiIndex > 0 ? value / row.endCpiIndex : NaN;
  }

  function chartSeries(rows, display) {
    if (!rows.length) return [];
    const first = rows[0];
    const startDivisor = display === 'real' ? first.cpiIndex : 1;
    const points = [{
      stock: first.startBalances.stock / startDivisor,
      bond: first.startBalances.bond / startDivisor,
      bill: first.startBalances.bill / startDivisor,
    }];
    for (const row of rows) {
      points.push({
        stock: displayBalance(row.endBalances.stock, row, display),
        bond: displayBalance(row.endBalances.bond, row, display),
        bill: displayBalance(row.endBalances.bill, row, display),
      });
    }
    return points;
  }

  function windowStatsModel(metrics, _display) {
    const outcome = classifyWindowOutcome(metrics);
    return [
      { label: 'Outcome', rawValue: outcome.label, detail: outcome.detail, format: 'text', className: outcome.kind === 'failed' ? 'warning' : outcome.kind === 'survived' ? 'success' : '' },
      { label: 'Terminal wealth · real', rawValue: metrics.terminalWealthReal, detail: 'purchasing-power dollars', format: 'money' },
      { label: 'Max real drawdown', rawValue: metrics.maxDrawdownReal, detail: 'real peak to trough', format: 'percent' },
    ];
  }

  function normalizeNotes(notes) {
    const entries = Array.isArray(notes) ? notes : notes === undefined || notes === null ? [] : [notes];
    return entries.filter((entry) => typeof entry === 'string' && entry.trim()).map((entry) => entry.trim());
  }

  function clampWindowSelection(startYear, horizon, range) {
    const first = Number.isSafeInteger(range && range.first) ? range.first : 0;
    const last = Number.isSafeInteger(range && range.last) ? range.last : first;
    const requestedYear = Number.isFinite(Number(startYear)) ? Math.trunc(Number(startYear)) : last;
    const requestedHorizon = Number.isFinite(Number(horizon)) ? Math.trunc(Number(horizon)) : 30;
    return {
      startYear: Math.min(last, Math.max(first, requestedYear)),
      horizon: Math.min(100, Math.max(1, requestedHorizon)),
    };
  }

  /* ===== Sweep view — summaries, safe-rate points, heatmap models and palettes ===== */
  function cohortStartYear(rows, cohort) {
    const ordered = Array.isArray(rows)
      ? rows.filter((row) => row && Number.isSafeInteger(row.year)).slice().sort((left, right) => left.year - right.year)
      : [];
    if (!ordered.length) return null;
    if (cohort !== 'modern') return ordered[0].year;
    for (let index = 0; index < ordered.length; index += 1) {
      if (ordered[index].quality !== 'reconstructed'
          && (index === 0 || ordered[index - 1].quality === 'reconstructed')) return ordered[index].year;
    }
    return ordered[0].year;
  }

  function intersectYearRanges(ranges) {
    if (!Array.isArray(ranges) || !ranges.length) return { first: null, last: null };
    if (!ranges.every((range) => range
      && Number.isSafeInteger(range.first)
      && Number.isSafeInteger(range.last)
      && range.first <= range.last)) return { first: null, last: null };
    const first = Math.max(...ranges.map((range) => range.first));
    const last = Math.min(...ranges.map((range) => range.last));
    return Number.isSafeInteger(first) && Number.isSafeInteger(last) && first <= last
      ? { first, last }
      : { first: null, last: null };
  }

  function summarizeSweep(results, supportsMaxSafeRate, needDollars = null) {
    const entries = Array.isArray(results) ? results : [];
    const partialCount = entries.filter((entry) => entry && (entry.partial || (entry.metrics && entry.metrics.partial))).length;
    const complete = entries.filter((entry) => entry && entry.metrics && !entry.partial && !entry.metrics.partial);
    const survivedCount = complete.filter((entry) => entry.metrics.success === true).length;
    const ranked = complete.slice().sort((left, right) => {
      if (supportsMaxSafeRate) {
        const leftRate = left.maxSafeRate === null ? -Infinity : Number.isFinite(left.maxSafeRate) ? left.maxSafeRate : Infinity;
        const rightRate = right.maxSafeRate === null ? -Infinity : Number.isFinite(right.maxSafeRate) ? right.maxSafeRate : Infinity;
        if (leftRate !== rightRate) return leftRate - rightRate;
      }
      const wealthDifference = left.metrics.terminalWealthReal - right.metrics.terminalWealthReal;
      return wealthDifference || left.startYear - right.startYear;
    });
    const worst = ranked[0] || null;
    const volatility = complete.map((entry) => entry.metrics.spendingVolatility).filter(Number.isFinite);
    const completeSafeRates = supportsMaxSafeRate ? complete.map((entry) => entry.maxSafeRate) : [];
    const noSurvivingRateCount = completeSafeRates.filter((rate) => rate === null).length;
    const finiteSafeRates = completeSafeRates.filter(Number.isFinite);
    return {
      completeCount: complete.length,
      survivedCount,
      survivedRate: complete.length ? survivedCount / complete.length : null,
      partialCount,
      worstStartYear: worst ? worst.startYear : null,
      worstFailureYear: worst && Number.isSafeInteger(worst.metrics.failureYear) ? worst.metrics.failureYear : null,
      medianTerminalWealthReal: median(complete.map((entry) => entry.metrics.terminalWealthReal)),
      worstTerminalWealthReal: complete.length ? Math.min(...complete.map((entry) => entry.metrics.terminalWealthReal)) : null,
      spendingVolatilityMin: extremeBy(volatility, value => value, 'min')?.value ?? null,
      spendingVolatilityMax: extremeBy(volatility, value => value, 'max')?.value ?? null,
      spendingVolatilityUndefinedCount: complete.length - volatility.length,
      minimumSafeRate: supportsMaxSafeRate && noSurvivingRateCount === 0 && finiteSafeRates.length
        ? Math.min(...finiteSafeRates)
        : null,
      noSurvivingRateCount,
      lifestyle: summarizeLifestyle(complete, needDollars),
    };
  }

  function summarizeLifestyle(complete, needDollars) {
    const fields = ['failedCount', 'worstFloor', 'worstFloorStartYear', 'worstFloorRatio',
      'worstSurvivingFloor', 'worstSurvivingStartYear', 'worstSurvivingRatio', 'survivorsUniform',
      'medianFloor', 'medianFloorRatio', 'p10Floor', 'p10FloorRatio', 'medianTypicalSpending',
      'deepestCut', 'deepestCutStartYear', 'longestBelowNeedRun', 'longestBelowNeedStartYear',
      'worstShortfallYears', 'worstShortfallStartYear', 'baseline', 'baselineUniform'];
    if (!complete.length) return { completeCount: 0, ...Object.fromEntries(fields.map(key => [key, null])) };
    if (complete.some(entry => !entry.metrics.spending)) return null;
    const ordered = complete.slice().sort((a, b) => a.startYear - b.startYear);
    const enriched = ordered.map(entry => ({ ...entry, spending: entry.metrics.spending,
      need: needProfile(entry.metrics.spending, needDollars) }));
    const survivors = enriched.filter(entry => entry.metrics.success === true);
    const floor = extremeBy(enriched, entry => entry.spending.floor, 'min');
    const survivingFloor = extremeBy(survivors, entry => entry.spending.floor, 'min');
    const minRatio = extremeBy(survivors, entry => entry.spending.floorRatio, 'min');
    const maxRatio = extremeBy(survivors, entry => entry.spending.floorRatio, 'max');
    const cut = extremeBy(enriched, entry => entry.spending.deepestCut, 'max');
    const run = extremeBy(enriched, entry => entry.need?.longestBelowRun, 'max');
    const shortfall = extremeBy(enriched, entry => entry.need?.shortfallYears, 'max');
    const hasShortfall = enriched.some(entry => entry.need?.shortfallYears > 0);
    const baseline = enriched[0].spending.baseline;
    return {
      completeCount: enriched.length,
      failedCount: enriched.length - survivors.length,
      worstFloor: floor?.value ?? null,
      worstFloorStartYear: floor?.item.startYear ?? null,
      worstFloorRatio: floor?.item.spending.floorRatio ?? null,
      worstSurvivingFloor: survivingFloor?.value ?? null,
      worstSurvivingStartYear: survivingFloor?.item.startYear ?? null,
      worstSurvivingRatio: survivingFloor?.item.spending.floorRatio ?? null,
      survivorsUniform: minRatio && maxRatio
        ? maxRatio.value - minRatio.value <= comparisonTolerance(minRatio.value, maxRatio.value) : null,
      medianFloor: median(enriched.map(entry => entry.spending.floor)),
      medianFloorRatio: median(enriched.map(entry => entry.spending.floorRatio)),
      p10Floor: quantile(enriched.map(entry => entry.spending.floor), .1),
      p10FloorRatio: quantile(enriched.map(entry => entry.spending.floorRatio), .1),
      medianTypicalSpending: median(enriched.map(entry => entry.spending.median)),
      deepestCut: cut?.value ?? null,
      deepestCutStartYear: cut?.item.startYear ?? null,
      longestBelowNeedRun: run?.value ?? null,
      longestBelowNeedStartYear: run?.item.startYear ?? null,
      worstShortfallYears: hasShortfall ? shortfall.value : null,
      worstShortfallStartYear: hasShortfall ? shortfall.item.startYear : null,
      baseline,
      baselineUniform: enriched.every(entry => Number.isFinite(baseline)
        && Number.isFinite(entry.spending.baseline)
        && Math.abs(entry.spending.baseline - baseline) <= comparisonTolerance(entry.spending.baseline, baseline)),
    };
  }

  function stableStringify(value) {
    if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`;
    if (value && typeof value === 'object') {
      return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(',')}}`;
    }
    return JSON.stringify(value);
  }

  function sweepConfigurationKey(configuration, horizon, startYear, marketGeneration) {
    return stableStringify({
      strategyId: configuration.strategyId,
      params: configuration.params,
      options: configuration.options,
      horizon,
      startYear,
      marketGeneration,
    });
  }

  function sweepYDomain(series, usesSafeRate) {
    const dataValues = series.flatMap((item) => item.results.map((result) => (
      usesSafeRate ? result.maxSafeRate : result.metrics.terminalWealthReal
    ))).filter(Number.isFinite);
    const referenceValues = usesSafeRate
      ? series.map((item) => {
        const key = item.strategy && item.strategy.rateParamKey;
        return key ? item.configuration.params[key] : null;
      }).filter(Number.isFinite)
      : [];
    return {
      minimum: 0,
      maximum: usesSafeRate
        ? Math.max(0.01, ...dataValues, ...referenceValues)
        : Math.max(1, ...dataValues),
    };
  }

  function sweepChartUsesSafeRate(series) {
    return Array.isArray(series)
      && series.length > 0
      && series.every((item) => item && item.strategy && item.strategy.supportsMaxSafeRate === true);
  }

  function contiguousSweepLineSegments(results, valueForResult) {
    const segments = [];
    let current = [];
    let previousYear = null;
    for (const result of Array.isArray(results) ? results : []) {
      const year = result && result.startYear;
      const value = typeof valueForResult === 'function' ? valueForResult(result) : null;
      const followsPrevious = current.length === 0 || (Number.isSafeInteger(year)
        && Number.isSafeInteger(previousYear) && year === previousYear + 1);
      if (!Number.isSafeInteger(year) || !Number.isFinite(value) || !followsPrevious) {
        if (current.length) segments.push(current);
        current = [];
      }
      if (Number.isSafeInteger(year) && Number.isFinite(value)) current.push({ result, value });
      previousYear = Number.isSafeInteger(year) ? year : null;
    }
    if (current.length) segments.push(current);
    return segments;
  }

  function safeRatePointModel(result) {
    if (result && (result.partial || (result.metrics && result.metrics.partial))) {
      return { plotValue: null, kind: 'partial', label: 'incomplete window' };
    }
    if (result && result.maxSafeRate === null) {
      return { plotValue: 0, kind: 'no-rate', label: 'no rate survives' };
    }
    return {
      plotValue: result && Number.isFinite(result.maxSafeRate) ? result.maxSafeRate : null,
      kind: 'rate',
      label: result && Number.isFinite(result.maxSafeRate) ? 'sustainable rate' : 'rate unavailable',
    };
  }

  function configurationLabelModel(configuration, strategy, humanLabels = {}) {
    const title = strategy && strategy.name ? strategy.name : configuration.strategyId;
    const details = [];
    for (const field of (strategy && strategy.paramSchema) || []) {
      const rawValue = configuration.params[field.key] === undefined ? field.default : configuration.params[field.key];
      let value;
      if (field.type === 'percent') value = fmtPctConcise(rawValue);
      else if (field.type === 'select' || field.type === 'enum') value = humanLabels[rawValue] || String(rawValue).replace(/_/g, ' ');
      else value = Number.isFinite(rawValue) ? String(Number(rawValue.toPrecision(12))) : String(rawValue);
      details.push(`${field.label || field.key}: ${value}`);
    }
    const allocation = configuration.options.allocation;
    const allocationLabel = `${Number((allocation.stock * 100).toFixed(2))}/${Number((allocation.bond * 100).toFixed(2))}/${Number((allocation.bill * 100).toFixed(2))}`;
    details.push(`Starting balance: ${fmtMoney(configuration.options.startingBalance)}`);
    details.push(`${strategy && typeof strategy.initialAllocation === 'function' ? 'Managed opening mix' : 'Allocation'}: ${allocationLabel}`);
    details.push(`Fee: ${fmtPctConcise(configuration.options.feeRate)}`);
    details.push(`Tax: ${fmtPctConcise(configuration.options.taxRate)}`);
    return { title, details: details.join(' · ') };
  }

  function createLruCache(limit) {
    if (!Number.isSafeInteger(limit) || limit < 1) throw new RangeError('LRU cache limit must be a positive safe integer.');
    const entries = new Map();
    return Object.freeze({
      has(key) { return entries.has(key); },
      get(key) {
        if (!entries.has(key)) return undefined;
        const value = entries.get(key);
        entries.delete(key);
        entries.set(key, value);
        return value;
      },
      set(key, value) {
        if (entries.has(key)) entries.delete(key);
        entries.set(key, value);
        while (entries.size > limit) entries.delete(entries.keys().next().value);
        return this;
      },
      get size() { return entries.size; },
    });
  }

  function marketGeneration(rows, generatedStamp) {
    const boundary = (row) => row ? {
      year: row.year,
      quality: row.quality,
      keys: Object.keys(row).sort(),
    } : null;
    return stableStringify({
      generatedStamp: generatedStamp || 'undated',
      count: rows.length,
      first: boundary(rows[0]),
      last: boundary(rows[rows.length - 1]),
    });
  }

  const HEATMAP_HORIZONS = Object.freeze(Array.from({ length: 12 }, (_, index) => (index + 1) * 5));
  /* Heatmap colours stay as literal hex rather than CSS tokens because they are
     numerically interpolated (mixHexColor) and contrast-tested (heatmapForeground).
     Both themes live here as pure data so this region remains DOM-free for the
     sandboxed helper tests; the render layer selects one via heatmapPalette(). */
  const HEATMAP_PALETTES = Object.freeze({
    light: Object.freeze({
      quantitative: Object.freeze({ minimum: '#aa573e', midpoint: '#b8862a', maximum: '#2c585a' }),
      categorical: Object.freeze({ survived: '#386b55', failed: '#943c32', partial: '#d8d0c1', noRate: '#1a1814' }),
      foreground: Object.freeze({ ink: '#000000', paper: '#ffffff' }),
    }),
    dark: Object.freeze({
      quantitative: Object.freeze({ minimum: '#d98570', midpoint: '#e8bd66', maximum: '#79aec4' }),
      categorical: Object.freeze({ survived: '#7fb79c', failed: '#e58f7c', partial: '#4a4238', noRate: '#ede5d6' }),
      foreground: Object.freeze({ ink: '#14120e', paper: '#f4ecdd' }),
    }),
  });

  /* Required, not defaulted: a forgotten argument used to fall back to the light
     palette, which renders light cells inside a dark page -- a silent visual bug.
     Failing loudly turns that into a caught mistake. */
  function requirePalette(palette, caller) {
    if (!palette || !palette.quantitative || !palette.categorical || !palette.foreground) {
      throw new TypeError(`${caller} requires a theme palette`);
    }
    return palette;
  }

  function heatmapPalette(theme) {
    return theme === 'dark' ? HEATMAP_PALETTES.dark : HEATMAP_PALETTES.light;
  }

  function mixHexColor(left, right, fraction) {
    const clamped = Math.max(0, Math.min(1, Number.isFinite(fraction) ? fraction : 0));
    const channel = (hex, offset) => Number.parseInt(hex.slice(offset, offset + 2), 16);
    const mixed = [1, 3, 5].map((offset) => Math.round(channel(left, offset) + (channel(right, offset) - channel(left, offset)) * clamped));
    return `#${mixed.map((value) => value.toString(16).padStart(2, '0')).join('')}`;
  }

  function compositeHexColor(background, foreground, alpha) {
    return mixHexColor(background, foreground, alpha);
  }

  function heatmapQuantitativeColor(value, domain, palette) {
    requirePalette(palette, 'heatmapQuantitativeColor');
    const span = domain.maximum - domain.minimum;
    const fraction = span > 0 ? Math.max(0, Math.min(1, (value - domain.minimum) / span)) : 0.5;
    return fraction <= 0.5
      ? mixHexColor(palette.quantitative.minimum, palette.quantitative.midpoint, fraction * 2)
      : mixHexColor(palette.quantitative.midpoint, palette.quantitative.maximum, (fraction - 0.5) * 2);
  }

  function relativeLuminance(hex) {
    const channels = [1, 3, 5].map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16) / 255)
      .map((channel) => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);
    return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  }

  function contrastRatio(left, right) {
    const [light, dark] = [relativeLuminance(left), relativeLuminance(right)].sort((a, b) => b - a);
    return (light + 0.05) / (dark + 0.05);
  }

  function heatmapForeground(background, palette) {
    requirePalette(palette, 'heatmapForeground');
    const { ink, paper } = palette.foreground;
    return contrastRatio(background, ink) >= contrastRatio(background, paper) ? ink : paper;
  }

  function heatmapCellTarget(target) {
    if (!target) return null;
    if (typeof target.matches === 'function' && target.matches('[data-heatmap-cell]')) return target;
    return typeof target.closest === 'function' ? target.closest('[data-heatmap-cell]') : null;
  }

  function setHeatmapRovingCell(table, cell) {
    const current = table && table.querySelector('[data-heatmap-cell][tabindex="0"]');
    if (current && current !== cell) current.tabIndex = -1;
    if (cell) cell.tabIndex = 0;
  }

  function moveHeatmapFocus(table, current, key) {
    const deltas = { ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [-1, 0], ArrowDown: [1, 0] };
    if (!table || !current || !deltas[key]) return false;
    const row = Number(current.dataset.heatmapRow) + deltas[key][0];
    const column = Number(current.dataset.heatmapColumn) + deltas[key][1];
    if (row < 0 || column < 0) return false;
    const next = table.querySelector(`[data-heatmap-row="${row}"][data-heatmap-column="${column}"]`);
    if (!next || next === current) return false;
    current.tabIndex = -1;
    setHeatmapRovingCell(table, next);
    next.focus();
    return true;
  }

  function heatmapSafeRateJobs(cells, cache) {
    const jobs = [];
    for (const cell of Array.isArray(cells) ? cells : []) {
      if (cell.partial || (cell.metrics && cell.metrics.partial)) continue;
      if (cache && cache.has(cell.key)) cell.maxSafeRate = cache.get(cell.key);
      else jobs.push(cell);
    }
    return jobs;
  }

  function heatmapMetricValue(cell, metric, needDollars = null) {
    if (metric === 'floor') return cell.metrics?.spending?.floorRatio ?? null;
    if (metric === 'belowNeed') return cell.metrics?.spending ? needProfile(cell.metrics.spending, needDollars)?.fractionBelow ?? null : null;
    if (metric === 'wealth') return cell.metrics && cell.metrics.terminalWealthReal;
    if (metric === 'safe') return cell.maxSafeRate;
    return cell.metrics && cell.metrics.success;
  }

  function heatmapModel(grid, metric, seamYear, palette, needDollars = null) {
    requirePalette(palette, 'heatmapModel');
    const entries = Array.isArray(grid) ? grid : [];
    const startYears = [...new Set(entries.map((cell) => cell.startYear).filter(Number.isSafeInteger))].sort((a, b) => a - b);
    const horizons = [...new Set(entries.map((cell) => cell.horizon).filter(Number.isSafeInteger))].sort((a, b) => a - b);
    const fixedLifestyleScale = metric === 'floor' || metric === 'belowNeed';
    const numeric = fixedLifestyleScale ? [] : entries.filter((cell) => !(cell.partial || (cell.metrics && cell.metrics.partial)))
      .map((cell) => heatmapMetricValue(cell, metric, needDollars)).filter(Number.isFinite);
    const minimum = metric === 'safe' ? 0 : numeric.length ? Math.min(...numeric) : 0;
    const maximum = numeric.length ? Math.max(...numeric) : metric === 'safe' ? 0.01 : 1;
    const domain = fixedLifestyleScale
      ? { minimum: 0, midpoint: .5, maximum: 1 }
      : { minimum, midpoint: minimum + (maximum - minimum) / 2, maximum };
    const cells = entries.map((cell) => {
      const partial = Boolean(cell.partial || (cell.metrics && cell.metrics.partial));
      const value = heatmapMetricValue(cell, metric, needDollars);
      let kind;
      let display;
      let color;
      if (partial) {
        kind = 'partial'; display = '◌'; color = palette.categorical.partial;
      } else if (metric === 'floor' && cell.metrics?.success === false) {
        kind = 'failed'; display = '×'; color = palette.categorical.failed;
      } else if ((metric === 'floor' || metric === 'belowNeed') && !Number.isFinite(value)) {
        kind = 'no-rate'; display = '—'; color = palette.categorical.noRate;
      } else if (metric === 'floor' || metric === 'belowNeed') {
        kind = metric; display = fmtPctConcise(value, 0);
        color = heatmapQuantitativeColor(metric === 'belowNeed' ? 1 - value : value, domain, palette);
      } else if (metric === 'success') {
        kind = cell.metrics && cell.metrics.success ? 'survived' : 'failed';
        display = kind === 'survived' ? '✓' : '×';
        color = palette.categorical[kind];
      } else if (metric === 'safe' && value === null) {
        kind = 'no-rate'; display = 'Ø'; color = palette.categorical.noRate;
      } else {
        kind = metric;
        display = metric === 'safe' ? fmtPctConcise(value, 1) : fmtMoneyCompact(value);
        color = heatmapQuantitativeColor(value, domain, palette);
      }
      const lifestyleStatus = metric === 'floor'
        ? kind === 'failed' ? `Failed in ${String(cell.metrics.failureYear)} · floor $0 · last partial ${fmtMoney(cell.metrics.spending?.lastPartial)}`
          : `floor ${fmtMoney(cell.metrics.spending?.floor)} real · ${display} of year 1`
        : metric === 'belowNeed' ? `${display} of years below need` : null;
      const status = partial
        ? 'Partial window, not classified as success or failure'
        : lifestyleStatus || (kind === 'survived' ? 'Survived'
          : kind === 'failed' ? `Failed${Number.isSafeInteger(cell.metrics.failureYear) ? ` in ${cell.metrics.failureYear}` : ''}`
            : kind === 'no-rate' ? 'No rate survives'
              : metric === 'safe' ? `Maximum safe rate ${display}` : `Real terminal wealth ${display}`);
      return { ...cell, kind, value, display, color, foreground: heatmapForeground(color, palette), label: `Start ${cell.startYear}, ${cell.horizon}-year horizon: ${status}` };
    });
    return {
      metric,
      startYears,
      horizons,
      seamYear: Number.isSafeInteger(seamYear) && startYears.includes(seamYear) ? seamYear : null,
      domain,
      cells,
      ...((metric === 'floor' || metric === 'belowNeed') ? {
        rowWorst: horizons.map(horizon => {
          const candidates = cells.filter(cell => cell.horizon === horizon && cell.kind !== 'partial')
            .slice().sort((a, b) => a.startYear - b.startYear);
          const hit = extremeBy(candidates, cell => cell.value, metric === 'floor' ? 'min' : 'max');
          return { horizon, value: hit?.value ?? null, startYear: hit?.item.startYear ?? null,
            display: hit ? fmtPctConcise(hit.value, 0) : '—' };
        }),
      } : {}),
    };
  }

  function heatmapLegendModel(metric, domain, approximate, palette) {
    requirePalette(palette, 'heatmapLegendModel');
    if (metric === 'floor' || metric === 'belowNeed') return {
      description: metric === 'floor' ? 'Spending floor · % of year 1 · × failed · ◌ partial'
        : 'Fraction of years below need · ◌ partial',
      ticks: [0, .5, 1].map(value => ({ value, label: fmtPctConcise(metric === 'belowNeed' ? 1 - value : value, 0) })),
      colors: Object.values(palette.quantitative),
    };
    if (metric === 'success') return {
      description: '✓ survived · × failed · ◌ partial (held out)',
      ticks: [],
    };
    const format = metric === 'safe' ? (value) => fmtPctConcise(value) : (value) => fmtMoneyCompact(value);
    return {
      description: metric === 'safe'
        ? `Ordered sustainable-rate scale${approximate ? ' · approximate at 0.1 percentage-point discovery resolution' : ' · exact binary search'} · Ø no rate survives · ◌ partial`
        : 'Ordered real terminal-wealth scale · ◌ partial',
      ticks: [domain.minimum, domain.midpoint, domain.maximum].map((value, index) => ({
        value,
        label: `${['Min', 'Mid', 'Max'][index]} ${format(value)}`,
      })),
      colors: Object.values(palette.quantitative),
    };
  }
  /* Only the endpoints are coloured. A partial survival rate is a historical
     frequency, not a risk grade, so tinting it would assert a judgement the
     data does not support -- and coding every rate green (the previous
     behaviour) made 0 of 69 read as success. */
  function survivalClassName(summary) {
    if (!Number.isFinite(summary.survivedRate) || summary.completeCount === 0) return '';
    if (summary.survivedCount === summary.completeCount) return 'success';
    if (summary.survivedCount === 0) return 'warning';
    return '';
  }

  /* In safe-rate mode partial windows have no plottable value and sit below the
     axis. In wealth mode they do have one -- wealth accumulated over fewer years
     -- so they plot in line with complete windows and invite a comparison that
     is not valid. They stay visible (ochre, smaller) but must say so. */
  const PARTIAL_WEALTH_CAVEAT = 'Ochre points are partial windows: wealth accumulated over fewer years than the horizon, not comparable with complete windows.';

  /* Applies a saved configuration snapshot back onto the sidebar controls, and
     opens the window a retained heatmap cell refers to.

     Every collaborator arrives through `deps` rather than being reached for as a
     global. That is what lets the tests construct it against fake controls and a
     fake state object, instead of scraping this block out of the source and
     evaluating it in a sandbox — which is how it used to be tested. */
  function createConfigurationApplier(deps) {
    const REQUIRED = [
      'getStrategies', 'state', 'byId', 'rememberVisibleParams', 'saveManualAllocation',
      'strategyManagesAllocation', 'renderSidebar', 'updateHeatmapMetricAvailability',
      'updateAllocationMode', 'updateYearRange', 'openWindow',
    ];
    for (const name of REQUIRED) {
      if (deps == null || deps[name] === undefined) {
        throw new TypeError(`createConfigurationApplier requires ${name}`);
      }
    }
    const {
      getStrategies, state, byId, rememberVisibleParams, saveManualAllocation,
      strategyManagesAllocation, renderSidebar, updateHeatmapMetricAvailability,
      updateAllocationMode, updateYearRange, openWindow,
    } = deps;

    function applyConfigurationToControls(configuration) {
      const targetStrategy = configuration && getStrategies()[configuration.strategyId];
      if (!configuration || !targetStrategy) return false;
      rememberVisibleParams();
      if (!state.allocationManaged) saveManualAllocation();
      const targetManaged = strategyManagesAllocation(targetStrategy);
      state.strategyId = configuration.strategyId;
      state.strategyParams[configuration.strategyId] = { ...configuration.params };
      byId('strategy-select').value = configuration.strategyId;
      renderSidebar();
      if (typeof updateHeatmapMetricAvailability === 'function') updateHeatmapMetricAvailability(targetStrategy);
      byId('starting-balance').value = String(configuration.options.startingBalance);
      byId('fee-rate').value = String(configuration.options.feeRate * 100);
      byId('tax-rate').value = String(configuration.options.taxRate * 100);
      if (!targetManaged) {
        for (const asset of ['stock', 'bond', 'bill']) {
          const value = String(Number((configuration.options.allocation[asset] * 100).toPrecision(12)));
          byId(`allocation-${asset}`).value = value;
          state.manualAllocationValues[asset] = value;
        }
      }
      updateAllocationMode();
      updateYearRange();
      return true;
    }

    function openRenderedHeatmapWindow(configuration, startYear, horizon) {
      if (!applyConfigurationToControls(configuration)) return null;
      return openWindow(startYear, horizon);
    }
    return Object.freeze({ applyConfigurationToControls, openRenderedHeatmapWindow });
  }

  return Object.freeze({
    createConfigurationApplier,
    HEATMAP_HORIZONS,
    HEATMAP_PALETTES,
    PARTIAL_WEALTH_CAVEAT,
    chartSeries,
    clampWindowSelection,
    classifyWindowOutcome,
    cohortStartYear,
    compositeHexColor,
    configurationLabelModel,
    contiguousSweepLineSegments,
    contrastRatio,
    createLatestWinsScheduler,
    createLruCache,
    createRenderCoordinator,
    displayBalance,
    executeRendererRequest,
    findQualitySeam,
    heatmapCellTarget,
    heatmapForeground,
    heatmapLegendModel,
    heatmapMetricValue,
    heatmapModel,
    heatmapPalette,
    heatmapQuantitativeColor,
    heatmapSafeRateJobs,
    intersectYearRanges,
    marketGeneration,
    mixHexColor,
    moveHeatmapFocus,
    normalizeNotes,
    relativeLuminance,
    requirePalette,
    safeRatePointModel,
    selectWindowRows,
    setHeatmapRovingCell,
    stableStringify,
    summarizeSweep,
    survivalClassName,
    sweepChartUsesSafeRate,
    sweepConfigurationKey,
    sweepYDomain,
    windowStatsModel,
  });
}));
