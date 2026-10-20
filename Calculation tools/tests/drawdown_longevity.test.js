'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { loadDrawdownApi } = require('./helpers/load_drawdown');

function scenario(overrides = {}) {
  return {
    buffer_initial: 270000, floor: 100000, external_income: 2000,
    investments_initial: 600000, investment_income: 6000, modifier: 1,
    expense: 5000, inflation: 0.03, tax_rate: 0.25, sale_tax_rate: 0.15,
    unit: 'months', num_periods: 0, ...overrides,
  };
}

// Cash sits exactly on the floor and net income exactly pays the expense.
const exactlyFunded = { buffer_initial: 100000, floor: 100000, external_income: 4000,
  investments_initial: 0, investment_income: 0, tax_rate: 0.25, expense: 3000, inflation: 0 };

test('a month that ends exactly at the floor is funded, not a failure', () => {
  const { simulate, fundedMonths } = loadDrawdownApi();
  const result = simulate(scenario({ ...exactlyFunded, num_periods: 24 }), []);
  assert.equal(result.terminatedReason, 'horizon');
  assert.equal(fundedMonths(result), 24);

  // 1000.10 × 0.7 is not exactly 700.07 in binary; the shortfall is roundoff, not money.
  const roundoff = simulate(scenario({ ...exactlyFunded, external_income: 1000.1, tax_rate: 0.3,
    expense: 700.07, num_periods: 24 }), []);
  assert.equal(roundoff.terminatedReason, 'horizon');
  assert.equal(fundedMonths(roundoff), 24);
});

test('the first month with a real shortfall is the failure month and is not counted', () => {
  const { simulate, fundedMonths } = loadDrawdownApi();
  // Month 1 is exactly funded; 12% inflation makes month 2's expense exceed net income.
  const result = simulate(scenario({ ...exactlyFunded, inflation: 0.12 }), []);
  assert.equal(result.terminatedReason, 'reserve_failure');
  assert.equal(result.terminatedAtMonth, 2);
  assert.equal(fundedMonths(result), 1);
});

const parityCases = [
  ['defaults to failure', scenario(), [], {}],
  ['sales and a 15-year horizon', scenario({ investments_initial: 420000, investment_income: 3600, num_periods: 180 }), [], {}],
  ['no principal', scenario({ investments_initial: 0, investment_income: 0 }), [], {}],
  ['the 1200-month cap', scenario({ investments_initial: 5e6, investment_income: 30000, inflation: 0 }), [], {}],
  ['a trial cutoff', scenario(), [], { throughMonth: 90 }],
  ['assumption and cash pins', scenario({ investments_initial: 200000, investment_income: 1500 }), [
    { id: 'a', at_month: 36, start: { expense: 3500, external_income: 4500, inflation: 0.05 }, end: {} },
    { id: 'b', at_month: 60, start: {}, end: { buffer: 150000 } },
  ], {}],
  ['a principal valuation pin', scenario(), [{ id: 'c', at_month: 24, start: {}, end: { investments: 300000 } }], {}],
];

for (const [name, params, pins, options] of parityCases) {
  test(`summary simulation matches the full projection: ${name}`, () => {
    const { simulate, fundedMonths } = loadDrawdownApi();
    const full = simulate(params, pins, options);
    const summary = simulate(params, pins, { ...options, summary: true });
    assert.notEqual(full.terminatedReason, 'invalid');
    assert.equal(summary.rows.length, 0);
    assert.equal(summary.terminatedReason, full.terminatedReason);
    assert.equal(summary.terminatedAtMonth, full.terminatedAtMonth);
    assert.equal(summary.lastMonth, full.rows.at(-1).month);
    assert.equal(fundedMonths(summary), fundedMonths(full));
  });
}

test('summary simulation reports the same invalid scenarios', () => {
  const { simulate } = loadDrawdownApi();
  const pins = [{ id: 'bad', at_month: 3, start: {}, end: { buffer: 10 } }];
  const full = simulate(scenario(), pins);
  const summary = simulate(scenario(), pins, { summary: true });
  assert.equal(full.terminatedReason, 'invalid');
  assert.equal(summary.terminatedReason, 'invalid');
  assert.deepEqual(summary.issues, full.issues);
});

// The waterline map: starting principal × monthly investment income.
const fifteenYears = scenario({ investments_initial: 420000, investment_income: 3600, unit: 'years', num_periods: 15 });

function lastsFor(api, params) {
  // Full projections, independent of the map's summary runs and searches.
  return (principal, income) => api.fundedMonths(api.simulate({ ...params,
    investments_initial: principal, investment_income: principal > 0 ? income : 0, num_periods: 0 }, []));
}

test('waterline is off while adjustments set principal or investment income', () => {
  const { waterlineBlockers } = loadDrawdownApi();
  const pins = [
    { id: 'expense', at_month: 12, start: { expense: 4000, inflation: 0.04 }, end: {} },
    { id: 'cash', at_month: 18, start: {}, end: { buffer: 150000 } },
    { id: 'crash', at_month: 24, start: {}, end: { investments: 300000 } },
    { id: 'income', at_month: 30, start: { investment_income: 2000 }, end: {} },
    { id: 'next', at_month: 36, start: {}, end: { investment_income: 1000 } },
  ];
  assert.deepEqual(Array.from(waterlineBlockers(pins), pin => pin.id), ['crash', 'income', 'next']);
  assert.equal(waterlineBlockers(pins.slice(0, 2)).length, 0);
});

test('waterline bands count exactly reaching the horizon as making it', () => {
  const { waterlineBand } = loadDrawdownApi();
  const band = months => { const b = waterlineBand(months, 120, 12); return `${b.side}-${b.depth}`; };
  assert.equal(band(120), 'long-1');
  assert.equal(band(131), 'long-1');
  assert.equal(band(132), 'long-2');
  assert.equal(band(119), 'short-1');
  assert.equal(band(108), 'short-1');
  assert.equal(band(107), 'short-2');
  assert.equal(band(10), 'short-6');
  assert.equal(band(1200), 'long-6');
});

test('waterline bands use whole years in yearly view and short spans in monthly view', () => {
  const { waterlineStep } = loadDrawdownApi();
  assert.equal(waterlineStep(120, 'years'), 12);
  assert.equal(waterlineStep(360, 'years'), 24);
  assert.equal(waterlineStep(600, 'years'), 60);
  assert.equal(waterlineStep(120, 'months'), 12);
  assert.equal(waterlineStep(24, 'months'), 3);
  assert.equal(waterlineStep(6, 'months'), 1);
});

test('waterline levels skip contours that cannot cross the view', () => {
  const { waterlineLevels } = loadDrawdownApi();
  const months = levels => Array.from(levels, level => level.months);
  assert.deepEqual(months(waterlineLevels(180, 'years', 44, 400)),
    [120, 132, 144, 156, 168, 180, 192, 204, 216, 228, 240]);
  assert.deepEqual(months(waterlineLevels(180, 'years', 150, 200)), [156, 168, 180, 192]);
  // Without a horizon, contours mark whole years, at most eight of them.
  assert.deepEqual(months(waterlineLevels(null, 'years', 44, 400)), [60, 120, 180, 240, 300, 360]);
});

test('waterline crossing is the least income that reaches each level', () => {
  const api = loadDrawdownApi();
  const lasts = lastsFor(api, fifteenYears);
  const model = { params: fifteenYears, pins: [] };
  for (const level of [168, 180, 192]) {
    const income = api.waterlineCrossing(model, 420000, level, 8000);
    assert.ok(lasts(420000, income) >= level, `level ${level} at ${income}`);
    assert.ok(lasts(420000, income - 2) < level, `level ${level} below ${income}`);
  }
  // Hand-checked with a separate full-projection search: $3,092.14/mo lasts 15 years at $420K.
  // The search resolves 1/4096 of the axis ($1.95 here).
  assert.ok(Math.abs(api.waterlineCrossing(model, 420000, 180, 8000) - 3092.14) < 2);
  assert.equal(api.waterlineCrossing(model, 900000, 120, 8000), 0);
  assert.equal(api.waterlineCrossing(model, 1000, 600, 8000), null);
});

test('waterline needs report the least income and principal that last the horizon', () => {
  const api = loadDrawdownApi();
  const lasts = lastsFor(api, fifteenYears);
  const needs = api.waterlineNeeds({ params: fifteenYears, pins: [] }, 180);
  assert.ok(Math.abs(needs.income - 3092.14) < 1);
  assert.ok(Math.abs(needs.principal - 332747.78) < 100);
  assert.ok(lasts(420000, needs.income) >= 180 && lasts(420000, needs.income - 1) < 180);
  assert.ok(lasts(needs.principal, 3600) >= 180 && lasts(needs.principal - 100, 3600) < 180);

  // With sales fully taxed away, principal cannot fund anything that income does not.
  const untouchable = scenario({ ...fifteenYears, sale_tax_rate: 1, investment_income: 1000 });
  assert.equal(api.waterlineNeeds({ params: untouchable, pins: [] }, 180).principal, null);
});

test('waterline axes frame the scenario, both intercepts, and round snap values', () => {
  const api = loadDrawdownApi();
  const lasts = lastsFor(api, fifteenYears);
  const axes = api.waterlineAxes({ params: fifteenYears, pins: [] }, 180);
  assert.ok(axes.xMax >= 840000 && axes.yMax >= 7200);
  assert.ok(lasts(axes.xMax, 0) >= 180, 'principal alone lasts at the right edge');
  assert.ok(lasts(axes.xMax / 400, axes.yMax) >= 180, 'income alone lasts at the top edge');
  assert.equal(420000 % axes.xStep, 0);
  assert.equal(3600 % axes.yStep, 0);
});
