'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { simulate, STRATEGIES } = require('../engine.js');

function loadWindowHelpers() {
  return require('../views.js');
}

function appSource() {
  return ['../index.html', '../app.js', '../views.js']
    .map((file) => fs.readFileSync(require.resolve(file), 'utf8'))
    .join('\n');
}

function controllerSource() {
  return fs.readFileSync(require.resolve('../app.js'), 'utf8')
    + fs.readFileSync(require.resolve('../views.js'), 'utf8');
}

test('window selection follows contiguous years and stops at the first gap', () => {
  const { selectWindowRows } = loadWindowHelpers();
  const rows = [{ year: 2002 }, { year: 2000 }, { year: 2003 }];
  assert.deepEqual(
    Array.from(selectWindowRows(rows, 2000, 5, 2003), (row) => row.year),
    [2000],
  );
});

test('quality seam comes from the displayed quality transition', () => {
  const { findQualitySeam } = loadWindowHelpers();
  const rows = [
    { year: 1926, quality: 'reconstructed' },
    { year: 1927, quality: 'reconstructed' },
    { year: 1928, quality: 'ok' },
    { year: 1929, quality: 'ok' },
  ];
  assert.deepEqual({ ...findQualitySeam(rows) }, { index: 2, year: 1928 });
  assert.equal(findQualitySeam(rows.slice(2)), null);
});

test('partial solvent outcome is distinct from survival and definitive failure', () => {
  const { classifyWindowOutcome } = loadWindowHelpers();
  assert.deepEqual(
    { ...classifyWindowOutcome({ success: true, partial: true, yearsCompleted: 2, horizon: 30, failureYear: null }) },
    { kind: 'partial', label: 'Solvent through 2 of 30', detail: 'recent window · outcome incomplete' },
  );
  assert.deepEqual(
    { ...classifyWindowOutcome({ success: false, partial: false, yearsCompleted: 9, horizon: 30, failureYear: 1981 }) },
    { kind: 'failed', label: 'Failed · 1981', detail: 'portfolio depleted during withdrawal' },
  );
  assert.equal(classifyWindowOutcome({ success: true, partial: false, yearsCompleted: 30, horizon: 30 }).kind, 'survived');
});

test('display conversion uses canonical end CPI and chart endpoint matches terminal real wealth', () => {
  const { displayBalance, chartSeries } = loadWindowHelpers();
  const row = {
    cpiIndex: 1.25,
    endCpiIndex: 1.5,
    startBalances: { stock: 150, bond: 75, bill: 75 },
    endBalances: { stock: 300, bond: 150, bill: 150 },
  };
  assert.equal(displayBalance(300, row, 'real'), 200);
  assert.equal(displayBalance(300, row, 'nominal'), 300);
  assert.equal(displayBalance(0, { endCpiIndex: null }, 'real'), 0);
  const endpoint = chartSeries([row], 'real').at(-1);
  assert.equal(endpoint.stock + endpoint.bond + endpoint.bill, 400);
});

test('final real table value and chart endpoint agree with the engine terminal metric', () => {
  const { displayBalance, chartSeries } = loadWindowHelpers();
  const result = simulate(
    [{ year: 2000, stock_tr: 0.10, bond10_tr: 0.05, tbill_tr: 0.03, cpi_change: 0.04, quality: 'ok' }],
    STRATEGIES.fixedReal,
    { initialRate: 0.04 },
    {
      startingBalance: 1_000,
      allocation: { stock: 0.6, bond: 0.4, bill: 0 },
      feeRate: 0,
      taxRate: 0,
      horizon: 1,
    },
  );
  const last = result.rows.at(-1);
  assert.equal(displayBalance(last.endTotal, last, 'real'), result.metrics.terminalWealthReal);
  const endpoint = chartSeries(result.rows, 'real').at(-1);
  const chartTotal = endpoint.stock + endpoint.bond + endpoint.bill;
  assert.ok(Math.abs(chartTotal - result.metrics.terminalWealthReal) < 1e-9);
});

test('notes accept arrays or strings', () => {
  const { normalizeNotes } = loadWindowHelpers();
  assert.deepEqual(Array.from(normalizeNotes(['Raised <spending>', '', null])), ['Raised <spending>']);
  assert.deepEqual(Array.from(normalizeNotes('Refilled & rebalanced')), ['Refilled & rebalanced']);
});

test('terminal wealth statistic is always real regardless of balance display toggle', () => {
  const { windowStatsModel } = loadWindowHelpers();
  const metrics = {
    success: true,
    partial: false,
    horizon: 1,
    yearsCompleted: 1,
    terminalWealthNominal: 600,
    terminalWealthReal: 400,
    maxDrawdownReal: 0,
    minRealSpending: 20,
    minRealSpendingYear: 2000,
    totalWithdrawnReal: 20,
  };
  for (const display of ['real', 'nominal']) {
    const terminal = windowStatsModel(metrics, display)[1];
    assert.equal(terminal.label, 'Terminal wealth · real');
    assert.equal(terminal.rawValue, 400);
  }
});

test('open-window inputs clamp to the available years and supported horizon', () => {
  const { clampWindowSelection } = loadWindowHelpers();
  assert.deepEqual(
    { ...clampWindowSelection(1800, 150, { first: 1872, last: 2025 }) },
    { startYear: 1872, horizon: 100 },
  );
  assert.deepEqual(
    { ...clampWindowSelection(2030, 0, { first: 1872, last: 2025 }) },
    { startYear: 2025, horizon: 1 },
  );
});

test('window renderer is registered and keeps simulation outside the commit callback', () => {
  const html = appSource();
  assert.match(html, /registerRenderer\('window',\s*renderWindowMode\)/);
  assert.match(html, /function renderWindowMode\(snapshot,\s*\{ signal \}\)/);
  assert.match(html, /return function commitWindowMode\(\)/);
  assert.match(html, /setAttribute\('viewBox',\s*'0 0 1000 200'\)/);
  assert.match(html, /<caption[^>]*>Year-by-year portfolio ledger<\/caption>/);
});

test('window solvency band has three cells after lifestyle metrics move to their own band', () => {
  // Spending minimum and total now appear together in windowLifestyleCells.
  const cells = loadWindowHelpers().windowStatsModel({ success: true, partial: false, horizon: 30, terminalWealthReal: 100, maxDrawdownReal: .2 }, 'real');
  assert.deepEqual(cells.map(cell => cell.label), ['Outcome', 'Terminal wealth · real', 'Max real drawdown']);
});

test('window lifestyle controls, grouping, strip and complete failed ledger are wired', () => {
  const html = fs.readFileSync(require.resolve('../index.html'), 'utf8');
  const app = fs.readFileSync(require.resolve('../app.js'), 'utf8');
  assert.match(html, /id="need-amount"[^>]*min="0"[^>]*step="1000"/);
  assert.match(html, /id="need-percent"[^>]*min="0"[^>]*max="200"[^>]*step="1"/);
  assert.match(html, /id="need-status"[^>]*role="status"/);
  assert.match(app, /function liveYearOneBaseline\(/);
  assert.match(app, /needDollars: resolveNeed\(AppState.need, liveYearOneBaseline\(\)\)/);
  assert.match(app, /windowLifestyleCells\(metrics, needDollars\)/);
  assert.match(app, /spendingStripSvg\(spendingStripModel\(result.rows, result.metrics.spending, snapshot.needDollars\)\)/);
  assert.match(app, /windowExportRows\(result.rows, result.metrics.spending, snapshot.needDollars\)/);
  assert.match(app, /ledgerFloorFlags\(spending\)/);
  assert.match(html, /\.stat-group-cells/);
  assert.doesNotMatch(html, /\.stats \{ display: block; \}/);
});

test('window group is named Portfolio in the placeholder and rendered band', () => {
  const html = fs.readFileSync(require.resolve('../index.html'), 'utf8');
  const app = fs.readFileSync(require.resolve('../app.js'), 'utf8');
  const placeholder = html.match(/id="window-stats"[\s\S]*?<div class="ledger-placeholder"/)[0];
  assert.match(placeholder, /stat-group-label">Portfolio</);
  const band = app.match(/function renderStatsBand[\s\S]*?\n\}/)[0];
  assert.match(band, /renderStatGroup\('Portfolio',/);
});
