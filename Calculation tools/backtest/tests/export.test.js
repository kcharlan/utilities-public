'use strict';

const test = require('node:test');
const { getMarketRows } = require('./helpers/dataset.cjs');
const assert = require('node:assert/strict');
const fs = require('node:fs');

/* csv.js publishes the pure transforms directly and hands back the downloader
   from a factory taking Blob/URL/document. This replaced a harness that sliced
   the block out of the application source and ran it in a VM sandbox. */
function loadExportHelpers(overrides = {}) {
  const csv = require('../csv.js');
  return {
    serializeCsv: csv.serializeCsv,
    windowExportRows: csv.windowExportRows,
    sweepCurveExportRows: csv.sweepCurveExportRows,
    heatmapExportRows: csv.heatmapExportRows,
    // Node has no document; the downloader is only built when a test supplies
    // browser fakes, and the pure transforms need none of them.
    exportCsv: overrides.document
      ? csv.createCsvDownloader({ Blob, URL: overrides.URL, document: overrides.document })
      : undefined,
  };
}

test('CSV serializer uses stable headers, RFC quoting, empty nulls, and formula-safe text', () => {
  const { serializeCsv } = loadExportHelpers();
  const csv = serializeCsv([
    {
      year: 1966, amount: -42.5, note: 'cut, then "hold"\r\nnext year', label: '=unsafe', missing: null,
      tab_formula: '\t=SUM(A1:A2)', cr_formula: '\r+1', lf_formula: '\n@cmd',
      spaced_formula: '  -danger', ordinary_space: ' ordinary text', numeric_negative: -7,
    },
    {
      year: 1967, amount: 0, note: '@mention', label: '-text', missing: undefined,
      tab_formula: 'plain', cr_formula: 'plain', lf_formula: 'plain',
      spaced_formula: 'plain', ordinary_space: ' plain text', numeric_negative: -8,
    },
  ]);
  assert.equal(
    csv,
    'year,amount,note,label,missing,tab_formula,cr_formula,lf_formula,spaced_formula,ordinary_space,numeric_negative\r\n'
      + '1966,-42.5,"cut, then ""hold""\r\nnext year",\'=unsafe,,'
      + '\'\t=SUM(A1:A2),"\'\r+1","\'\n@cmd",\'  -danger, ordinary text,-7\r\n'
      + '1967,0,\'@mention,\'-text,,plain,plain,plain,plain, plain text,-8',
  );
});

test('window export model preserves raw nominal and real ledger values', () => {
  const { windowExportRows } = loadExportHelpers();
  const rows = windowExportRows([{
    year: 2008,
    returnRates: { stock: -0.3655, bond: 0.2025, bill: null },
    withdrawalNominal: 40000,
    withdrawalReal: 38500,
    grossWithdrawal: 50000,
    taxPaid: 10000,
    endBalances: { stock: 300000, bond: 410000, bill: 0 },
    endTotal: 710000,
    endTotalReal: 680000,
    notes: '=guardrail cut',
    failed: false,
    quality: 'ok',
  }]);
  assert.deepEqual(JSON.parse(JSON.stringify(rows)), [{
    year: 2008,
    stock_return_nominal: -0.3655,
    bond_return_nominal: 0.2025,
    bill_return_nominal: null,
    withdrawal_nominal: 40000,
    withdrawal_real: 38500,
    gross_withdrawal_nominal: 50000,
    tax_nominal: 10000,
    stock_balance_nominal: 300000,
    bond_balance_nominal: 410000,
    bill_balance_nominal: 0,
    total_balance_nominal: 710000,
    total_balance_real: 680000,
    notes: '=guardrail cut',
    status: 'completed',
    quality: 'ok',
    // Additive lifestyle columns preserve every existing ledger assertion.
    withdrawal_real_pct_of_year1: null,
    need_real: null,
  }]);
  const failed = windowExportRows([{
    year: 2009, returnRates: { stock: 0, bond: 0, bill: 0 },
    withdrawalNominal: 1, withdrawalReal: 1, grossWithdrawal: 1, taxPaid: 0,
    endBalances: { stock: 0, bond: 0, bill: 0 }, endTotal: 0, endTotalReal: 0,
    notes: '@strategy note', failed: true, quality: 'ok',
  }])[0];
  assert.equal(failed.notes, 'Portfolio depleted before returns were applied · @strategy note');
});

test('sweep curve and heatmap models expose partial, failure, and no-rate states', () => {
  const { sweepCurveExportRows, heatmapExportRows } = loadExportHelpers();
  const curve = sweepCurveExportRows([{
    label: 'Fixed real · Initial rate: 4%',
    configuration: { id: 'active', strategyId: 'fixedReal' },
    results: [
      { startYear: 1966, maxSafeRate: 0.0367, metrics: { success: false, partial: false, failureYear: 1994, yearsCompleted: 28, horizon: 30, terminalWealthReal: 0, spendingVolatility: 0 } },
      { startYear: 2000, maxSafeRate: null, metrics: { success: true, partial: true, failureYear: null, yearsCompleted: 26, horizon: 30, terminalWealthReal: 100, spendingVolatility: null } },
    ],
  }]);
  // Legacy fixtures lack spending profiles; new columns remain null.
  const absentLifestyle = {
    year1_spending_real: null, spending_floor_real: null, spending_floor_pct_of_year1: null,
    funded_floor_real: null, last_partial_real: null, spending_ceiling_real: null,
    spending_median_real: null, deepest_cut: null, need_real: null,
    years_below_need: null, longest_run_below_need: null, shortfall_years: null,
  };
  assert.deepEqual(JSON.parse(JSON.stringify(curve)), [
    { configuration_label: 'Fixed real · Initial rate: 4%', configuration_id: 'active', strategy_id: 'fixedReal', start_year: 1966, status: 'failed', partial: false, success: false, failure_year: 1994, years_complete: 28, horizon: 30, terminal_wealth_real: 0, spending_volatility: 0, max_safe_rate: 0.0367, ...absentLifestyle },
    { configuration_label: 'Fixed real · Initial rate: 4%', configuration_id: 'active', strategy_id: 'fixedReal', start_year: 2000, status: 'partial', partial: true, success: null, failure_year: null, years_complete: 26, horizon: 30, terminal_wealth_real: 100, spending_volatility: null, max_safe_rate: null, ...absentLifestyle },
  ]);

  const heatmap = heatmapExportRows({ metric: 'safe', cells: [
    { startYear: 1966, horizon: 30, kind: 'no-rate', partial: false, value: null },
    { startYear: 2000, horizon: 30, kind: 'partial', partial: true, value: null },
  ] });
  assert.deepEqual(JSON.parse(JSON.stringify(heatmap)), [
    { start_year: 1966, horizon: 30, metric: 'safe', status: 'no_rate', partial: false, value: null },
    { start_year: 2000, horizon: 30, metric: 'safe', status: 'partial', partial: true, value: null },
  ]);
});

test('export creates one object URL, clicks a detached anchor, and always revokes on click error', () => {
  const calls = [];
  const fakeUrl = {
    createObjectURL(blob) { calls.push(['create', blob.type]); return 'blob:test'; },
    revokeObjectURL(url) { calls.push(['revoke', url]); },
  };
  const fakeDocument = {
    createElement(tag) {
      assert.equal(tag, 'a');
      return {
        set href(value) { calls.push(['href', value]); },
        set download(value) { calls.push(['download', value]); },
        click() { calls.push(['click']); throw new Error('blocked click'); },
      };
    },
  };
  const { exportCsv } = loadExportHelpers({ URL: fakeUrl, document: fakeDocument });
  assert.throws(() => exportCsv([{ value: 1 }], 'ledger.csv'), /blocked click/);
  assert.deepEqual(calls, [
    ['create', 'text/csv;charset=utf-8'], ['href', 'blob:test'], ['download', 'ledger.csv'], ['click'], ['revoke', 'blob:test'],
  ]);
});

test('static export controls and dynamic method-footnote contracts are present', () => {
  const html = ['../index.html', '../app.js', '../views.js']
    .map((file) => fs.readFileSync(require.resolve(file), 'utf8'))
    .join('\n');
  for (const id of ['export-window-csv', 'export-sweep-curve-csv', 'export-sweep-heatmap-csv']) {
    assert.match(html, new RegExp(`id="${id}"[^>]*disabled`));
    assert.match(html, new RegExp(`id="${id}"[^>]*aria-describedby="app-status-message"`));
  }
  assert.match(html, /function renderMethodFootnote\(\)/);
  assert.match(html, /Object\.entries\(globalThis\.MARKET_DATA\.sources/);
  assert.doesNotMatch(html, /Dataset generated <span/);
});


test('the downloader refuses to construct without its browser collaborators', () => {
  const { createCsvDownloader } = require('../csv.js');
  for (const missing of ['Blob', 'URL', 'document']) {
    const deps = { Blob, URL: {}, document: {} };
    delete deps[missing];
    assert.throws(() => createCsvDownloader(deps), new RegExp(`requires ${missing}`));
  }
  assert.throws(() => createCsvDownloader(null), /requires Blob/);
});

test('csv.js reaches for no browser global of its own', () => {
  // The module must work in Node without a DOM; every browser API arrives as an
  // argument. Requiring it above already proves it loads, so this pins the rule.
  const source = fs.readFileSync(require.resolve('../csv.js'), 'utf8');
  const factoryStart = source.indexOf('function createCsvDownloader');
  const beforeFactory = source.slice(0, factoryStart);
  for (const global of ['document', 'window', 'Blob', 'URL']) {
    assert.ok(
      !new RegExp(`\\b${global}\\b`).test(beforeFactory.replace(/\/\*[\s\S]*?\*\//g, '')),
      `${global} must only be reachable inside createCsvDownloader`,
    );
  }
});

const { spendingProfile, needProfile } = require('../stats.js');
const { simulate, STRATEGIES } = require('../engine.js');
const vm = require('node:vm');

function ledgerRow(year, withdrawalReal = 40, failed = false) {
  return { year, returnRates: { stock: .1, bond: .2, bill: 0 }, withdrawalNominal: withdrawalReal,
    withdrawalReal, grossWithdrawal: withdrawalReal, taxPaid: 0,
    endBalances: { stock: 10, bond: 20, bill: 0 }, endTotal: 30, endTotalReal: 30,
    notes: '', failed, quality: 'ok' };
}
function spending(realSpending, extra = {}) {
  return spendingProfile({ realSpending, baseline: 40, startYear: 2000, horizon: realSpending.length,
    failed: false, partial: false, ...extra });
}

test('window lifestyle export pads unfunded years with the same keys and export-wide need', () => {
  const { windowExportRows, serializeCsv } = loadExportHelpers();
  const profile = spending([40, 10], { failed: true, horizon: 4 });
  const result = windowExportRows([ledgerRow(2000), ledgerRow(2001, 10, true)], profile, 36);
  assert.equal(result.length, 4);
  assert.equal(result[0].withdrawal_real_pct_of_year1, 1);
  assert.equal(result[1].withdrawal_real_pct_of_year1, .25);
  for (let index = 0; index < result.length; index++) {
    assert.deepEqual(Object.keys(result[index]), Object.keys(result[0]));
    assert.equal(result[index].year, 2000 + index);
    assert.equal(result[index].need_real, 36);
  }
  for (const row of result.slice(2)) {
    assert.equal(row.status, 'unfunded');
    assert.equal(row.notes, 'unfunded');
    assert.equal(row.quality, '');
    for (const key of Object.keys(row)) {
      if (['year', 'need_real', 'status', 'notes', 'quality'].includes(key)) continue;
      assert.equal(row[key], ['withdrawal_nominal', 'withdrawal_real', 'withdrawal_real_pct_of_year1'].includes(key) ? 0 : null, key);
    }
  }
  assert.equal(serializeCsv(result).split('\r\n').length, 5);
});

test('window export preserves zero spending and need while absent or zero baselines stay null', () => {
  const { windowExportRows } = loadExportHelpers();
  for (const profile of [null, spending([0], { baseline: 0 })]) {
    const row = windowExportRows([ledgerRow(2000, 0)], profile, 0)[0];
    assert.equal(row.withdrawal_real, 0);
    assert.equal(row.withdrawal_real_pct_of_year1, null);
    assert.equal(row.need_real, 0);
  }
  const zero = spending([0], { baseline: 0, failed: true, horizon: 2 });
  assert.equal(windowExportRows([ledgerRow(2000, 0, true)], zero)[1].withdrawal_real_pct_of_year1, null);
  assert.equal(windowExportRows([ledgerRow(2000)], spending([40]), null)[0].need_real, null);
  assert.equal(windowExportRows([ledgerRow(2000)], spending([40], { partial: true, horizon: 3 })).length, 1);
});

test('1966 fixed-real CSV retains 25 delivered years plus five unfunded years and a $36000 need', async () => {
  const marketRows = (await getMarketRows()).filter(row => row.year >= 1966).slice(0, 30);
  const result = simulate(marketRows, STRATEGIES.fixedReal, { initialRate: .04 }, {
    startingBalance: 1000000, allocation: { stock: .5, bond: .5, bill: 0 }, horizon: 30,
  });
  const rows = loadExportHelpers().windowExportRows(result.rows, result.metrics.spending, 36000);
  assert.equal(rows.length, 30);
  assert.equal(rows.filter(row => row.status === 'unfunded').length, 5);
  assert.equal(rows[24].year, 1990);
  assert.equal(rows[24].status, 'failed');
  assert.equal(rows[24].withdrawal_real, result.metrics.spending.lastPartial);
  assert.equal(rows.at(-1).year, 1995);
  rows.forEach(row => assert.equal(row.need_real, 36000));
  rows.slice(25).forEach(row => assert.equal(row.withdrawal_real_pct_of_year1, 0));
});

test('curve CSV appends shared spending and need metrics without losing legacy fields', () => {
  const { sweepCurveExportRows } = loadExportHelpers();
  const profile = spending([40, 30, 10], { horizon: 5, failed: true });
  const metrics = { success: false, horizon: 5, yearsCompleted: 2, spending: profile };
  const curve = sweepCurveExportRows([{ label: 'fixture', configuration: { id: 'active', strategyId: 'fixedReal' },
    results: [{ startYear: 2000, metrics }] }], 36)[0];
  const need = needProfile(profile, 36);
  const expected = {
    year1_spending_real: profile.baseline, spending_floor_real: profile.floor,
    spending_floor_pct_of_year1: profile.floorRatio, funded_floor_real: profile.fundedFloor,
    last_partial_real: profile.lastPartial, spending_ceiling_real: profile.ceiling,
    spending_median_real: profile.median, deepest_cut: profile.deepestCut, need_real: need.need,
    years_below_need: need.yearsBelow, longest_run_below_need: need.longestBelowRun,
    shortfall_years: need.shortfallYears,
  };
  assert.deepEqual(Object.keys(curve).slice(13), Object.keys(expected));
  for (const [key, value] of Object.entries(expected)) assert.equal(curve[key], value, key);
  assert.equal(curve.configuration_id, 'active');
  assert.equal(curve.status, 'failed');
});

test('curve CSV keeps export-wide need for missing profiles and validates unavailable need metrics', () => {
  const { sweepCurveExportRows } = loadExportHelpers();
  const series = [{ label: 'fixture', configuration: { id: 'active', strategyId: 'fixedReal' }, results: [
    { startYear: 2000, metrics: {} }, { startYear: 2001, metrics: { spending: spending([0], { baseline: 0 }) } },
  ] }];
  const [absent, zero] = sweepCurveExportRows(series, 0);
  assert.equal(absent.need_real, 0);
  assert.equal(absent.years_below_need, null);
  assert.equal(zero.year1_spending_real, 0);
  assert.equal(zero.spending_floor_real, 0);
  assert.equal(zero.spending_floor_pct_of_year1, null);
  assert.equal(zero.years_below_need, 0);
  assert.equal(zero.shortfall_years, null);
  for (const need of [null, NaN, Infinity, -1]) {
    for (const row of sweepCurveExportRows(series, need)) {
      assert.equal(row.need_real, null);
      assert.equal(row.years_below_need, null);
    }
  }
});

test('CSV browser loader requires Stats and publishes only its frozen namespace', () => {
  const source = fs.readFileSync(require.resolve('../csv.js'), 'utf8');
  assert.throws(() => vm.runInNewContext(source, {}), /csv.js requires stats.js to be loaded first/);
  const stats = require('../stats.js');
  const context = { MarketAtlasStats: stats };
  vm.runInNewContext(source, context);
  assert.ok(Object.isFrozen(context.MarketAtlasCsv));
  assert.deepEqual(Object.keys(context).sort(), ['MarketAtlasCsv', 'MarketAtlasStats']);
  assert.equal(context.MarketAtlasCsv.windowExportRows([ledgerRow(2000)], spending([40]), 36)[0].need_real, 36);
});

test('heatmap CSV preserves new floor and belowNeed metrics including zeros and unavailable cells', () => {
  const { heatmapExportRows } = loadExportHelpers();
  for (const metric of ['floor', 'belowNeed']) {
    const rows = heatmapExportRows({ metric, cells: [
      { startYear: 2000, horizon: 30, kind: 'value', value: 0 },
      { startYear: 2001, horizon: 30, kind: 'partial', value: .2, partial: true },
    ] });
    assert.equal(rows[0].value, 0);
    assert.equal(rows[0].metric, metric);
    assert.equal(rows[1].value, null);
  }
});
