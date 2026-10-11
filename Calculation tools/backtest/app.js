'use strict';

/* Module imports. Named rather than ambient: format.js, views.js, and csv.js
   publish only their namespace object, so a missing or renamed export fails
   here at load instead of surfacing as an undefined identifier mid-render. */
const { fmtMoney, fmtPct, fmtMoneyCompact, fmtPctConcise, fmtCount, escapeHtml } = globalThis.MarketAtlasFormat;

const { resolveNeed, comparisonTolerance } = globalThis.MarketAtlasStats;
const {
  windowLifestyleCells, sweepSolvencyCells, sweepLifestyleCells, sweepSummaryRows,
  spendingRangeModel, frontierPlan, frontierModel, horizonCaveat, spendingStripModel, ledgerFloorFlags, needReadout,
} = globalThis.MarketAtlasLifestyle;
const { spendingStripSvg, spendingRangeSvg, frontierSvg } = globalThis.MarketAtlasCharts;

const {
  createConfigurationApplier, HEATMAP_HORIZONS, PARTIAL_WEALTH_CAVEAT, chartSeries,
  clampWindowSelection, cohortStartYear, configurationLabelModel, contiguousSweepLineSegments,
  createLatestWinsScheduler, createLruCache, createRenderCoordinator, displayBalance,
  executeRendererRequest, findQualitySeam, heatmapCellTarget, heatmapLegendModel,
  heatmapModel, heatmapPalette, heatmapSafeRateJobs, intersectYearRanges,
  marketGeneration, moveHeatmapFocus, normalizeNotes,
  safeRatePointModel, selectWindowRows, setHeatmapRovingCell, stableStringify,
  summarizeSweep, sweepChartUsesSafeRate, sweepConfigurationKey,
  sweepYDomain, windowStatsModel,
} = globalThis.MarketAtlasViews;

const {
  windowExportRows, sweepCurveExportRows, heatmapExportRows, createCsvDownloader,
  failureNote,
} = globalThis.MarketAtlasCsv;

/*
 * Market Atlas application controller.
 *
 * Owns application state, the sidebar, DOM rendering for both views, and event
 * wiring. Pure view logic (models, palettes, the render coordinator) lives in
 * views.js; number formatting lives in format.js. This file is the only one that
 * touches the DOM.
 *
 * Loaded as a classic script after market-data.js, format.js, views.js, and
 * engine.js, so those globals are available here.
 */
'use strict';

const AppState = {
  stageInFlight: null,
  frontier: { visible: false, paramKey: null, override: null },
  mode: 'window',
  display: 'real',
  need: { anchor: 'percent', ratio: .9 },
  strategyId: null,
  strategyParams: Object.create(null),
  yearRange: { first: null, last: null, excludedAssets: [] },
  allocationValid: true,
  allocationManaged: false,
  manualAllocationValues: { stock: '60', bond: '40', bill: '0' },
  sweepCohort: 'modern',
  heatmapMetric: 'success',
  sweepChartMetric: 'auto',
  comparisons: [],
  nextComparisonId: 1,
  exportModels: { window: null, sweepCurve: null, sweepHeatmap: null },
};

const Renderers = { window: null, sweep: null };

/* LATEST-WINS COORDINATOR: extracted to views.js */

function resetSweepProgress() {
  const progress = byId('sweep-progress');
  if (!progress) return;
  progress.hidden = true;
  progress.textContent = '';
  const cancel = byId('cancel-heatmap');
  if (cancel) cancel.hidden = true;
  /* A new render invalidates the sweep-derived exports it is about to
     recompute; the window model belongs to the other mode and is left alone. */
  commitExportModels({ sweepCurve: null, sweepHeatmap: null });
}

function updateExportControls() {
  const bindings = [
    ['export-window-csv', 'window'],
    ['export-sweep-curve-csv', 'sweepCurve'],
    ['export-sweep-heatmap-csv', 'sweepHeatmap'],
  ];
  for (const [id, key] of bindings) {
    const button = byId(id);
    if (button) button.disabled = !AppState.exportModels[key];
  }
}

/* Merge rather than replace: window and sweep commit different subsets, and
   replacing wiped whichever mode was not committing. Pass an explicit null to
   clear one deliberately. */
function commitExportModels(models) {
  AppState.exportModels = { ...AppState.exportModels };
  for (const key of ['window', 'sweepCurve', 'sweepHeatmap']) {
    if (key in models) AppState.exportModels[key] = models[key] || null;
  }
  updateExportControls();
}

const RenderCoordinator = createRenderCoordinator(resetSweepProgress);
function resetFrontierProgress() {
  const progress = byId('sweep-progress');
  if (progress) { progress.hidden = true; progress.textContent = ''; }
  const cancel = byId('cancel-heatmap');
  if (cancel) cancel.hidden = true;
}
const FrontierCoordinator = createRenderCoordinator(resetFrontierProgress);
const FrontierCache = createLruCache(2000);
let lastFrontierInput = null;
let stageRequest = null;

function setFrontierSweepBusy(busy) {
  const run = byId('frontier-run');
  if (!run) return;
  if (busy) {
    if (!Object.hasOwn(run.dataset, 'sweepDisabled')) run.dataset.sweepDisabled = String(run.disabled);
    run.disabled = true;
  } else if (Object.hasOwn(run.dataset, 'sweepDisabled')) {
    run.disabled = run.dataset.sweepDisabled === 'true';
    delete run.dataset.sweepDisabled;
  }
}

const HUMAN_LABELS = Object.freeze({
  bills: 'Treasury bills',
  bonds: '10-year bonds',
  split: '50 / 50 split',
  reserve_after_down: 'Reserve after down years',
  reserve_first: 'Reserve first',
  after_up_years: 'After positive years',
  annual: 'Every year',
  stock: 'US stocks',
  bond: '10-year bonds',
  bill: 'Treasury bills',
});


function byId(id) { return document.getElementById(id); }
function finiteNumber(value) {
  if (typeof value === 'string' && value.trim() === '') return NaN;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : NaN;
}

function immutableSnapshot(value) {
  if (Array.isArray(value)) return Object.freeze(value.map(immutableSnapshot));
  if (value && typeof value === 'object') {
    const copy = {};
    for (const [key, entry] of Object.entries(value)) copy[key] = immutableSnapshot(entry);
    return Object.freeze(copy);
  }
  return value;
}

/* CSV serialization lives in csv.js; only the download needs browser APIs and
   is constructed with them here. */
const exportCsv = createCsvDownloader({ Blob, URL, document });

/* Formatting lives in format.js so every view renders a value the same way.
   See the note there for the divergence this replaced. */

/* WINDOW VIEW HELPERS: extracted to views.js */

/* SWEEP VIEW HELPERS: extracted to views.js */

function convertParamValue(field, value, direction) {
  if (field.type === 'select' || field.type === 'enum') return value;
  const numeric = finiteNumber(value);
  if (!Number.isFinite(numeric)) return numeric;
  const scale = field.type === 'percent' ? 100 : 1;
  return direction === 'display' ? numeric * scale : numeric / scale;
}

function currentStrategy() {
  return globalThis.BacktestEngine && globalThis.BacktestEngine.STRATEGIES
    ? globalThis.BacktestEngine.STRATEGIES[AppState.strategyId]
    : null;
}

function schemaOption(option) {
  if (option && typeof option === 'object') {
    return { value: String(option.value), label: String(option.label || HUMAN_LABELS[option.value] || option.value) };
  }
  return { value: String(option), label: HUMAN_LABELS[option] || String(option).replace(/_/g, ' ') };
}

function createField(schema) {
  const row = document.createElement('div');
  row.className = 'field';
  const label = document.createElement('label');
  const id = `strategy-param-${schema.key}`;
  label.htmlFor = id;
  label.append(document.createTextNode(schema.label || schema.key));
  if (schema.hint) {
    const hint = document.createElement('span');
    hint.className = 'hint';
    hint.id = `${id}-hint`;
    hint.textContent = schema.hint;
    label.append(hint);
  }

  const wrap = document.createElement('span');
  wrap.className = `input-wrap${schema.type === 'select' || schema.type === 'enum' ? ' select-wrap' : ''}`;
  let control;
  if (schema.type === 'select' || schema.type === 'enum') {
    control = document.createElement('select');
    for (const rawOption of schema.options || []) {
      const normalized = schemaOption(rawOption);
      const option = document.createElement('option');
      option.value = normalized.value;
      option.textContent = normalized.label;
      control.append(option);
    }
  } else {
    control = document.createElement('input');
    control.type = 'number';
    control.inputMode = 'decimal';
    if (schema.min !== undefined) control.min = String(convertParamValue(schema, schema.min, 'display'));
    if (schema.max !== undefined) control.max = String(convertParamValue(schema, schema.max, 'display'));
    if (schema.step !== undefined) control.step = String(convertParamValue(schema, schema.step, 'display'));
  }
  control.id = id;
  control.name = schema.key;
  control.dataset.paramKey = schema.key;
  control.setAttribute('aria-describedby', `${schema.hint ? `${id}-hint ` : ''}app-status-message`);
  const stored = AppState.strategyParams[AppState.strategyId][schema.key];
  control.value = String(convertParamValue(schema, stored, 'display'));
  wrap.append(control);
  if (schema.type === 'percent') {
    const suffix = document.createElement('span');
    suffix.className = 'suffix';
    suffix.textContent = '%';
    wrap.append(suffix);
  }
  row.append(label, wrap);
  return row;
}

function rememberVisibleParams() {
  const strategy = currentStrategy();
  if (!strategy) return;
  const saved = AppState.strategyParams[AppState.strategyId] || (AppState.strategyParams[AppState.strategyId] = {});
  for (const field of strategy.paramSchema || []) {
    const control = byId(`strategy-param-${field.key}`);
    if (!control) continue;
    saved[field.key] = field.type === 'select' || field.type === 'enum'
      ? control.value
      : convertParamValue(field, control.value, 'internal');
  }
}

function renderSidebar() {
  const strategy = currentStrategy();
  const target = byId('strategy-params');
  target.replaceChildren();
  if (!strategy) {
    const message = document.createElement('p');
    message.className = 'hint';
    message.textContent = 'No strategy schema is available.';
    target.append(message);
    return;
  }
  if (!AppState.strategyParams[AppState.strategyId]) {
    AppState.strategyParams[AppState.strategyId] = Object.fromEntries(
      (strategy.paramSchema || []).map((field) => [field.key, field.default]),
    );
  }
  for (const schema of strategy.paramSchema || []) target.append(createField(schema));
}

function readParams() {
  rememberVisibleParams();
  return { ...(AppState.strategyParams[AppState.strategyId] || {}) };
}

function validateParams() {
  const strategy = currentStrategy();
  if (!strategy) return false;
  let valid = true;
  for (const field of strategy.paramSchema || []) {
    const control = byId(`strategy-param-${field.key}`);
    if (!control) { valid = false; continue; }
    let fieldValid;
    if (field.type === 'select' || field.type === 'enum') {
      fieldValid = (field.options || []).map((option) => schemaOption(option).value).includes(control.value);
    } else {
      const value = convertParamValue(field, control.value, 'internal');
      const step = finiteNumber(field.step);
      const stepBase = Number.isFinite(field.min) ? field.min : 0;
      const stepUnits = Number.isFinite(step) && step > 0 ? (value - stepBase) / step : 0;
      const onStep = !Number.isFinite(step) || step <= 0
        || Math.abs(stepUnits - Math.round(stepUnits)) <= 1e-9 * Math.max(1, Math.abs(stepUnits));
      fieldValid = Number.isFinite(value)
        && (field.min === undefined || value >= field.min)
        && (field.max === undefined || value <= field.max)
        && onStep;
    }
    control.setAttribute('aria-invalid', String(!fieldValid));
    valid = valid && fieldValid;
  }
  return valid;
}

function readAllocation() {
  return {
    stock: finiteNumber(byId('allocation-stock').value) / 100,
    bond: finiteNumber(byId('allocation-bond').value) / 100,
    bill: finiteNumber(byId('allocation-bill').value) / 100,
  };
}

function allocationInputs() {
  return {
    stock: byId('allocation-stock'),
    bond: byId('allocation-bond'),
    bill: byId('allocation-bill'),
  };
}

function strategyManagesAllocation(strategy = currentStrategy()) {
  return Boolean(strategy && typeof strategy.initialAllocation === 'function');
}

function saveManualAllocation() {
  for (const [asset, input] of Object.entries(allocationInputs())) {
    AppState.manualAllocationValues[asset] = input.value;
  }
}

function restoreManualAllocation() {
  for (const [asset, input] of Object.entries(allocationInputs())) {
    input.value = AppState.manualAllocationValues[asset];
  }
}

function validAllocationOrFallback(allocation) {
  const values = Object.values(allocation);
  const sum = values.reduce((total, value) => total + value, 0);
  return values.every((value) => Number.isFinite(value) && value >= 0 && value <= 1)
    && Math.abs(sum - 1) < 1e-9
    ? allocation
    : { stock: 1, bond: 0, bill: 0 };
}

function updateAllocationMode() {
  const managed = strategyManagesAllocation();
  const inputs = allocationInputs();
  if (managed && !AppState.allocationManaged) saveManualAllocation();
  if (!managed && AppState.allocationManaged) restoreManualAllocation();
  AppState.allocationManaged = managed;
  for (const input of Object.values(inputs)) input.disabled = managed;
  if (!managed) return;

  const manual = {
    stock: finiteNumber(AppState.manualAllocationValues.stock) / 100,
    bond: finiteNumber(AppState.manualAllocationValues.bond) / 100,
    bill: finiteNumber(AppState.manualAllocationValues.bill) / 100,
  };
  const resolved = globalThis.BacktestEngine.resolveInitialAllocation(
    currentStrategy(),
    readParams(),
    {
      startingBalance: finiteNumber(byId('starting-balance').value),
      allocation: validAllocationOrFallback(manual),
      feeRate: finiteNumber(byId('fee-rate').value) / 100,
      taxRate: finiteNumber(byId('tax-rate').value) / 100,
      billSeries: byId('bill-series').value,
      horizon: finiteNumber(byId('horizon').value),
    },
  );
  for (const [asset, input] of Object.entries(inputs)) {
    input.value = String(Number((resolved[asset] * 100).toPrecision(12)));
  }
  const status = byId('allocation-status');
  status.className = 'allocation-status managed';
  status.textContent = `Strategy managed · stocks ${fmtPct(resolved.stock)}, bonds ${fmtPct(resolved.bond)}, bills ${fmtPct(resolved.bill)}. Opening weights follow the method and are read-only.`;
}

function readOptions() {
  return {
    startingBalance: finiteNumber(byId('starting-balance').value),
    allocation: readAllocation(),
    feeRate: finiteNumber(byId('fee-rate').value) / 100,
    taxRate: finiteNumber(byId('tax-rate').value) / 100,
    billSeries: byId('bill-series').value,
    display: AppState.display,
    horizon: finiteNumber(byId('horizon').value),
    startYear: finiteNumber(byId('start-year').value),
  };
}

function liveYearOneBaseline() {
  const select = byId('start-year');
  const year = select.disabled ? AppState.yearRange.first : Number(select.value);
  const row = globalThis.MARKET_DATA.rows.find(candidate => candidate.year === year);
  if (!row || !currentStrategy()) return null;
  const result = globalThis.BacktestEngine.simulate([row], currentStrategy(), readParams(), { ...readOptions(), horizon: 1 });
  return result.metrics.spending.baseline;
}

function updateNeedReadout() {
  const baseline = liveYearOneBaseline();
  const readout = needReadout(AppState.need, baseline);
  const linked = byId(AppState.need.anchor === 'percent' ? 'need-amount' : 'need-percent');
  if (document.activeElement !== linked && linked.getAttribute('aria-invalid') !== 'true') {
    linked.value = AppState.need.anchor === 'percent' ? readout.dollars ?? ''
      : baseline > 0 && readout.dollars != null ? Number((readout.dollars / baseline * 100).toPrecision(12)) : '';
  }
  if (['need-amount', 'need-percent'].some(id => byId(id).getAttribute('aria-invalid') === 'true')) return;
  byId('need-status').textContent = 'Need ' + readout.amountText + ' real/yr · ' + readout.percentText
    + ' of the live configuration’s year-1 spending (' + fmtMoney(baseline) + '). Pinned comparisons use the same '
    + readout.amountText + '.' + (readout.followsConfiguration ? ' Follows the live configuration — enter dollars to hold it fixed.' : '');
}

function editNeed(anchor) {
  const input = byId(anchor === 'dollars' ? 'need-amount' : 'need-percent');
  const value = Number(input.value);
  const valid = input.value.trim() !== '' && Number.isFinite(value) && value >= 0 && (anchor === 'dollars' || value <= 200);
  input.setAttribute('aria-invalid', String(!valid));
  if (!valid) {
    byId('need-status').textContent = anchor === 'dollars' ? 'Enter a spending need of zero or more real dollars.' : 'Enter a spending need between 0% and 200% of year 1.';
    return;
  }
  AppState.need = anchor === 'dollars' ? { anchor, amount: value } : { anchor, ratio: value / 100 };
  const other = byId(anchor === 'dollars' ? 'need-percent' : 'need-amount');
  other.setAttribute('aria-invalid', 'false');
  scheduleRecalculate();
}

function validateAllocation() {
  const allocation = readAllocation();
  const values = Object.values(allocation);
  const sum = values.reduce((total, value) => total + value, 0);
  const validParts = values.every((value) => Number.isFinite(value) && value >= 0 && value <= 1);
  const valid = validParts && Math.abs(sum - 1) < 1e-9;
  AppState.allocationValid = valid;
  const status = byId('allocation-status');
  if (!AppState.allocationManaged) {
    status.className = `allocation-status${valid ? '' : ' invalid'}`;
    status.textContent = Number.isFinite(sum)
      ? `Allocation totals ${(sum * 100).toLocaleString('en-US', { maximumFractionDigits: 2 })}%.${valid ? '' : ' Enter exactly 100%.'}`
      : 'Allocation contains an invalid value. Enter exactly 100%.';
  }
  for (const input of document.querySelectorAll('[data-allocation]')) input.setAttribute('aria-invalid', String(!valid));
  return valid;
}

function validateSharedInputs() {
  const fields = [
    { id: 'starting-balance', valid: (value) => value > 0 },
    { id: 'fee-rate', valid: (value) => value >= 0 && value <= 100 },
    { id: 'tax-rate', valid: (value) => value >= 0 && value <= 95 },
    { id: 'horizon', valid: (value) => Number.isInteger(value) && value >= 1 && value <= 100 },
  ];
  let valid = true;
  for (const field of fields) {
    const input = byId(field.id);
    const fieldValid = Number.isFinite(finiteNumber(input.value)) && field.valid(finiteNumber(input.value));
    input.setAttribute('aria-invalid', String(!fieldValid));
    valid = valid && fieldValid;
  }
  return valid;
}

function firstUsableYearForAsset(asset) {
  const column = globalThis.BacktestEngine.returnColumns(byId('bill-series').value)[asset];
  if (!column || !globalThis.MARKET_DATA || !Array.isArray(globalThis.MARKET_DATA.rows)) return null;
  const match = globalThis.MARKET_DATA.rows
    .filter((row) => row && Number.isFinite(row.year) && Number.isFinite(row[column]) && row[column] >= -1)
    .sort((left, right) => left.year - right.year)[0];
  return match ? match.year : null;
}

function populateStartYears(range) {
  const select = byId('start-year');
  const prior = finiteNumber(select.value);
  const fragment = document.createDocumentFragment();
  if (!Number.isSafeInteger(range.first) || !Number.isSafeInteger(range.last) || range.first > range.last) {
    select.replaceChildren();
    select.disabled = true;
    return;
  }
  for (let year = range.first; year <= range.last; year += 1) {
    const option = document.createElement('option');
    option.value = String(year);
    option.textContent = String(year);
    fragment.append(option);
  }
  select.replaceChildren(fragment);
  select.disabled = false;
  const fallback = range.last;
  const chosen = Number.isFinite(prior) ? Math.min(range.last, Math.max(range.first, prior)) : fallback;
  select.value = String(chosen);
}

function updateYearRange() {
  const note = byId('range-note');
  if (!validateAllocation()) {
    note.className = 'range-note error';
    note.textContent = 'Correct the allocation before the usable year range can be calculated.';
    return false;
  }
  const strategy = currentStrategy();
  if (!strategy || !globalThis.BacktestEngine || typeof globalThis.BacktestEngine.availableYearRange !== 'function') {
    throw new Error('The simulation engine is unavailable.');
  }
  if (!globalThis.MARKET_DATA || !Array.isArray(globalThis.MARKET_DATA.rows)) {
    throw new Error('The historical market dataset is unavailable.');
  }
  const range = globalThis.BacktestEngine.availableYearRange(
    strategy,
    readParams(),
    globalThis.MARKET_DATA.rows,
    { allocation: readAllocation(), billSeries: byId('bill-series').value },
  );
  AppState.yearRange = range;
  populateStartYears(range);
  note.className = 'range-note';
  if (range.first === null || range.last === null) {
    note.className = 'range-note error';
    note.textContent = 'No contiguous years support this strategy and allocation.';
    return false;
  }
  const restrictions = (range.excludedAssets || []).map((asset) => {
    const begins = firstUsableYearForAsset(asset);
    return `${HUMAN_LABELS[asset] || asset}${begins === null ? ' is unavailable' : ` data begins in ${begins}`}`;
  });
  note.textContent = restrictions.length
    ? `${restrictions.join('; ')}. Usable record: ${range.first}–${range.last}.`
    : `Usable record: ${range.first}–${range.last}. No funded asset shortens the range.`;
  return true;
}

function setStatus(message, isError = false) {
  byId('app-status').classList.toggle('error', isError);
  byId('app-status-message').textContent = message;
}

function replaceWithMessage(target, message) {
  target.className = 'empty-window';
  const copy = document.createElement('p');
  copy.textContent = message;
  target.replaceChildren(copy);
}

const WINDOW_LIFESTYLE_LABEL = 'Lifestyle · real after-tax · retirement-start dollars · always real';

function renderStatGroup(labelText, cells, lifestyle = false) {
  const group = document.createElement('div');
  group.className = 'stat-group ' + (lifestyle ? 'lifestyle-group' : 'solvency-group');
  const heading = document.createElement('div');
  heading.className = 'stat-group-label';
  heading.textContent = labelText;
  const content = document.createElement('div');
  content.className = 'stat-group-cells';
  for (const cell of cells) {
    const stat = document.createElement('div');
    stat.className = 'stat';
    if (cell.label === 'Spending range') stat.classList.add('spending-range-stat');
    const label = document.createElement('div');
    label.className = 'stat-label';
    label.textContent = cell.label;
    const value = document.createElement('div');
    value.className = 'stat-value' + (cell.className ? ' ' + cell.className : '');
    value.textContent = cell.value ?? (cell.format === 'money' ? fmtMoneyCompact(cell.rawValue)
      : cell.format === 'percent' ? fmtPct(cell.rawValue) : cell.rawValue);
    const detail = document.createElement('div');
    detail.className = 'stat-detail';
    detail.textContent = cell.detail;
    stat.append(label, value, detail);
    content.append(stat);
  }
  group.append(heading, content);
  return group;
}

function renderUnavailableStats(detail, targetId = 'window-stats') {
  const labels = targetId === 'window-stats' ? ['Outcome', 'Terminal wealth · real', 'Max real drawdown']
    : ['Survived', 'Worst solvency start', 'Terminal wealth · real'];
  const cells = labels.map((label, index) => ({ label, value: '—', detail: index ? 'not calculated' : detail }));
  const windowMode = targetId === 'window-stats';
  const lifestyleCells = (windowMode ? windowLifestyleCells({}, null) : sweepLifestyleCells({}))
    .map(cell => ({ ...cell, value: '—', detail: 'not calculated' }));
  byId(targetId).replaceChildren(renderStatGroup(windowMode ? 'Portfolio' : 'Solvency', cells),
    renderStatGroup(windowMode ? WINDOW_LIFESTYLE_LABEL : 'Lifestyle · across 0 complete windows · partial windows held out', lifestyleCells, true));
}

function renderStatsBand(metrics, display = 'real', needDollars = null) {
  byId('window-stats').replaceChildren(
    renderStatGroup('Portfolio', windowStatsModel(metrics, display)),
    renderStatGroup(WINDOW_LIFESTYLE_LABEL, windowLifestyleCells(metrics, needDollars), true));
}

function stackedAreaPath(points, topValue, lowerValue, xOf, yOf) {
  const upper = points.map((point, index) => `${index ? 'L' : 'M'} ${xOf(index)} ${yOf(topValue(point))}`).join(' ');
  const lower = points.slice().reverse().map((point, reverseIndex) => {
    const index = points.length - reverseIndex - 1;
    return `L ${xOf(index)} ${yOf(lowerValue(point))}`;
  }).join(' ');
  return `${upper} ${lower} Z`;
}

function renderBalanceChart(rows, metrics, display) {
  const figure = document.createElement('figure');
  figure.className = 'balance-figure';
  const heading = document.createElement('div');
  heading.className = 'chart-heading';
  const title = document.createElement('h4');
  title.textContent = 'Portfolio balance by sleeve';
  const basis = document.createElement('p');
  basis.textContent = `${display} balances · end of year`;
  heading.append(title, basis);

  const wrap = document.createElement('div');
  wrap.className = 'balance-chart-wrap';
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.classList.add('balance-chart');
  svg.setAttribute('viewBox', '0 0 1000 200');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-labelledby', 'window-chart-title window-chart-desc');

  const points = chartSeries(rows, display);
  const endpoint = points[points.length - 1];
  svg.dataset.endTotal = String(endpoint.stock + endpoint.bond + endpoint.bill);
  const W = 1000;
  const H = 200;
  const padTop = 10;
  const padBottom = 10;
  const maxTotal = Math.max(1, ...points.map((point) => point.stock + point.bond + point.bill));
  const chartMax = maxTotal * 1.06;
  const xOf = (index) => points.length === 1 ? W / 2 : index / (points.length - 1) * W;
  const yOf = (value) => padTop + (1 - Math.max(0, value) / chartMax) * (H - padTop - padBottom);
  const stockTop = (point) => point.stock;
  const bondTop = (point) => point.stock + point.bond;
  const billTop = (point) => point.stock + point.bond + point.bill;
  const zero = () => 0;
  const seam = findQualitySeam(rows);
  const seamX = seam ? seam.index / rows.length * W : null;
  const failureIndex = rows.findIndex((row) => row.failed);
  const failureX = failureIndex >= 0 ? xOf(failureIndex + 1) : null;
  const gridLines = [0, 0.5, 1].map((fraction) => {
    const y = yOf(chartMax * fraction);
    return `<line x1="0" y1="${y}" x2="1000" y2="${y}" stroke="var(--chart-grid)" stroke-width="0.7" opacity="0.72"/>`;
  }).join('');
  svg.innerHTML = `
    <title id="window-chart-title">Portfolio balance by asset sleeve</title>
    <desc id="window-chart-desc">Stacked ${display} balances for stocks, ten-year bonds, and Treasury bills across the selected historical window.</desc>
    <defs>
      <linearGradient id="window-stock-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--chart-stock)" stop-opacity="0.9"/><stop offset="1" stop-color="var(--chart-stock)" stop-opacity="0.58"/></linearGradient>
      <linearGradient id="window-bond-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--chart-bond)" stop-opacity="0.86"/><stop offset="1" stop-color="var(--chart-bond)" stop-opacity="0.55"/></linearGradient>
      <linearGradient id="window-bill-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--chart-bill)" stop-opacity="0.78"/><stop offset="1" stop-color="var(--chart-bill)" stop-opacity="0.48"/></linearGradient>
    </defs>
    ${gridLines}
    <path d="${stackedAreaPath(points, billTop, bondTop, xOf, yOf)}" fill="url(#window-bill-fill)"/>
    <path d="${stackedAreaPath(points, bondTop, stockTop, xOf, yOf)}" fill="url(#window-bond-fill)"/>
    <path d="${stackedAreaPath(points, stockTop, zero, xOf, yOf)}" fill="url(#window-stock-fill)"/>
    ${seamX === null ? '' : `<line x1="${seamX}" y1="5" x2="${seamX}" y2="195" stroke="var(--chart-seam)" stroke-width="1.2" stroke-dasharray="4 4"/><text x="${Math.min(990, seamX + 7)}" y="19" fill="var(--chart-seam-label)" font-family="SFMono-Regular, Menlo, Consolas, monospace" font-size="9">published record · ${seam.year}</text>`}
    ${failureX === null ? '' : `<line x1="${failureX}" y1="5" x2="${failureX}" y2="195" stroke="var(--chart-fail)" stroke-width="1.8" stroke-dasharray="3 3"/><text x="${Math.max(10, failureX - 7)}" y="190" fill="var(--chart-fail)" font-family="Iowan Old Style, Baskerville, Palatino Linotype, Book Antiqua, Georgia, serif" font-style="italic" font-size="11" text-anchor="end">failed · ${metrics.failureYear}</text>`}
  `;

  const yLabels = document.createElement('div');
  yLabels.className = 'chart-y-labels';
  for (const [top, label] of [[padTop, fmtMoneyCompact(chartMax)], [H / 2, fmtMoneyCompact(chartMax / 2)], [H - padBottom, '$0']]) {
    const item = document.createElement('span');
    item.className = 'chart-y-label';
    item.style.top = `${top}px`;
    item.textContent = label;
    yLabels.append(item);
  }
  wrap.append(svg, yLabels);

  const xLabels = document.createElement('div');
  xLabels.className = 'chart-x-labels';
  const middle = rows[Math.floor((rows.length - 1) / 2)];
  for (const year of [rows[0].year, middle.year, rows[rows.length - 1].year]) {
    const label = document.createElement('span');
    label.textContent = String(year);
    xLabels.append(label);
  }
  const legend = document.createElement('figcaption');
  legend.className = 'chart-legend';
  for (const [className, labelText] of [['stock', 'US stocks'], ['bond', '10-year bonds'], ['bill', 'Treasury bills']]) {
    const item = document.createElement('span');
    item.className = className;
    item.textContent = labelText;
    legend.append(item);
  }
  figure.append(heading, wrap, xLabels, legend);
  return figure;
}

/* Marked years carry their explanation on the cell itself; the visible key
   below the ledger covers sighted users who never hover. */
const RECONSTRUCTED_YEAR_TITLE = 'Reconstructed record — Cowles splice from monthly-average prices, not a published year-end index';

function appendLedgerCell(rowElement, value, className = '', title = '') {
  const cell = document.createElement('td');
  if (className) cell.className = className;
  if (title) {
    cell.title = title;
    cell.setAttribute('aria-description', title);
  }
  cell.textContent = value;
  rowElement.append(cell);
}

/* Returns a key element when the rendered rows actually contain marked
   years, so the page never explains a mark that is not on screen. */
function renderLedgerKey(rows) {
  if (!rows.some((row) => row.quality === 'reconstructed')) return null;
  const key = document.createElement('p');
  key.className = 'ledger-key';
  key.innerHTML = '<span class="quality-mark">Ochre dashed years</span> are reconstructed observations (pre-1928 Cowles splice, monthly-average prices) rather than the published year-end record.';
  return key;
}

function renderWindowTable(rows, display, spending, needDollars) {
  const wrap = document.createElement('div');
  wrap.className = 'ledger-table-wrap';
  wrap.tabIndex = 0;
  wrap.setAttribute('role', 'region');
  wrap.setAttribute('aria-label', 'Scrollable year-by-year portfolio ledger');
  const table = document.createElement('table');
  table.className = 'ledger-table';
  table.innerHTML = `<caption>Year-by-year portfolio ledger</caption><thead><tr>
    <th scope="col">Year</th><th scope="col">Stock return · nominal</th><th scope="col">Bond return · nominal</th><th scope="col">Bill return · nominal</th>
    <th scope="col">Withdrawal · nominal</th><th scope="col">Withdrawal · real</th><th scope="col">Real · % of yr 1</th><th scope="col">Stock balance · ${display}</th><th scope="col">Bond balance · ${display}</th><th scope="col">Bill balance · ${display}</th><th scope="col">Total · ${display}</th><th scope="col">Notes</th>
  </tr></thead>`;
  const body = document.createElement('tbody');
  const floorFlags = ledgerFloorFlags(spending);
  const exported = windowExportRows(rows, spending, needDollars);
  for (const [index, values] of exported.entries()) {
    const row = rows[index];
    const tr = document.createElement('tr');
    if (!row) {
      tr.className = 'unfunded-row';
      appendLedgerCell(tr, String(values.year));
      for (let i = 0; i < 4; i++) appendLedgerCell(tr, '—');
      appendLedgerCell(tr, fmtMoney(values.withdrawal_real));
      appendLedgerCell(tr, fmtPct(values.withdrawal_real_pct_of_year1, 0));
      for (let i = 0; i < 4; i++) appendLedgerCell(tr, '—');
      appendLedgerCell(tr, 'unfunded · $0 real spending', 'notes-cell');
      body.append(tr);
      continue;
    }
    if (floorFlags[index]) tr.classList.add('at-floor');
    if (row.failed) tr.classList.add('failure-row');
    const yearClass = row.quality === 'reconstructed' ? 'quality-mark' : '';
    appendLedgerCell(tr, String(row.year), yearClass, yearClass ? RECONSTRUCTED_YEAR_TITLE : '');
    for (const asset of ['stock', 'bond', 'bill']) {
      const value = row.returnRates[asset];
      appendLedgerCell(tr, fmtPct(value), Number.isFinite(value) ? value > 0 ? 'delta-pos' : value < 0 ? 'delta-neg' : '' : '');
    }
    appendLedgerCell(tr, fmtMoney(row.withdrawalNominal));
    const threshold = Number.isFinite(needDollars) ? needDollars : spending.baseline * .9;
    const below = threshold - row.withdrawalReal > comparisonTolerance(threshold, row.withdrawalReal);
    appendLedgerCell(tr, fmtMoney(row.withdrawalReal), below ? 'delta-neg' : '');
    appendLedgerCell(tr, fmtPct(values.withdrawal_real_pct_of_year1, 0), below ? 'delta-neg' : '');
    appendLedgerCell(tr, fmtMoney(displayBalance(row.endBalances.stock, row, display)));
    appendLedgerCell(tr, fmtMoney(displayBalance(row.endBalances.bond, row, display)));
    appendLedgerCell(tr, fmtMoney(displayBalance(row.endBalances.bill, row, display)));
    appendLedgerCell(tr, fmtMoney(displayBalance(row.endTotal, row, display)), row.failed ? 'delta-neg' : '');
    const notes = normalizeNotes(row.notes);
    if (floorFlags[index]) notes.unshift('floor');
    if (row.failed) notes.unshift(failureNote(row));
    appendLedgerCell(tr, notes.length ? notes.join(' · ') : '—', 'notes-cell');
    body.append(tr);
  }
  table.append(body);
  wrap.append(table);
  return wrap;
}

function renderSpendingStrip(svg) {
  const figure = document.createElement('figure');
  figure.className = 'spending-strip';
  figure.innerHTML = '<div class="chart-heading"><h4>Real spending, year by year</h4><p>always real · after tax · retirement-start dollars</p></div>'
    + svg;
  return figure;
}

function renderWindowMode(snapshot, { signal }) {
  if (signal.aborted) return () => {};
  const sequence = selectWindowRows(
    snapshot.marketRows,
    snapshot.options.startYear,
    snapshot.options.horizon,
    snapshot.yearRange.last,
  );
  if (signal.aborted) return () => {};
  if (!sequence.length) {
    const commitEmptyWindow = function commitWindowMode() {
      renderUnavailableStats('no contiguous rows');
      replaceWithMessage(byId('window-output'), 'No contiguous market rows are available for this selection.');
    };
    commitEmptyWindow.errorMessage = 'No contiguous market rows are available for this selection.';
    return commitEmptyWindow;
  }
  const strategy = globalThis.BacktestEngine.STRATEGIES[snapshot.strategyId];
  if (!strategy) {
    const commitMissingStrategy = function commitWindowMode() {
      renderUnavailableStats('strategy unavailable');
      replaceWithMessage(byId('window-output'), 'The selected withdrawal strategy is unavailable.');
    };
    commitMissingStrategy.errorMessage = 'The selected withdrawal strategy is unavailable.';
    return commitMissingStrategy;
  }
  let result;
  try {
    const engineOptions = {
      startingBalance: snapshot.options.startingBalance,
      allocation: snapshot.options.allocation,
      feeRate: snapshot.options.feeRate,
      taxRate: snapshot.options.taxRate,
      billSeries: snapshot.options.billSeries,
      horizon: snapshot.options.horizon,
    };
    result = globalThis.BacktestEngine.simulate(sequence, strategy, snapshot.params, engineOptions);
  } catch (error) {
    const message = error && error.message ? error.message : 'The selected window could not be simulated.';
    const commitWindowError = function commitWindowMode() {
      renderUnavailableStats('simulation error');
      replaceWithMessage(byId('window-output'), message);
    };
    commitWindowError.errorMessage = message;
    return commitWindowError;
  }
  if (signal.aborted) return () => {};
  const exportModel = immutableSnapshot({
    rows: windowExportRows(result.rows, result.metrics.spending, snapshot.needDollars),
    filename: `market-atlas-window-${result.rows[0].year}-${result.metrics.spending.startYear + result.metrics.spending.path.length - 1}.csv`,
  });
  return function commitWindowMode() {
    renderStatsBand(result.metrics, snapshot.options.display, snapshot.needDollars);
    const output = byId('window-output');
    output.className = 'window-ledger';
    output.replaceChildren(...[
      renderBalanceChart(result.rows, result.metrics, snapshot.options.display),
      renderSpendingStrip(spendingStripSvg(spendingStripModel(result.rows, result.metrics.spending, snapshot.needDollars))),
      renderWindowTable(result.rows, snapshot.options.display, result.metrics.spending, snapshot.needDollars),
      renderLedgerKey(result.rows),
    ].filter(Boolean));
    commitExportModels({ window: exportModel });
  };
}

const SWEEP_COLORS = Object.freeze(['var(--series-1)', 'var(--series-2)', 'var(--series-3)']);
const SweepSafeRateCache = createLruCache(5000);
const SweepGridCache = createLruCache(12);

function configurationOptions(options) {
  return {
    startingBalance: options.startingBalance,
    allocation: { ...options.allocation },
    feeRate: options.feeRate,
    taxRate: options.taxRate,
    billSeries: options.billSeries,
  };
}

function currentSweepConfiguration(snapshot) {
  return {
    id: 'active',
    strategyId: snapshot.strategyId,
    params: { ...snapshot.params },
    options: configurationOptions(snapshot.options),
    color: SWEEP_COLORS[0],
    pinned: false,
  };
}

function strategyConfigurationLabel(configuration) {
  const strategy = globalThis.BacktestEngine.STRATEGIES[configuration.strategyId];
  const model = configurationLabelModel(configuration, strategy, HUMAN_LABELS);
  return `${model.title} · ${model.details}`;
}

function yieldToUi(signal) {
  return new Promise((resolve) => {
    const schedule = typeof requestAnimationFrame === 'function'
      ? requestAnimationFrame
      : (callback) => setTimeout(callback, 0);
    schedule(() => resolve(!signal.aborted));
  });
}

/* The curve and the heatmap report into the same progress element and differ
   only in wording, so the mechanism lives once and the noun is a parameter. */
const SAFE_RATE_PROGRESS_NOUNS = Object.freeze({
  curve: { work: 'sustainable rates', unit: 'complete windows' },
  heatmap: { work: 'heatmap rates', unit: 'complete cells' },
  frontier: { work: 'frontier values', unit: 'parameter values' },
});

function reportSafeRateProgress(kind, reportProgress, completed, total) {
  const noun = SAFE_RATE_PROGRESS_NOUNS[kind];
  return reportProgress(() => {
    const progress = byId('sweep-progress');
    const cancel = byId('cancel-heatmap');
    if (!progress) return;
    progress.hidden = total === 0 || completed >= total;
    if (cancel) cancel.hidden = progress.hidden;
    progress.textContent = total ? `Calculating ${noun.work} · ${completed} of ${total} ${noun.unit}` : '';
  });
}

function cachedHeatmapGrid(snapshot, configuration, strategy, range, generation) {
  const key = stableStringify({
    type: 'heatmap-grid',
    configuration,
    first: range.first,
    last: range.last,
    generation,
  });
  if (SweepGridCache.has(key)) return SweepGridCache.get(key).map((cell) => ({ ...cell }));
  const grid = globalThis.BacktestEngine.sweepGrid(
    snapshot.marketRows,
    HEATMAP_HORIZONS,
    strategy,
    configuration.params,
    configuration.options,
  ).filter((cell) => cell.startYear >= range.first && cell.startYear <= range.last);
  SweepGridCache.set(key, grid);
  return grid.map((cell) => ({ ...cell }));
}

/* Both safe-rate passes -- the start-year curve and the heatmap grid -- do the
   same work: build the year sequence, consult the shared cache, run the engine,
   account for progress, and yield to the UI often enough to stay cancellable.
   They previously carried two near-identical copies of that loop, so a fix to
   cache handling or cancellation reached only one of them. One worker now; the
   callers supply what genuinely differs.

   job: { key, startYear, horizon, strategy, params, options, assign(rate) }
   `cachedCount` is the number of jobs already satisfied from cache, so progress
   starts partway along instead of jumping. */
async function runProgressiveJobs(kind, jobs, cachedCount, signal, reportProgress) {
  const total = cachedCount + jobs.length;
  let completed = cachedCount;
  reportSafeRateProgress(kind, reportProgress, completed, total);
  for (const job of jobs) {
    if (signal.aborted) return false;
    job.assign(job.run());
    completed += 1;
    reportSafeRateProgress(kind, reportProgress, completed, total);
    if (completed % job.chunkWeight === 0) await yieldToUi(signal);
  }
  reportSafeRateProgress(kind, reportProgress, completed, total);
  return !signal.aborted;
}

async function runSafeRateJobs(kind, jobs, cachedCount, signal, reportProgress) {
  const progressiveJobs = jobs.map(job => ({
    chunkWeight: job.strategy.safeRateSearch === 'adaptive' ? 1 : 6,
    assign: job.assign,
    run() {
      if (SweepSafeRateCache.has(job.key)) return SweepSafeRateCache.get(job.key);
      const rate = globalThis.BacktestEngine.maxSafeRate(
        job.sequence, job.strategy, job.params,
        { ...job.options, horizon: job.horizon }, { adaptiveStep: 0.001 },
      );
      SweepSafeRateCache.set(job.key, rate);
      return rate;
    },
  }));
  return runProgressiveJobs(kind, progressiveJobs, cachedCount, signal, reportProgress);
}

function safeRateSequence(rowsByYear, startYear, horizon) {
  const sequence = [];
  for (let offset = 0; offset < horizon; offset += 1) {
    const row = rowsByYear.get(startYear + offset);
    if (!row) break;
    sequence.push(row);
  }
  return sequence;
}

async function attachHeatmapSafeRates(cells, configuration, strategy, snapshot, signal, reportProgress, generation) {
  const rowsByYear = new Map(snapshot.marketRows.map((row) => [row.year, row]));
  for (const cell of cells) {
    cell.key = sweepConfigurationKey(configuration, cell.horizon, cell.startYear, generation);
  }
  const completeCount = cells.filter((cell) => !(cell.partial || cell.metrics.partial)).length;
  const pending = heatmapSafeRateJobs(cells, SweepSafeRateCache);
  const jobs = pending.map((cell) => ({
    key: cell.key,
    startYear: cell.startYear,
    horizon: cell.horizon,
    strategy,
    params: configuration.params,
    options: configuration.options,
    sequence: safeRateSequence(rowsByYear, cell.startYear, cell.horizon),
    assign(rate) { cell.maxSafeRate = rate; },
  }));
  return runSafeRateJobs('heatmap', jobs, completeCount - jobs.length, signal, reportProgress);
}

async function attachSafeRates(series, snapshot, signal, reportProgress) {
  const rowsByYear = new Map(snapshot.marketRows.map((row) => [row.year, row]));
  const generation = marketGeneration(snapshot.marketRows, globalThis.MARKET_DATA && globalThis.MARKET_DATA.generated);
  const horizon = snapshot.options.horizon;
  const jobs = [];
  for (const item of series) {
    if (!item.strategy.supportsMaxSafeRate) continue;
    for (const result of item.results) {
      if (result.partial || result.metrics.partial) continue;
      jobs.push({
        key: sweepConfigurationKey(item.configuration, horizon, result.startYear, generation),
        startYear: result.startYear,
        horizon,
        strategy: item.strategy,
        params: item.configuration.params,
        options: item.configuration.options,
        sequence: safeRateSequence(rowsByYear, result.startYear, horizon),
        assign(rate) { result.maxSafeRate = rate; },
      });
    }
  }
  /* The curve counts every job as outstanding; the worker still short-circuits
     cache hits, they just are not pre-counted the way the heatmap pre-counts. */
  return runSafeRateJobs('curve', jobs, 0, signal, reportProgress);
}

function renderSweepStats(summary, strategy) {
  byId('sweep-stats').replaceChildren(
    renderStatGroup('Solvency', sweepSolvencyCells(summary, strategy)),
    renderStatGroup(`Lifestyle · across ${fmtCount(summary.completeCount)} complete windows · partial windows held out`, sweepLifestyleCells(summary), true));
}

function renderComparisonTray(series) {
  const tray = byId('comparison-tray');
  tray.replaceChildren();
  for (const [index, item] of series.entries()) {
    const chip = document.createElement('div');
    chip.className = 'comparison-chip';
    chip.style.setProperty('--series-color', item.configuration.color);
    const model = configurationLabelModel(item.configuration, item.strategy, HUMAN_LABELS);
    chip.innerHTML = `<span class="series-swatch" aria-hidden="true"></span><span><strong>${index === 0 ? 'Live' : `Pinned ${index}`} · ${escapeHtml(model.title)}</strong><small class="comparison-details">${escapeHtml(model.details)}</small></span>`;
    if (item.configuration.pinned) {
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'chip-remove';
      remove.dataset.removeComparison = String(item.configuration.id);
      remove.setAttribute('aria-label', `Remove ${strategyConfigurationLabel(item.configuration)}`);
      remove.textContent = '×';
      chip.append(remove);
    }
    tray.append(chip);
  }
  byId('add-comparison').disabled = AppState.comparisons.length >= 2;
  byId('clear-comparisons').disabled = AppState.comparisons.length === 0;
}

function sweepDescription(series, commonRange, horizon, usesSafeRate) {
  const summaries = series.map((item) => {
    const summary = item.summary;
    return `${strategyConfigurationLabel(item.configuration)} survived ${summary.survivedCount} of ${summary.completeCount} complete windows; ${summary.partialCount} partial windows are held out; worst opening ${summary.worstStartYear || 'unavailable'}.`;
  });
  const partialNote = !usesSafeRate && series.some((item) => item.summary.partialCount > 0)
    ? ` ${PARTIAL_WEALTH_CAVEAT}`
    : '';
  return `${usesSafeRate ? 'Maximum sustainable initial withdrawal rate' : 'Terminal real wealth'} by start year for a ${horizon}-year horizon, restricted to the shared ${commonRange.first}–${commonRange.last} record. ${summaries.join(' ')}${partialNote}`;
}

function renderSweepChart(series, commonRange, snapshot, usesSafeRate) {
  if (snapshot.sweepChartMetric === 'spending') {
    const figure = document.createElement('figure');
    figure.className = 'sweep-figure';
    figure.innerHTML = `<div class="chart-heading"><h4>Real spending range</h4><p>${snapshot.options.horizon}-year passages · click a point to inspect</p></div><div class="sweep-chart-scroll">${spendingRangeSvg(spendingRangeModel(series, snapshot.needDollars))}</div>`;
    return figure;
  }
  const W = 1000;
  const H = 340;
  const pad = { left: 64, right: 22, top: 34, bottom: 54 };
  const { minimum, maximum } = sweepYDomain(series, usesSafeRate);
  const xOf = (year) => pad.left + ((year - commonRange.first) / Math.max(1, commonRange.last - commonRange.first)) * (W - pad.left - pad.right);
  const yOf = (value) => H - pad.bottom - ((value - minimum) / Math.max(Number.EPSILON, maximum - minimum)) * (H - pad.top - pad.bottom);
  const title = `${usesSafeRate ? 'Sustainable withdrawal rate' : 'Terminal real wealth'} by start year`;
  const description = sweepDescription(series, commonRange, snapshot.options.horizon, usesSafeRate);
  const grid = [0, 0.25, 0.5, 0.75, 1].map((fraction) => {
    const value = maximum * fraction;
    const y = yOf(value);
    const label = usesSafeRate ? fmtPct(value, 1) : fmtMoneyCompact(value);
    return `<line x1="${pad.left}" y1="${y}" x2="${W - pad.right}" y2="${y}" stroke="var(--chart-grid-soft)"/><text x="${pad.left - 9}" y="${y + 3}" text-anchor="end" fill="var(--chart-label)" font-family="SFMono-Regular, Menlo, Consolas, monospace" font-size="9">${escapeHtml(label)}</text>`;
  }).join('');
  const seamYear = cohortStartYear(snapshot.marketRows, 'modern');
  const seamX = Number.isSafeInteger(seamYear) && seamYear >= commonRange.first && seamYear <= commonRange.last ? xOf(seamYear) : null;
  const seam = seamX === null ? '' : `<line x1="${seamX}" y1="${pad.top}" x2="${seamX}" y2="${H - pad.bottom}" stroke="var(--chart-seam)" stroke-dasharray="5 4"/><text x="${Math.min(W - 120, seamX + 7)}" y="${pad.top + 12}" fill="var(--chart-seam-label)" font-family="SFMono-Regular, Menlo, Consolas, monospace" font-size="9">modern record · ${seamYear}</text>`;
  const plotted = series.map((item, seriesIndex) => {
    const lineSegments = contiguousSweepLineSegments(item.results, (result) => {
      if (usesSafeRate) {
        const point = safeRatePointModel(result);
        return point.kind === 'rate' ? point.plotValue : null;
      }
      return result && result.metrics && !result.partial && !result.metrics.partial
        ? result.metrics.terminalWealthReal : null;
    });
    const paths = lineSegments.map((segment) => {
      const path = segment.map((point, index) => `${index ? 'L' : 'M'}${xOf(point.result.startYear).toFixed(2)},${yOf(point.value).toFixed(2)}`).join(' ');
      return `<path d="${path}" fill="none" stroke="${item.configuration.color}" stroke-width="2" stroke-opacity="0.84"/>`;
    }).join('');
    const referenceKey = item.strategy.rateParamKey;
    const reference = usesSafeRate && referenceKey && Number.isFinite(item.configuration.params[referenceKey])
      ? `<line x1="${pad.left}" y1="${yOf(item.configuration.params[referenceKey])}" x2="${W - pad.right}" y2="${yOf(item.configuration.params[referenceKey])}" stroke="${item.configuration.color}" stroke-opacity="0.5" stroke-dasharray="3 5"/>`
      : '';
    const points = item.results.map((result) => {
      const safePoint = usesSafeRate ? safeRatePointModel(result) : null;
      const value = usesSafeRate ? safePoint.plotValue : result.metrics.terminalWealthReal;
      const y = Number.isFinite(value) ? yOf(value) : H - pad.bottom + 15;
      const partial = result.partial || result.metrics.partial;
      const noRate = Boolean(safePoint && safePoint.kind === 'no-rate');
      const fill = partial ? 'var(--chart-seam)' : noRate ? 'var(--chart-bg)' : result.metrics.success ? item.configuration.color : 'var(--chart-fail)';
      const stroke = noRate ? 'var(--chart-fail)' : 'var(--chart-bg)';
      const shapeLabel = safePoint && safePoint.kind !== 'rate'
        ? safePoint.label
        : result.metrics.success ? 'survived' : `failed${result.metrics.failureYear ? ` in ${result.metrics.failureYear}` : ''}`;
      const valueLabel = noRate ? 'No rate survives' : Number.isFinite(value) ? usesSafeRate ? fmtPct(value, 2) : fmtMoney(value) : 'not available for an incomplete window';
      return `<circle class="sweep-point" tabindex="0" role="button" data-series-index="${seriesIndex}" data-start-year="${result.startYear}" cx="${xOf(result.startYear)}" cy="${y}" r="${noRate ? 5 : partial ? 3 : 3.5}" fill="${fill}" stroke="${stroke}" stroke-width="${noRate ? 2 : 1}"><title>${result.startYear}: ${shapeLabel}; ${valueLabel}. Open window.</title></circle>`;
    }).join('');
    return `${reference}${paths}${points}`;
  }).join('');
  const axisYears = [commonRange.first, Math.round((commonRange.first + commonRange.last) / 2), commonRange.last]
    .map((year) => `<text x="${xOf(year)}" y="${H - 18}" text-anchor="middle" fill="var(--chart-label)" font-family="SFMono-Regular, Menlo, Consolas, monospace" font-size="10">${year}</text>`).join('');
  const figure = document.createElement('figure');
  figure.className = 'sweep-figure';
  const partialCaveat = !usesSafeRate && series.some((item) => item.summary.partialCount > 0)
    ? `<p class="chart-caveat">${escapeHtml(PARTIAL_WEALTH_CAVEAT)}</p>`
    : '';
  figure.innerHTML = `<div class="chart-heading"><h4>${escapeHtml(title)}</h4><p>${snapshot.options.horizon}-year passages · click a point to inspect</p></div>${partialCaveat}<div class="sweep-chart-scroll"><svg class="sweep-chart" viewBox="0 0 ${W} ${H}" role="img" aria-labelledby="sweep-chart-title sweep-chart-desc"><title id="sweep-chart-title">${escapeHtml(title)}</title><desc id="sweep-chart-desc">${escapeHtml(description)}</desc>${grid}${seam}${plotted}<line x1="${pad.left}" y1="${H - pad.bottom}" x2="${W - pad.right}" y2="${H - pad.bottom}" stroke="var(--chart-axis)"/>${axisYears}</svg></div>`;
  const legend = document.createElement('figcaption');
  legend.className = 'sweep-legend';
  for (const item of series) {
    const entry = document.createElement('span');
    entry.style.setProperty('--series-color', item.configuration.color);
    entry.innerHTML = `<i class="series-swatch" aria-hidden="true"></i>${escapeHtml(strategyConfigurationLabel(item.configuration))}`;
    legend.append(entry);
  }
  const range = document.createElement('span');
  range.textContent = `Shared intersection ${commonRange.first}–${commonRange.last} · series color survived · oxblood failed · ochre partial/held out`;
  legend.append(range);
  figure.append(legend);
  return figure;
}

function renderSweepSummaryTable(series, needDollars) {
  const wrap = document.createElement('div');
  wrap.className = 'ledger-table-wrap';
  wrap.tabIndex = 0;
  wrap.setAttribute('role', 'region');
  wrap.setAttribute('aria-label', 'Scrollable sweep comparison summary');
  const table = document.createElement('table');
  table.className = 'ledger-table sweep-table';
  const headings = series.map((item) => `<th scope="col">${escapeHtml(strategyConfigurationLabel(item.configuration))}</th>`).join('');
  const rows = sweepSummaryRows(series, needDollars).map((row) => `<tr><th scope="row">${escapeHtml(row.label)}</th>${row.values.map((value) => `<td>${escapeHtml(value)}</td>`).join('')}</tr>`).join('');
  table.innerHTML = `<caption>Sweep comparison summary</caption><thead><tr><th scope="col">Measure</th>${headings}</tr></thead><tbody>${rows}</tbody>`;
  const caveat = document.createElement('p');
  caveat.className = 'chart-caveat';
  caveat.textContent = 'Percentile rows are historical frequencies over overlapping windows, not probabilities.';
  wrap.append(table, caveat);
  return wrap;
}

function renderHeatmap(grid, metric, seamYear, strategy, needDollars) {
  const model = heatmapModel(grid, metric, seamYear, Theme.palette(), needDollars);
  const figure = document.createElement('figure');
  figure.className = 'heatmap-figure';
  const heading = document.createElement('div');
  heading.className = 'chart-heading';
  heading.innerHTML = `<h4>Horizon atlas · live configuration</h4><p>start year → · horizon ↓</p>`;
  const caption = document.createElement('figcaption');
  caption.className = 'heatmap-caption';
  caption.textContent = 'Each square is one overlapping historical window. Partial end-of-record windows are held out, not counted as successes or failures.';
  if (metric === 'floor' || metric === 'belowNeed') caption.textContent += ` ${horizonCaveat(strategy)}`;
  const scroll = document.createElement('div');
  scroll.className = 'heatmap-scroll';
  scroll.setAttribute('role', 'region');
  scroll.setAttribute('aria-label', 'Scrollable start year by horizon heatmap');
  const table = document.createElement('table');
  table.className = 'heatmap-table';
  const cellMap = new Map(model.cells.map((cell) => [`${cell.horizon}:${cell.startYear}`, cell]));
  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  const corner = document.createElement('th');
  corner.scope = 'col';
  corner.textContent = 'Years';
  headRow.append(corner);
  for (const year of model.startYears) {
    const th = document.createElement('th');
    th.scope = 'col';
    th.textContent = year === model.seamYear ? `${year} · modern` : String(year);
    if (year === model.seamYear) th.className = 'quality-seam';
    headRow.append(th);
  }
  const worstHead = document.createElement('th');
  worstHead.scope = 'col';
  worstHead.textContent = 'Worst';
  headRow.append(worstHead);
  head.append(headRow);
  const body = document.createElement('tbody');
  const rowsFragment = document.createDocumentFragment();
  let firstHeatmapCell = true;
  for (const [rowIndex, horizon] of model.horizons.entries()) {
    const tr = document.createElement('tr');
    const rowHead = document.createElement('th');
    rowHead.scope = 'row';
    rowHead.textContent = `${horizon} years`;
    tr.append(rowHead);
    for (const [columnIndex, year] of model.startYears.entries()) {
      const td = document.createElement('td');
      if (year === model.seamYear) td.className = 'quality-seam';
      const cell = cellMap.get(`${horizon}:${year}`);
      if (cell) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `heatmap-cell kind-${cell.kind}`;
        button.dataset.heatmapCell = '';
        button.dataset.startYear = String(year);
        button.dataset.horizon = String(horizon);
        button.dataset.heatmapRow = String(rowIndex);
        button.dataset.heatmapColumn = String(columnIndex);
        button.tabIndex = firstHeatmapCell ? 0 : -1;
        firstHeatmapCell = false;
        button.style.setProperty('--cell-color', cell.color);
        button.style.setProperty('--cell-foreground', cell.foreground);
        button.setAttribute('aria-label', cell.label);
        button.title = cell.label;
        button.textContent = cell.display;
        td.append(button);
      }
      tr.append(td);
    }
    const worst = model.rowWorst?.[rowIndex];
    const worstCell = document.createElement('td');
    worstCell.textContent = worst?.startYear != null ? `${worst.display} · ${worst.startYear}` : '';
    tr.append(worstCell);
    rowsFragment.append(tr);
  }
  body.append(rowsFragment);
  table.append(head, body);
  scroll.append(table);
  const legendModel = heatmapLegendModel(metric, model.domain, strategy.safeRateSearch === 'adaptive', Theme.palette());
  const legend = document.createElement('div');
  legend.className = 'heatmap-legend';
  if (metric !== 'success') {
    const ramp = document.createElement('span');
    ramp.className = 'heatmap-ramp';
    ramp.setAttribute('aria-hidden', 'true');
    ramp.style.setProperty('--heatmap-min', legendModel.colors[0]);
    ramp.style.setProperty('--heatmap-mid', legendModel.colors[1]);
    ramp.style.setProperty('--heatmap-max', legendModel.colors[2]);
    legend.append(ramp);
    for (const tick of legendModel.ticks) {
      const label = document.createElement('span');
      label.textContent = tick.label;
      legend.append(label);
    }
  }
  const description = document.createElement('span');
  description.textContent = legendModel.description;
  legend.append(description);
  if (model.seamYear !== null) {
    const seam = document.createElement('span');
    seam.className = 'heatmap-seam-note';
    seam.textContent = `Dashed rule · modern quality begins ${model.seamYear}`;
    legend.append(seam);
  }
  figure.append(heading, caption, scroll, legend);
  return figure;
}

/* The configuration applier is a factory in views.js so it can be constructed
   with fake controls in tests. It was previously sliced out of this file by
   comment markers and evaluated in a VM sandbox; injecting its dependencies
   removes the need for that entirely. */
const ConfigurationApplier = createConfigurationApplier({
  getStrategies: () => globalThis.BacktestEngine.STRATEGIES,
  state: AppState,
  byId,
  rememberVisibleParams: (...args) => rememberVisibleParams(...args),
  saveManualAllocation: (...args) => saveManualAllocation(...args),
  strategyManagesAllocation: (...args) => strategyManagesAllocation(...args),
  renderSidebar: (...args) => renderSidebar(...args),
  updateHeatmapMetricAvailability: (...args) => updateHeatmapMetricAvailability(...args),
  updateAllocationMode: (...args) => updateAllocationMode(...args),
  updateYearRange: (...args) => updateYearRange(...args),
  openWindow: (...args) => openWindow(...args),
});

function resetFrontierParameter() {
  AppState.frontier.paramKey = null;
  AppState.frontier.override = null;
}

function applyConfigurationToControls(configuration) {
  const previousStrategyId = AppState.strategyId;
  const applied = ConfigurationApplier.applyConfigurationToControls(configuration);
  if (applied && previousStrategyId !== AppState.strategyId) resetFrontierParameter();
  return applied;
}

function openRenderedHeatmapWindow(configuration, startYear, horizon) {
  if (!applyConfigurationToControls(configuration)) return null;
  return openWindow(startYear, horizon);
}

function openSweepPoint(configurationId, startYear, horizon) {
  if (configurationId !== 'active') {
    const configuration = AppState.comparisons.find((item) => String(item.id) === String(configurationId));
    if (configuration) applyConfigurationToControls(configuration);
  }
  return openWindow(startYear, horizon);
}

async function renderSweepMode(snapshot, { signal, reportProgress }) {
  if (signal.aborted) return () => {};
  const active = currentSweepConfiguration(snapshot);
  const configurations = [active, ...snapshot.comparisons.map((comparison, index) => ({
    ...comparison,
    color: SWEEP_COLORS[index + 1],
    pinned: true,
  }))];
  const ranges = configurations.map((configuration) => {
    const strategy = globalThis.BacktestEngine.STRATEGIES[configuration.strategyId];
    return globalThis.BacktestEngine.availableYearRange(strategy, configuration.params, snapshot.marketRows, configuration.options);
  });
  const intersection = intersectYearRanges(ranges);
  const sampleFirst = cohortStartYear(snapshot.marketRows, snapshot.sweepCohort);
  const commonRange = intersection.first === null ? intersection : {
    first: Math.max(intersection.first, sampleFirst),
    last: intersection.last,
  };
  const liveRange = ranges[0] && Number.isSafeInteger(ranges[0].first) ? {
    first: Math.max(ranges[0].first, sampleFirst),
    last: ranges[0].last,
  } : { first: null, last: null };
  if (commonRange.first === null || commonRange.first > commonRange.last) {
    const commitNoRange = function commitSweepMode() {
      lastFrontierInput = null;
      renderUnavailableStats('no shared range', 'sweep-stats');
      replaceWithMessage(byId('sweep-output'), 'The compared configurations have no shared usable historical years.');
      byId('sweep-notice').textContent = 'No common historical range is available.';
    };
    commitNoRange.errorMessage = 'No common historical range is available.';
    return commitNoRange;
  }
  const series = configurations.map((configuration) => {
    const strategy = globalThis.BacktestEngine.STRATEGIES[configuration.strategyId];
    const results = globalThis.BacktestEngine.sweepStartYears(
      snapshot.marketRows,
      snapshot.options.horizon,
      strategy,
      configuration.params,
      configuration.options,
    ).filter((result) => result.startYear >= commonRange.first && result.startYear <= commonRange.last)
      .map((result) => ({ ...result }));
    return { configuration, strategy, results };
  });
  const heatmapMetric = (snapshot.heatmapMetric === 'safe' && !series[0].strategy.supportsMaxSafeRate)
    || (snapshot.heatmapMetric === 'belowNeed' && snapshot.needDollars === null)
    ? 'success' : snapshot.heatmapMetric;
  const usesSafeRate = sweepChartUsesSafeRate(series);
  if (usesSafeRate) {
    const finished = await attachSafeRates(series, snapshot, signal, reportProgress);
    if (!finished || signal.aborted) return () => {};
  }
  for (const item of series) item.summary = summarizeSweep(item.results, usesSafeRate && item.strategy.supportsMaxSafeRate, snapshot.needDollars);
  const generation = marketGeneration(snapshot.marketRows, globalThis.MARKET_DATA && globalThis.MARKET_DATA.generated);
  const heatmapGrid = cachedHeatmapGrid(snapshot, active, series[0].strategy, liveRange, generation);
  if (heatmapMetric === 'safe') {
    const finished = await attachHeatmapSafeRates(
      heatmapGrid, active, series[0].strategy, snapshot, signal, reportProgress, generation,
    );
    if (!finished || signal.aborted) return () => {};
  }
  const renderedHeatmapConfiguration = immutableSnapshot(active);
  const exportSeries = series.map((item) => {
    const labelModel = configurationLabelModel(item.configuration, item.strategy, HUMAN_LABELS);
    return { ...item, label: `${labelModel.title} · ${labelModel.details}` };
  });
  const renderedHeatmapModel = heatmapModel(
    heatmapGrid,
    heatmapMetric,
    cohortStartYear(snapshot.marketRows, 'modern'),
    Theme.palette(),
    snapshot.needDollars,
  );
  const sweepCurveExportModel = immutableSnapshot({
    rows: sweepCurveExportRows(exportSeries, snapshot.needDollars),
    filename: `market-atlas-sweep-curve-${snapshot.options.horizon}y.csv`,
  });
  const sweepHeatmapExportModel = immutableSnapshot({
    rows: heatmapExportRows(renderedHeatmapModel),
    filename: `market-atlas-heatmap-${heatmapMetric}.csv`,
  });
  return function commitSweepMode() {
    renderSweepStats(series[0].summary, series[0].strategy);
    renderComparisonTray(series);
    const seamYear = cohortStartYear(snapshot.marketRows, 'modern');
    const cohortLabel = snapshot.sweepCohort === 'modern' ? `Modern sample begins at the derived quality transition (${seamYear}).` : 'Full record includes reconstructed observations, marked at the quality seam.';
    byId('sweep-notice').textContent = `${cohortLabel} All configurations use the shared ${commonRange.first}–${commonRange.last} intersection; ${series[0].summary.partialCount} recent active windows are held out.`;
    byId('sweep-progress').hidden = true;
    const output = byId('sweep-output');
    // Visibility is a current UI intent: Hide can be clicked while this
    // numerical Sweep snapshot is still computing.
    const frontierUi = immutableSnapshot(AppState.frontier);
    // Reuse the committed body until the independently cancellable frontier
    // replaces it; refreshing Sweep controls must not erase that last result.
    const committedFrontierBody = frontierUi.visible ? output.querySelector('.frontier-body') : null;
    output.className = 'window-ledger';
    output.replaceChildren(
      renderSweepChart(series, commonRange, snapshot, usesSafeRate),
      renderSweepSummaryTable(series, snapshot.needDollars),
      renderHeatmap(heatmapGrid, heatmapMetric, seamYear, series[0].strategy, snapshot.needDollars),
    );
    lastFrontierInput = Object.freeze({
      configurations: immutableSnapshot(configurations), commonRange: immutableSnapshot(commonRange),
      horizon: snapshot.options.horizon, generation, marketRows: snapshot.marketRows,
    });
    output.append(renderFrontierPanel(lastFrontierInput, frontierUi, committedFrontierBody));
    commitExportModels({ sweepCurve: sweepCurveExportModel, sweepHeatmap: sweepHeatmapExportModel });
    const chart = output.querySelector('.sweep-chart');
    const activatePoint = (target) => {
      const point = target.closest && target.closest('.sweep-point');
      if (!point) return;
      const item = series[Number(point.dataset.seriesIndex)];
      openSweepPoint(item.configuration.id, Number(point.dataset.startYear), snapshot.options.horizon);
    };
    chart.addEventListener('click', (event) => activatePoint(event.target));
    chart.addEventListener('keydown', (event) => {
      if (!['Enter', ' '].includes(event.key)) return;
      event.preventDefault();
      activatePoint(event.target);
    });
    const heatmap = output.querySelector('.heatmap-table');
    heatmap.addEventListener('click', (event) => {
      const cell = heatmapCellTarget(event.target);
      if (!cell) return;
      openRenderedHeatmapWindow(renderedHeatmapConfiguration, Number(cell.dataset.startYear), Number(cell.dataset.horizon));
    });
    heatmap.addEventListener('keydown', (event) => {
      const cell = heatmapCellTarget(event.target);
      if (!cell || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
      event.preventDefault();
      moveHeatmapFocus(heatmap, cell, event.key);
    });
    heatmap.addEventListener('focusin', (event) => {
      const cell = heatmapCellTarget(event.target);
      if (cell) setHeatmapRovingCell(heatmap, cell);
    });
  };
}

/* A frontier reads only the last committed Sweep snapshot. Its coordinator
   owns transient progress, never the Sweep's committed figures or exports. */
function frontierEntries(input, paramKey, override) {
  const each = paramKey === '__each__';
  return input.configurations.filter((configuration, index) => each || index === 0).map(configuration => {
    const strategy = globalThis.BacktestEngine.STRATEGIES[configuration.strategyId];
    const key = each ? strategy.frontierParamKey : paramKey;
    const plan = frontierPlan(strategy, configuration.params, key, override);
    if (plan.error) throw new Error(plan.error);
    return { configuration, strategy, plan };
  });
}

function renderFrontierPanel(input, frontierState, committedBody = null) {
  const figure = document.createElement('figure');
  figure.className = 'sweep-figure frontier-figure';
  const headingRow = document.createElement('div');
  headingRow.className = 'chart-heading';
  const heading = document.createElement('h4');
  heading.textContent = 'Worst real floor by parameter value';
  headingRow.append(heading);
  const controls = document.createElement('div');
  controls.className = 'frontier-controls';
  const strategy = globalThis.BacktestEngine.STRATEGIES[input.configurations[0].strategyId];
  const numeric = strategy.paramSchema.filter(field => field.type !== 'select' && field.type !== 'enum');
  const choices = [];
  if (input.configurations.every(configuration => globalThis.BacktestEngine.STRATEGIES[configuration.strategyId].frontierParamKey)) {
    choices.push({ key: '__each__', label: 'Initial rate (each configuration)' });
  }
  choices.push(...numeric);
  let paramKey = choices.some(field => field.key === frontierState.paramKey) ? frontierState.paramKey : choices[0]?.key;
  let override = frontierState.override ? { ...frontierState.override } : null;
  const selectField = document.createElement('div');
  selectField.className = 'compact-field frontier-parameter';
  const selectLabel = document.createElement('label');
  selectLabel.htmlFor = 'frontier-param';
  selectLabel.textContent = 'Parameter';
  const select = document.createElement('select');
  select.id = 'frontier-param';
  for (const field of choices) {
    const option = document.createElement('option');
    option.value = field.key; option.textContent = field.label || field.key;
    select.append(option);
  }
  select.value = paramKey || '';
  selectField.append(selectLabel, select); controls.append(selectField);
  const fields = {};
  for (const key of ['from', 'to', 'step']) {
    const group = document.createElement('div');
    group.className = 'compact-field frontier-range';
    const label = document.createElement('label');
    label.htmlFor = `frontier-${key}`;
    label.textContent = key[0].toUpperCase() + key.slice(1);
    const field = document.createElement('input');
    field.id = `frontier-${key}`; field.type = 'number'; field.step = 'any';
    group.append(label, field); controls.append(group); fields[key] = field;
    field.addEventListener('input', () => {
      const entries = frontierEntries(input, paramKey, null);
      const multiplier = entries[0].plan.isPercent ? 100 : 1;
      override = { ...override, [key]: field.value.trim() === '' ? NaN : Number(field.value) / multiplier };
    });
  }
  const run = document.createElement('button');
  run.id = 'frontier-run'; run.type = 'button'; run.className = 'small-button';
  run.textContent = frontierState.visible ? 'Recompute' : 'Compute frontier';
  const hide = document.createElement('button');
  hide.id = 'frontier-hide'; hide.type = 'button'; hide.textContent = 'Hide'; hide.className = 'small-button';
  hide.hidden = !frontierState.visible;
  const body = committedBody || document.createElement('div');
  body.className = 'frontier-body'; body.hidden = !frontierState.visible;
  function fillDefaults() {
    try {
      const { plan } = frontierEntries(input, paramKey, null)[0];
      const values = { ...plan.range, ...override };
      for (const key of Object.keys(fields)) {
        fields[key].value = String(Number((values[key] * (plan.isPercent ? 100 : 1)).toPrecision(12)));
        fields[key].previousElementSibling.textContent = key[0].toUpperCase() + key.slice(1) + (plan.isPercent ? ' (%)' : '');
      }
      run.disabled = false;
    } catch (error) { run.disabled = true; setStatus(error.message, true); }
  }
  select.addEventListener('change', () => {
    paramKey = select.value; override = null; fillDefaults();
  });
  run.addEventListener('click', () => {
    if (AppState.stageInFlight === 'sweep') return;
    try {
      frontierEntries(input, paramKey, override);
      AppState.frontier = { visible: true, paramKey, override: override ? { ...override } : null };
      body.hidden = false; hide.hidden = false; run.textContent = 'Recompute';
      scheduleFrontier(lastFrontierInput);
    } catch (error) { setStatus(error.message, true); }
  });
  hide.addEventListener('click', () => {
    AppState.frontier.visible = false;
    if (AppState.stageInFlight === 'frontier') {
      FrontierCoordinator.cancelCurrent(); AppState.stageInFlight = null; stageRequest = null;
    }
    body.hidden = true; hide.hidden = true; run.textContent = 'Compute frontier';
  });
  fillDefaults();
  controls.append(run, hide); figure.append(headingRow, controls, body);
  return figure;
}

function scheduleFrontier(input) {
  if (!input || AppState.stageInFlight === 'sweep') return;
  const state = immutableSnapshot(AppState.frontier);
  const request = FrontierCoordinator.begin();
  void runFrontierStage(Object.freeze({ ...input, frontier: state }), request);
}

async function runFrontierStage(input, request) {
  AppState.stageInFlight = 'frontier';
  stageRequest = request;
  try {
    const paramKey = input.frontier.paramKey || (input.configurations.every(configuration => globalThis.BacktestEngine.STRATEGIES[configuration.strategyId].frontierParamKey)
      ? '__each__' : globalThis.BacktestEngine.STRATEGIES[input.configurations[0].strategyId].paramSchema.find(field => field.type !== 'select' && field.type !== 'enum')?.key);
    const entries = frontierEntries(input, paramKey, input.frontier.override);
    const jobs = [];
    let cachedCount = 0;
    const fixedLast = input.commonRange.last - input.horizon + 1;
    const perSeries = entries.map(({ configuration, strategy, plan }) => {
      const label = configurationLabelModel(configuration, strategy, HUMAN_LABELS);
      const points = plan.values.map(value => {
        const point = { value, lifestyle: null };
        const varied = { ...configuration, params: { ...configuration.params, [plan.key]: value } };
        const key = sweepConfigurationKey(varied, input.horizon, `frontier:${input.commonRange.first}-${fixedLast}`, input.generation);
        if (FrontierCache.has(key)) {
          point.lifestyle = FrontierCache.get(key); cachedCount += 1;
        } else jobs.push({
          chunkWeight: 1,
          assign(lifestyle) { point.lifestyle = lifestyle; },
          run() {
            const results = globalThis.BacktestEngine.sweepStartYears(
              input.marketRows, input.horizon, strategy, varied.params, configuration.options,
            ).filter(result => result.startYear >= input.commonRange.first && result.startYear <= fixedLast);
            const lifestyle = summarizeSweep(results, false, null).lifestyle;
            FrontierCache.set(key, lifestyle);
            return lifestyle;
          },
        });
        return point;
      });
      return { label: `${configuration.id === 'active' ? 'Live' : `Pinned ${configuration.id}`} · ${label.title}`, color: configuration.color,
        startingBalance: configuration.options.startingBalance, isPercent: plan.isPercent,
        paramLabel: paramKey === '__each__' ? 'Initial rate (each configuration)' : plan.label, points };
    });
    const reportProgress = commit => FrontierCoordinator.commitTransient(request, commit);
    const finished = await runProgressiveJobs('frontier', jobs, cachedCount, request.signal, reportProgress);
    if (!finished || !FrontierCoordinator.isCurrent(request)) return;
    const model = frontierModel(perSeries);
    FrontierCoordinator.commitTransient(request, () => {
      const body = document.querySelector('.frontier-figure .frontier-body');
      if (!body) return;
      const caption = document.createElement('figcaption');
      caption.className = 'chart-caveat';
      caption.textContent = `Solid: worst floor across all ${model.windowCount} fixed windows (a failure counts as $0) · dashed: median floor · counts: windows that failed at that value.`;
      const scroll = document.createElement('div'); scroll.className = 'sweep-chart-scroll';
      scroll.innerHTML = frontierSvg(model);
      body.replaceChildren(caption, scroll); body.hidden = false;
      setStatus('Frontier calculated.');
    });
  } catch (error) {
    if (FrontierCoordinator.isCurrent(request)) setStatus(error.message || 'Frontier could not be calculated.', true);
  } finally {
    if (AppState.stageInFlight === 'frontier' && stageRequest === request) {
      AppState.stageInFlight = null; stageRequest = null;
      if (FrontierCoordinator.isCurrent(request)) resetFrontierProgress();
    }
  }
}

function registerRenderer(mode, renderer) {
  if (!Object.prototype.hasOwnProperty.call(Renderers, mode)) throw new RangeError('Unknown render mode.');
  if (renderer !== null && typeof renderer !== 'function') throw new TypeError('Renderer must be a function or null.');
  Renderers[mode] = renderer;
  scheduleRecalculate();
}

async function renderActiveMode(request) {
  const renderer = Renderers[AppState.mode];
  if (typeof renderer === 'function') {
    const snapshot = immutableSnapshot({
      mode: AppState.mode,
      strategyId: AppState.strategyId,
      params: readParams(),
      options: readOptions(),
      yearRange: AppState.yearRange,
      marketRows: globalThis.MARKET_DATA.rows,
      sweepCohort: AppState.sweepCohort,
      heatmapMetric: AppState.heatmapMetric,
      sweepChartMetric: AppState.sweepChartMetric,
      comparisons: AppState.comparisons,
      needDollars: resolveNeed(AppState.need, liveYearOneBaseline()),
      needState: AppState.need,
      frontier: AppState.frontier,
    });
    return executeRendererRequest(RenderCoordinator, request, renderer, snapshot);
  }
  return { noRenderer: true };
}

async function performRecalculation(request) {
  if (!RenderCoordinator.isCurrent(request)) return;
  FrontierCoordinator.cancelCurrent();
  AppState.stageInFlight = 'sweep';
  stageRequest = request;
  setFrontierSweepBusy(true);
  let sweepCommitted = false;
  try {
    if (!RenderCoordinator.isCurrent(request)) return;
    if (!validateParams()) throw new Error('Review the highlighted strategy parameters.');
    if (!validateSharedInputs()) throw new Error('Review the highlighted portfolio and horizon fields.');
    updateAllocationMode();
    if (!updateYearRange()) {
      setStatus('Inputs need attention before the historical record can be drawn.', true);
      return;
    }
    const options = readOptions();
    if (!Number.isFinite(options.startingBalance) || options.startingBalance <= 0) throw new Error('Starting balance must be greater than zero.');
    if (!Number.isInteger(options.horizon) || options.horizon < 1 || options.horizon > 100) throw new Error('Horizon must be a whole number from 1 to 100.');
    if (!Number.isFinite(options.feeRate) || options.feeRate < 0 || options.feeRate > 1) throw new Error('Annual fee must be between 0% and 100%.');
    if (!Number.isFinite(options.taxRate) || options.taxRate < 0 || options.taxRate > 0.95) throw new Error('Effective tax must be between 0% and 95%.');
    updateHeatmapMetricAvailability(currentStrategy());
    const renderResult = await renderActiveMode(request);
    if (!RenderCoordinator.isCurrent(request) || renderResult.stale) return;
    sweepCommitted = AppState.mode === 'sweep' && renderResult.committed && !renderResult.errorMessage;
    if (renderResult.committed) updateNeedReadout();
    setStatus(
      renderResult.errorMessage || (renderResult.committed
        ? `${AppState.mode === 'window' ? 'Window' : 'Sweep'} view recalculated.`
        : `Parameters ready. The ${AppState.mode} analysis plate is reserved for the next rendering stage.`),
      Boolean(renderResult.errorMessage),
    );
  } catch (error) {
    if (!RenderCoordinator.isCurrent(request)) return;
    setStatus(error && error.message ? error.message : 'The requested range could not be prepared.', true);
    const note = byId('range-note');
    note.className = 'range-note error';
    note.textContent = 'Historical range unavailable for the current settings.';
  } finally {
    if (AppState.stageInFlight === 'sweep' && stageRequest === request) {
      AppState.stageInFlight = null;
      stageRequest = null;
      setFrontierSweepBusy(false);
      if (RenderCoordinator.isCurrent(request) && sweepCommitted && AppState.frontier.visible && lastFrontierInput) scheduleFrontier(lastFrontierInput);
    }
  }
}

/* ============================================================
   THEME
   Three states: 'system' (no data-theme attribute, CSS follows
   prefers-color-scheme), 'light', and 'dark'. CSS tokens re-resolve on
   their own, but heatmap cell colours are computed hex baked into the
   rendered model, so a theme change re-runs the render. Cached safe
   rates survive because the sweep cache key is theme-independent.
   ============================================================ */
const THEME_STORAGE_KEY = 'market-atlas-theme';
const THEME_CHOICES = Object.freeze(['system', 'light', 'dark']);

const Theme = (() => {
  let choice = 'system';

  function readStoredChoice() {
    try {
      const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
      return THEME_CHOICES.includes(stored) ? stored : 'system';
    } catch (error) {
      return 'system';
    }
  }

  function persistChoice(next) {
    try {
      if (next === 'system') window.localStorage.removeItem(THEME_STORAGE_KEY);
      else window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch (error) {
      /* Storage unavailable; the choice still applies for this session. */
    }
  }

  function systemPrefersDark() {
    return typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-color-scheme: dark)').matches;
  }

  function resolved() {
    if (choice === 'dark') return 'dark';
    if (choice === 'light') return 'light';
    return systemPrefersDark() ? 'dark' : 'light';
  }

  function palette() {
    return heatmapPalette(resolved());
  }

  function applyChoice(next) {
    choice = THEME_CHOICES.includes(next) ? next : 'system';
    if (choice === 'system') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', choice);
    for (const button of document.querySelectorAll('[data-theme-choice]')) {
      const active = button.getAttribute('data-theme-choice') === choice;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    }
  }

  function initialize(onSystemChange) {
    applyChoice(readStoredChoice());
    for (const button of document.querySelectorAll('[data-theme-choice]')) {
      button.addEventListener('click', () => {
        const next = button.getAttribute('data-theme-choice');
        if (next === choice) return;
        applyChoice(next);
        persistChoice(next);
        setStatus(next === 'system'
          ? 'Plate finish now follows your system setting.'
          : `Plate finish set to ${next}.`);
        onSystemChange();
      });
    }
    if (typeof window.matchMedia === 'function') {
      const query = window.matchMedia('(prefers-color-scheme: dark)');
      const listener = () => { if (choice === 'system') onSystemChange(); };
      if (typeof query.addEventListener === 'function') query.addEventListener('change', listener);
      else if (typeof query.addListener === 'function') query.addListener(listener);
    }
  }

  return { initialize, resolved, palette };
})();

function recalculate() {
  return performRecalculation(RenderCoordinator.begin());
}

function cancelCurrentRender() {
  if (AppState.stageInFlight === 'frontier') {
    FrontierCoordinator.cancelCurrent();
    setStatus('Frontier calculation cancelled; the last committed frontier remains visible.');
  } else if (AppState.stageInFlight === 'sweep') {
    RenderCoordinator.cancelCurrent();
    setFrontierSweepBusy(false);
    setStatus('Heatmap calculation cancelled; the last completed view remains visible.');
  } else return;
  AppState.stageInFlight = null;
  stageRequest = null;
}

const scheduleFrame = typeof requestAnimationFrame === 'function'
  ? requestAnimationFrame
  : (callback) => setTimeout(callback, 0);
const scheduleRecalculate = createLatestWinsScheduler(
  RenderCoordinator,
  performRecalculation,
  scheduleFrame,
);

function setMode(mode, focusTab = false) {
  if (!['window', 'sweep'].includes(mode)) return;
  AppState.mode = mode;
  for (const tab of document.querySelectorAll('[data-mode]')) {
    const active = tab.dataset.mode === mode;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    if (active && focusTab) tab.focus();
  }
  byId('window-mode').hidden = mode !== 'window';
  byId('sweep-mode').hidden = mode !== 'sweep';
  scheduleRecalculate();
}

function setSharedHorizon(value) {
  const normalized = String(value);
  byId('horizon').value = normalized;
  byId('sweep-horizon').value = normalized;
}

function updateHeatmapMetricAvailability(strategy) {
  const select = byId('heatmap-metric');
  if (!select) return;
  const safeOption = select.querySelector('option[value="safe"]');
  safeOption.disabled = !strategy.supportsMaxSafeRate;
  safeOption.textContent = strategy.supportsMaxSafeRate ? 'Maximum safe rate' : 'Maximum safe rate · unavailable';
  if (safeOption.disabled && AppState.heatmapMetric === 'safe') AppState.heatmapMetric = 'success';
  const belowNeedOption = select.querySelector('option[value="belowNeed"]');
  belowNeedOption.disabled = resolveNeed(AppState.need, liveYearOneBaseline()) === null;
  if (belowNeedOption.disabled && AppState.heatmapMetric === 'belowNeed') AppState.heatmapMetric = 'success';
  select.value = AppState.heatmapMetric;
}

function openWindow(startYear, horizon) {
  const selection = clampWindowSelection(startYear, horizon, AppState.yearRange);
  const startSelect = byId('start-year');
  if (startSelect && !startSelect.disabled) startSelect.value = String(selection.startYear);
  setSharedHorizon(selection.horizon);
  setMode('window');
  return selection;
}

function addCurrentComparison() {
  if (AppState.comparisons.length >= 2) {
    setStatus('Three configurations are already visible. Remove a pinned comparison before adding another.', true);
    return false;
  }
  const candidate = {
    strategyId: AppState.strategyId,
    params: readParams(),
    options: configurationOptions(readOptions()),
  };
  const candidateKey = sweepConfigurationKey(candidate, 0, 0, 'comparison');
  if (AppState.comparisons.some((item) => sweepConfigurationKey(item, 0, 0, 'comparison') === candidateKey)) {
    setStatus('That exact configuration is already pinned.', true);
    return false;
  }
  AppState.comparisons.push(immutableSnapshot({ ...candidate, id: AppState.nextComparisonId }));
  AppState.nextComparisonId += 1;
  setStatus('Current configuration pinned for comparison.');
  scheduleRecalculate();
  return true;
}

function downloadCommittedExport(key) {
  const model = AppState.exportModels[key];
  if (!model) {
    setStatus('Recalculate this view before exporting its committed results.', true);
    return false;
  }
  try {
    exportCsv(model.rows, model.filename);
    setStatus(`Exported ${model.filename}.`);
    return true;
  } catch (error) {
    setStatus(error && error.message ? `CSV export failed: ${error.message}` : 'CSV export failed.', true);
    return false;
  }
}

function renderMethodFootnote() {
  const target = byId('method-footnote');
  const data = globalThis.MARKET_DATA || {};
  const rows = Array.isArray(data.rows) ? data.rows : [];
  const observationCount = rows.length;
  const independentThirtyYearPeriods = Math.max(1, Math.floor(observationCount / 30));
  const method = document.createElement('p');
  const title = document.createElement('strong');
  title.id = 'method-footnote-title';
  title.textContent = 'Method note. ';
  method.append(title, document.createTextNode(
    `Historical windows overlap and are not independent. With about ${observationCount} annual observations, the record contains only roughly ${independentThirtyYearPeriods} non-overlapping 30-year periods; failures cluster around the mid-1960s cohort. Reported percentages are historical frequencies, not probabilities. Pre-1928 observations use the Cowles splice derived from monthly-average prices, which slightly dampens volatility relative to the modern series. No T-bill observations exist before 1928, so bill-funded strategies begin in 1928. Stock and bond figures are total returns with dividends and coupons reinvested. Taxes use one flat effective-rate gross-up on withdrawals. Lifestyle values always use real, after-tax retirement-start dollars, regardless of the Real/Nominal display toggle. Any failure gives a zero spending floor, including a partial withdrawal in the final year. Guyton–Klinger's portfolio management rule is omitted. Its heatmap spending paths can differ by horizon because the capital-preservation cutoff depends on years remaining. Adaptive maximum-safe-rate values are approximate at the displayed 0.1 percentage-point discovery resolution; progress is reported while they are calculated.`,
  ));
  const provenance = document.createElement('p');
  method.append(document.createTextNode(' The daily 3-month T-bill (FRED DTB3) option uses annual mean discount-basis rates from 1954, spliced with Damodaran through 1953; neither bill series compounds within the year.'));
  provenance.className = 'footnote-sources';
  const provenanceTitle = document.createElement('strong');
  provenanceTitle.textContent = 'Data lineage. ';
  provenance.append(provenanceTitle, document.createTextNode(`Generated ${data.generated || 'date not recorded'}. `));
  const sources = data.sources && typeof data.sources === 'object'
    ? Object.entries(globalThis.MARKET_DATA.sources)
    : [];
  sources.forEach(([column, source], index) => {
    if (index) provenance.append(document.createTextNode(' · '));
    provenance.append(document.createTextNode(`${column}: ${source}`));
  });
  if (!sources.length) provenance.append(document.createTextNode('Column sources were not recorded.'));
  target.replaceChildren(method, provenance);
}

function renderDataLineage() {
  const rows = globalThis.MARKET_DATA && Array.isArray(globalThis.MARKET_DATA.rows)
    ? globalThis.MARKET_DATA.rows.slice().sort((left, right) => left.year - right.year)
    : [];
  if (!rows.length) return;
  const reconstructed = rows.filter((row) => row.quality === 'reconstructed');
  const observed = rows.filter((row) => row.quality !== 'reconstructed');
  const span = (set, fallback) => set.length ? `${set[0].year}–${set[set.length - 1].year}` : fallback;
  byId('reconstructed-era').textContent = `Reconstructed · ${span(reconstructed, 'none')}`;
  byId('observed-era').textContent = `Published record · ${span(observed, 'none')}`;
  byId('folio-range').textContent = `${rows[0].year}—${rows[rows.length - 1].year}`;
}

function initialize() {
  try {
    if (!globalThis.BacktestEngine || !globalThis.BacktestEngine.STRATEGIES) throw new Error('The simulation engine did not load.');
    if (!globalThis.MARKET_DATA || !Array.isArray(globalThis.MARKET_DATA.rows)) throw new Error('The historical market dataset did not load.');
    const strategies = globalThis.BacktestEngine.STRATEGIES;
    const strategySelect = byId('strategy-select');
    for (const [id, strategy] of Object.entries(strategies)) {
      const option = document.createElement('option');
      option.value = id;
      option.textContent = strategy.name || id;
      strategySelect.append(option);
      AppState.strategyParams[id] = Object.fromEntries(
        (strategy.paramSchema || []).map((field) => [field.key, field.default]),
      );
    }
    AppState.strategyId = strategySelect.value || Object.keys(strategies)[0] || null;
    Theme.initialize(scheduleRecalculate);
    renderSidebar();
    updateHeatmapMetricAvailability(strategies[AppState.strategyId]);
    renderDataLineage();
    renderMethodFootnote();

    strategySelect.addEventListener('change', () => {
      rememberVisibleParams();
      AppState.strategyId = strategySelect.value;
      resetFrontierParameter();
      renderSidebar();
      updateHeatmapMetricAvailability(strategies[AppState.strategyId]);
      scheduleRecalculate();
    });
    byId('strategy-params').addEventListener('input', scheduleRecalculate);
    byId('strategy-params').addEventListener('change', scheduleRecalculate);
    for (const input of document.querySelectorAll('[data-allocation]')) input.addEventListener('input', scheduleRecalculate);
    for (const id of ['starting-balance', 'fee-rate', 'tax-rate']) {
      byId(id).addEventListener('input', scheduleRecalculate);
    }
    byId('bill-series').addEventListener('change', scheduleRecalculate);
    byId('horizon').addEventListener('input', () => {
      setSharedHorizon(byId('horizon').value);
      scheduleRecalculate();
    });
    byId('sweep-horizon').addEventListener('input', () => {
      setSharedHorizon(byId('sweep-horizon').value);
      scheduleRecalculate();
    });
    byId('start-year').addEventListener('change', scheduleRecalculate);
    byId('need-amount').addEventListener('input', () => editNeed('dollars'));
    byId('need-percent').addEventListener('input', () => editNeed('percent'));
    byId('sweep-cohort').addEventListener('change', () => {
      AppState.sweepCohort = byId('sweep-cohort').value === 'full' ? 'full' : 'modern';
      scheduleRecalculate();
    });
    byId('heatmap-metric').addEventListener('change', () => {
      AppState.heatmapMetric = ['success', 'wealth', 'safe', 'floor', 'belowNeed'].includes(byId('heatmap-metric').value)
        ? byId('heatmap-metric').value : 'success';
      scheduleRecalculate();
    });
    byId('sweep-chart-metric').addEventListener('change', () => {
      AppState.sweepChartMetric = byId('sweep-chart-metric').value === 'spending' ? 'spending' : 'auto';
      scheduleRecalculate();
    });
    byId('cancel-heatmap').addEventListener('click', cancelCurrentRender);
    byId('add-comparison').addEventListener('click', addCurrentComparison);
    byId('clear-comparisons').addEventListener('click', () => {
      AppState.comparisons = [];
      scheduleRecalculate();
    });
    byId('export-window-csv').addEventListener('click', () => downloadCommittedExport('window'));
    byId('export-sweep-curve-csv').addEventListener('click', () => downloadCommittedExport('sweepCurve'));
    byId('export-sweep-heatmap-csv').addEventListener('click', () => downloadCommittedExport('sweepHeatmap'));
    byId('comparison-tray').addEventListener('click', (event) => {
      const button = event.target.closest && event.target.closest('[data-remove-comparison]');
      if (!button) return;
      AppState.comparisons = AppState.comparisons.filter((item) => String(item.id) !== button.dataset.removeComparison);
      scheduleRecalculate();
    });
    byId('controls-form').addEventListener('submit', (event) => {
      event.preventDefault();
      void recalculate();
    });
    for (const tab of document.querySelectorAll('[data-mode]')) {
      tab.addEventListener('click', () => setMode(tab.dataset.mode));
      tab.addEventListener('keydown', (event) => {
        if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
        event.preventDefault();
        setMode(tab.dataset.mode === 'window' ? 'sweep' : 'window', true);
      });
    }
    for (const button of document.querySelectorAll('[data-display]')) {
      button.addEventListener('click', () => {
        AppState.display = button.dataset.display;
        for (const peer of document.querySelectorAll('[data-display]')) {
          const active = peer === button;
          peer.classList.toggle('active', active);
          peer.setAttribute('aria-pressed', String(active));
        }
        scheduleRecalculate();
      });
    }
    void recalculate();
  } catch (error) {
    setStatus(error && error.message ? error.message : 'The application could not be initialized.', true);
    byId('recalculate').disabled = true;
  }
}

globalThis.BacktestApp = Object.freeze({
  state: AppState,
  renderSidebar,
  readParams,
  readOptions,
  recalculate,
  registerRenderer,
  setMode,
  openWindow,
  cancelCurrentRender,
  openSweepPoint,
  applyConfigurationToControls,
  renderStatsBand,
  renderBalanceChart,
  fmtMoney,
  fmtPct,
  fmtMoneyCompact,
  escapeHtml,
});

registerRenderer('window', renderWindowMode);
registerRenderer('sweep', renderSweepMode);
initialize();
