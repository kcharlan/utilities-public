'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const calculatorPath = path.join(__dirname, '..', 'drawdown.html');
const calculatorHtml = fs.readFileSync(calculatorPath, 'utf8');
const scriptMatch = calculatorHtml.match(/<script>\s*([\s\S]*?)<\/script>/);

assert.ok(scriptMatch, 'drawdown.html must contain an inline script');

function loadDrawdownApi() {
  const context = {
    document: {
      addEventListener() {},
    },
  };
  vm.createContext(context);
  vm.runInContext(
    `${scriptMatch[1]}
globalThis.__drawdownApi = {
  state,
  PARAM_DEFS,
  simulate,
  aggregateForView,
  renderStats,
  calculateAssetSale: typeof calculateAssetSale === 'function' ? calculateAssetSale : undefined,
};`,
    context,
  );
  return context.__drawdownApi;
}

function assertClose(actual, expected, tolerance = 1e-9) {
  assert.ok(
    Math.abs(actual - expected) <= tolerance,
    `expected ${actual} to be within ${tolerance} of ${expected}`,
  );
}

function assertSaleInvariants(result, deficit, availableInvestments) {
  for (const field of [
    'grossSold',
    'saleTaxPaid',
    'netSaleProceeds',
    'unfundedDeficit',
  ]) {
    assert.equal(Number.isFinite(result[field]), true, `${field} must be finite`);
  }
  assert.equal(result.grossSold, result.saleTaxPaid + result.netSaleProceeds);
  assert.ok(result.grossSold <= availableInvestments);
  assert.ok(result.netSaleProceeds <= deficit);
}

test('[helper] calculateAssetSale returns zeros when no sale can or needs to occur', () => {
  const { calculateAssetSale } = loadDrawdownApi();
  assert.equal(typeof calculateAssetSale, 'function');

  const noDeficit = calculateAssetSale(0, 2500, 0.15);
  assertSaleInvariants(noDeficit, 0, 2500);
  assert.equal(noDeficit.grossSold, 0);
  assert.equal(noDeficit.saleTaxPaid, 0);
  assert.equal(noDeficit.netSaleProceeds, 0);
  assert.equal(noDeficit.unfundedDeficit, 0);

  const noInvestments = calculateAssetSale(1000, 0, 0.15);
  assertSaleInvariants(noInvestments, 1000, 0);
  assert.equal(noInvestments.grossSold, 0);
  assert.equal(noInvestments.saleTaxPaid, 0);
  assert.equal(noInvestments.netSaleProceeds, 0);
  assert.equal(noInvestments.unfundedDeficit, 1000);
});

test('[helper] calculateAssetSale funds a $1,000 deficit without tax', () => {
  const { calculateAssetSale } = loadDrawdownApi();
  const result = calculateAssetSale(1000, 2500, 0);

  assertSaleInvariants(result, 1000, 2500);
  assert.equal(result.grossSold, 1000);
  assert.equal(result.saleTaxPaid, 0);
  assert.equal(result.netSaleProceeds, 1000);
  assert.equal(result.unfundedDeficit, 0);
});

test('[helper] calculateAssetSale grosses up a fully funded sale for 15% tax', () => {
  const { calculateAssetSale } = loadDrawdownApi();
  const result = calculateAssetSale(1000, 2500, 0.15);

  assertSaleInvariants(result, 1000, 2500);
  assertClose(result.grossSold, 1000 / 0.85);
  assertClose(result.saleTaxPaid, (1000 / 0.85) - 1000);
  assert.equal(result.netSaleProceeds, 1000);
  assert.equal(result.unfundedDeficit, 0);
});

test('[helper] calculateAssetSale sells all principal when 15% tax leaves a shortfall', () => {
  const { calculateAssetSale } = loadDrawdownApi();
  const result = calculateAssetSale(1000, 500, 0.15);

  assertSaleInvariants(result, 1000, 500);
  assert.equal(result.grossSold, 500);
  assertClose(result.saleTaxPaid, 75);
  assert.equal(result.netSaleProceeds, 425);
  assert.equal(result.unfundedDeficit, 575);
});

test('[helper] calculateAssetSale treats a 100% rate as consuming the entire sale', () => {
  const { calculateAssetSale } = loadDrawdownApi();
  const result = calculateAssetSale(1000, 600, 1);

  assertSaleInvariants(result, 1000, 600);
  assert.equal(result.grossSold, 600);
  assert.equal(result.saleTaxPaid, 600);
  assert.equal(result.netSaleProceeds, 0);
  assert.equal(result.unfundedDeficit, 1000);
});

test('[helper] calculateAssetSale stays finite just below 100% when maximum net is insufficient', () => {
  const { calculateAssetSale } = loadDrawdownApi();
  const rate = 0.9999999999999999;
  const result = calculateAssetSale(1000, 600, rate);
  const expectedNet = 600 * (1 - rate);

  assertSaleInvariants(result, 1000, 600);
  assert.equal(result.grossSold, 600);
  assertClose(result.saleTaxPaid, 600 - expectedNet);
  assert.equal(result.netSaleProceeds, expectedNet);
  assert.equal(result.unfundedDeficit, 1000 - expectedNet);
});
