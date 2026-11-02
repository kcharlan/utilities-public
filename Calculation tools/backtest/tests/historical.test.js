'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { getMarketRows } = require('./helpers/dataset.cjs');
const {
  sweepStartYears,
  simulate,
  STRATEGIES,
} = require('../engine.js');

const loadMarketRows = getMarketRows;

test('historical fixed-real controls hold for the current engine on the selected history', async () => {
  const { checkHistorical } = await import('../tools/check_historical.mjs');
  checkHistorical(await loadMarketRows());
});

// Derived outcome controls only; all observations remain in the external bundle.
for (const [billSeries, horizon, depleted, under100k] of [
  ['damodaran', 25, [1928, 1929, 1930, 1931, 1999, 2000], [1937]],
  ['damodaran', 30, [1928, 1929, 1930, 1931, 1937], []],
  ['dtb3', 25, [1928, 1929, 1930, 1931, 2000], [1937]],
  ['dtb3', 30, [1928, 1929, 1930, 1931, 1937], []],
]) {
  test(`historical Josh Tbill full refill ${billSeries} ${horizon}-year complete outcome controls`, async () => {
    const rows = await loadMarketRows();
    const options = { startingBalance: 1_000_000, allocation: { stock: 1, bond: 0, bill: 0 },
      feeRate: 0, taxRate: 0, billSeries };
    // Failure before available data ends is definitive but not a complete window.
    const complete = sweepStartYears(rows, horizon, STRATEGIES.joshTbillFullRefill, {}, options)
      .filter(({ startYear }) => startYear >= 1928 && startYear + horizon - 1 <= 2025);
    assert.equal(complete.length, 2025 - horizon + 1 - 1928 + 1);
    assert.deepEqual(complete.filter(({ metrics }) => !metrics.success).map(({ startYear }) => startYear), depleted);
    assert.deepEqual(complete.filter(({ metrics }) => metrics.success && metrics.terminalWealthNominal < 100_000)
      .map(({ startYear }) => startYear), under100k);
  });
}

const lifestyleMarketRows = getMarketRows;
const lifestyleOptions = { startingBalance: 1_000_000, allocation: { stock: 0.6, bond: 0.4, bill: 0 }, horizon: 30 };
function close(actual, expected) {
  assert.ok(Math.abs(actual - expected) <= 1e-9 * Math.max(1, Math.abs(expected)));
}

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
