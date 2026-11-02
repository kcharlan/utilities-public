'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { getMarketRows } = require('./helpers/dataset.cjs');
const {
  sweepStartYears,
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
