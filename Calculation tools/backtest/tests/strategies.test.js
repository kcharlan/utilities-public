'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { simulate, availableYearRange, STRATEGIES } = require('../engine.js');

function close(actual, expected) {
  assert.ok(Math.abs(actual - expected) <= 1e-9 * Math.max(1, Math.abs(expected)));
}

test('afterYear receives defensive completed-year inputs and updates state before the next step', () => {
  const observations = [];
  const strategy = {
    init() {
      return { completed: 0 };
    },
    step(state) {
      return { withdrawal: state.completed };
    },
    afterYear(state, row, ctx) {
      observations.push({
        rowFrozen: Object.isFrozen(row) && Object.isFrozen(row.endBalances),
        contextFrozen: Object.isFrozen(ctx) && Object.isFrozen(ctx.yearRow),
        matchingYear: row.year === ctx.yearRow.year,
      });
      assert.throws(() => { row.endBalances.stock = -1; }, TypeError);
      assert.throws(() => { ctx.yearRow.year = -1; }, TypeError);
      state.completed += 1;
    },
  };
  const years = [
    { year: 2010, stock_tr: 0, bond10_tr: 0, tbill_tr: 0, cpi_change: 0, quality: 'ok' },
    { year: 2011, stock_tr: 0, bond10_tr: 0, tbill_tr: 0, cpi_change: 0, quality: 'ok' },
  ];

  const result = simulate(years, strategy, {}, {
    startingBalance: 1_000,
    allocation: { stock: 1, bond: 0, bill: 0 },
  });

  assert.deepEqual(result.rows.map((row) => row.withdrawalNominal), [0, 1]);
  assert.deepEqual(observations, [
    { rowFrozen: true, contextFrozen: true, matchingYear: true },
    { rowFrozen: true, contextFrozen: true, matchingYear: true },
  ]);
});

function marketYear(year, stockReturn, inflation = 0) {
  return {
    year,
    stock_tr: stockReturn,
    bond10_tr: 0,
    tbill_tr: 0,
    cpi_change: inflation,
    quality: 'ok',
  };
}

function runGuyton(years, params = {}, optionOverrides = {}) {
  return simulate(years, STRATEGIES.guytonKlinger, params, {
    startingBalance: 1_000,
    allocation: { stock: 1, bond: 0, bill: 0 },
    ...optionOverrides,
  });
}

function guytonDecision(currentWithdrawal, total, params = {}, yearsRemaining = 16, inflation = 0) {
  const state = STRATEGIES.guytonKlinger.init(params, { startingBalance: 1_000 });
  STRATEGIES.guytonKlinger.afterYear(state, {
    withdrawalNominal: currentWithdrawal,
    portfolioReturn: 0,
  }, { yearRow: { cpi_change: inflation } });
  return STRATEGIES.guytonKlinger.step(state, {
    index: 1,
    total,
    yearsRemaining,
  });
}

test('guytonKlinger publishes bounded parameter metadata and max-safe-rate support', () => {
  const strategy = STRATEGIES.guytonKlinger;
  assert.equal(strategy.id, 'guytonKlinger');
  assert.equal(strategy.name, 'Guyton-Klinger guardrails');
  assert.deepEqual(strategy.assets, ['stock', 'bond', 'bill']);
  assert.equal(strategy.supportsMaxSafeRate, true);
  assert.equal(strategy.rateParamKey, 'initialRate');
  assert.equal(strategy.safeRateSearch, 'adaptive');
  assert.deepEqual(
    strategy.paramSchema.map(({ key, type, default: defaultValue, min, max, step }) => (
      { key, type, default: defaultValue, min, max, step }
    )),
    [
      { key: 'initialRate', type: 'percent', default: 0.04, min: 0, max: 0.20, step: 0.001 },
      { key: 'guardrail', type: 'percent', default: 0.20, min: 0, max: 1, step: 0.01 },
      { key: 'adjustment', type: 'percent', default: 0.10, min: 0, max: 1, step: 0.01 },
      { key: 'preservationCutoffYears', type: 'number', default: 15, min: 0, max: 100, step: 1 },
    ],
  );
  for (const field of strategy.paramSchema) {
    assert.equal(typeof field.label, 'string');
    assert.ok(field.label.length > 0);
    assert.equal(typeof field.hint, 'string');
    assert.ok(field.hint.length > 0);
  }
});

test('guytonKlinger applies defaults, permits zero parameters, and rejects invalid parameters', () => {
  const years = [marketYear(2020, 0)];
  close(runGuyton(years).rows[0].withdrawalNominal, 40);
  close(runGuyton(years, {
    initialRate: 0,
    guardrail: 0,
    adjustment: 0,
    preservationCutoffYears: 0,
  }).rows[0].withdrawalNominal, 0);

  for (const [key, value, pattern] of [
    ['initialRate', '0.04', /initialRate.*finite number/i],
    ['initialRate', -0.01, /initialRate.*between 0 and 0\.2/i],
    ['initialRate', 0.21, /initialRate.*between 0 and 0\.2/i],
    ['guardrail', NaN, /guardrail.*finite number/i],
    ['guardrail', -0.01, /guardrail.*between 0 and 1/i],
    ['guardrail', 1.01, /guardrail.*between 0 and 1/i],
    ['adjustment', '0.10', /adjustment.*finite number/i],
    ['adjustment', -0.01, /adjustment.*between 0 and 1/i],
    ['adjustment', 1.01, /adjustment.*between 0 and 1/i],
    ['preservationCutoffYears', 1.5, /preservationCutoffYears.*integer/i],
    ['preservationCutoffYears', -1, /preservationCutoffYears.*between 0 and 100/i],
    ['preservationCutoffYears', 101, /preservationCutoffYears.*between 0 and 100/i],
  ]) {
    assert.throws(() => runGuyton(years, { [key]: value }), pattern);
  }
});

test('guytonKlinger skips prior inflation after a negative return when the current rate is above initial', () => {
  const result = runGuyton([
    marketYear(2020, -0.10, 0.10),
    marketYear(2021, 0),
  ]);

  close(result.rows[1].startTotal, 864);
  close(result.rows[1].withdrawalNominal, 40);
  assert.equal(result.rows[1].notes, 'inflation raise skipped');
});

test('guytonKlinger consumes the engine portfolioReturn scalar without reconstructing returns', () => {
  const state = STRATEGIES.guytonKlinger.init({}, { startingBalance: 1_000 });
  const row = new Proxy(
    { withdrawalNominal: 40, portfolioReturn: -0.10 },
    {
      get(target, property) {
        if (property === 'returnAmounts' || property === 'balancesAfterReturns') {
          throw new Error(`strategy attempted duplicate portfolio arithmetic via ${String(property)}`);
        }
        return target[property];
      },
    },
  );

  STRATEGIES.guytonKlinger.afterYear(state, row, { yearRow: { cpi_change: 0.10 } });
  const decision = STRATEGIES.guytonKlinger.step(state, {
    index: 1,
    total: 864,
    yearsRemaining: 1,
  });

  close(decision.withdrawal, 40);
  assert.equal(decision.notes, 'inflation raise skipped');
});

test('guytonKlinger applies prior inflation after a negative return when the current rate is below initial', () => {
  const result = runGuyton([
    marketYear(2020, 1),
    marketYear(2021, -0.10, 0.10),
    marketYear(2022, 0),
  ], { guardrail: 1 });

  close(result.rows[1].startTotal, 1_920);
  close(result.rows[1].withdrawalNominal, 40);
  close(result.rows[2].startTotal, 1_692);
  close(result.rows[2].withdrawalNominal, 44);
  assert.equal(result.rows[2].notes, '');
});

test('guytonKlinger cuts after a large drawdown in year 1 and records ordered rule notes', () => {
  const result = runGuyton([
    marketYear(2020, -0.30, 0.10),
    marketYear(2021, 0),
  ], {}, { horizon: 20 });

  close(result.rows[1].startTotal, 672);
  close(result.rows[1].withdrawalNominal, 36);
  assert.equal(result.rows[1].notes, 'inflation raise skipped; capital preservation −10%');
});

test('guytonKlinger raises spending after a large gain', () => {
  const result = runGuyton([
    marketYear(2020, 1),
    marketYear(2021, 0),
  ]);

  close(result.rows[1].startTotal, 1_920);
  close(result.rows[1].withdrawalNominal, 44);
  assert.equal(result.rows[1].notes, 'prosperity +10%');
});

test('guytonKlinger suppresses capital preservation inside the final cutoff years', () => {
  const result = runGuyton([
    marketYear(2020, 0),
    marketYear(2021, 0),
  ], { initialRate: 0.20, guardrail: 0.20 });

  close(result.rows[1].startTotal, 800);
  close(result.rows[1].withdrawalNominal, 200);
  assert.equal(result.rows[1].notes, '');
});

test('guytonKlinger applies the preservation cutoff strictly after 15 years remaining', () => {
  const atCutoff = guytonDecision(50, 1_000, {}, 15);
  close(atCutoff.withdrawal, 50);
  assert.equal(atCutoff.notes, '');

  const outsideCutoff = guytonDecision(50, 1_000, {}, 16);
  close(outsideCutoff.withdrawal, 45);
  assert.equal(outsideCutoff.notes, 'capital preservation −10%');
});

test('guytonKlinger guardrails preserve strict decimal boundaries with floating-point tolerance', () => {
  const upperParams = { initialRate: 0.04, guardrail: 0.20 };
  assert.equal(guytonDecision(0.048 * 3, 3, upperParams).notes, '');
  assert.equal(guytonDecision((0.048 - 1e-8) * 3, 3, upperParams).notes, '');
  assert.equal(
    guytonDecision((0.048 + 1e-8) * 3, 3, upperParams).notes,
    'capital preservation −10%',
  );

  const lowerParams = { initialRate: 0.04, guardrail: 0.25 };
  assert.equal(guytonDecision(0.03 * 30, 30, lowerParams).notes, '');
  assert.equal(guytonDecision((0.03 + 1e-8) * 30, 30, lowerParams).notes, '');
  assert.equal(
    guytonDecision((0.03 - 1e-8) * 30, 30, lowerParams).notes,
    'prosperity +10%',
  );
});

test('guytonKlinger formats configured adjustment percentages in guardrail notes', () => {
  const capital = runGuyton([
    marketYear(2020, 0),
    marketYear(2021, 0),
  ], { initialRate: 0.20, guardrail: 0.20, adjustment: 0.075 }, { horizon: 20 });
  close(capital.rows[1].withdrawalNominal, 185);
  assert.equal(capital.rows[1].notes, 'capital preservation −7.5%');

  const prosperity = runGuyton([
    marketYear(2020, 1),
    marketYear(2021, 0),
  ], { adjustment: 0.125 });
  close(prosperity.rows[1].withdrawalNominal, 45);
  assert.equal(prosperity.rows[1].notes, 'prosperity +12.5%');

  const tiny = guytonDecision(50, 1_000, { adjustment: 1e-13 });
  assert.ok(tiny.withdrawal < 50);
  assert.equal(tiny.notes, 'capital preservation −1e-11%');
});

test('guytonKlinger uses the single pre-inflation rate for guardrail triggers', () => {
  const result = runGuyton([
    marketYear(2020, -0.30),
    marketYear(2021, 41 / 159, 0.10),
    marketYear(2022, 0),
  ], {}, { horizon: 25 });

  close(result.rows[0].withdrawalNominal, 40);
  close(result.rows[1].withdrawalNominal, 36);
  close(result.rows[1].endTotal, 800);
  close(result.rows[2].withdrawalNominal, 39.60);
  assert.equal(result.rows[2].notes, '');
});

test('guytonKlinger applies prosperity to the inflation-updated amount using the pre-inflation rate', () => {
  const result = runGuyton([
    marketYear(2020, 17 / 48, 0.10),
    marketYear(2021, 0),
  ]);

  close(result.rows[1].startTotal, 1_300);
  // 40 / 1,300 is below the 3.2% lower guardrail. Inflation first makes the
  // withdrawal 44, then the pre-inflation trigger raises that amount to 48.4.
  close(result.rows[1].withdrawalNominal, 48.40);
  assert.equal(result.rows[1].notes, 'prosperity +10%');
});

test('guytonKlinger leaves guardrails and notes inactive at a zero portfolio balance', () => {
  const result = runGuyton([
    marketYear(2020, -1),
    marketYear(2021, 0),
  ], { initialRate: 0.20 });

  assert.equal(result.rows[0].endTotal, 0);
  assert.equal(result.rows[1].failed, true);
  assert.equal(result.rows[1].requestedWithdrawalNominal, 200);
  assert.equal(result.rows[1].notes, '');
});

test('guytonKlinger uses proportional withdrawals and the global annual rebalance default', () => {
  const result = simulate([
    {
      year: 2020,
      stock_tr: 1,
      bond10_tr: 0,
      tbill_tr: 0,
      cpi_change: 0,
      quality: 'ok',
    },
  ], STRATEGIES.guytonKlinger, {}, {
    startingBalance: 1_000,
    allocation: { stock: 0.5, bond: 0.5, bill: 0 },
  });

  close(result.rows[0].withdrawalsByAsset.stock, 20);
  close(result.rows[0].withdrawalsByAsset.bond, 20);
  close(result.rows[0].endBalances.stock, 720);
  close(result.rows[0].endBalances.bond, 720);
});

test('fixedReal uses cumulative CPI for nominal withdrawals and keeps real spending flat', () => {
  const years = [
    { year: 2020, stock_tr: 0, bond10_tr: 0, tbill_tr: 0, cpi_change: 0.10, quality: 'ok' },
    { year: 2021, stock_tr: 0, bond10_tr: 0, tbill_tr: 0, cpi_change: -0.05, quality: 'ok' },
    { year: 2022, stock_tr: 0, bond10_tr: 0, tbill_tr: 0, cpi_change: 0.20, quality: 'ok' },
  ];
  const result = simulate(years, STRATEGIES.fixedReal, { initialRate: 0.04 }, {
    startingBalance: 1_000,
    allocation: { stock: 0.5, bond: 0.5, bill: 0 },
    feeRate: 0,
    taxRate: 0,
    rebalance: 'annual',
  });

  close(result.rows[0].withdrawalNominal, 40);
  close(result.rows[1].withdrawalNominal, 44);
  close(result.rows[2].withdrawalNominal, 41.8);
  for (const row of result.rows) close(row.withdrawalReal, 40);
  close(result.metrics.spendingVolatility, 0);
});

test('fixedReal publishes the rate strategy metadata', () => {
  const fixedReal = STRATEGIES.fixedReal;
  assert.equal(fixedReal.id, 'fixedReal');
  assert.equal(fixedReal.name, 'Fixed real (4% rule)');
  assert.deepEqual(fixedReal.assets, ['stock', 'bond', 'bill']);
  assert.equal(fixedReal.supportsMaxSafeRate, true);
  assert.equal(fixedReal.rateParamKey, 'initialRate');
  assert.equal(fixedReal.safeRateSearch, 'monotonic');
  assert.equal(fixedReal.paramSchema.find((field) => field.key === 'initialRate').default, 0.04);
});

test('fixedReal enforces its published initial-rate schema', () => {
  const years = [{ year: 2020, stock_tr: 0, bond10_tr: 0, tbill_tr: 0, cpi_change: 0, quality: 'ok' }];
  const run = (initialRate) => simulate(years, STRATEGIES.fixedReal, { initialRate }, {
    startingBalance: 1_000,
    allocation: { stock: 1, bond: 0, bill: 0 },
  });

  assert.throws(() => run('0.04'), /initialRate.*finite number/i);
  assert.throws(() => run(-0.01), /initialRate.*between 0 and 0\.2/i);
  assert.throws(() => run(0.21), /initialRate.*between 0 and 0\.2/i);
  assert.equal(run(0.20).rows[0].withdrawalNominal, 200);
});

test('fixedPercent withdraws its rate from each start-of-year portfolio total', () => {
  const years = [
    { year: 2020, stock_tr: 0.10, bond10_tr: 0, tbill_tr: 0, cpi_change: 0, quality: 'ok' },
    { year: 2021, stock_tr: -0.20, bond10_tr: 0, tbill_tr: 0, cpi_change: 0, quality: 'ok' },
    { year: 2022, stock_tr: 0.50, bond10_tr: 0, tbill_tr: 0, cpi_change: 0, quality: 'ok' },
  ];
  const result = simulate(years, STRATEGIES.fixedPercent, { rate: 0.10 }, {
    startingBalance: 1_000,
    allocation: { stock: 1, bond: 0, bill: 0 },
  });

  close(result.rows[0].withdrawalNominal, 100);
  close(result.rows[1].withdrawalNominal, 99);
  close(result.rows[2].withdrawalNominal, 71.28);
  for (const row of result.rows) close(row.withdrawalNominal, 0.10 * row.startTotal);
});

test('fixedPercent never fails from withdrawals at a valid rate despite severe losses', () => {
  const years = Array.from({ length: 8 }, (_, index) => ({
    year: 2030 + index,
    stock_tr: -0.99,
    bond10_tr: -0.99,
    tbill_tr: -0.99,
    cpi_change: 0,
    quality: 'ok',
  }));
  const result = simulate(years, STRATEGIES.fixedPercent, { rate: 0.20 }, {
    startingBalance: 1_000,
    allocation: { stock: 0.5, bond: 0.3, bill: 0.2 },
  });

  assert.equal(result.metrics.success, true);
  assert.equal(result.metrics.failureYear, null);
  assert.equal(result.rows.length, years.length);
});

test('fixedPercent spending varies where fixedReal spending stays constant', () => {
  const years = [
    { year: 2040, stock_tr: 0.20, bond10_tr: 0, tbill_tr: 0, cpi_change: 0, quality: 'ok' },
    { year: 2041, stock_tr: -0.10, bond10_tr: 0, tbill_tr: 0, cpi_change: 0, quality: 'ok' },
    { year: 2042, stock_tr: 0.10, bond10_tr: 0, tbill_tr: 0, cpi_change: 0, quality: 'ok' },
  ];
  const options = {
    startingBalance: 1_000,
    allocation: { stock: 1, bond: 0, bill: 0 },
  };
  const fixedPercent = simulate(years, STRATEGIES.fixedPercent, { rate: 0.04 }, options);
  const fixedReal = simulate(years, STRATEGIES.fixedReal, { initialRate: 0.04 }, options);

  assert.ok(fixedPercent.metrics.spendingVolatility > 0);
  close(fixedReal.metrics.spendingVolatility, 0);
});

test('fixedPercent publishes and enforces its rate metadata', () => {
  const fixedPercent = STRATEGIES.fixedPercent;
  assert.equal(fixedPercent.id, 'fixedPercent');
  assert.equal(fixedPercent.name, 'Fixed percentage');
  assert.deepEqual(fixedPercent.assets, ['stock', 'bond', 'bill']);
  assert.equal(fixedPercent.supportsMaxSafeRate, false);
  assert.equal(fixedPercent.rateParamKey, null);
  assert.equal(fixedPercent.safeRateSearch, null);
  assert.deepEqual(
    fixedPercent.paramSchema.find((field) => field.key === 'rate'),
    {
      key: 'rate',
      label: 'Annual distribution rate',
      type: 'percent',
      default: 0.04,
      min: 0,
      max: 0.20,
      step: 0.001,
      hint: 'Gross portfolio distribution each year; after-tax spending is net of the configured tax.',
      // frontierRange is an additive schema key; the existing rate bounds remain unchanged.
      frontierRange: { from: 0.02, to: 0.08, step: 0.0025 },
    },
  );

  const years = [{ year: 2050, stock_tr: 0, bond10_tr: 0, tbill_tr: 0, cpi_change: 0, quality: 'ok' }];
  const run = (params) => simulate(years, fixedPercent, params, {
    startingBalance: 1_000,
    allocation: { stock: 1, bond: 0, bill: 0 },
  });
  assert.equal(run({}).rows[0].withdrawalNominal, 40);
  assert.equal(run({ rate: 0.20 }).rows[0].withdrawalNominal, 200);
  assert.throws(() => run({ rate: '0.04' }), /rate.*finite number/i);
  assert.throws(() => run({ rate: -0.01 }), /rate.*between 0 and 0\.2/i);
  assert.throws(() => run({ rate: 0.21 }), /rate.*between 0 and 0\.2/i);
});

test('fixedPercent treats rate as gross distribution and remains solvent under maximum tax', () => {
  const years = [
    { year: 2060, stock_tr: -0.999999, bond10_tr: 0, tbill_tr: 0, cpi_change: 0, quality: 'ok' },
    { year: 2061, stock_tr: 0, bond10_tr: 0, tbill_tr: 0, cpi_change: 0, quality: 'ok' },
  ];
  const result = simulate(years, STRATEGIES.fixedPercent, { rate: 0.20 }, {
    startingBalance: 1_000,
    allocation: { stock: 1, bond: 0, bill: 0 },
    taxRate: 0.95,
  });

  assert.equal(result.metrics.success, true);
  for (const row of result.rows) {
    close(row.requestedGrossWithdrawal, 0.20 * row.startTotal);
    close(row.grossWithdrawal, 0.20 * row.startTotal);
    close(row.withdrawalNominal, 0.20 * row.startTotal * 0.05);
  }
});

test('fixedPercent handles zero tax, zero rate, and total market loss without false failure', () => {
  const zeroTax = simulate([
    { year: 2070, stock_tr: 0, bond10_tr: 0, tbill_tr: 0, cpi_change: 0, quality: 'ok' },
  ], STRATEGIES.fixedPercent, { rate: 0.20 }, {
    startingBalance: 1_000,
    allocation: { stock: 1, bond: 0, bill: 0 },
    taxRate: 0,
  });
  close(zeroTax.rows[0].withdrawalNominal, 200);
  close(zeroTax.rows[0].grossWithdrawal, 200);

  const zeroRate = simulate([
    { year: 2071, stock_tr: -1, bond10_tr: -1, tbill_tr: -1, cpi_change: 0, quality: 'ok' },
    { year: 2072, stock_tr: -1, bond10_tr: -1, tbill_tr: -1, cpi_change: 0, quality: 'ok' },
  ], STRATEGIES.fixedPercent, { rate: 0 }, {
    startingBalance: 1_000,
    allocation: { stock: 1, bond: 0, bill: 0 },
    taxRate: 0.95,
  });
  assert.equal(zeroRate.metrics.success, true);
  assert.deepEqual(zeroRate.rows.map((row) => row.grossWithdrawal), [0, 0]);

  const totalLoss = simulate([
    { year: 2073, stock_tr: -1, bond10_tr: 0, tbill_tr: 0, cpi_change: 0, quality: 'ok' },
    { year: 2074, stock_tr: 0, bond10_tr: 0, tbill_tr: 0, cpi_change: 0, quality: 'ok' },
  ], STRATEGIES.fixedPercent, { rate: 0.20 }, {
    startingBalance: 1_000,
    allocation: { stock: 1, bond: 0, bill: 0 },
    taxRate: 0.95,
  });
  assert.equal(totalLoss.metrics.success, true);
  assert.deepEqual(totalLoss.rows.map((row) => row.grossWithdrawal), [200, 0]);
});

function runBarbell(years, params = {}, optionOverrides = {}) {
  return simulate(years, STRATEGIES.barbell, params, {
    startingBalance: 1_000,
    allocation: { stock: 0.88, bond: 0, bill: 0.12 },
    rebalance: 'annual',
    ...optionOverrides,
  });
}

test('barbell publishes bounded metadata, defaults, and dynamic reserve assets', () => {
  const strategy = STRATEGIES.barbell;
  assert.equal(strategy.id, 'barbell');
  assert.equal(strategy.supportsMaxSafeRate, true);
  assert.equal(strategy.rateParamKey, 'initialRate');
  assert.equal(strategy.safeRateSearch, 'adaptive');
  assert.deepEqual(
    strategy.paramSchema.map(({ key, default: defaultValue }) => ({ key, default: defaultValue })),
    [
      { key: 'initialRate', default: 0.04 },
      { key: 'reserveYears', default: 3 },
      { key: 'reserveMix', default: 'bills' },
      { key: 'spendRule', default: 'reserve_after_down' },
      { key: 'refillRule', default: 'after_up_years' },
    ],
  );
  assert.deepEqual(strategy.resolveAssets({}), ['stock', 'bill']);
  assert.deepEqual(strategy.resolveAssets({ reserveMix: 'bonds' }), ['stock', 'bond']);
  assert.deepEqual(strategy.resolveAssets({ reserveMix: 'split' }), ['stock', 'bond', 'bill']);
  assert.deepEqual(strategy.resolveAssets({ reserveYears: 0, reserveMix: 'split' }), ['stock']);
});

test('barbell rejects invalid parameters and accepts all boundary values', () => {
  const years = [marketYear(2020, 0)];
  for (const [params, pattern] of [
    [{ initialRate: '0.04' }, /initialRate.*finite number/i],
    [{ initialRate: -0.01 }, /initialRate.*between 0 and 0\.2/i],
    [{ initialRate: 0.21 }, /initialRate.*between 0 and 0\.2/i],
    [{ reserveYears: NaN }, /reserveYears.*finite number/i],
    [{ reserveYears: -1 }, /reserveYears.*between 0 and 100/i],
    [{ reserveYears: 101 }, /reserveYears.*between 0 and 100/i],
    [{ reserveMix: 'cash' }, /reserveMix.*bills.*bonds.*split/i],
    [{ spendRule: 'random' }, /spendRule.*reserve_after_down.*reserve_first/i],
    [{ refillRule: 'never' }, /refillRule.*after_up_years.*annual/i],
  ]) {
    assert.throws(() => runBarbell(years, params), pattern);
  }

  const result = runBarbell(years, {
    initialRate: 0.20,
    reserveYears: 100,
    reserveMix: 'bills',
    spendRule: 'reserve_first',
    refillRule: 'annual',
  });
  assert.equal(result.rows[0].withdrawalNominal, 200);
});

test('barbell reserve target follows CPI-adjusted spending and annual refill weights', () => {
  const result = runBarbell([
    marketYear(2020, 0, 0.10),
    marketYear(2021, 0, 0.20),
    marketYear(2022, 0),
  ], { refillRule: 'annual' });

  // Year zero establishes the reserve from current spending. Later refills
  // restore that CPI-adjusted dollar target after returns and fees.
  close(result.rows[0].endBalances.bill, 120);
  close(result.rows[1].withdrawalNominal, 44);
  close(result.rows[1].endBalances.bill, 132);
  close(result.rows[2].withdrawalNominal, 52.8);
  close(result.rows[2].endBalances.bill, 158.4);
  assert.equal(result.rows[0].notes, 'initial reserve established; withdrawal funded by stock');
  assert.equal(result.rows[0].endBalances.stock, 840);
  assert.equal(result.rows[1].notes, 'withdrawal funded by stock; reserve refilled');
});

test('barbell reserve-after-down changes next-year withdrawal order from canonical stock returns', () => {
  const down = runBarbell([
    marketYear(2020, -0.10),
    marketYear(2021, 0),
  ]);
  close(down.rows[1].withdrawalsByAsset.bill, 40);
  close(down.rows[1].withdrawalsByAsset.stock, 0);
  assert.equal(down.rows[1].notes, 'withdrawal funded by bills');

  const up = runBarbell([
    marketYear(2020, 0.10),
    marketYear(2021, 0),
  ]);
  close(up.rows[1].withdrawalsByAsset.stock, 40);
  close(up.rows[1].withdrawalsByAsset.bill, 0);
  assert.equal(up.rows[1].notes, 'withdrawal funded by stock; reserve refilled');
});

test('barbell after-up-years preserves drift with exactly null rebalancing after a down year', () => {
  const state = STRATEGIES.barbell.init({}, {
    startingBalance: 1_000,
    allocation: { stock: 0.88, bond: 0, bill: 0.12 },
  });
  STRATEGIES.barbell.afterYear(state, { returnRates: { stock: -0.10 } });
  const decision = STRATEGIES.barbell.step(state, {
    index: 1,
    cpiIndex: 1,
    total: 872,
  });
  assert.equal(decision.rebalanceTo, null);

  const result = runBarbell([
    marketYear(2020, -0.50),
    marketYear(2021, 0),
  ]);
  assert.equal(result.rows[1].endBalances.stock, 420);
  assert.equal(result.rows[1].endBalances.bill, 80);
  assert.notEqual(result.rows[1].endBalances.bill / result.rows[1].endTotal, 120 / 540);
});

test('barbell split reserves set equal targets and draw bills, bonds, then stocks', () => {
  const result = runBarbell([
    marketYear(2020, 0.10),
    marketYear(2021, 0),
    marketYear(2022, 0),
  ], {
    reserveYears: 4,
    reserveMix: 'split',
    spendRule: 'reserve_first',
    refillRule: 'annual',
  }, {
    allocation: { stock: 0.84, bond: 0.08, bill: 0.08 },
  });

  close(result.rows[1].endBalances.bill, result.rows[1].endBalances.bond);
  close(result.rows[1].endBalances.bill, 80);
  close(result.rows[1].endBalances.bond, 80);
  close(result.rows[2].withdrawalsByAsset.bill, 40);
  close(result.rows[2].withdrawalsByAsset.bond, 0);
  assert.equal(result.rows[2].notes, 'withdrawal funded by bills; reserve refilled');
});

test('barbell reserve-first falls through an insufficient reserve to stocks', () => {
  const result = runBarbell([marketYear(2020, 0), marketYear(2021, 0)], {
    reserveYears: 1.25,
    spendRule: 'reserve_first',
  });
  close(result.rows[1].withdrawalsByAsset.bill, 10);
  close(result.rows[1].withdrawalsByAsset.stock, 30);
  assert.equal(result.rows[1].notes, 'withdrawal funded by bills and stock');
});

test('barbell establishes its year-zero reserve target independent of caller allocation', () => {
  for (const [reserveMix, expected] of [
    ['bills', { stock: 880, bond: 0, bill: 120 }],
    ['bonds', { stock: 880, bond: 120, bill: 0 }],
    ['split', { stock: 880, bond: 60, bill: 60 }],
  ]) {
    const result = runBarbell([marketYear(2020, 0)], { reserveMix }, {
      allocation: { stock: 0, bond: 1, bill: 0 },
    });
    assert.deepEqual(result.rows[0].startBalances, expected);
  }

  const capped = runBarbell([marketYear(2020, 0)], {
    initialRate: 0.20,
    reserveYears: 100,
    reserveMix: 'split',
  });
  assert.deepEqual(capped.rows[0].startBalances, { stock: 0, bond: 500, bill: 500 });

  const zero = runBarbell([marketYear(2020, 0)], { reserveYears: 0 }, {
    allocation: { stock: 0, bond: 1, bill: 0 },
  });
  assert.deepEqual(zero.rows[0].startBalances, { stock: 1_000, bond: 0, bill: 0 });
});

test('barbell refills to exact post-return reserve dollars after gain, loss, and fees', () => {
  for (const [secondReturn, feeRate] of [[1, 0], [-0.5, 0], [0.25, 0.10]]) {
    const result = runBarbell([
      marketYear(2020, 0.10),
      marketYear(2021, secondReturn),
    ], {}, { feeRate });
    close(result.rows[1].endBalances.bill, 120);
    close(result.rows[1].endBalances.stock, result.rows[1].endTotal - 120);
    assert.equal(result.rows[1].notes, 'withdrawal funded by stock; reserve refilled');
  }
});

test('barbell caps refill target to actual post-return total and handles zero safely', () => {
  const capped = runBarbell([
    marketYear(2020, 1),
    marketYear(2021, -0.99),
  ], { initialRate: 0.20, reserveYears: 100, refillRule: 'annual' });
  assert.equal(capped.rows[1].endBalances.stock, 0);
  close(capped.rows[1].endBalances.bill, capped.rows[1].endTotal);

  const zero = runBarbell([
    marketYear(2020, -1),
    marketYear(2021, 0),
  ], { initialRate: 0, reserveYears: 3, refillRule: 'annual' });
  assert.deepEqual(zero.rows[1].endBalances, { stock: 0, bond: 0, bill: 0 });
});

test('barbell appends refill notes only after successful rebalance execution', () => {
  const failed = runBarbell([
    marketYear(2020, 0.10, 100),
    marketYear(2021, 0),
  ]);
  assert.equal(failed.rows[1].failed, true);
  assert.doesNotMatch(failed.rows[1].notes, /reserve refilled/);

  const partial = runBarbell([
    marketYear(2020, 0.10),
    marketYear(2021, 0),
  ], {}, { horizon: 3 });
  assert.equal(partial.metrics.partial, true);
  assert.match(partial.rows[1].notes, /reserve refilled/);
});

test('barbell year zero never invents a prior return or refill decision', () => {
  for (const refillRule of ['after_up_years', 'annual']) {
    const state = STRATEGIES.barbell.init({ refillRule }, {
      startingBalance: 1_000,
      allocation: { stock: 0.88, bond: 0, bill: 0.12 },
    });
    const decision = STRATEGIES.barbell.step(state, { index: 0, cpiIndex: 1, total: 1_000 });
    assert.equal(decision.rebalanceTo, null);
    assert.deepEqual(decision.withdrawFrom, ['stock', 'bill']);
    assert.match(decision.notes, /initial reserve established/);
  }
});

test('zero-reserve barbell degenerates to all-stock fixed-real row by row', () => {
  const years = [
    marketYear(2020, 0.10, 0.05),
    marketYear(2021, -0.20, 0.02),
    marketYear(2022, 0.30),
  ];
  const options = {
    startingBalance: 1_000,
    allocation: { stock: 1, bond: 0, bill: 0 },
    rebalance: 'none',
  };
  const actual = simulate(years, STRATEGIES.barbell, { reserveYears: 0 }, options);
  const expected = simulate(years, STRATEGIES.fixedReal, {}, options);
  for (let index = 0; index < years.length; index += 1) {
    assert.deepEqual(actual.rows[index], expected.rows[index]);
  }
});

test('barbell asset resolution produces bill and bond historical boundaries', () => {
  const rows = Array.from({ length: 1928 - 1872 + 1 }, (_, index) => ({
    year: 1872 + index,
    stock_tr: 0,
    bond10_tr: 0,
    tbill_tr: 1872 + index < 1928 ? null : 0,
    cpi_change: 0,
  }));
  assert.deepEqual(
    availableYearRange(STRATEGIES.barbell, { reserveMix: 'bills' }, rows, {
      allocation: { stock: 0, bond: 1, bill: 0 },
    }),
    { first: 1928, last: 1928, excludedAssets: ['bill'] },
  );
  assert.deepEqual(
    availableYearRange(STRATEGIES.barbell, { reserveMix: 'bonds' }, rows, {
      allocation: { stock: 0, bond: 0, bill: 1 },
    }),
    { first: 1872, last: 1928, excludedAssets: [] },
  );
  assert.deepEqual(
    availableYearRange(STRATEGIES.barbell, { reserveYears: 0, reserveMix: 'split' }, rows, {
      allocation: { stock: 0, bond: 0, bill: 1 },
    }),
    { first: 1872, last: 1928, excludedAssets: [] },
  );
  assert.deepEqual(
    availableYearRange(STRATEGIES.barbell, { reserveMix: 'split' }, rows, {
      allocation: { stock: 1, bond: 0, bill: 0 },
    }),
    { first: 1928, last: 1928, excludedAssets: ['bill'] },
  );
});

test('barbell consumes canonical completed-row stock return without duplicate arithmetic', () => {
  const state = STRATEGIES.barbell.init({}, {
    startingBalance: 1_000,
    allocation: { stock: 0.88, bond: 0, bill: 0.12 },
  });
  const row = new Proxy({ returnRates: { stock: 0.10 } }, {
    get(target, property) {
      if (property === 'returnAmounts' || property === 'balancesAfterReturns' || property === 'portfolioReturn') {
        throw new Error(`duplicate arithmetic via ${String(property)}`);
      }
      return target[property];
    },
  });
  STRATEGIES.barbell.afterYear(state, row);
  const decision = STRATEGIES.barbell.step(state, { index: 1, cpiIndex: 1, total: 1_000 });
  assert.notEqual(decision.rebalanceToDollars, null);
  assert.equal(decision.rebalanceNote, 'reserve refilled');
});

test('strategies expose depletion and independent frozen frontier range metadata', () => {
  for (const [id, strategy] of Object.entries(STRATEGIES)) {
    assert.equal(strategy.canDeplete, id !== 'fixedPercent');
    const key = id === 'fixedPercent' ? 'rate' : 'initialRate';
    assert.equal(strategy.frontierParamKey, key);
    const range = strategy.paramSchema.find(field => field.key === key).frontierRange;
    assert.deepEqual(range, { from: 0.02, to: 0.08, step: 0.0025 });
    assert.ok(Object.isFrozen(range));
    assert.throws(() => { range.from = 0; }, TypeError);
  }
  assert.equal(STRATEGIES.fixedPercent.rateParamKey, null);
  for (const [strategy, key, expected] of [
    [STRATEGIES.guytonKlinger, 'preservationCutoffYears', {from:0,to:30,step:1}],
    [STRATEGIES.barbell, 'reserveYears', {from:0,to:10,step:1}],
  ]) {
    const range = strategy.paramSchema.find(field=>field.key===key).frontierRange;
    assert.deepEqual(range, expected);
    assert.ok(Object.isFrozen(range));
  }
});
