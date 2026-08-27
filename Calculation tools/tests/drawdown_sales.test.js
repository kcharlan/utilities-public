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

function loadDrawdownApi(documentOverrides = {}) {
  const context = {
    document: {
      addEventListener() {},
      ...documentOverrides,
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
  normalizeTaxPercent: typeof normalizeTaxPercent === 'function' ? normalizeTaxPercent : undefined,
  readNormalizedTaxRate: typeof readNormalizedTaxRate === 'function' ? readNormalizedTaxRate : undefined,
  readPinFieldValue: typeof readPinFieldValue === 'function' ? readPinFieldValue : undefined,
  collectPinOverrides: typeof collectPinOverrides === 'function' ? collectPinOverrides : undefined,
  renderPinEditor: typeof renderPinEditor === 'function' ? renderPinEditor : undefined,
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
  const keys = JSON.parse(JSON.stringify(Object.keys(result)));
  assert.deepEqual(keys, [
    'grossSold',
    'saleTaxPaid',
    'netSaleProceeds',
    'unfundedDeficit',
  ]);

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

test('[ui] tax control labels recurring and asset-sale rates', () => {
  assert.match(
    calculatorHtml,
    /<label>Income effective rate<span class="hint">applied to recurring income<\/span><\/label>\s*<span class="input-wrap"><input type="number" id="tax-rate" value="25" step="0\.5" min="0" max="100">/,
  );
  assert.match(
    calculatorHtml,
    /<label>Asset sale effective rate<span class="hint">applied to gross sale proceeds<\/span><\/label>\s*<span class="input-wrap"><input type="number" id="sale-tax-rate" value="15" step="0\.5" min="0" max="100">/,
  );
  assert.match(calculatorHtml, /const inputs = \[[^\]]*'sale-tax-rate'[^\]]*\];/);
});

test('[ui] pin field metadata bounds tax rates', () => {
  const { PARAM_DEFS } = loadDrawdownApi();
  const inflation = PARAM_DEFS.find(def => def.key === 'inflation');
  const taxIndex = PARAM_DEFS.findIndex(def => def.key === 'tax_rate');
  const taxRate = PARAM_DEFS[taxIndex];
  const saleTaxRate = PARAM_DEFS[taxIndex + 1];

  assert.deepEqual(JSON.parse(JSON.stringify(inflation)), {
    key: 'inflation', label: 'Annual inflation', fmt: 'pct', min: -1, max: 10,
  });
  assert.deepEqual(JSON.parse(JSON.stringify(taxRate)), {
    key: 'tax_rate', label: 'Tax rate', fmt: 'pct', min: 0, max: 1,
  });
  assert.deepEqual(JSON.parse(JSON.stringify(saleTaxRate)), {
    key: 'sale_tax_rate', label: 'Asset sale tax rate', fmt: 'pct', min: 0, max: 1,
  });
});

test('[ui] normalization clamps finite rates and falls back', () => {
  const { normalizeTaxPercent } = loadDrawdownApi();
  assert.equal(typeof normalizeTaxPercent, 'function');

  assert.equal(normalizeTaxPercent('27.5', 25), 27.5);
  assert.equal(normalizeTaxPercent('-0.5', 25), 0);
  assert.equal(normalizeTaxPercent('100.5', 25), 100);
  assert.equal(normalizeTaxPercent('100', 25), 100);
  for (const invalid of [null, undefined, '', '   ', 'NaN', 'Infinity', '-Infinity']) {
    assert.equal(normalizeTaxPercent(invalid, 25), 25, `expected ${String(invalid)} to fall back`);
  }
});

test('[ui] normalization reflects decimal rates into inputs', () => {
  const { readNormalizedTaxRate } = loadDrawdownApi();
  assert.equal(typeof readNormalizedTaxRate, 'function');

  const incomeInput = { value: '' };
  const saleInput = { value: '   ' };
  assert.equal(readNormalizedTaxRate(incomeInput, 0.25), 0.25);
  assert.equal(incomeInput.value, 25);
  assert.equal(readNormalizedTaxRate(saleInput, 0.15), 0.15);
  assert.equal(saleInput.value, 15);

  const below = { value: '-7' };
  const above = { value: '130' };
  assert.equal(readNormalizedTaxRate(below, 0.25), 0);
  assert.equal(below.value, 0);
  assert.equal(readNormalizedTaxRate(above, 0.15), 1);
  assert.equal(above.value, 100);
});

test('[ui] pin field uses tax baseline for invalid input', () => {
  const { readPinFieldValue } = loadDrawdownApi();
  assert.equal(typeof readPinFieldValue, 'function');

  const incomeTax = { value: '' };
  const saleTax = { value: 'Infinity' };
  assert.equal(readPinFieldValue(incomeTax, 'tax_rate', 'pct', 0.25), 0.25);
  assert.equal(incomeTax.value, 25);
  assert.equal(readPinFieldValue(saleTax, 'sale_tax_rate', 'pct', 0.15), 0.15);
  assert.equal(saleTax.value, 15);
  assert.equal(readPinFieldValue({ value: '-125' }, 'inflation', 'pct', 0.03), -1.25);
  assert.equal(readPinFieldValue({ value: '1234.5' }, 'expense', 'money', 5000), 1234.5);
  assert.equal(readPinFieldValue({ value: '1.75' }, 'modifier', 'num', 1), 1.75);
});

test('[ui] pin field collector persists only normalized dirty changes', () => {
  const { collectPinOverrides } = loadDrawdownApi();
  assert.equal(typeof collectPinOverrides, 'function');

  function fieldInput(key, fmt, baseline, value) {
    const attrs = { 'data-fmt': fmt, 'data-baseline': String(baseline) };
    return {
      value,
      getAttribute(name) { return name === 'data-key' ? key : null; },
      closest() { return { getAttribute(name) { return attrs[name]; } }; },
    };
  }

  const incomeTax = fieldInput('tax_rate', 'pct', 0.25, '30');
  const saleTax = fieldInput('sale_tax_rate', 'pct', 0.15, '');
  const untouchedExpense = fieldInput('expense', 'money', 5000, '6000');
  const overrides = collectPinOverrides(
    [incomeTax, saleTax, untouchedExpense],
    new Set(['tax_rate', 'sale_tax_rate']),
  );

  assert.deepEqual(JSON.parse(JSON.stringify(overrides)), { tax_rate: 0.3 });
  assert.equal(saleTax.value, 15);
});

test('[ui] pin field render normalizes tax bounds without clamping inflation', () => {
  const { state, renderPinEditor } = loadDrawdownApi();
  assert.equal(typeof renderPinEditor, 'function');
  state.params.unit = 'months';
  state.pins = [];
  const baseline = Object.fromEntries(PARAM_DEFS_FOR_RENDER().map(def => [def.key, def.value]));
  const html = renderPinEditor(
    { month: 1 },
    [{ month: 1, pre_state: baseline }],
  );

  assert.match(html, /data-key="tax_rate"[\s\S]*?<input[^>]*data-key="tax_rate"[^>]*min="0" max="100"/);
  assert.match(html, /data-key="sale_tax_rate"[\s\S]*?<input[^>]*data-key="sale_tax_rate"[^>]*min="0" max="100"/);
  assert.match(html, /data-key="inflation"[\s\S]*?<input[^>]*data-key="inflation"[^>]*min="-100" max="1000"/);
});

function PARAM_DEFS_FOR_RENDER() {
  return [
    { key: 'buffer', value: 100000 },
    { key: 'investments', value: 600000 },
    { key: 'investment_income', value: 6000 },
    { key: 'modifier', value: 1 },
    { key: 'floor', value: 100000 },
    { key: 'external_income', value: 2000 },
    { key: 'expense', value: 5000 },
    { key: 'inflation', value: 0.03 },
    { key: 'tax_rate', value: 0.25 },
    { key: 'sale_tax_rate', value: 0.15 },
  ];
}

test('[aggregate] yearly view sums every sale and tax flow from monthly rows', () => {
  const { aggregateForView } = loadDrawdownApi();
  const rows = Array.from({ length: 12 }, (_, index) => ({
    month: index + 1,
    date: new Date(2026, index, 1),
    expense: 100,
    investment_income: 20,
    external_income: 10,
    income_tax_paid: index + 1,
    sale_tax_paid: (index + 1) * 2,
    tax_paid: (index + 1) * 3,
    net_income: 25,
    delta: -75,
    buffer: 500 - index,
    investments: 5000 - index * 100,
    sold: (index + 1) * 4,
    net_sale_proceeds: (index + 1) * 5,
    hitFloor: index === 2,
    insolvency: false,
    surplus: false,
    pinned_at_this_row: null,
    overrides_applied: null,
    pre_state: { marker: index },
    effective_state: { marker: index + 1 },
  }));

  const [year] = aggregateForView(rows, 'years');

  assert.equal(year.income_tax_paid, 78);
  assert.equal(year.sale_tax_paid, 156);
  assert.equal(year.tax_paid, 234);
  assert.equal(year.sold, 312);
  assert.equal(year.net_sale_proceeds, 390);
});

test('[summary] reports summed gross sales and both tax components in five cards', () => {
  const stats = { innerHTML: '' };
  const { state, renderStats } = loadDrawdownApi({
    getElementById(id) {
      assert.equal(id, 'stats');
      return stats;
    },
  });
  Object.assign(state.params, {
    investments_initial: 1000,
    floor: 100,
    tax_rate: 0.25,
    unit: 'months',
  });
  const rows = [
    {
      buffer: 100,
      investments: 950,
      sold: 100,
      income_tax_paid: 10,
      sale_tax_paid: 5,
      tax_paid: 15,
    },
    {
      buffer: 100,
      investments: 900,
      sold: 250,
      income_tax_paid: 20,
      sale_tax_paid: 15,
      tax_paid: 35,
    },
  ];

  renderStats(rows, { terminatedReason: 'cap' });

  assert.equal((stats.innerHTML.match(/class="stat"/g) || []).length, 5);
  assert.match(stats.innerHTML, /Total liquidated[\s\S]*?\$350[\s\S]*?gross sales across projection/);
  assert.doesNotMatch(stats.innerHTML, /% of principal/);
  assert.match(stats.innerHTML, /Total tax paid[\s\S]*?\$50/);
  assert.match(stats.innerHTML, /Income tax[^<]*\$30/);
  assert.match(stats.innerHTML, /Asset sale tax[^<]*\$20/);
});

test('[Gross sold] table renames only the visible sale heading', () => {
  assert.match(calculatorHtml, /<th>Gross sold<\/th>/);
  assert.doesNotMatch(calculatorHtml, /<th>Sold<\/th>/);
  assert.match(calculatorHtml, /r\.sold > 0 \? fmtMoney\(r\.sold\) : '—'/);
});

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

test('[helper] calculateAssetSale caps a fully funded exact-capacity sale', () => {
  const { calculateAssetSale } = loadDrawdownApi();
  const availableInvestments = 0.01;
  const saleTaxRate = 0.94;
  const deficit = availableInvestments * (1 - saleTaxRate);
  const result = calculateAssetSale(deficit, availableInvestments, saleTaxRate);

  assertSaleInvariants(result, deficit, availableInvestments);
  assert.equal(result.grossSold, availableInvestments);
  assert.equal(result.saleTaxPaid, availableInvestments - deficit);
  assert.equal(result.netSaleProceeds, deficit);
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

test('[simulation] defaults asset-sale tax to 15%', () => {
  const { state } = loadDrawdownApi();

  assert.equal(state.params.sale_tax_rate, 0.15);
});

test('[simulation] grosses up a one-month shortfall', () => {
  const { state, simulate } = loadDrawdownApi();
  Object.assign(state.params, {
    buffer_initial: 0,
    floor: 100,
    expense: 100,
    investment_income: 0,
    external_income: 0,
    investments_initial: 1000,
    tax_rate: 0,
    sale_tax_rate: 0.15,
    modifier: 1,
    inflation: 0,
    unit: 'months',
    num_periods: 1,
  });
  state.pins = [];

  const result = simulate();
  const row = result.rows[0];

  assertClose(row.sold, 235.2941176471);
  assertClose(row.sale_tax_paid, 35.2941176471);
  assert.equal(row.net_sale_proceeds, 200);
  assert.equal(row.buffer, 100);
  assertClose(row.investments, 764.7058823529);
});

test('[simulation] records combined tax without changing recurring flow', () => {
  const { state, simulate } = loadDrawdownApi();
  Object.assign(state.params, {
    buffer_initial: 0,
    floor: 100,
    expense: 175,
    investment_income: 0,
    external_income: 100,
    investments_initial: 1000,
    tax_rate: 0.25,
    sale_tax_rate: 0.15,
    modifier: 1,
    inflation: 0,
    unit: 'months',
    num_periods: 1,
  });
  state.pins = [];

  const row = simulate().rows[0];

  assert.equal(row.net_income, 75);
  assert.equal(row.delta, -100);
  assert.equal(row.income_tax_paid, 25);
  assertClose(row.sale_tax_paid, 35.2941176471);
  assertClose(row.tax_paid, 60.2941176471);
});

test('[simulation] records zero sale flows without a shortfall', () => {
  const { state, simulate } = loadDrawdownApi();
  Object.assign(state.params, {
    buffer_initial: 100,
    floor: 100,
    expense: 100,
    investment_income: 0,
    external_income: 100,
    investments_initial: 1000,
    tax_rate: 0,
    sale_tax_rate: 0.15,
    modifier: 1,
    inflation: 0,
    unit: 'months',
    num_periods: 1,
  });
  state.pins = [];

  const row = simulate().rows[0];

  assert.equal(row.sold, 0);
  assert.equal(row.sale_tax_paid, 0);
  assert.equal(row.net_sale_proceeds, 0);
});

test('[simulation] depletes insufficient investments after tax', () => {
  const { state, simulate } = loadDrawdownApi();
  Object.assign(state.params, {
    buffer_initial: 0,
    floor: 100,
    expense: 100,
    investment_income: 0,
    external_income: 0,
    investments_initial: 100,
    tax_rate: 0,
    sale_tax_rate: 0.15,
    modifier: 1,
    inflation: 0,
    unit: 'months',
    num_periods: 1,
  });
  state.pins = [];

  const result = simulate();
  const row = result.rows[0];

  assert.equal(row.sold, 100);
  assert.equal(row.sale_tax_paid, 15);
  assert.equal(row.net_sale_proceeds, 85);
  assert.equal(row.buffer, -15);
  assert.equal(row.insolvency, true);
  assert.equal(result.terminatedReason, 'depleted');
});

test('[simulation] stays finite at 100% sale tax', () => {
  const { state, simulate } = loadDrawdownApi();
  Object.assign(state.params, {
    buffer_initial: 0,
    floor: 100,
    expense: 100,
    investment_income: 0,
    external_income: 0,
    investments_initial: 100,
    tax_rate: 0,
    sale_tax_rate: 1,
    modifier: 1,
    inflation: 0,
    unit: 'months',
    num_periods: 1,
  });
  state.pins = [];

  const row = simulate().rows[0];

  for (const field of ['sold', 'sale_tax_paid', 'net_sale_proceeds', 'buffer', 'investments']) {
    assert.equal(Number.isFinite(row[field]), true, `${field} must be finite`);
  }
  assert.equal(row.sold, 100);
  assert.equal(row.sale_tax_paid, 100);
  assert.equal(row.net_sale_proceeds, 0);
  assert.equal(row.insolvency, true);
});

test('[simulation] decays income from gross sale', () => {
  const { state, simulate } = loadDrawdownApi();
  Object.assign(state.params, {
    buffer_initial: 100,
    floor: 100,
    expense: 200,
    investment_income: 100,
    external_income: 0,
    investments_initial: 1000,
    tax_rate: 0,
    sale_tax_rate: 0.15,
    modifier: 1,
    inflation: 0,
    unit: 'months',
    num_periods: 2,
  });
  state.pins = [];

  const rows = simulate().rows;

  assertClose(rows[0].sold, 117.6470588235);
  assertClose(rows[1].investment_income, 88.2352941176);
});

test('[simulation] applies pinned sale tax prospectively', () => {
  const { state, simulate } = loadDrawdownApi();
  Object.assign(state.params, {
    buffer_initial: 100,
    floor: 100,
    expense: 200,
    investment_income: 100,
    external_income: 0,
    investments_initial: 5000,
    tax_rate: 0,
    sale_tax_rate: 0,
    modifier: 0,
    inflation: 0,
    unit: 'months',
    num_periods: 3,
  });
  state.pins = [{ at_month: 2, overrides: { sale_tax_rate: 0.25 } }];

  const rows = simulate().rows;

  assert.equal(rows[0].sold, 100);
  assertClose(rows[1].sold, 133.3333333333);
  assertClose(rows[2].sold, 133.3333333333);
  assert.equal(rows[1].pre_state.sale_tax_rate, 0);
  assert.equal(rows[1].effective_state.sale_tax_rate, 0.25);
  assert.equal(rows[2].pre_state.sale_tax_rate, 0.25);
});
