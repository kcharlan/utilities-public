'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { getMarketRows } = require('./helpers/dataset.cjs');
const {
  sweepStartYears,
  maxSafeRate,
  STRATEGIES,
} = require('../engine.js');

const loadMarketRows = getMarketRows;

async function runConfiguration(allocation) {
  const rows = await loadMarketRows();
  const options = {
    startingBalance: 1_000_000,
    allocation,
    feeRate: 0,
    taxRate: 0,
    rebalance: 'annual',
  };
  const sweep = sweepStartYears(rows, 30, STRATEGIES.fixedReal, { initialRate: 0.04 }, options);
  const complete = sweep.filter(({ startYear, partial }) => (
    startYear >= 1928 && startYear <= 1996 && !partial
  ));
  const rowsByYear = new Map(rows.map((row) => [row.year, row]));
  const safeRates = complete.map(({ startYear }) => ({
    startYear,
    rate: maxSafeRate(
      Array.from({ length: 30 }, (_, offset) => rowsByYear.get(startYear + offset)),
      STRATEGIES.fixedReal,
      { initialRate: 0.04 },
      options,
    ),
  }));
  return { complete, safeRates };
}

function assertWithinPercentagePoints(actualRate, expectedPercent, tolerancePercentagePoints = 0.05) {
  const actualPercent = actualRate * 100;
  assert.ok(
    Math.abs(actualPercent - expectedPercent) <= tolerancePercentagePoints,
    `expected ${expectedPercent}% ± ${tolerancePercentagePoints}pp, got ${actualPercent}%`,
  );
}

test('historical 50/50 fixed-real acceptance matches the 69 complete 30-year windows', async () => {
  const { complete, safeRates } = await runConfiguration({ stock: 0.5, bond: 0.5, bill: 0 });

  assert.equal(complete.length, 69);
  assert.equal(complete.filter(({ metrics }) => metrics.success).length, 64);
  assert.deepEqual(
    complete.filter(({ metrics }) => !metrics.success).map(({ startYear }) => startYear),
    [1964, 1965, 1966, 1968, 1969],
  );

  const worst = safeRates.slice().sort((left, right) => left.rate - right.rate);
  assert.deepEqual(worst.slice(0, 4).map(({ startYear }) => startYear), [1966, 1965, 1968, 1969]);
  assertWithinPercentagePoints(worst[0].rate, 3.67);
  assertWithinPercentagePoints(worst[1].rate, 3.75);
  assertWithinPercentagePoints(worst[2].rate, 3.85);
  assertWithinPercentagePoints(worst[3].rate, 3.88);
});

test('historical 75/25 fixed-real acceptance matches the 69 complete 30-year windows', async () => {
  const { complete, safeRates } = await runConfiguration({ stock: 0.75, bond: 0.25, bill: 0 });

  assert.equal(complete.length, 69);
  assert.equal(complete.filter(({ metrics }) => metrics.success).length, 65);
  assert.deepEqual(
    complete.filter(({ metrics }) => !metrics.success).map(({ startYear }) => startYear),
    [1965, 1966, 1968, 1969],
  );
  const worst = safeRates.slice().sort((left, right) => left.rate - right.rate)[0];
  assert.equal(worst.startYear, 1966);
  assertWithinPercentagePoints(worst.rate, 3.80);
});
