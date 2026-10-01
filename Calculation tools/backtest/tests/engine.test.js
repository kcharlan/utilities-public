'use strict';

const test = require('node:test');
const { getMarketRows } = require('./helpers/dataset.cjs');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {
  simulate,
  availableYearRange,
  sweepStartYears,
  sweepGrid,
  maxSafeRate,
  resolveInitialAllocation,
  STRATEGIES,
} = require('../engine.js');

const EPSILON = 1e-9;

function close(actual, expected, message) {
  assert.ok(
    Math.abs(actual - expected) <= EPSILON * Math.max(1, Math.abs(expected)),
    `${message || 'values differ'}: expected ${expected}, got ${actual}`,
  );
}

function year(year, stock, bond = 0, bill = 0, inflation = 0, quality = 'ok') {
  return {
    year,
    stock_tr: stock,
    bond10_tr: bond,
    tbill_tr: bill,
    cpi_change: inflation,
    quality,
  };
}

function strategy(step) {
  return {
    id: 'test',
    name: 'Test strategy',
    assets: ['stock', 'bond', 'bill'],
    supportsMaxSafeRate: false,
    rateParamKey: null,
    paramSchema: [],
    init: () => ({}),
    step,
  };
}

function options(overrides = {}) {
  return {
    startingBalance: 100,
    allocation: { stock: 1, bond: 0, bill: 0 },
    feeRate: 0,
    taxRate: 0,
    rebalance: 'annual',
    ...overrides,
  };
}

test('one-year stock run withdraws at CPI index 1 and applies the stock return', () => {
  let observedCpi;
  const result = simulate(
    [year(2000, 0.10, 0, 0, 0.03)],
    strategy((_state, ctx) => {
      observedCpi = ctx.cpiIndex;
      return { withdrawal: 10, withdrawFrom: 'proportional' };
    }),
    {},
    options(),
  );

  assert.equal(observedCpi, 1);
  assert.equal(result.rows[0].cpiIndex, 1);
  assert.equal(result.rows[0].endCpiIndex, 1.03);
  close(result.rows[0].endTotal, 99);
  close(result.metrics.terminalWealthNominal, 99);
  close(result.metrics.terminalWealthReal, 99 / 1.03);
});

test('failed pre-return rows have no end-of-year CPI index', () => {
  const result = simulate(
    [year(2000, 0.10, 0, 0, 0.03)],
    strategy(() => ({ withdrawal: 101, withdrawFrom: 'proportional' })),
    {},
    options(),
  );

  assert.equal(result.rows[0].failed, true);
  assert.equal(result.rows[0].endCpiIndex, null);
});

test('portfolioReturn is weighted from post-withdrawal pre-return balances', () => {
  const result = simulate(
    [year(2000, 0.25, -0.25, 0.125)],
    strategy(() => ({ withdrawal: 20, withdrawFrom: 'proportional' })),
    {},
    options({ allocation: { stock: 0.5, bond: 0.3, bill: 0.2 } }),
  );

  // After the proportional withdrawal, balances are 40/24/16. Their return
  // amounts are 10/-6/2, so the canonical portfolio return is 6 / 80 = 7.5%.
  close(result.rows[0].portfolioReturn, 0.075);
});

test('portfolioReturn is zero when no balance remains for the returns stage', () => {
  const result = simulate(
    [year(2000, 0.25, -0.25, 0.125)],
    strategy(() => ({ withdrawal: 100, withdrawFrom: 'proportional' })),
    {},
    options({ allocation: { stock: 0.5, bond: 0.3, bill: 0.2 } }),
  );

  assert.equal(result.rows[0].failed, false);
  assert.equal(result.rows[0].portfolioReturn, 0);
});

test('portfolioReturn excludes tax, fees, and either rebalancing policy', () => {
  for (const rebalance of ['annual', 'none']) {
    const result = simulate(
      [year(2000, 0.20)],
      strategy(() => ({ withdrawal: 80, withdrawFrom: 'proportional' })),
      {},
      options({
        startingBalance: 1_000,
        allocation: { stock: 0.5, bond: 0.5, bill: 0 },
        taxRate: 0.20,
        feeRate: 0.10,
        rebalance,
      }),
    );

    // Tax gross-up removes 100, leaving 450/450 before returns. The stock's
    // 90 gain is 10% of that 900 base regardless of later fees/rebalancing.
    close(result.rows[0].grossWithdrawal, 100);
    close(result.rows[0].portfolioReturn, 0.10);
  }
});

test('afterYear is not called for a failed withdrawal row', () => {
  let calls = 0;
  const hookStrategy = {
    ...strategy(() => ({ withdrawal: 101 })),
    afterYear() { calls += 1; },
  };

  const result = simulate([year(2000, 0)], hookStrategy, {}, options());

  assert.equal(result.rows[0].failed, true);
  assert.equal(calls, 0);
});

test('afterYear is called for every completed year in a partial run', () => {
  const completedYears = [];
  const hookStrategy = {
    ...strategy(() => ({ withdrawal: 0 })),
    afterYear(_state, row) { completedYears.push(row.year); },
  };

  const result = simulate(
    [year(2000, 0), year(2001, 0)],
    hookStrategy,
    {},
    options({ horizon: 3 }),
  );

  assert.equal(result.metrics.partial, true);
  assert.deepEqual(completedYears, [2000, 2001]);
});

test('afterYear errors propagate to the simulate caller', () => {
  const hookStrategy = {
    ...strategy(() => ({ withdrawal: 0 })),
    afterYear() { throw new Error('afterYear hook failed'); },
  };

  assert.throws(
    () => simulate([year(2000, 0)], hookStrategy, {}, options()),
    /afterYear hook failed/,
  );
});

test('tax gross-up removes gross spending and records tax paid', () => {
  const result = simulate(
    [year(2001, 0)],
    strategy(() => ({ withdrawal: 40_000, withdrawFrom: 'proportional' })),
    {},
    options({ startingBalance: 100_000, taxRate: 0.25 }),
  );

  close(result.rows[0].grossWithdrawal, 53_333.333333333336);
  close(result.rows[0].taxPaid, 13_333.333333333336);
  close(result.rows[0].endTotal, 46_666.666666666664);
});

test('fees are recorded from post-return balances after the withdrawal stage', () => {
  const result = simulate(
    [year(2002, 1)],
    strategy(() => ({ withdrawal: 10, withdrawFrom: 'proportional' })),
    {},
    options({ feeRate: 0.10 }),
  );

  // Required stages: withdraw => 90, return => 180, fee => 18, end => 162.
  // Return and fee multiplication commute on the same base, so observing the
  // post-return balance is what makes this a non-vacuous ordering assertion.
  close(result.rows[0].balancesAfterReturns.stock, 180);
  close(result.rows[0].fees.stock, 18);
  close(result.rows[0].endTotal, 162);
  assert.notEqual(result.rows[0].endTotal, 160); // fee-before-withdrawal result
});

test('priority withdrawal drains bills then bonds without touching stock', () => {
  const result = simulate(
    [year(2003, 0)],
    strategy(() => ({
      withdrawal: 25,
      withdrawFrom: ['bill', 'bond', 'stock'],
      rebalanceTo: null,
    })),
    {},
    options({ allocation: { stock: 0.5, bond: 0.3, bill: 0.2 } }),
  );

  assert.deepEqual(result.rows[0].withdrawalsByAsset, { stock: 0, bond: 5, bill: 20 });
  assert.deepEqual(result.rows[0].endBalances, { stock: 50, bond: 25, bill: 0 });
});

test('rebalanceTo null preserves drift after divergent returns', () => {
  const result = simulate(
    [year(2004, 1, 0)],
    strategy(() => ({ withdrawal: 0, withdrawFrom: 'proportional', rebalanceTo: null })),
    {},
    options({ allocation: { stock: 0.5, bond: 0.5, bill: 0 } }),
  );

  assert.deepEqual(result.rows[0].endBalances, { stock: 100, bond: 50, bill: 0 });
});

test('depletion records the failure year and stops immediately', () => {
  const result = simulate(
    [year(2005, 0), year(2006, 0), year(2007, 0)],
    strategy(() => ({ withdrawal: 60, withdrawFrom: 'proportional' })),
    {},
    options(),
  );

  assert.equal(result.metrics.success, false);
  assert.equal(result.metrics.failureYear, 2006);
  assert.equal(result.rows.length, 2);
  assert.equal(result.rows[1].failed, true);
  assert.equal(result.rows[1].endTotal, 0);
});

test('depletion drains assets omitted from a withdrawal priority before recording failure', () => {
  const result = simulate(
    [year(2008, 0)],
    strategy(() => ({ withdrawal: 200, withdrawFrom: ['bill'] })),
    {},
    options(),
  );

  assert.equal(result.metrics.success, false);
  assert.equal(result.metrics.failureYear, 2008);
  assert.equal(result.rows.length, 1);
  assert.equal(result.rows[0].failed, true);
  assert.equal(result.rows[0].grossWithdrawal, 100);
  assert.deepEqual(result.rows[0].withdrawalsByAsset, { stock: 100, bond: 0, bill: 0 });
  assert.deepEqual(result.rows[0].endBalances, { stock: 0, bond: 0, bill: 0 });
});

test('forced-depletion source notes list priority assets before canonical drained extras', () => {
  for (const [withdrawal, taxRate] of [[200, 0], [60, 0.5]]) {
    const result = simulate(
      [year(2008, 0)],
      strategy(() => ({
        withdrawal,
        withdrawFrom: ['bill'],
        noteWithdrawalSources: true,
      })),
      {},
      options({
        allocation: { stock: 0.5, bond: 0.3, bill: 0.2 },
        taxRate,
      }),
    );

    assert.equal(result.rows[0].failed, true);
    assert.deepEqual(result.rows[0].withdrawalsByAsset, { stock: 50, bond: 30, bill: 20 });
    assert.equal(result.rows[0].notes, 'withdrawal funded by bills, stock, and bonds');
  }
});

test('exact-total proportional withdrawal safely drains every asset without failure', () => {
  const result = simulate(
    [year(2009, 0, 0, 0)],
    strategy(() => ({ withdrawal: 100, withdrawFrom: 'proportional' })),
    {},
    options({ allocation: { stock: 0.5, bond: 0.3, bill: 0.2 } }),
  );

  assert.equal(result.metrics.success, true);
  assert.equal(result.metrics.yearsCompleted, 1);
  assert.deepEqual(result.rows[0].withdrawalsByAsset, { stock: 50, bond: 30, bill: 20 });
  assert.deepEqual(result.rows[0].endBalances, { stock: 0, bond: 0, bill: 0 });
});

test('exact-total incomplete priority cannot bypass its declared source list', () => {
  assert.throws(
    () => simulate(
      [year(2009, 0)],
      strategy(() => ({ withdrawal: 100, withdrawFrom: ['bill'] })),
      {},
      options(),
    ),
    /priority.*enough/i,
  );
});

test('exact-total complete priority drains in declared order without failure', () => {
  const result = simulate(
    [year(2009, 0, 0, 0)],
    strategy(() => ({ withdrawal: 100, withdrawFrom: ['bill', 'bond', 'stock'] })),
    {},
    options({ allocation: { stock: 0.5, bond: 0.3, bill: 0.2 } }),
  );

  assert.equal(result.metrics.success, true);
  assert.deepEqual(result.rows[0].withdrawalsByAsset, { stock: 50, bond: 30, bill: 20 });
  assert.deepEqual(result.rows[0].endBalances, { stock: 0, bond: 0, bill: 0 });
});

test('invalid allocation throws a descriptive error', () => {
  assert.throws(
    () => simulate([], strategy(() => ({ withdrawal: 0 })), {}, options({ allocation: { stock: 0.8, bond: 0.1, bill: 0 } })),
    /allocation.*sum to 1/i,
  );
});

test('tax rate of 1 throws a descriptive error', () => {
  assert.throws(
    () => simulate([], strategy(() => ({ withdrawal: 0 })), {}, options({ taxRate: 1 })),
    /taxRate.*0.*0\.95/i,
  );
});

test('negative starting balance throws a descriptive error', () => {
  assert.throws(
    () => simulate([], strategy(() => ({ withdrawal: 0 })), {}, options({ startingBalance: -1 })),
    /startingBalance.*greater than 0/i,
  );
});

test('three-year known-answer metrics use end-of-year CPI and real spending changes', () => {
  const withdrawals = [10, 22, 16.5];
  const result = simulate(
    [year(2010, 0.20, 0, 0, 0.10), year(2011, -0.50), year(2012, 1, 0, 0, 0.10)],
    strategy((_state, ctx) => ({ withdrawal: withdrawals[ctx.index], withdrawFrom: 'proportional' })),
    {},
    options({ rebalance: 'none' }),
  );

  // Nominal ends: (100-10)*1.2=108; (108-22)*.5=43;
  // (43-16.5)*2=53. End CPI: 1.1, 1.1, 1.21, so real ends are
  // 98.1818, 39.0909, 43.8017. The trough from the initial real peak
  // of 100 is 1 - 39.0909/100. Real spending is 10, 20, 15;
  // changes are +100% and -25%, whose population stdev is 62.5%.
  close(result.metrics.terminalWealthReal, 53 / 1.21);
  close(result.metrics.maxDrawdownReal, 1 - (43 / 1.1) / 100);
  close(result.metrics.spendingVolatility, 0.625);
  close(result.metrics.totalWithdrawnReal, 45);
  assert.equal(result.metrics.minRealSpending, 10);
  assert.equal(result.metrics.minRealSpendingYear, 2010);
  assert.equal(result.metrics.spending.floor, 10);
  assert.equal(result.metrics.spending.floorFirstIndex, 0);
  assert.equal(result.metrics.spending.baseline, 10);
});

test('rejects a return below -100% or a non-finite applied return', () => {
  for (const stockReturn of [-1.01, Infinity, NaN]) {
    assert.throws(
      () => simulate(
        [year(2020, stockReturn)],
        strategy(() => ({ withdrawal: 0 })),
        {},
        options(),
      ),
      /stock_tr.*finite.*at least -1|stock_tr.*at least -1.*finite/i,
    );
  }
});

test('allows a missing return only when that asset balance is exactly zero', () => {
  const zeroBill = simulate(
    [year(2020, 0, 0, null)],
    strategy(() => ({ withdrawal: 0 })),
    {},
    options(),
  );
  assert.equal(zeroBill.rows[0].endBalances.bill, 0);

  assert.throws(
    () => simulate(
      [year(2020, 0, 0, null)],
      strategy(() => ({ withdrawal: 0 })),
      {},
      options({ allocation: { stock: 0, bond: 0, bill: 1 } }),
    ),
    /tbill_tr.*finite.*funded|tbill_tr.*funded.*finite/i,
  );
});

test('proportional withdrawal assigns rounding residual only to a funded asset', () => {
  const result = simulate(
    [year(1937, 0, 0, null)],
    strategy(() => ({
      withdrawal: 32_369.944031957148,
      withdrawFrom: 'proportional',
      rebalanceTo: null,
    })),
    {},
    options({
      startingBalance: 1_121_242.5442542322,
      allocation: { stock: 0.5, bond: 0.5, bill: 0 },
      rebalance: 'none',
    }),
  );

  assert.equal(result.rows[0].endBalances.bill, 0);
  close(
    Object.values(result.rows[0].withdrawalsByAsset).reduce((sum, amount) => sum + amount, 0),
    result.rows[0].grossWithdrawal,
  );
});

test('rejects arithmetic overflow instead of reporting non-finite success metrics', () => {
  assert.throws(
    () => simulate(
      [year(2020, 1)],
      strategy(() => ({ withdrawal: 0 })),
      {},
      options({ startingBalance: Number.MAX_VALUE }),
    ),
    /finite|overflow/i,
  );
});

test('validates CPI changes and rejects a non-finite real result', () => {
  for (const inflation of [-1.01, Infinity, NaN]) {
    assert.throws(
      () => simulate(
        [year(2020, 0, 0, 0, inflation)],
        strategy(() => ({ withdrawal: 0 })),
        {},
        options(),
      ),
      /cpi_change|CPI/i,
    );
  }
  assert.throws(
    () => simulate(
      [year(2020, 0, 0, 0, -1)],
      strategy(() => ({ withdrawal: 0 })),
      {},
      options(),
    ),
    /CPI index.*greater than 0|real.*finite/i,
  );
});

test('spending volatility is null when a required percentage change starts at zero', () => {
  function volatility(withdrawals) {
    return simulate(
      withdrawals.map((_, index) => year(2030 + index, 0)),
      strategy((_state, ctx) => ({ withdrawal: withdrawals[ctx.index] })),
      {},
      options(),
    ).metrics.spendingVolatility;
  }

  assert.equal(volatility([0, 0, 0]), null); // all-zero, two undefined changes
  assert.equal(volatility([0, 10]), null);
  assert.equal(volatility([10, 0]), 0); // one defined -100% change
  assert.equal(volatility([0, 0]), null);
  assert.equal(volatility([0]), 0); // no required year-over-year changes
});

test('a failed run is not partial even when source data is shorter than requested horizon', () => {
  const result = simulate(
    [year(2040, 0)],
    strategy(() => ({ withdrawal: 200 })),
    {},
    options({ horizon: 5 }),
  );

  assert.equal(result.metrics.success, false);
  assert.equal(result.metrics.partial, false);
  assert.equal(result.metrics.failureYear, 2040);
});

test('truncated solvent source is partial and default annual rebalancing restores allocation', () => {
  const result = simulate(
    [year(2041, 1, 0)],
    strategy(() => ({ withdrawal: 0 })),
    {},
    options({ allocation: { stock: 0.5, bond: 0.5, bill: 0 }, horizon: 2 }),
  );

  assert.equal(result.metrics.partial, true);
  assert.deepEqual(result.rows[0].endBalances, { stock: 75, bond: 75, bill: 0 });
});

test('rejects malformed decisions, withdrawals, rebalancing, notes, and priorities', () => {
  const cases = [
    { decision: [], pattern: /decision.*plain object/i },
    { decision: { withdrawal: NaN }, pattern: /withdrawal.*finite/i },
    { decision: { withdrawal: -1 }, pattern: /withdrawal.*negative/i },
    { decision: { withdrawal: 0, rebalanceTo: 'none' }, pattern: /rebalanceTo.*undefined.*null.*allocation/i },
    { decision: { withdrawal: 0, rebalanceTo: { stock: 0.5, bond: 0.4, bill: 0 } }, pattern: /rebalanceTo.*sum to 1/i },
    { decision: { withdrawal: 0, notes: [] }, pattern: /notes.*string/i },
    { decision: { withdrawal: 0, noteWithdrawalSources: 'yes' }, pattern: /noteWithdrawalSources.*boolean/i },
    { decision: { withdrawal: 0, rebalanceNote: [] }, pattern: /rebalanceNote.*string/i },
    { decision: { withdrawal: 0, rebalanceToDollars: [] }, pattern: /rebalanceToDollars.*plain object/i },
    { decision: { withdrawal: 0, rebalanceToDollars: { dollarTargets: { bill: -1 }, remainderAsset: 'stock' } }, pattern: /dollarTargets.*bill.*non-negative/i },
    { decision: { withdrawal: 0, rebalanceToDollars: { dollarTargets: { gold: 1 }, remainderAsset: 'stock' } }, pattern: /unknown.*gold/i },
    { decision: { withdrawal: 0, rebalanceToDollars: { dollarTargets: { bill: 1 }, remainderAsset: 'gold' } }, pattern: /remainderAsset.*stock.*bond.*bill/i },
    { decision: { withdrawal: 0, rebalanceTo: { stock: 1, bond: 0, bill: 0 }, rebalanceToDollars: { dollarTargets: {}, remainderAsset: 'stock' } }, pattern: /only one.*rebalance/i },
    { decision: { withdrawal: 1, withdrawFrom: ['stock', 'stock'] }, pattern: /duplicate.*stock/i },
    { decision: { withdrawal: 1, withdrawFrom: ['gold'] }, pattern: /unknown.*gold/i },
    { decision: { withdrawal: 1, withdrawFrom: ['bill'] }, pattern: /priority.*enough/i },
  ];

  for (const { decision, pattern } of cases) {
    assert.throws(
      () => simulate([year(2050, 0)], strategy(() => decision), {}, options()),
      pattern,
    );
  }
});

test('engine resolves post-return dollar targets exactly after gains, losses, and fees', () => {
  const dollarStrategy = {
    init() { return {}; },
    step() {
      return {
        withdrawal: 10,
        withdrawFrom: ['stock', 'bill'],
        rebalanceToDollars: { dollarTargets: { bill: 25 }, remainderAsset: 'stock' },
        rebalanceNote: 'dollar rebalance executed',
      };
    },
  };
  for (const [stockReturn, feeRate] of [[1, 0], [-0.5, 0], [0.25, 0.10]]) {
    const result = simulate([year(2042, stockReturn, 0, 0)], dollarStrategy, {}, options({
      allocation: { stock: 0.9, bond: 0, bill: 0.1 },
      feeRate,
    }));
    assert.equal(result.rows[0].endBalances.bill, 25);
    assert.equal(result.rows[0].endBalances.stock, result.rows[0].endTotal - 25);
    assert.equal(result.rows[0].notes, 'dollar rebalance executed');
  }
});

test('engine caps dollar targets to post-return total and handles a zero total safely', () => {
  const target = (withdrawal) => ({
    init() { return {}; },
    step() {
      return {
        withdrawal,
        rebalanceToDollars: { dollarTargets: { bond: 60, bill: 60 }, remainderAsset: 'stock' },
      };
    },
  });
  const capped = simulate([year(2043, 0)], target(50), {}, options());
  assert.deepEqual(capped.rows[0].endBalances, { stock: 0, bond: 25, bill: 25 });

  const zero = simulate([year(2044, -1)], target(0), {}, options());
  assert.deepEqual(zero.rows[0].endBalances, { stock: 0, bond: 0, bill: 0 });
});

test('engine initialAllocation hook overrides caller allocation using validated dollar targets', () => {
  let observedContext;
  const strategyWithInitialPlan = {
    init() { return { target: 30 }; },
    initialAllocation(state, ctx) {
      observedContext = ctx;
      return { dollarTargets: { bill: state.target }, remainderAsset: 'stock' };
    },
    step() { return { withdrawal: 0 }; },
  };
  const result = simulate([year(2045, 0)], strategyWithInitialPlan, {}, options({
    allocation: { stock: 0, bond: 1, bill: 0 },
  }));
  assert.deepEqual(result.rows[0].startBalances, { stock: 70, bond: 0, bill: 30 });
  assert.equal(observedContext.startingBalance, 100);
  assert.equal(Object.isFrozen(observedContext), true);
  assert.throws(
    () => simulate([year(2045, 0)], {
      ...strategyWithInitialPlan,
      initialAllocation: () => ({ dollarTargets: { bill: NaN }, remainderAsset: 'stock' }),
    }, {}, options()),
    /initialAllocation.*dollarTargets.*bill.*finite/i,
  );
});

test('resolveInitialAllocation returns caller weights for conventional strategies', () => {
  const allocation = { stock: 0.55, bond: 0.35, bill: 0.10 };
  for (const [candidate, params] of [
    [STRATEGIES.fixedReal, { initialRate: 0.04 }],
    [STRATEGIES.fixedPercent, { rate: 0.04 }],
    [STRATEGIES.guytonKlinger, { initialRate: 0.04 }],
  ]) {
    assert.deepEqual(
      resolveInitialAllocation(
        candidate,
        params,
        options({ startingBalance: 1_000, allocation }),
      ),
      allocation,
    );
  }
});

test('resolveInitialAllocation uses the barbell initial plan for every reserve mix', () => {
  const run = (reserveMix) => resolveInitialAllocation(
    STRATEGIES.barbell,
    { initialRate: 0.04, reserveYears: 3, reserveMix },
    options({ startingBalance: 1_000, allocation: { stock: 0, bond: 1, bill: 0 } }),
  );

  assert.deepEqual(run('bills'), { stock: 0.88, bond: 0, bill: 0.12 });
  assert.deepEqual(run('bonds'), { stock: 0.88, bond: 0.12, bill: 0 });
  assert.deepEqual(run('split'), { stock: 0.88, bond: 0.06, bill: 0.06 });
});

test('resolveInitialAllocation applies the same cap as simulation initialization', () => {
  const params = { initialRate: 0.20, reserveYears: 100, reserveMix: 'split' };
  const runOptions = options({
    startingBalance: 1_000,
    allocation: { stock: 1, bond: 0, bill: 0 },
  });
  const resolved = resolveInitialAllocation(STRATEGIES.barbell, params, runOptions);
  const result = simulate([year(2045, 0)], STRATEGIES.barbell, params, runOptions);

  assert.deepEqual(resolved, { stock: 0, bond: 0.5, bill: 0.5 });
  assert.deepEqual(result.rows[0].startBalances, { stock: 0, bond: 500, bill: 500 });
});

test('priority withdrawal reconciles floating dust and source notes follow funded priority', () => {
  const priorityStrategy = (withdrawal) => strategy(() => ({
    withdrawal,
    withdrawFrom: ['bill', 'bond', 'stock'],
    noteWithdrawalSources: true,
  }));
  for (const taxRate of [0, 0.30]) {
    const requestedNet = taxRate === 0 ? 0.3 : 0.21;
    const result = simulate([year(2046, 0)], priorityStrategy(requestedNet), {}, options({
      startingBalance: 1,
      allocation: { stock: 0.7, bond: 0.2, bill: 0.1 },
      taxRate,
    }));
    assert.equal(result.rows[0].withdrawalsByAsset.stock, 0);
    close(result.rows[0].withdrawalsByAsset.bill, 0.1);
    close(result.rows[0].withdrawalsByAsset.bond, 0.2);
    assert.equal(result.rows[0].notes, 'withdrawal funded by bills and bonds');
  }

  const tiny = simulate([year(2047, 0)], priorityStrategy(1e-12), {}, options({
    startingBalance: 1,
    allocation: { stock: 0, bond: 0, bill: 1 },
  }));
  assert.equal(tiny.rows[0].withdrawalsByAsset.bill, 1e-12);
  assert.equal(tiny.rows[0].notes, 'withdrawal funded by bills');
});

test('fixed-real strategies share one initial spending expression', () => {
  const source = fs.readFileSync(require.resolve('../engine.js'), 'utf8');
  assert.equal((source.match(/initialRate \* options\.startingBalance/g) || []).length, 1);
  assert.ok((source.match(/initializeFixedReal\(params, options\)/g) || []).length >= 3);
});

test('strategy inputs are defensive frozen copies while strategy state remains mutable', () => {
  const callerYear = year(2060, 0.10);
  const callerParams = { nested: { rate: 1 } };
  const callerOptions = options();
  let initParams;
  let initOptions;
  const mutatingStrategy = {
    ...strategy((state, ctx) => {
      assert.equal(Object.isFrozen(ctx), true);
      assert.equal(Object.isFrozen(ctx.balances), true);
      assert.equal(Object.isFrozen(ctx.yearRow), true);
      assert.equal(Object.isFrozen(ctx.options), true);
      assert.equal(Object.isFrozen(ctx.options.allocation), true);
      assert.equal(Object.isFrozen(ctx.params), true);
      assert.equal(Object.isFrozen(ctx.params.nested), true);
      assert.equal(ctx.params, initParams);
      assert.equal(ctx.options, initOptions);
      assert.notEqual(ctx.params, callerParams);
      assert.notEqual(ctx.options, callerOptions);
      state.steps += 1;
      assert.throws(() => { ctx.balances.stock = 0; }, TypeError);
      assert.throws(() => { ctx.yearRow.stock_tr = 9; }, TypeError);
      assert.throws(() => { ctx.options.taxRate = 0.9; }, TypeError);
      assert.throws(() => { ctx.params.nested.rate = 9; }, TypeError);
      return { withdrawal: 0, notes: `step ${state.steps}` };
    }),
    init(paramsCopy, optionsCopy) {
      initParams = paramsCopy;
      initOptions = optionsCopy;
      return { steps: 0 };
    },
  };

  const result = simulate([callerYear, { ...callerYear, year: 2061 }], mutatingStrategy, callerParams, callerOptions);
  assert.equal(result.rows[0].endTotal, 110);
  close(result.rows[1].endTotal, 121);
  assert.deepEqual(result.rows.map((row) => row.notes), ['step 1', 'step 2']);
  assert.equal(callerYear.stock_tr, 0.10);
  assert.deepEqual(callerParams, { nested: { rate: 1 } });
  assert.equal(callerOptions.taxRate, 0);
});

test('failed rows skip returns, fees, rebalancing, and CPI advancement', () => {
  const result = simulate(
    [year(2070, Infinity, Infinity, Infinity, Infinity)],
    strategy(() => ({ withdrawal: 200, rebalanceTo: { stock: 0, bond: 1, bill: 0 } })),
    {},
    options({ feeRate: 0.5 }),
  );

  const row = result.rows[0];
  assert.equal(row.failed, true);
  assert.deepEqual(row.returnAmounts, { stock: 0, bond: 0, bill: 0 });
  assert.deepEqual(row.fees, { stock: 0, bond: 0, bill: 0 });
  assert.deepEqual(row.endBalances, { stock: 0, bond: 0, bill: 0 });
  assert.equal(result.metrics.yearsCompleted, 0);
  assert.equal(result.metrics.terminalWealthReal, 0);
});

test('failed rows normalize skipped invalid or missing returns to JSON-safe nulls', () => {
  const result = simulate(
    [{ year: 2071, stock_tr: Infinity, bond10_tr: undefined, tbill_tr: NaN, cpi_change: Infinity, quality: 'ok' }],
    strategy(() => ({ withdrawal: 200 })),
    {},
    options(),
  );

  assert.deepEqual(result.rows[0].returns, { stock: null, bond: null, bill: null });
  assert.deepEqual(result.rows[0].returnRates, { stock: null, bond: null, bill: null });
  assert.deepEqual(JSON.parse(JSON.stringify(result.rows[0])).returns, { stock: null, bond: null, bill: null });
});

test('params must be a plain object', () => {
  for (const params of [null, [], new Date(0)]) {
    assert.throws(
      () => simulate([], strategy(() => ({ withdrawal: 0 })), params, options()),
      /params.*plain object/i,
    );
  }
});

test('cyclic params and year rows fail with descriptive input errors', () => {
  const cyclicParams = {};
  cyclicParams.self = cyclicParams;
  assert.throws(
    () => simulate([], strategy(() => ({ withdrawal: 0 })), cyclicParams, options()),
    /params.*cyclic/i,
  );

  const cyclicYear = year(2072, 0);
  cyclicYear.self = cyclicYear;
  assert.throws(
    () => simulate([cyclicYear], strategy(() => ({ withdrawal: 0 })), {}, options()),
    /yearSequence\[0\].*cyclic/i,
  );
});

test('CommonJS loading avoids global pollution and browser loading exposes BacktestEngine', () => {
  const source = fs.readFileSync(require.resolve('../engine.js'), 'utf8');
  const browserContext = vm.createContext({});
  // The browser loads the local statistics dependency before the engine.
  vm.runInContext(fs.readFileSync(require.resolve('../stats.js'), 'utf8'), browserContext);
  vm.runInContext(source, browserContext);
  assert.equal(typeof browserContext.BacktestEngine.simulate, 'function');
  assert.equal(typeof browserContext.BacktestEngine.availableYearRange, 'function');
  assert.equal(typeof browserContext.BacktestEngine.resolveInitialAllocation, 'function');
  assert.equal(browserContext.BacktestEngine.STRATEGIES.fixedReal.id, 'fixedReal');
  assert.equal(browserContext.BacktestEngine.STRATEGIES.fixedPercent.id, 'fixedPercent');

  const commonJsContext = vm.createContext({ module: { exports: {} }, require: (dependency) => {
    assert.equal(dependency, './stats.js');
    return require('../stats.js');
  } });
  vm.runInContext(source, commonJsContext);
  assert.equal(typeof commonJsContext.module.exports.simulate, 'function');
  assert.equal(commonJsContext.BacktestEngine, undefined);
});

const realMarketRows = getMarketRows;

test('availableYearRange applies the real-data bill boundary only to nonzero bill allocations', async () => {
  const rows = await realMarketRows();
  assert.equal(rows.length, 154);

  const withBills = availableYearRange(
    STRATEGIES.fixedReal,
    { initialRate: 0.04 },
    rows,
    { allocation: { stock: 0.5, bond: 0.4, bill: 0.1 } },
  );
  const withoutBills = availableYearRange(
    STRATEGIES.fixedReal,
    { initialRate: 0.04 },
    rows,
    { allocation: { stock: 0.5, bond: 0.5, bill: 0 } },
  );

  assert.deepEqual(withBills, { first: 1928, last: 2025, excludedAssets: ['bill'] });
  assert.deepEqual(withoutBills, { first: 1872, last: 2025, excludedAssets: [] });
});

test('availableYearRange prefers fourth-argument allocation and preserves three-argument compatibility', () => {
  const rows = [year(2000, 0, 0, null), year(2001, 0, 0, 0)];

  assert.deepEqual(
    availableYearRange(
      STRATEGIES.fixedReal,
      { allocation: { stock: 0, bond: 0, bill: 1 } },
      rows,
      { allocation: { stock: 1, bond: 0, bill: 0 } },
    ),
    { first: 2000, last: 2001, excludedAssets: [] },
  );
  assert.deepEqual(
    availableYearRange(
      STRATEGIES.fixedReal,
      { allocation: { stock: 0, bond: 0, bill: 1 } },
      rows,
    ),
    { first: 2001, last: 2001, excludedAssets: ['bill'] },
  );
  assert.deepEqual(
    availableYearRange(STRATEGIES.fixedReal, {}, rows),
    { first: 2001, last: 2001, excludedAssets: ['bill'] },
  );
  assert.throws(
    () => availableYearRange(STRATEGIES.fixedReal, {}, rows, []),
    /options.*plain object/i,
  );
});

test('availableYearRange resolves dynamic strategy assets before applying allocation weights', () => {
  const rows = [
    year(2000, 0, 0, null),
    year(2001, 0, 0, 0),
  ];
  const assetsFunction = {
    assets: (params) => params.useBills ? ['stock', 'bill'] : ['stock'],
  };
  const resolveMethod = {
    assets: ['stock'],
    resolveAssets: (params) => params.useBills ? ['stock', 'bill'] : ['stock'],
  };

  assert.deepEqual(
    availableYearRange(assetsFunction, { useBills: true, allocation: { stock: 0.5, bond: 0, bill: 0.5 } }, rows),
    { first: 2001, last: 2001, excludedAssets: ['bill'] },
  );
  assert.deepEqual(
    availableYearRange(resolveMethod, { useBills: true, allocation: { stock: 1, bond: 0, bill: 0 } }, rows),
    { first: 2001, last: 2001, excludedAssets: ['bill'] },
  );
  assert.deepEqual(
    availableYearRange(
      { assets: () => ['stock'] },
      { allocation: { stock: 0.5, bond: 0, bill: 0.5 } },
      rows,
    ),
    { first: 2001, last: 2001, excludedAssets: ['bill'] },
  );
  assert.deepEqual(
    availableYearRange(
      { assets: ['stock'] },
      {},
      rows,
      { allocation: { stock: 0, bond: 0, bill: 1 } },
    ),
    { first: 2001, last: 2001, excludedAssets: ['bill'] },
  );
  assert.deepEqual(
    availableYearRange(
      { assets: ['stock'], initialAllocation: () => ({ stock: 1, bond: 0, bill: 0 }) },
      {},
      rows,
      { allocation: { stock: 0, bond: 0, bill: 1 } },
    ),
    { first: 2000, last: 2001, excludedAssets: [] },
  );
});

test('availableYearRange returns the longest contiguous valid block across interior gaps', () => {
  const rows = [
    year(2000, 0, 0),
    year(2001, 0, null),
    year(2002, 0, 0),
    year(2003, 0, 0),
    year(2004, 0, null),
    year(2005, 0, 0),
    year(2006, 0, 0),
  ];

  assert.deepEqual(
    availableYearRange({ assets: ['stock', 'bond'] }, {}, rows),
    { first: 2002, last: 2003, excludedAssets: ['bond'] },
  );
});

test('availableYearRange excludes unusable CPI years without attributing them to an asset', () => {
  const rows = [
    year(2000, 0, 0, 0, 0),
    year(2001, 0, 0, 0, -1),
    year(2002, 0, 0, 0, NaN),
    year(2003, 0, 0, 0, Infinity),
    year(2004, 0, 0, 0, -0.999999),
  ];

  assert.deepEqual(
    availableYearRange(
      STRATEGIES.fixedReal,
      {},
      rows,
      { allocation: { stock: 1, bond: 0, bill: 0 } },
    ),
    { first: 2000, last: 2000, excludedAssets: [] },
  );
  assert.deepEqual(
    availableYearRange(
      STRATEGIES.fixedReal,
      {},
      [year(2000, 0, 0, 0, -1)],
      { allocation: { stock: 1, bond: 0, bill: 0 } },
    ),
    { first: null, last: null, excludedAssets: [] },
  );
});

test('availableYearRange handles unsorted rows, earliest ties, and invalid return variants', () => {
  const unsortedTie = [
    year(2005, 0),
    year(2001, 0),
    year(2004, 0),
    year(2000, 0),
  ];
  assert.deepEqual(
    availableYearRange({ assets: ['stock'] }, {}, unsortedTie),
    { first: 2000, last: 2001, excludedAssets: [] },
  );

  for (const invalidReturn of [null, undefined, NaN, Infinity, -1.000001]) {
    assert.deepEqual(
      availableYearRange(
        { assets: ['stock'] },
        {},
        [year(2000, invalidReturn)],
      ),
      { first: null, last: null, excludedAssets: ['stock'] },
    );
  }
  assert.deepEqual(
    availableYearRange({ assets: ['stock'] }, {}, [year(2000, -1)]),
    { first: 2000, last: 2000, excludedAssets: [] },
  );
});

test('availableYearRange isolates resolver params, propagates resolver errors, and validates safe unique years', () => {
  const params = { nested: { useBills: true } };
  let resolvedParams;
  const resolvingStrategy = {
    resolveAssets(received) {
      resolvedParams = received;
      assert.equal(Object.isFrozen(received), true);
      assert.equal(Object.isFrozen(received.nested), true);
      return ['stock'];
    },
  };
  availableYearRange(resolvingStrategy, params, [year(2000, 0)]);
  assert.notEqual(resolvedParams, params);
  assert.deepEqual(params, { nested: { useBills: true } });

  const resolverFailure = new Error('resolver failed');
  assert.throws(
    () => availableYearRange({ resolveAssets: () => { throw resolverFailure; } }, {}, [year(2000, 0)]),
    (error) => error === resolverFailure,
  );
  assert.throws(
    () => availableYearRange({ assets: ['stock'] }, {}, [year(Number.MAX_SAFE_INTEGER + 1, 0)]),
    /year.*safe integer/i,
  );
  assert.throws(
    () => availableYearRange({ assets: ['stock'] }, {}, [year(2000, 0), year(2000, 0)]),
    /duplicate year 2000/i,
  );
});

test('availableYearRange validates inputs and reports no usable rows without mutation', () => {
  const strategyMetadata = { assets: ['stock'] };
  const params = { allocation: { stock: 1, bond: 0, bill: 0 } };
  const rows = [year(2001, null), year(2000, null)];
  const snapshot = JSON.stringify({ strategyMetadata, params, rows });

  assert.deepEqual(
    availableYearRange(strategyMetadata, params, rows),
    { first: null, last: null, excludedAssets: ['stock'] },
  );
  assert.equal(JSON.stringify({ strategyMetadata, params, rows }), snapshot);
  assert.deepEqual(
    availableYearRange(strategyMetadata, params, []),
    { first: null, last: null, excludedAssets: [] },
  );
  assert.throws(() => availableYearRange(null, {}, rows), /strategy/i);
  assert.throws(() => availableYearRange(strategyMetadata, [], rows), /params.*plain object/i);
  assert.throws(() => availableYearRange(strategyMetadata, {}, null), /rows.*array/i);
  assert.throws(() => availableYearRange({ assets: ['gold'] }, {}, rows), /unknown.*gold/i);
  assert.throws(
    () => availableYearRange(strategyMetadata, { allocation: { stock: 0.5, bond: 0.5, bill: 0.5 } }, rows),
    /allocation.*sum to 1/i,
  );
});

test('sweepStartYears includes every usable start year and keeps partials out of complete counts', () => {
  const rows = [
    year(2004, 0),
    year(2000, 0),
    year(2002, 0),
    year(2001, 0),
    year(2003, 0),
  ];
  const results = sweepStartYears(
    rows,
    3,
    STRATEGIES.fixedReal,
    { initialRate: 0.10 },
    options(),
  );

  assert.deepEqual(results.map((entry) => entry.startYear), [2000, 2001, 2002, 2003, 2004]);
  assert.deepEqual(results.map((entry) => entry.partial), [false, false, false, true, true]);
  assert.ok(results.every((entry) => entry.partial === entry.metrics.partial));
  const complete = results.filter((entry) => !entry.partial);
  assert.equal(complete.filter((entry) => entry.metrics.success).length, 3);
  assert.equal(complete.filter((entry) => !entry.metrics.success).length, 0);
});

test('sweepStartYears uses the selected contiguous usable range without bridging gaps', () => {
  const rows = [
    year(2000, 0),
    year(2001, null),
    year(2002, 0),
    year(2003, 0),
    year(2004, 0),
  ];

  const results = sweepStartYears(rows, 2, STRATEGIES.fixedReal, {}, options());

  assert.deepEqual(results.map((entry) => entry.startYear), [2002, 2003, 2004]);
  assert.deepEqual(results.map((entry) => entry.metrics.yearsCompleted), [2, 2, 1]);
  assert.deepEqual(results.map((entry) => entry.partial), [false, false, true]);
});

test('sweepGrid returns the start-year cross product in deterministic ascending order', () => {
  const rows = [year(2002, 0), year(2000, 0), year(2001, 0)];

  const results = sweepGrid(rows, [2, 1], STRATEGIES.fixedReal, {}, options());

  assert.equal(results.length, 6);
  assert.deepEqual(
    results.map(({ startYear, horizon }) => [startYear, horizon]),
    [[2000, 1], [2000, 2], [2001, 1], [2001, 2], [2002, 1], [2002, 2]],
  );
});

test('maxSafeRate finds the just-surviving rate and preserves the supplied rate parameter', () => {
  const rows = Array.from({ length: 10 }, (_, index) => year(2000 + index, 0));
  const params = { initialRate: 0.04 };
  const runOptions = options();
  const snapshot = JSON.stringify({ rows, params, runOptions });

  const rate = maxSafeRate(rows, STRATEGIES.fixedReal, params, runOptions);

  assert.ok(Math.abs(rate - 0.10) < 0.0001, `expected approximately 0.10, got ${rate}`);
  assert.equal(simulate(rows, STRATEGIES.fixedReal, { ...params, initialRate: rate }, runOptions).metrics.success, true);
  assert.equal(simulate(rows, STRATEGIES.fixedReal, { ...params, initialRate: rate + 0.001 }, runOptions).metrics.success, false);
  assert.equal(JSON.stringify({ rows, params, runOptions }), snapshot);
  assert.equal(params.initialRate, 0.04);
});

test('maxSafeRate returns null for unsupported strategies and unresolved partial runs', () => {
  const rows = [year(2000, 0), year(2001, 0)];

  assert.equal(maxSafeRate(rows, STRATEGIES.fixedPercent, { rate: 0.04 }, options()), null);
  assert.equal(
    maxSafeRate(
      rows,
      STRATEGIES.fixedReal,
      { initialRate: 0.04 },
      options({ horizon: 3 }),
    ),
    null,
  );
});

test('sweep helpers validate horizons, rows, empty ranges, and authoritative option allocation', () => {
  const rows = [year(2000, 0, 0, null), year(2001, 0, 0, 0)];

  for (const invalid of [0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
    assert.throws(() => sweepStartYears(rows, invalid, STRATEGIES.fixedReal, {}, options()), /horizon.*positive safe integer/i);
  }
  assert.throws(() => sweepGrid(rows, [], STRATEGIES.fixedReal, {}, options()), /horizons.*non-empty/i);
  assert.throws(() => sweepGrid(rows, [1, 1], STRATEGIES.fixedReal, {}, options()), /duplicate horizon 1/i);
  assert.throws(() => sweepGrid(rows, [1, 0], STRATEGIES.fixedReal, {}, options()), /horizon.*positive safe integer/i);
  assert.throws(
    () => sweepStartYears([year(2000, 0), year(2000, 0)], 1, STRATEGIES.fixedReal, {}, options()),
    /duplicate year 2000/i,
  );
  assert.deepEqual(
    sweepStartYears([year(2000, null)], 1, STRATEGIES.fixedReal, {}, options()),
    [],
  );
  assert.deepEqual(
    sweepStartYears(rows, 1, STRATEGIES.fixedReal, {}, options({ allocation: { stock: 1, bond: 0, bill: 0 } }))
      .map((entry) => entry.startYear),
    [2000, 2001],
  );
});

test('maxSafeRate validates strategy support and search metadata', () => {
  const rows = [year(2000, 0)];
  const valid = STRATEGIES.fixedReal;

  for (const supportsMaxSafeRate of [undefined, null, 1, 'true']) {
    assert.throws(
      () => maxSafeRate(rows, { ...valid, supportsMaxSafeRate }, {}, options()),
      /supportsMaxSafeRate.*boolean/i,
    );
  }
  for (const rateParamKey of ['', ' ', ' initialRate']) {
    assert.throws(
      () => maxSafeRate(rows, { ...valid, rateParamKey }, {}, options()),
      /rateParamKey.*trimmed non-empty string/i,
    );
  }
  assert.throws(
    () => maxSafeRate(rows, { ...valid, rateParamKey: 'missing' }, {}, options()),
    /rateParamKey.*paramSchema/i,
  );
  assert.throws(
    () => maxSafeRate(rows, { ...valid, safeRateSearch: 'guess' }, {}, options()),
    /safeRateSearch.*monotonic.*adaptive/i,
  );
  assert.throws(
    () => maxSafeRate(rows, {
      ...STRATEGIES.fixedPercent,
      rateParamKey: 'rate',
    }, {}, options()),
    /unsupported.*rateParamKey/i,
  );
});

test('maxSafeRate handles both search endpoints exactly', () => {
  const rows = Array.from({ length: 5 }, (_, index) => year(2000 + index, 0));
  assert.equal(maxSafeRate(rows, STRATEGIES.fixedReal, {}, options()), 0.20);

  const noSurvivingRate = {
    id: 'noSurvivingRate',
    supportsMaxSafeRate: true,
    rateParamKey: 'rate',
    safeRateSearch: 'monotonic',
    paramSchema: [{ key: 'rate' }],
    init: () => ({}),
    step: (_state, ctx) => ({ withdrawal: ctx.options.startingBalance + 1 }),
  };
  assert.equal(maxSafeRate(rows, noSurvivingRate, {}, options()), null);
});

test('adaptive maxSafeRate finds the highest survival island within the global scan resolution', () => {
  let evaluations = 0;
  const adaptiveIsland = {
    id: 'adaptiveIsland',
    supportsMaxSafeRate: true,
    rateParamKey: 'rate',
    safeRateSearch: 'adaptive',
    paramSchema: [{ key: 'rate' }],
    init(params) {
      evaluations += 1;
      return { rate: params.rate };
    },
    step(state, ctx) {
      const survives = state.rate <= 0.15 || (state.rate >= 0.16 && state.rate <= 0.16005);
      return { withdrawal: survives ? 0 : ctx.options.startingBalance + 1 };
    },
  };

  const rate = maxSafeRate([year(2000, 0)], adaptiveIsland, {}, options());

  assert.ok(rate >= 0.16 && rate <= 0.16005, `expected upper survival island, got ${rate}`);
  assert.equal(evaluations, 441);

  evaluations = 0;
  const coarseRate = maxSafeRate(
    [year(2000, 0)],
    adaptiveIsland,
    {},
    options(),
    { adaptiveStep: 0.001 },
  );
  assert.ok(coarseRate >= 0.16 && coarseRate <= 0.16005, `expected upper survival island, got ${coarseRate}`);
  assert.equal(evaluations, 81);
});

test('adaptive maxSafeRate avoids the Guyton-Klinger non-monotonic survival trap', () => {
  const rows = [
    year(2000, 0.6646997861564159, 0.3534751815721393, -0.0795435176929459, 0.06736498255748302),
    year(2001, -0.021291894093155905, 0.23284821417182688, 0.10704648073296993, 0.043698508800007405),
    year(2002, 1.1205840826034545, -0.12310741562396288, 0.0305821567075327, 0.022855631341226396),
    year(2003, -0.10832788906991486, 0.39703273829072716, -0.003888202854432171, 0.0046757180476561175),
    year(2004, -0.55471655651927, -0.041641716845333576, 0.059413249813951546, 0.07703776386100798),
    year(2005, -0.6179668951779604, 0.050375940464437, 0.08786123290192335, -0.010046591623686252),
    year(2006, 0.4174424305558204, 0.3335427490994335, 0.03540597271639853, 0.10374198467005044),
    year(2007, 0.5280572313815355, -0.02591948155313728, -0.04880558049771935, 0.11410009937826543),
    year(2008, 0.9823315821588039, 0.3795715315267444, 0.053865291387774045, 0.10187824402470141),
  ];
  const params = { guardrail: 0.20, adjustment: 0.10, preservationCutoffYears: 3 };
  const runOptions = options({
    allocation: { stock: 0.5, bond: 0.25, bill: 0.25 },
    horizon: 9,
  });
  const survives = (initialRate) => simulate(
    rows,
    STRATEGIES.guytonKlinger,
    { ...params, initialRate },
    runOptions,
  ).metrics.success;

  assert.equal(survives(0.15), true);
  assert.equal(survives(0.155), false);
  assert.equal(survives(0.16), true);
  const rate = maxSafeRate(rows, STRATEGIES.guytonKlinger, params, runOptions);
  assert.ok(Math.abs(rate - 0.1622432881487462) < 1e-12, `unexpected adaptive maximum ${rate}`);
  const coarseRate = maxSafeRate(
    rows,
    STRATEGIES.guytonKlinger,
    params,
    runOptions,
    { adaptiveStep: 0.001 },
  );
  assert.ok(Math.abs(coarseRate - 0.1622432881487462) < 1e-12, `unexpected coarse adaptive maximum ${coarseRate}`);
});

test('maxSafeRate validates deterministic adaptive discovery steps', () => {
  const rows = [year(2000, 0)];
  const validArguments = [rows, STRATEGIES.guytonKlinger, {}, options()];

  for (const searchOptions of [null, [], 'adaptive']) {
    assert.throws(
      () => maxSafeRate(...validArguments, searchOptions),
      /searchOptions.*plain object/i,
    );
  }
  for (const adaptiveStep of [NaN, Infinity, 0, 0.00001, 0.0101]) {
    assert.throws(
      () => maxSafeRate(...validArguments, { adaptiveStep }),
      /adaptiveStep.*between 0\.0001 and 0\.01/i,
    );
  }
  assert.throws(
    () => maxSafeRate(...validArguments, { adaptiveStep: 0.003 }),
    /adaptiveStep.*divide 0\.20.*integral/i,
  );
  assert.throws(
    () => maxSafeRate(rows, STRATEGIES.fixedPercent, {}, options(), { adaptiveStep: 0.003 }),
    /adaptiveStep.*divide 0\.20.*integral/i,
  );

  assert.doesNotThrow(
    () => maxSafeRate(rows, STRATEGIES.fixedReal, {}, options(), { adaptiveStep: 0.001 }),
  );
});

const lifestyleMarketRows = getMarketRows;

const lifestyleOptions = { startingBalance: 1_000_000, allocation: { stock: 0.6, bond: 0.4, bill: 0 }, horizon: 30 };

test('historical guardrails use the first tolerant minimum and expose a frozen spending profile', async () => {
  const result = simulate((await lifestyleMarketRows()).filter(row => row.year >= 1966 && row.year <= 1995), STRATEGIES.guytonKlinger, { initialRate: 0.04 }, lifestyleOptions);
  // Floating-point drift of about 1e-16 used to select 1991 instead of the first minimum in 1978.
  assert.equal(result.metrics.minRealSpendingYear, 1978);
  close(result.metrics.minRealSpending, 22631.650335181035);
  assert.equal(result.metrics.spending.floorFirstIndex, 12);
  assert.equal(result.metrics.spending.floorHeldYears, 14);
  close(result.metrics.spending.floor, 22631.650335181035);
  assert.ok(Object.isFrozen(result.metrics.spending));
  assert.ok(Object.isFrozen(result.metrics.spending.path));
});

test('failed fixed-real profile keeps the failure payout and pads only unfunded years', async () => {
  const result = simulate((await lifestyleMarketRows()).filter(row => row.year >= 1966 && row.year <= 1995), STRATEGIES.fixedReal, { initialRate: 0.04 }, { ...lifestyleOptions, allocation: { stock: 0.5, bond: 0.5, bill: 0 } });
  assert.equal(result.metrics.failureYear, 1990);
  assert.equal(result.rows.length, 25);
  const spending = result.metrics.spending;
  assert.equal(spending.floor, 0);
  assert.equal(spending.unfundedYears, 5);
  close(spending.lastPartial, 36296.481024963985);
  assert.equal(spending.baseline, 40000);
  assert.equal(spending.path.length, 30);
});

test('empty and partial spending profiles preserve requested horizon and legacy minimum values', () => {
  for (const horizon of [0, 30]) {
    const result = simulate([], STRATEGIES.fixedReal, {}, { ...lifestyleOptions, horizon });
    assert.equal(result.metrics.minRealSpending, null);
    assert.equal(result.metrics.minRealSpendingYear, null);
    assert.deepEqual(result.metrics.spending.path, []);
    assert.equal(result.metrics.spending.horizon, horizon);
    assert.equal(result.metrics.spending.baseline, 0);
    assert.equal(result.metrics.spending.startYear, null);
    assert.equal(result.metrics.spending.partial, horizon > 0);
  }
  const result = simulate([year(2000, 0)], STRATEGIES.fixedReal, {}, lifestyleOptions);
  assert.equal(result.metrics.spending.partial, true);
  assert.equal(result.metrics.spending.path.length, 1);
});

test('solvency searches preserve all captured adaptive safe rates bit for bit', async () => {
  const rows = await lifestyleMarketRows();
  const expected = [
  {
    "id": "guytonKlinger",
    "start": 1929,
    "value": 0.08250147163958535
  },
  {
    "id": "guytonKlinger",
    "start": 1937,
    "value": 0.09803611146446112
  },
  {
    "id": "guytonKlinger",
    "start": 1959,
    "value": 0.059607565219892425
  },
  {
    "id": "guytonKlinger",
    "start": 1966,
    "value": 0.08065796208196752
  },
  {
    "id": "guytonKlinger",
    "start": 1968,
    "value": 0.08818604233835321
  },
  {
    "id": "guytonKlinger",
    "start": 1973,
    "value": 0.0978790480023754
  },
  {
    "id": "guytonKlinger",
    "start": 1982,
    "value": 0.09807653470734841
  },
  {
    "id": "guytonKlinger",
    "start": 1990,
    "value": 0.07710272695124967
  },
  {
    "id": "guytonKlinger",
    "start": 1995,
    "value": 0.07731539053286085
  },
  {
    "id": "guytonKlinger",
    "start": 1996,
    "value": 0.08228150058581835
  },
  {
    "id": "barbell",
    "start": 1929,
    "value": 0.0346829474262777
  },
  {
    "id": "barbell",
    "start": 1937,
    "value": 0.04119167861204278
  },
  {
    "id": "barbell",
    "start": 1959,
    "value": 0.05387837098858836
  },
  {
    "id": "barbell",
    "start": 1966,
    "value": 0.03857175876996098
  },
  {
    "id": "barbell",
    "start": 1968,
    "value": 0.03899752967418317
  },
  {
    "id": "barbell",
    "start": 1973,
    "value": 0.04122533502177976
  },
  {
    "id": "barbell",
    "start": 1982,
    "value": 0.0930058760502252
  },
  {
    "id": "barbell",
    "start": 1990,
    "value": 0.06890524175728023
  },
  {
    "id": "barbell",
    "start": 1995,
    "value": 0.07546501632857783
  },
  {
    "id": "barbell",
    "start": 1996,
    "value": 0.06395506737446979
  }
];
  for (const { id, start, value } of expected) {
    const actual = maxSafeRate(rows.filter(row => row.year >= start && row.year < start + 30), STRATEGIES[id], id === 'guytonKlinger' ? { initialRate: 0.04 } : {}, lifestyleOptions, { adaptiveStep: 0.001 });
    assert.equal(actual, value, id + ' ' + start);
  }
});

test('safe-rate search skips spending-profile metrics while public simulation builds them', () => {
  const context = vm.createContext({ MarketAtlasStats: { ...require('../stats.js'), spendingProfile() { throw new Error('profile metrics invoked'); } } });
  vm.runInContext(fs.readFileSync(require('node:path').join(__dirname, '..', 'engine.js'), 'utf8'), context);
  vm.runInContext(`const sequence = [{ year: 2000, stock_tr: 0, bond10_tr: 0, tbill_tr: 0, cpi_change: 0, quality: 'ok' }];
    const opts = { startingBalance: 100, allocation: { stock: 1, bond: 0, bill: 0 }, horizon: 1 };
    globalThis.safeRate = BacktestEngine.maxSafeRate(sequence, BacktestEngine.STRATEGIES.fixedReal, {}, opts);
    globalThis.full = () => BacktestEngine.simulate(sequence, BacktestEngine.STRATEGIES.fixedReal, {}, opts);`, context);
  assert.equal(context.safeRate, 0.2);
  assert.throws(() => context.full(), /profile metrics invoked/);
});
