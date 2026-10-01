'use strict';

const test = require('node:test');
const { getMarketRows } = require('./helpers/dataset.cjs');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('progressive jobs stop between chunks without assigning any remaining work', async () => {
  const source = fs.readFileSync(require.resolve('../app.js'), 'utf8');
  const worker = source.slice(source.indexOf('async function runProgressiveJobs('), source.indexOf('\nasync function runSafeRateJobs('));
  const controller = new AbortController();
  const assigned = [], progress = [];
  const run = vm.runInNewContext(`${worker}; runProgressiveJobs`, {
    reportSafeRateProgress(kind, reporter, completed, total) { progress.push({ kind, completed, total }); },
    async yieldToUi() { controller.abort(); },
  });
  const finished = await run('frontier', [1, 2, 3].map(value => ({ chunkWeight: 1, run: () => value, assign: value => assigned.push(value) })), 2, controller.signal, () => {});
  assert.equal(finished, false);
  assert.deepEqual(assigned, [1]);
  assert.deepEqual(progress, [{kind:'frontier',completed:2,total:5},{kind:'frontier',completed:3,total:5}]);
});

test('real-data frontier compares the same 69 windows even when recent early failures look complete', async () => {
  const marketRows = await getMarketRows();
  const { STRATEGIES, sweepStartYears } = require('../engine.js');
  const { summarizeSweep } = require('../views.js');
  const options = { startingBalance: 1_000_000, allocation: {stock:.6,bond:.4,bill:0}, feeRate:0,taxRate:0 };
  const summary = (strategy, value) => summarizeSweep(sweepStartYears(marketRows,30,strategy,{...Object.fromEntries(strategy.paramSchema.map(field=>[field.key,field.default])),[strategy.frontierParamKey]:value},options).filter(result=>result.startYear>=1928 && result.startYear<=1996),false,null).lifestyle;
  const floors = [];
  for (const [value, expected] of [[.03,17561],[.04,21073],[.0575,22083]]) {
    const actual = summary(STRATEGIES.guytonKlinger,value);
    assert.equal(actual.completeCount,69);
    assert.equal(actual.failedCount,0);
    assert.ok(Math.abs(actual.worstFloor-expected)<2);
    floors.push(actual.worstFloor);
  }
  // A lower initial rate need not deliver a higher worst spending floor.
  assert.ok(floors[0] < floors[1]);
  const failed = summary(STRATEGIES.guytonKlinger,.06);
  assert.equal(failed.failedCount,1);
  assert.equal(failed.worstFloor,0);
  assert.equal(failed.worstFloorStartYear,1959);
  const fixed = summary(STRATEGIES.fixedReal,.08);
  assert.equal(fixed.completeCount,69);
  assert.equal(fixed.failedCount,55);
  const fixedResults = sweepStartYears(marketRows, 30, STRATEGIES.fixedReal, {initialRate:.08}, options)
    .filter(result => result.startYear >= 1928 && result.startYear <= 1996);
  assert.equal(fixedResults.find(result => result.metrics.success).startYear, 1948);
});

test('frontier shares the progressive worker while owning cancellation independently', () => {
  const source = fs.readFileSync(require.resolve('../app.js'), 'utf8');
  assert.equal((source.match(/async function runProgressiveJobs\(/g) || []).length, 1);
  assert.match(source, /return runProgressiveJobs\(kind,/);
  assert.match(source, /runProgressiveJobs\('frontier',/);
  assert.match(source, /frontier: \{ work: 'frontier values', unit: 'parameter values' \}/);
  assert.match(source, /function performRecalculation\(request\) \{\s*if \(!RenderCoordinator.isCurrent\(request\)\) return;\s*FrontierCoordinator.cancelCurrent\(\)/);
  assert.match(source, /const FrontierCoordinator = createRenderCoordinator\(resetFrontierProgress\)/);
});

/* The view controller moved out of index.html into app.js; markup and styles
   stayed behind. Assertions about behaviour read app.js (plus views.js for the
   pure helpers), assertions about markup or CSS read index.html. */
function appSource() {
  return ['../index.html', '../app.js', '../views.js']
    .map((file) => fs.readFileSync(require.resolve(file), 'utf8'))
    .join('\n');
}

function controllerSource() {
  return fs.readFileSync(require.resolve('../app.js'), 'utf8')
    + fs.readFileSync(require.resolve('../views.js'), 'utf8');
}

function loadSweepHelpers() {
  return require('../views.js');
}

test('modern cohort derives its first year from the reconstructed-to-modern quality seam', () => {
  const { cohortStartYear } = loadSweepHelpers();
  const rows = [
    { year: 1926, quality: 'reconstructed' },
    { year: 1927, quality: 'reconstructed' },
    { year: 1928, quality: 'ok' },
    { year: 1929, quality: 'ok' },
  ];
  assert.equal(cohortStartYear(rows, 'modern'), 1928);
  assert.equal(cohortStartYear(rows, 'full'), 1926);
});

test('comparison range is the intersection of every available range', () => {
  const { intersectYearRanges } = loadSweepHelpers();
  assert.deepEqual(
    { ...intersectYearRanges([{ first: 1872, last: 2025 }, { first: 1928, last: 2024 }]) },
    { first: 1928, last: 2024 },
  );
  assert.deepEqual(
    { ...intersectYearRanges([{ first: 2000, last: 2001 }, { first: 2002, last: 2003 }]) },
    { first: null, last: null },
  );
  assert.deepEqual(
    { ...intersectYearRanges([{ first: 1928, last: 2025 }, { first: null, last: null }]) },
    { first: null, last: null },
  );
  assert.deepEqual(
    { ...intersectYearRanges([{ first: 1928, last: 2025 }, { first: 2025, last: 1928 }]) },
    { first: null, last: null },
  );
});

test('safe-rate Y domain includes every configured reference and remains non-flat at zero', () => {
  const { sweepYDomain } = loadSweepHelpers();
  const withExtremeReference = [{
    strategy: { rateParamKey: 'initialRate' },
    configuration: { params: { initialRate: 0.20 } },
    results: [{ maxSafeRate: 0.04, metrics: { terminalWealthReal: 0 } }],
  }];
  assert.deepEqual({ ...sweepYDomain(withExtremeReference, true) }, { minimum: 0, maximum: 0.20 });

  const flatZero = [{
    strategy: { rateParamKey: 'initialRate' },
    configuration: { params: { initialRate: 0 } },
    results: [{ maxSafeRate: 0, metrics: { terminalWealthReal: 0 } }],
  }];
  assert.deepEqual({ ...sweepYDomain(flatZero, true) }, { minimum: 0, maximum: 0.01 });
  assert.deepEqual({ ...sweepYDomain(flatZero, false) }, { minimum: 0, maximum: 1 });
});

test('1D chart metric depends on every visible strategy, never the heatmap metric', () => {
  const { sweepChartUsesSafeRate } = loadSweepHelpers();
  const fixedReal = { strategy: { supportsMaxSafeRate: true, safeRateSearch: 'monotonic' } };
  const guardrails = { strategy: { supportsMaxSafeRate: true, safeRateSearch: 'adaptive' } };
  const fixedPercent = { strategy: { supportsMaxSafeRate: false } };

  assert.equal(sweepChartUsesSafeRate([fixedReal]), true, 'default success heatmap still uses a safe-rate curve');
  assert.equal(sweepChartUsesSafeRate([guardrails]), true, 'adaptive strategies still use a safe-rate curve');
  assert.equal(sweepChartUsesSafeRate([fixedReal, guardrails]), true);
  assert.equal(sweepChartUsesSafeRate([fixedReal, fixedPercent]), false, 'mixed comparisons use coherent wealth units');
  assert.equal(sweepChartUsesSafeRate([]), false);
});

test('1D line segments break at partial, no-rate, unavailable, and missing-year gaps', () => {
  const { contiguousSweepLineSegments, safeRatePointModel } = loadSweepHelpers();
  const results = [
    { startYear: 1964, metrics: { partial: false }, maxSafeRate: 0.04 },
    { startYear: 1965, metrics: { partial: false }, maxSafeRate: null },
    { startYear: 1966, metrics: { partial: false }, maxSafeRate: 0.035 },
    { startYear: 1967, partial: true, metrics: { partial: true }, maxSafeRate: null },
    { startYear: 1968, metrics: { partial: false }, maxSafeRate: 0.038 },
    { startYear: 1970, metrics: { partial: false }, maxSafeRate: 0.041 },
    { startYear: 1971, metrics: { partial: false } },
    { startYear: 1972, metrics: { partial: false }, maxSafeRate: 0.043 },
    { startYear: 1973, metrics: { partial: false }, maxSafeRate: 0.044 },
  ];
  const segments = contiguousSweepLineSegments(results, (result) => {
    const point = safeRatePointModel(result);
    return point.kind === 'rate' ? point.plotValue : null;
  });
  assert.deepEqual(
    Array.from(segments, (segment) => Array.from(segment, (point) => [point.result.startYear, point.value])),
    [[[1964, 0.04]], [[1966, 0.035]], [[1968, 0.038]], [[1970, 0.041]], [[1972, 0.043], [1973, 0.044]]],
  );
});

test('complete null safe rate is a worst zero-baseline result while partial null stays incomplete', () => {
  const { safeRatePointModel, summarizeSweep } = loadSweepHelpers();
  assert.deepEqual(
    { ...safeRatePointModel({ partial: false, metrics: { partial: false }, maxSafeRate: null }) },
    { plotValue: 0, kind: 'no-rate', label: 'no rate survives' },
  );
  assert.deepEqual(
    { ...safeRatePointModel({ partial: true, metrics: { partial: true }, maxSafeRate: null }) },
    { plotValue: null, kind: 'partial', label: 'incomplete window' },
  );
  const summary = summarizeSweep([
    { startYear: 1965, metrics: { success: true, partial: false, failureYear: null, terminalWealthReal: 10, spendingVolatility: 0 }, maxSafeRate: 0.01 },
    { startYear: 1966, metrics: { success: false, partial: false, failureYear: 1967, terminalWealthReal: 0, spendingVolatility: 0 }, maxSafeRate: null },
    { startYear: 2000, partial: true, metrics: { success: true, partial: true, failureYear: null, terminalWealthReal: 20, spendingVolatility: 0 }, maxSafeRate: null },
  ], true);
  assert.equal(summary.worstStartYear, 1966);
  assert.equal(summary.noSurvivingRateCount, 1);
  assert.equal(summary.minimumSafeRate, null);
});

test('configuration labels include every parameter and material shared option', () => {
  const { configurationLabelModel } = loadSweepHelpers();
  const strategy = {
    name: 'Guyton-Klinger guardrails',
    paramSchema: [
      { key: 'initialRate', label: 'Initial rate', type: 'percent' },
      { key: 'guardrail', label: 'Guardrail', type: 'percent' },
      { key: 'adjustment', label: 'Adjustment', type: 'percent' },
      { key: 'capitalPreservationCutoff', label: 'Cutoff', type: 'number' },
      { key: 'rule', label: 'Rule', type: 'select' },
    ],
  };
  const model = configurationLabelModel({
    strategyId: 'guytonKlinger',
    params: { initialRate: 0.04, guardrail: 0.2, adjustment: 0.1, capitalPreservationCutoff: 15, rule: 'annual' },
    options: { startingBalance: 1_000_000, allocation: { stock: 0.55, bond: 0.45, bill: 0 }, feeRate: 0.005, taxRate: 0.2 },
  }, strategy, { annual: 'Every year' });
  const label = `${model.title} ${model.details}`;
  for (const expected of ['Initial rate: 4%', 'Guardrail: 20%', 'Adjustment: 10%', 'Cutoff: 15', 'Rule: Every year', 'Starting balance: $1,000,000', 'Allocation: 55/45/0', 'Fee: 0.5%', 'Tax: 20%']) {
    assert.match(label, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }

  const managed = configurationLabelModel({
    strategyId: 'barbell', params: { reserveMix: 'split' },
    options: { startingBalance: 500_000, allocation: { stock: 0.7, bond: 0.15, bill: 0.15 }, feeRate: 0, taxRate: 0 },
  }, { name: 'Barbell reserve', initialAllocation() {}, paramSchema: [{ key: 'reserveMix', label: 'Reserve mix', type: 'select' }] }, { split: '50 / 50 split' });
  assert.match(managed.details, /Reserve mix: 50 \/ 50 split/);
  assert.match(managed.details, /Managed opening mix: 70\/15\/15/);
});

test('bounded LRU evicts the least recently used entry and generation captures row shape', () => {
  const { createLruCache, marketGeneration } = loadSweepHelpers();
  const cache = createLruCache(2);
  cache.set('a', 1);
  cache.set('b', null);
  assert.equal(cache.get('a'), 1);
  cache.set('c', 3);
  assert.equal(cache.has('a'), true);
  assert.equal(cache.has('b'), false);
  assert.equal(cache.get('c'), 3);
  assert.equal(cache.size, 2);

  const base = marketGeneration([{ year: 1928, quality: 'ok', stock_tr: 1 }, { year: 2025, quality: 'ok', stock_tr: 1 }], 'stamp');
  const changedShape = marketGeneration([{ year: 1928, quality: 'ok', stock_tr: 1, extra: 0 }, { year: 2025, quality: 'ok', stock_tr: 1 }], 'stamp');
  assert.notEqual(base, changedShape);
});

test('summary excludes partial windows and reports survival, worst opening, wealth, and volatility', () => {
  const { summarizeSweep } = loadSweepHelpers();
  const results = [
    { startYear: 1964, metrics: { success: true, partial: false, failureYear: null, terminalWealthReal: 200, spendingVolatility: 0.02 }, maxSafeRate: 0.05 },
    { startYear: 1965, metrics: { success: false, partial: false, failureYear: 1988, terminalWealthReal: 0, spendingVolatility: null }, maxSafeRate: 0.04 },
    { startYear: 1966, metrics: { success: false, partial: false, failureYear: 1987, terminalWealthReal: 0, spendingVolatility: 0.01 }, maxSafeRate: 0.035 },
    { startYear: 1997, metrics: { success: true, partial: true, failureYear: null, terminalWealthReal: 400, spendingVolatility: 0.03 }, maxSafeRate: null },
  ];
  const summary = summarizeSweep(results, true);
  assert.deepEqual(JSON.parse(JSON.stringify(summary)), {
    completeCount: 3,
    survivedCount: 1,
    survivedRate: 1 / 3,
    partialCount: 1,
    worstStartYear: 1966,
    worstFailureYear: 1987,
    medianTerminalWealthReal: 0,
    worstTerminalWealthReal: 0,
    spendingVolatilityMin: 0.01,
    spendingVolatilityMax: 0.02,
    spendingVolatilityUndefinedCount: 1,
    minimumSafeRate: 0.035,
    noSurvivingRateCount: 0,
    // Additive lifestyle key: legacy fixtures intentionally lack spending profiles.
    lifestyle: null,
  });
});

test('configuration cache key includes strategy, parameters, options, horizon, start, and market generation', () => {
  const { sweepConfigurationKey } = loadSweepHelpers();
  const base = {
    strategyId: 'fixedReal', params: { initialRate: 0.04 },
    options: { startingBalance: 1e6, allocation: { stock: 0.5, bond: 0.5, bill: 0 }, feeRate: 0, taxRate: 0 },
  };
  const key = sweepConfigurationKey(base, 30, 1966, '2026-08-20');
  assert.notEqual(key, sweepConfigurationKey({ ...base, params: { initialRate: 0.05 } }, 30, 1966, '2026-08-20'));
  assert.notEqual(key, sweepConfigurationKey(base, 31, 1966, '2026-08-20'));
  assert.notEqual(key, sweepConfigurationKey(base, 30, 1967, '2026-08-20'));
  assert.notEqual(key, sweepConfigurationKey(base, 30, 1966, 'new-data'));
});

test('sweep renderer and comparison UI satisfy async, accessibility, and click-through contracts', () => {
  const html = appSource();
  assert.match(html, /registerRenderer\('sweep',\s*renderSweepMode\)/);
  assert.match(html, /id="sweep-cohort"[\s\S]*value="modern"[\s\S]*Modern/);
  assert.match(html, /id="sweep-horizon"/);
  assert.match(html, /function setSharedHorizon\(/);
  assert.match(html, /id="add-comparison"[\s\S]*Add current comparison/);
  assert.match(html, /maxSafeRate\([\s\S]*adaptiveStep:\s*0\.001/);
  assert.match(html, /await yieldToUi\(signal\)/);
  assert.match(html, /if \(signal\.aborted\)/);
  assert.match(html, /return runSafeRateJobs\('curve', jobs, 0, signal, reportProgress\)/);
  assert.match(html, /const usesSafeRate\s*=\s*sweepChartUsesSafeRate\(series\)/);
  assert.match(html, /await attachSafeRates\(series, snapshot, signal, reportProgress\)/);
  assert.match(html, /if \(heatmapMetric === 'safe'\)[\s\S]*attachHeatmapSafeRates/);
  assert.match(html, /contiguousSweepLineSegments\(item\.results,/);
  assert.match(html, /function reportSafeRateProgress\([^)]*\)\s*\{[\s\S]{0,120}?return reportProgress\(\(\) => \{/);
  assert.match(html, /function applyConfigurationToControls\(/);
  assert.match(html, /No rate survives/);
  assert.match(html, /safePoint\.label/);
  assert.match(html, /createLruCache\(5000\)/);
  assert.match(html, /function openSweepPoint\([\s\S]*openWindow\(/);
  assert.match(html, /<title[^>]*>/);
  assert.match(html, /<desc[^>]*>/);
  assert.match(html, /<caption[^>]*>Sweep comparison summary<\/caption>/);
});

test('heatmap model orders the 5–60 horizon grid and keeps partial and failed cells distinct', () => {
  const { heatmapModel, HEATMAP_HORIZONS, HEATMAP_PALETTES } = loadSweepHelpers();
  assert.deepEqual(Array.from(HEATMAP_HORIZONS), [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60]);
  const grid = [
    { startYear: 1927, horizon: 5, partial: false, metrics: { partial: false, success: true, terminalWealthReal: 150 } },
    { startYear: 1928, horizon: 5, partial: false, metrics: { partial: false, success: false, terminalWealthReal: 0, failureYear: 1931 } },
    { startYear: 1929, horizon: 5, partial: true, metrics: { partial: true, success: true, terminalWealthReal: 200 } },
  ];
  const model = heatmapModel(grid, 'success', 1928, HEATMAP_PALETTES.light);
  assert.deepEqual(Array.from(model.startYears), [1927, 1928, 1929]);
  assert.equal(model.seamYear, 1928);
  assert.equal(model.cells[0].kind, 'survived');
  assert.equal(model.cells[1].kind, 'failed');
  assert.equal(model.cells[2].kind, 'partial');
  assert.match(model.cells[1].label, /Start 1928.*5-year horizon.*Failed.*1931/i);
  assert.match(model.cells[2].label, /partial.*not classified/i);
});

test('quantitative heatmap models expose numeric legends and a separate no-rate class', () => {
  const { heatmapModel, heatmapLegendModel, HEATMAP_PALETTES } = loadSweepHelpers();
  const grid = [
    { startYear: 1965, horizon: 30, metrics: { partial: false, success: true, terminalWealthReal: 0 }, maxSafeRate: null },
    { startYear: 1966, horizon: 30, metrics: { partial: false, success: true, terminalWealthReal: 100 }, maxSafeRate: 0.03 },
    { startYear: 1967, horizon: 30, metrics: { partial: false, success: true, terminalWealthReal: 200 }, maxSafeRate: 0.06 },
  ];
  const wealth = heatmapModel(grid, 'wealth', null, HEATMAP_PALETTES.light);
  assert.deepEqual({ ...wealth.domain }, { minimum: 0, midpoint: 100, maximum: 200 });
  assert.notEqual(wealth.cells[0].color, wealth.cells[2].color);
  const safe = heatmapModel(grid, 'safe', null, HEATMAP_PALETTES.light);
  assert.equal(safe.cells[0].kind, 'no-rate');
  assert.match(safe.cells[0].label, /no rate survives/i);
  const legend = heatmapLegendModel('safe', safe.domain, true, HEATMAP_PALETTES.light);
  assert.match(legend.description, /approximate.*0\.1 percentage-point/i);
  assert.deepEqual(Array.from(legend.ticks).map((tick) => tick.value), [0, 0.03, 0.06]);
});

test('quantitative colors interpolate through the shared ochre midpoint palette', () => {
  const { HEATMAP_PALETTES, heatmapQuantitativeColor, heatmapLegendModel } = loadSweepHelpers();
  const palette = HEATMAP_PALETTES.light;
  const domain = { minimum: 0, midpoint: 50, maximum: 100 };
  assert.equal(heatmapQuantitativeColor(0, domain, palette), palette.quantitative.minimum);
  assert.equal(heatmapQuantitativeColor(50, domain, palette), palette.quantitative.midpoint);
  assert.equal(heatmapQuantitativeColor(100, domain, palette), palette.quantitative.maximum);
  assert.equal(heatmapQuantitativeColor(25, domain, palette), '#b16f34');
  assert.equal(heatmapQuantitativeColor(75, domain, palette), '#726f42');
  assert.deepEqual(
    Array.from(heatmapLegendModel('wealth', domain, false, palette).colors),
    [palette.quantitative.minimum, palette.quantitative.midpoint, palette.quantitative.maximum],
  );
});

test('every heatmap palette branch chooses text with WCAG AA contrast', () => {
  const { HEATMAP_PALETTES, heatmapQuantitativeColor, heatmapForeground, contrastRatio } = loadSweepHelpers();
  const palette = HEATMAP_PALETTES.light;
  const domain = { minimum: 0, midpoint: 50, maximum: 100 };
  const backgrounds = [
    ...Object.values(palette.categorical),
    ...Array.from({ length: 21 }, (_, index) => heatmapQuantitativeColor(index * 5, domain, palette)),
  ];
  for (const background of backgrounds) {
    const foreground = heatmapForeground(background, palette);
    assert.ok(contrastRatio(background, foreground) >= 4.5, `${background} / ${foreground} must meet 4.5:1`);
  }
});

test('partial cell foreground remains legible on its solid fill and hatch composite', () => {
  const { HEATMAP_PALETTES, heatmapForeground, contrastRatio, compositeHexColor } = loadSweepHelpers();
  const palette = HEATMAP_PALETTES.light;
  const background = palette.categorical.partial;
  const foreground = heatmapForeground(background, palette);
  const hatch = compositeHexColor(background, palette.foreground.ink, 0.12);
  assert.ok(contrastRatio(background, foreground) >= 4.5);
  assert.ok(contrastRatio(hatch, foreground) >= 4.5);
  const html = appSource();
  const partialRule = html.match(/\.heatmap-cell\.kind-partial\s*\{([^}]+)\}/);
  assert.ok(partialRule, 'partial-cell style must exist');
  assert.doesNotMatch(partialRule[1], /\bcolor\s*:/, 'partial style must retain the computed foreground');
});

test('safe-rate heatmap schedules only complete uncached cells', () => {
  const { heatmapSafeRateJobs, createLruCache } = loadSweepHelpers();
  const cache = createLruCache(4);
  cache.set('cached', 0.04);
  const cells = [
    { key: 'cached', partial: false, metrics: { partial: false } },
    { key: 'fresh', partial: false, metrics: { partial: false } },
    { key: 'partial', partial: true, metrics: { partial: true } },
  ];
  const jobs = heatmapSafeRateJobs(cells, cache);
  assert.deepEqual(Array.from(jobs, (cell) => cell.key), ['fresh']);
  assert.equal(cells[0].maxSafeRate, 0.04);
  assert.equal(Object.hasOwn(cells[2], 'maxSafeRate'), false);
});

test('delegated heatmap activation resolves only a cell button', () => {
  const { heatmapCellTarget } = loadSweepHelpers();
  const button = { matches: (selector) => selector === '[data-heatmap-cell]' };
  const child = { matches: () => false, closest: (selector) => selector === '[data-heatmap-cell]' ? button : null };
  assert.equal(heatmapCellTarget(button), button);
  assert.equal(heatmapCellTarget(child), button);
  assert.equal(heatmapCellTarget({ matches: () => false, closest: () => null }), null);
});

test('roving heatmap focus follows table directions and keeps one cell tabbable', () => {
  const { moveHeatmapFocus } = loadSweepHelpers();
  const cells = new Map();
  for (let row = 0; row < 2; row += 1) {
    for (let column = 0; column < 3; column += 1) {
      const cell = { dataset: { heatmapRow: String(row), heatmapColumn: String(column) }, tabIndex: -1, focused: false, focus() { this.focused = true; } };
      cells.set(`${row}:${column}`, cell);
    }
  }
  const table = { querySelector: (selector) => {
    const match = selector.match(/row="(\d+)"\]\[data-heatmap-column="(\d+)"/);
    return match ? cells.get(`${match[1]}:${match[2]}`) : null;
  } };
  const start = cells.get('0:1');
  start.tabIndex = 0;
  assert.equal(moveHeatmapFocus(table, start, 'ArrowDown'), true);
  assert.equal(start.tabIndex, -1);
  assert.equal(cells.get('1:1').tabIndex, 0);
  assert.equal(cells.get('1:1').focused, true);
  assert.equal(moveHeatmapFocus(table, cells.get('1:1'), 'ArrowRight'), true);
  assert.equal(cells.get('1:2').tabIndex, 0);
  assert.equal(moveHeatmapFocus(table, cells.get('1:2'), 'ArrowRight'), false, 'edge does not wrap');
  assert.equal(moveHeatmapFocus(table, cells.get('1:2'), 'Enter'), false);
});

test('heatmap controls expose lazy cancellation, disabled unsupported safe rate, and one delegated listener', () => {
  const html = appSource();
  assert.match(html, /id="heatmap-metric"/);
  assert.match(html, /id="cancel-heatmap"[^>]*>Cancel/);
  assert.match(html, /function cancelCurrentRender\(/);
  assert.match(html, /cancel-heatmap[\s\S]*cancelCurrentRender/);
  assert.match(html, /heatmapSafeRateJobs\(/);
  assert.match(html, /return runSafeRateJobs\('heatmap', jobs, [^,]+, signal, reportProgress\)/);
  assert.match(html, /heatmap\.addEventListener\('click'/);
  assert.match(html, /heatmap\.addEventListener\('keydown'/);
  assert.match(html, /heatmap\.addEventListener\('focusin'/);
  assert.match(html, /button\.tabIndex\s*=\s*firstHeatmapCell/);
  assert.match(html, /openRenderedHeatmapWindow\(renderedHeatmapConfiguration,/);
  assert.doesNotMatch(html, /cell\.addEventListener\(/);
  assert.match(html, /safeOption\.disabled\s*=\s*!strategy\.supportsMaxSafeRate/);
  assert.match(html, /DocumentFragment|createDocumentFragment/);
});


test('both theme palettes keep every heatmap branch at WCAG AA contrast', () => {
  const {
    HEATMAP_PALETTES,
    heatmapPalette,
    heatmapQuantitativeColor,
    heatmapForeground,
    contrastRatio,
    compositeHexColor,
  } = loadSweepHelpers();

  assert.deepEqual(Object.keys(HEATMAP_PALETTES).sort(), ['dark', 'light']);
  assert.equal(heatmapPalette('dark'), HEATMAP_PALETTES.dark);
  assert.equal(heatmapPalette('light'), HEATMAP_PALETTES.light);
  // Unknown or absent themes must degrade to light rather than throw.
  assert.equal(heatmapPalette('system'), HEATMAP_PALETTES.light);
  assert.equal(heatmapPalette(undefined), HEATMAP_PALETTES.light);

  for (const [name, palette] of Object.entries(HEATMAP_PALETTES)) {
    const domain = { minimum: 0, midpoint: 50, maximum: 100 };
    const backgrounds = [
      ...Object.values(palette.categorical),
      ...Array.from({ length: 11 }, (_, step) => heatmapQuantitativeColor(step * 10, domain, palette)),
    ];
    for (const background of backgrounds) {
      const foreground = heatmapForeground(background, palette);
      assert.ok(
        contrastRatio(background, foreground) >= 4.5,
        `${name}: ${background} / ${foreground} must meet 4.5:1`,
      );
    }
    // The partial cell is drawn as a hatch composited over its own fill; both must stay legible.
    const partial = palette.categorical.partial;
    const partialForeground = heatmapForeground(partial, palette);
    const hatch = compositeHexColor(partial, palette.foreground.ink, 0.12);
    assert.ok(contrastRatio(hatch, partialForeground) >= 4.5, `${name}: hatched partial cell must meet 4.5:1`);
  }
});

test('dark and light palettes are genuinely distinct across every role', () => {
  const { HEATMAP_PALETTES } = loadSweepHelpers();
  const { light, dark } = HEATMAP_PALETTES;
  for (const group of ['quantitative', 'categorical', 'foreground']) {
    for (const role of Object.keys(light[group])) {
      assert.notEqual(
        light[group][role],
        dark[group][role],
        `${group}.${role} must differ between themes`,
      );
    }
  }
});


test('heatmap cell colours come from the palette argument, not a baked-in default', () => {
  const { heatmapModel, HEATMAP_PALETTES } = loadSweepHelpers();
  // One survived window and one failed window is enough to pin both categorical roles.
  const grid = [
    { startYear: 1950, horizon: 30, partial: false, metrics: { success: true, terminalWealthReal: 2e6 } },
    { startYear: 1966, horizon: 30, partial: false, metrics: { success: false, failureYear: 1990, terminalWealthReal: 0 } },
  ];

  for (const [themeName, palette] of Object.entries(HEATMAP_PALETTES)) {
    const model = heatmapModel(grid, 'success', 1928, palette);
    const survived = model.cells.find((cell) => cell.kind === 'survived');
    const failed = model.cells.find((cell) => cell.kind === 'failed');
    assert.equal(survived.color, palette.categorical.survived, `${themeName} survived colour`);
    assert.equal(failed.color, palette.categorical.failed, `${themeName} failed colour`);
    assert.equal(survived.foreground, heatmapModelForeground(palette, survived.color), `${themeName} survived foreground`);
  }

  // The two themes must actually produce different cell colours for the same grid.
  const light = heatmapModel(grid, 'success', 1928, HEATMAP_PALETTES.light);
  const dark = heatmapModel(grid, 'success', 1928, HEATMAP_PALETTES.dark);
  assert.notEqual(light.cells[0].color, dark.cells[0].color);

  function heatmapModelForeground(palette, background) {
    const { heatmapForeground } = loadSweepHelpers();
    return heatmapForeground(background, palette);
  }
});

test('every render-layer heatmap model is built with an explicit theme palette', () => {
  // Guards against a future call site silently falling back to the light default,
  // which would strand the heatmap in light colours while the page is dark.
  // The render layer is app.js by construction now: views.js holds the pure
  // model builders, so their definitions can no longer be mistaken for call sites.
  const renderLayer = fs.readFileSync(require.resolve('../app.js'), 'utf8');
  const calls = renderLayer.match(/heatmap(?:Legend)?Model\(/g) || [];
  assert.ok(calls.length >= 3, `expected render-layer heatmap model calls, found ${calls.length}`);
  for (const match of renderLayer.matchAll(/heatmap(?:Legend)?Model\(([\s\S]{0,240}?)\)\s*;/g)) {
    assert.match(
      match[1],
      /Theme\.palette\(\)/,
      `render-layer call must pass Theme.palette(): ${match[0].slice(0, 120)}`,
    );
  }
});


test('heatmap helpers reject a missing or malformed palette', () => {
  const {
    heatmapQuantitativeColor, heatmapForeground, heatmapModel, heatmapLegendModel,
  } = loadSweepHelpers();
  const domain = { minimum: 0, midpoint: 50, maximum: 100 };
  assert.throws(() => heatmapQuantitativeColor(50, domain), /requires a theme palette/);
  assert.throws(() => heatmapForeground('#386b55'), /requires a theme palette/);
  assert.throws(() => heatmapModel([], 'success', 1928), /requires a theme palette/);
  assert.throws(() => heatmapLegendModel('wealth', domain, false), /requires a theme palette/);
  // A partially-shaped object is as dangerous as none at all.
  assert.throws(() => heatmapForeground('#386b55', { quantitative: {} }), /requires a theme palette/);
});

test('survival colour marks only the categorical endpoints, never a mid-range rate', () => {
  const { survivalClassName } = loadSweepHelpers();
  const at = (survivedCount, completeCount) => survivalClassName({
    survivedCount, completeCount, survivedRate: completeCount ? survivedCount / completeCount : NaN,
  });

  // Regression: every rate used to render success-green, so 0 of 69 read as a win.
  assert.equal(at(0, 69), 'warning');
  assert.equal(at(69, 69), 'success');

  // Everything between is a historical frequency, not a grade — left neutral.
  for (const survived of [1, 34, 64, 68]) {
    assert.equal(at(survived, 69), '', `${survived}/69 must stay neutral`);
  }

  // Degenerate inputs must not colour anything.
  assert.equal(at(0, 0), '');
  assert.equal(survivalClassName({ survivedCount: 0, completeCount: 0, survivedRate: NaN }), '');
});

test('the partial-wealth caveat names the incomparability, not just the colour', () => {
  const { PARTIAL_WEALTH_CAVEAT } = loadSweepHelpers();
  assert.match(PARTIAL_WEALTH_CAVEAT, /partial/i);
  assert.match(PARTIAL_WEALTH_CAVEAT, /fewer years/i);
  assert.match(PARTIAL_WEALTH_CAVEAT, /not comparable/i);
});

test('the wealth chart carries the partial caveat only when partials are plotted', () => {
  // The caveat is rendered from the same constant in both the visible <p> and the
  // SVG description, and both are gated on the series actually holding a partial.
  const html = appSource();
  const renderLayer = controllerSource();
  const gates = [...renderLayer.matchAll(/!usesSafeRate && series\.some\(\(item\) => item\.summary\.partialCount > 0\)/g)];
  assert.equal(gates.length, 2, 'both the chart caveat and the SVG description must be gated');
  assert.match(renderLayer, /class="chart-caveat"/);
});

test('the reconstructed-year key is rendered only when marked rows are on screen', () => {
  const html = appSource();
  assert.match(html, /function renderLedgerKey\(rows\) \{\s*if \(!rows\.some\(\(row\) => row\.quality === 'reconstructed'\)\) return null;/);
  // The marked cells must also carry the explanation for non-hovering and AT users.
  assert.match(html, /const RECONSTRUCTED_YEAR_TITLE = '[^']*Cowles splice[^']*'/);
  assert.match(html, /cell\.setAttribute\('aria-description', title\)/);
  assert.match(html, /\.ledger-key \{/);
});

test('export commits merge so one mode never clears the other mode models', () => {
  const html = appSource();
  // Merge semantics: only keys actually supplied are touched.
  assert.match(html, /for \(const key of \['window', 'sweepCurve', 'sweepHeatmap'\]\) \{\s*if \(key in models\)/);
  // The transient reset clears the sweep-derived models it is about to recompute,
  // and must leave the window model alone.
  assert.match(html, /commitExportModels\(\{ sweepCurve: null, sweepHeatmap: null \}\)/);
  assert.doesNotMatch(html, /AppState\.exportModels = \{ window: null, sweepCurve: null, sweepHeatmap: null \}/);
});

test('one safe-rate worker serves both the curve and the heatmap', () => {
  // Regression: the two passes carried near-identical loops, so a fix to cache
  // handling, cancellation, or chunk yielding reached only one of them.
  const html = appSource();
  const script = controllerSource();

  assert.equal((script.match(/async function runSafeRateJobs\(/g) || []).length, 1);
  assert.equal((script.match(/function safeRateSequence\(/g) || []).length, 1);
  assert.equal((script.match(/function reportSafeRateProgress\(/g) || []).length, 1);

  // The engine call, the cache writes, and the yield decision must each exist once.
  assert.equal((script.match(/BacktestEngine\.maxSafeRate\(/g) || []).length, 1);
  assert.equal((script.match(/SweepSafeRateCache\.set\(/g) || []).length, 1);
  assert.equal((script.match(/safeRateSearch === 'adaptive' \? 1 : 6/g) || []).length, 1);

  // Both callers delegate rather than looping themselves.
  assert.match(script, /return runSafeRateJobs\('heatmap',/);
  assert.match(script, /return runSafeRateJobs\('curve',/);
});

test('the safe-rate worker keeps both progress wordings without duplicating the mechanism', () => {
  const html = appSource();
  assert.match(html, /curve: \{ work: 'sustainable rates', unit: 'complete windows' \}/);
  assert.match(html, /heatmap: \{ work: 'heatmap rates', unit: 'complete cells' \}/);
  // One template builds both messages.
  const script = controllerSource();
  assert.equal((script.match(/Calculating \$\{noun\.work\}/g) || []).length, 1);
});

test('floor and below-need heatmaps use fixed and inverted scales, hold out partials and choose earliest worst starts', () => {
  const { spendingProfile } = require('../stats.js');
  const { heatmapModel, heatmapPalette, heatmapLegendModel, contrastRatio } = loadSweepHelpers();
  const make = (startYear, realSpending, extras = {}) => ({ startYear, horizon: 4, metrics: { success: !extras.failed, failureYear: extras.failed ? startYear + 1 : null, spending: spendingProfile({ realSpending, startYear, horizon: 4, baseline: 100, failed: false, partial: false, ...extras }), partial: Boolean(extras.partial) } });
  const grid = [make(2002, [100, 50, 50, 100]), make(2001, [100, 20], { failed: true }), make(2000, [100, 20], { failed: true }), make(2003, [100, 200, 200, 200]), make(2004, [100, 1], { partial: true }), make(2005, [0, 0, 0, 0], { baseline: 0 })];
  for (const theme of ['light', 'dark']) for (const metric of ['floor', 'belowNeed']) {
    const palette = heatmapPalette(theme);
    const model = heatmapModel(grid, metric, 2002, palette, 90);
    assert.deepEqual(model.domain, { minimum: 0, midpoint: .5, maximum: 1 });
    assert.equal(model.cells[4].kind, 'partial');
    assert.equal(model.rowWorst[0].startYear, metric === 'floor' ? 2000 : 2005);
    for (const cell of model.cells) assert.ok(contrastRatio(cell.color, cell.foreground) >= 4.5, `${theme} ${metric} ${cell.startYear}`);
    if (metric === 'floor') {
      assert.equal(model.cells[1].kind, 'failed'); assert.equal(model.cells[1].display, '×');
      assert.equal(model.cells[5].kind, 'no-rate'); assert.equal(model.cells[5].display, '—');
      assert.match(model.cells[0].label, /floor \$50 real · 50% of year 1/);
      assert.match(model.cells[1].label, /Failed in 2002 · floor \$0 · last partial \$20/);
    } else {
      assert.equal(model.cells[1].kind, 'belowNeed'); assert.equal(model.cells[1].value, .75);
      assert.equal(model.cells[3].color, palette.quantitative.maximum);
      assert.deepEqual(heatmapLegendModel(metric, model.domain, false, palette).ticks.map(t => t.label), ['100%', '50%', '0%']);
    }
  }
});

test('floor heatmap clamps above 100 percent and preserves null worst fields for held-out horizons', () => {
  const { heatmapModel, heatmapPalette } = loadSweepHelpers();
  const palette = heatmapPalette('light');
  const grid = [{ startYear: 2000, horizon: 5, metrics: { success: true, spending: { floorRatio: 1.5, floor: 150 } } }, { startYear: 2001, horizon: 10, partial: true, metrics: { partial: true, spending: { floorRatio: .5, floor: 50 } } }];
  const model = heatmapModel(grid, 'floor', null, palette);
  assert.equal(model.cells[0].color, palette.quantitative.maximum);
  assert.equal(model.cells[0].display, '150%');
  assert.deepEqual(model.rowWorst[1], { horizon: 10, value: null, startYear: null, display: '—' });
});

test('need never enters simulation cache keys or pinned configuration data', () => {
  const app = fs.readFileSync(require.resolve('../app.js'), 'utf8');
  const configuration = app.match(/function currentSweepConfiguration\(snapshot\) \{([\s\S]*?)\n\}/)[1];
  const key = app.match(/function cachedHeatmapGrid[\s\S]*?const key = stableStringify\(\{([\s\S]*?)\}\)/)[1];
  assert.doesNotMatch(configuration, /need/i);
  assert.doesNotMatch(key, /need/i);
  const html = fs.readFileSync(require.resolve('../index.html'), 'utf8');
  const placeholder = html.match(/id="sweep-stats"[\s\S]*?<div class="ledger-placeholder"/)[0];
  assert.equal((placeholder.match(/class="stat-group /g) || []).length, 2);
  assert.equal((placeholder.match(/class="stat"/g) || []).length, 7);
});

test('sweep UI connects grouped lifestyle summaries and spending range inside the chart scroller', () => {
  const app = fs.readFileSync(require.resolve('../app.js'), 'utf8');
  const html = fs.readFileSync(require.resolve('../index.html'), 'utf8');
  assert.match(html, /id="sweep-chart-metric"[\s\S]*value="auto" selected>Sustainable rate \/ wealth[\s\S]*value="spending">Real spending range/);
  assert.match(app, /sweepChartMetric: AppState\.sweepChartMetric/);
  assert.match(app, /function renderSweepStats\(summary, strategy\)/);
  assert.match(app, /renderStatGroup\('Solvency', sweepSolvencyCells\(summary, strategy\)\)/);
  assert.match(app, /sweepLifestyleCells\(summary\)/);
  assert.match(app, /snapshot\.sweepChartMetric === 'spending'/);
  assert.match(app, /spendingRangeSvg\(spendingRangeModel\(series, snapshot\.needDollars\)\)/);
  assert.match(app, /sweepSummaryRows\(series, needDollars\)/);
  assert.match(app, /Percentile rows are historical frequencies over overlapping windows, not probabilities\./);
  assert.doesNotMatch(app, /sweepTopStats|summaryValue|strategyId === 'fixedPercent'/);
});

test('sweep heatmap exposes lifestyle metrics, null-need fallback and noninteractive worst column', () => {
  const app = fs.readFileSync(require.resolve('../app.js'), 'utf8');
  const html = fs.readFileSync(require.resolve('../index.html'), 'utf8');
  assert.match(html, /value="floor">Spending floor · % of year 1/);
  assert.match(html, /value="belowNeed">Years below need/);
  assert.match(app, /\['success', 'wealth', 'safe', 'floor', 'belowNeed'\]\.includes/);
  assert.match(app, /snapshot\.heatmapMetric === 'belowNeed' && snapshot\.needDollars === null/);
  assert.match(app, /belowNeedOption\.disabled = [^;]*=== null/);
  assert.match(app, /function renderHeatmap\(grid, metric, seamYear, strategy, needDollars\)/);
  assert.match(app, /heatmapModel\(grid, metric, seamYear, Theme\.palette\(\), needDollars\)/);
  assert.match(app, /worstHead\.scope = 'col'/);
  assert.match(app, /worstHead\.textContent = 'Worst'/);
  assert.match(app, /model\.rowWorst/);
  assert.match(app, /horizonCaveat\(strategy\)/);
  assert.match(app, /sweepCurveExportRows\(exportSeries, snapshot\.needDollars\)/);
  assert.match(app, /summarizeSweep\(item\.results, usesSafeRate && item\.strategy\.supportsMaxSafeRate, snapshot\.needDollars\)/);
});
