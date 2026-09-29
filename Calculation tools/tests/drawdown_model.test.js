'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { loadDrawdownApi } = require('./helpers/load_drawdown');

function scenario(overrides = {}) {
  return {
    buffer_initial: 100, floor: 0, external_income: 0,
    investments_initial: 100, investment_income: 0, modifier: 1,
    expense: 0, inflation: 0, tax_rate: 0, sale_tax_rate: 0,
    unit: 'months', num_periods: 2, ...overrides,
  };
}

test('annual aggregation retains planned span and sums unrounded flows before formatting', () => {
  const { simulate, aggregateForView } = loadDrawdownApi();
  const params = scenario({ buffer_initial: 10, floor: 10, investments_initial: 0,
    expense: 0, external_income: 0.004, num_periods: 12 });
  const result = simulate(params, [{ id: 'late', at_month: 12,
    start: { floor: 12 }, end: {} }]);
  const [year] = aggregateForView(result.rows, 'years', result.plannedLastMonth);
  assert.equal(year.first_month, 1);
  assert.equal(year.last_month, 12);
  assert.equal(year.planned_last_month, 12);
  assert.equal(year.months_in_period, 12);
  assert.equal(year.external_income, result.rows.reduce((sum, row) => sum + row.external_income, 0));
  assert.equal(year.floor, 12);

  const late = [{ id: 'late', at_month: 12, start: { expense: 2 }, end: {} }];
  const failed = simulate(scenario({ buffer_initial: 10, floor: 10, investments_initial: 0,
    expense: 1, num_periods: 12 }), late);
  const [partial] = aggregateForView(failed.rows, 'years', failed.plannedLastMonth, late);
  assert.equal(partial.last_month, 1);
  assert.equal(partial.planned_last_month, 12);
  assert.equal(partial.first_failure_month, 1);
  assert.equal(partial.unfunded_expense, 1);
  assert.equal(partial.adjustment_applications.length, 0);
  assert.equal(partial.adjustments.length, 1);
  assert.equal(partial.adjustments[0].id, 'late');
  assert.equal(partial.adjustments[0].start_applied, false);
  const eightMonths = simulate(scenario({ num_periods: 8 }), []);
  const [requested] = aggregateForView(eightMonths.rows, 'years', eightMonths.plannedLastMonth);
  assert.equal(requested.last_month, 8);
  assert.equal(requested.planned_last_month, 8);
  assert.equal(requested.label, `${requested.source_rows[0].date.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })}–${requested.source_rows.at(-1).date.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })}`);
  assert.equal(aggregateForView.length, 3);
});

test('phased closing valuation follows sales and does not change tax or cash', () => {
  const { simulate } = loadDrawdownApi();
  const params = scenario({ buffer_initial: 100, floor: 100, investments_initial: 1000,
    investment_income: 100, expense: 200, modifier: 1, num_periods: 2 });
  const [first, second] = simulate(params, [{ id: 'valuation', at_month: 1,
    start: {}, end: { investments: 800 } }]).rows;
  assert.equal(first.sold, 100);
  assert.equal(first.natural_end_state.investments, 900);
  assert.equal(first.investments, 800);
  assert.equal(first.valuation_adjustment, -100);
  assert.equal(first.cash_adjustment, 0);
  assert.equal(first.buffer, 100);
  assert.equal(first.tax_paid, 0);
  assert.equal(first.investment_income, 100);
  assert.equal(second.investment_income, 80);
  for (const phase of ['pre_start_state', 'post_start_state', 'natural_end_state', 'end_state']) {
    assert.equal(typeof first[phase].income_raw, 'number');
    assert.equal(typeof first[phase].income_yield, 'number');
  }
  assert.notStrictEqual(first.pre_start_state, first.post_start_state);
  assert.notStrictEqual(first.natural_end_state, first.end_state);
});

test('closing cash is a separate adjustment and cannot fall below floor', () => {
  const { simulate } = loadDrawdownApi();
  const params = scenario({ buffer_initial: 100, floor: 100, investments_initial: 0, num_periods: 2 });
  const pin = { id: 'cash', at_month: 1, start: {}, end: { buffer: 150 } };
  const result = simulate(params, [pin]);
  assert.equal(result.rows[0].cash_adjustment, 50);
  assert.equal(result.rows[0].net_income, 0);
  assert.equal(result.rows[0].tax_paid, 0);
  assert.equal(result.rows[1].pre_start_state.buffer, 150);
  const invalid = simulate(params, [{ ...pin, end: { buffer: 99 } }]);
  assert.equal(invalid.terminatedReason, 'invalid');
  assert.ok(invalid.issues.some(item => item.field === 'buffer' && item.phase === 'end'));
});

test('end income reset follows closing principal and affects the next receipt', () => {
  const { simulate } = loadDrawdownApi();
  const params = scenario({ investments_initial: 1000, investment_income: 100,
    buffer_initial: 100, floor: 100, expense: 200, num_periods: 2 });
  const [first, second] = simulate(params, [{ id: 'both', at_month: 1,
    start: { modifier: 2 }, end: { investments: 800, investment_income: 40 } }]).rows;
  assert.equal(first.investment_income, 100);
  assert.equal(first.sold, 100);
  assert.equal(first.valuation_adjustment, -100);
  assert.equal(first.end_state.income_yield, 0.05);
  assert.equal(second.investment_income, 40);
});

test('start income reset determines this receipt before ending principal valuation', () => {
  const { simulate } = loadDrawdownApi();
  const params = scenario({ investments_initial: 1000, investment_income: 100,
    buffer_initial: 100, floor: 100, expense: 0, num_periods: 2 });
  const [first, second] = simulate(params, [{ id: 'both-phases', at_month: 1,
    start: { investment_income: 50 }, end: { investments: 800 } }]).rows;
  assert.equal(first.investment_income, 50);
  assert.equal(first.end_state.income_raw, 40);
  assert.equal(second.investment_income, 40);
});

test('failed operating month applies start but skips same-month and later end recovery', () => {
  const { simulate } = loadDrawdownApi();
  const result = simulate(scenario({ buffer_initial: 100, floor: 100,
    investments_initial: 0, expense: 10, num_periods: 3 }), [
    { id: 'same', at_month: 1, start: { expense: 10 }, end: { buffer: 1000, investments: 1000 } },
    { id: 'later', at_month: 2, start: {}, end: { buffer: 1000 } },
  ]);
  assert.equal(result.terminatedReason, 'reserve_failure');
  assert.equal(result.rows.length, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(result.rows[0].adjustment_application)),
    { id: 'same', at_month: 1, start_applied: true, end_applied: false });
  assert.equal(result.rows[0].buffer, 100);
  assert.equal(result.rows[0].investments, 0);
  assert.equal(result.rows[0].cash_adjustment, 0);
});

test('explicit reset to displayed zero clears hidden raw loss while no-op preserves it', () => {
  const { simulate } = loadDrawdownApi();
  const params = scenario({ investments_initial: 1000, investment_income: 10,
    modifier: 2, num_periods: 3 });
  const base = [{ id: 'loss', at_month: 1, start: {}, end: { investments: 400 } },
    { id: 'recovery', at_month: 2, start: {}, end: { investments: 550 } }];
  const ordinary = simulate(params, base).rows;
  assert.equal(ordinary[0].end_state.income_raw, -2);
  assert.equal(ordinary[1].investment_income, 0);
  assert.equal(ordinary[1].end_state.income_raw, 1);
  assert.equal(ordinary[2].investment_income, 1);
  const reset = simulate(params, [{ ...base[0] },
    { ...base[1], start: { investment_income: 0 } }]).rows;
  assert.equal(reset[1].investment_income, 0);
  assert.equal(reset[1].end_state.income_raw, 0);
  assert.equal(reset[2].investment_income, 0);
});

test('explicit simulation has its own scenario, cap, and independent snapshots', () => {
  const { state, simulate } = loadDrawdownApi();
  const params = Object.freeze(scenario({ num_periods: 2 }));
  const start = Object.freeze({ expense: 1 });
  const pins = Object.freeze([Object.freeze({ id: 'expense-2', at_month: 2, start, end: {} })]);
  const previousState = JSON.stringify(state.params);
  const result = simulate(params, pins);
  assert.equal(result.plannedLastMonth, 2);
  assert.equal(result.terminatedReason, 'horizon');
  assert.equal(result.terminatedAtMonth, null);
  assert.deepEqual(JSON.parse(JSON.stringify(result.issues)), []);
  assert.equal(result.rows[0].date.getMonth(), 7);
  assert.equal(result.rows[1].date.getMonth(), 8);
  assert.equal(JSON.stringify(state.params), previousState);
  assert.equal(params.expense, 0);
  assert.equal(pins[0].start.expense, 1);
  assert.notStrictEqual(result.rows[0].pre_start_state, result.rows[0].post_start_state);
  assert.notStrictEqual(result.rows[0].end_state, result.rows[1].pre_start_state);
  assert.notStrictEqual(result.rows[1].post_start_state, start);
});

test('zero horizon reaches the 1200-month cap; fixed horizons are capped', () => {
  const { simulate } = loadDrawdownApi();
  const zero = simulate(scenario({ num_periods: 0 }), []);
  assert.equal(zero.plannedLastMonth, 1200);
  assert.equal(zero.rows.length, 1200);
  assert.equal(zero.terminatedReason, 'cap');
  const long = simulate(scenario({ num_periods: 1201 }), []);
  assert.equal(long.plannedLastMonth, 1200);
  assert.equal(long.terminatedReason, 'cap');
});

test('a trial cutoff does not report the planned horizon as reached', () => {
  const { simulate } = loadDrawdownApi();
  const result = simulate(scenario({ num_periods: 24 }), [], { throughMonth: 1 });
  assert.equal(result.plannedLastMonth, 24);
  assert.equal(result.rows.length, 1);
  assert.equal(result.terminatedReason, 'trial_limit');
  assert.equal(result.terminatedAtMonth, null);
});

test('invalid horizon and inflation return field issues without nonfinite rows', () => {
  const { simulate } = loadDrawdownApi();
  for (const [change, field] of [
    [{ num_periods: 0.5 }, 'num_periods'],
    [{ num_periods: -1 }, 'num_periods'],
    [{ inflation: -1.25 }, 'inflation'],
    [{ inflation: 10.01 }, 'inflation'],
  ]) {
    const result = simulate(scenario(change), []);
    assert.equal(result.terminatedReason, 'invalid');
    assert.equal(result.terminatedAtMonth, null);
    assert.equal(result.rows.length, 0);
    assert.ok(result.issues.some(issue => issue.field === field), field);
  }
  assert.equal(simulate(scenario({ inflation: -1 }), []).terminatedReason, 'horizon');
  assert.equal(simulate(scenario({ inflation: 10 }), []).terminatedReason, 'horizon');
});

test('malformed explicit scenario and options return invalid results', () => {
  const { simulate } = loadDrawdownApi();
  for (const result of [simulate(null, []), simulate(scenario(), [], null)]) {
    assert.equal(result.terminatedReason, 'invalid');
    assert.equal(result.rows.length, 0);
    assert.ok(result.issues.length > 0);
  }
});

test('symbols and invalid date anchors return field issues without throwing', () => {
  const { simulate } = loadDrawdownApi();
  const cases = [
    [() => simulate(scenario({ expense: Symbol('invalid-money') }), []), 'expense'],
    [() => simulate(scenario({ modifier: Symbol('invalid-modifier') }), []), 'modifier'],
    [() => simulate(scenario({ inflation: Symbol('invalid-inflation') }), []), 'inflation'],
    [() => simulate(scenario({ num_periods: Symbol('invalid-horizon') }), []), 'num_periods'],
    [() => simulate(scenario(), [{ id: 'bad', at_month: Symbol('invalid-month'), start: {}, end: {} }]), 'at_month'],
    [() => simulate(scenario(), [], { throughMonth: Symbol('invalid-trial') }), 'throughMonth'],
    [() => simulate(scenario(), [], { dateAnchor: null }), 'dateAnchor'],
  ];
  for (const [run, field] of cases) {
    let result;
    assert.doesNotThrow(() => { result = run(); }, field);
    assert.equal(result.terminatedReason, 'invalid');
    assert.equal(result.rows.length, 0);
    assert.ok(result.issues.some(issue => issue.field === field), field);
  }
});

test('date overflow returns an invalid result without partial rows', () => {
  const { simulate } = loadDrawdownApi();
  const anchor = new Date(275760, 0, 1);
  assert.equal(Number.isFinite(anchor.getTime()), true);
  const result = simulate(scenario({ num_periods: 12 }), [], { dateAnchor: anchor });
  assert.equal(result.terminatedReason, 'invalid');
  assert.equal(result.rows.length, 0);
  assert.ok(result.issues.some(issue => issue.field === 'dateAnchor'));
});

test('invalid pin month and zero-principal income are structured input failures', () => {
  const { simulate } = loadDrawdownApi();
  for (const month of [0, 0.5, 1201, Infinity]) {
    const result = simulate(scenario(), [{ id: 'bad-month', at_month: month, start: { expense: 1 }, end: {} }]);
    assert.equal(result.terminatedReason, 'invalid');
    assert.ok(result.issues.some(issue => issue.field === 'at_month'));
  }
  const result = simulate(scenario({ investments_initial: 0, investment_income: 1 }), []);
  assert.equal(result.terminatedReason, 'invalid');
  assert.ok(result.issues.some(issue => issue.field === 'investment_income'));
});

test('an ending principal adjustment at zero gates retained income without clearing its ledger', () => {
  const { simulate } = loadDrawdownApi();
  const result = simulate(scenario({ investments_initial: 100, investment_income: 2 }), [
    { id: 'zero', at_month: 1, start: {}, end: { investments: 0 } },
    { id: 'restore', at_month: 2, start: {}, end: { investments: 100 } },
  ]);
  assert.equal(result.terminatedReason, 'horizon');
  assert.equal(result.rows[0].investment_income, 2);
  assert.equal(result.rows[1].investment_income, 0);
  assert.equal(result.rows[1].end_state.investment_income, 2);
});

test('an invalid pin tax inherits the active rate at its own month', () => {
  const { simulate } = loadDrawdownApi();
  const rows = simulate(scenario({ num_periods: 3, external_income: 10 }), [
    { id: 'tax-1', at_month: 1, start: { tax_rate: 0.5 }, end: {} },
    { id: 'tax-2', at_month: 2, start: { tax_rate: 'Infinity' }, end: {} },
  ]).rows;
  assert.equal(rows[1].post_start_state.tax_rate, 0.5);
  assert.equal(rows[1].adjustment_application.start_applied, true);
});

test('a reserve shortfall is a scenario outcome rather than malformed input', () => {
  const { simulate } = loadDrawdownApi();
  const result = simulate(scenario({ buffer_initial: 0, floor: 100, investments_initial: 0, expense: 1 }), []);
  assert.notEqual(result.terminatedReason, 'invalid');
  assert.deepEqual(JSON.parse(JSON.stringify(result.issues)), []);
  assert.equal(result.terminatedAtMonth, 1);
});

test('balanced recurring income spends above the floor without selling or terminating', () => {
  const { simulate } = loadDrawdownApi();
  const result = simulate(scenario({ buffer_initial: 100, floor: 100, investments_initial: 0,
    external_income: 10, expense: 10, num_periods: 3 }), []);
  assert.equal(result.terminatedReason, 'horizon');
  assert.equal(result.rows.length, 3);
  for (const row of result.rows) {
    assert.equal(row.buffer, 100);
    assert.equal(row.expense_paid, 10);
    assert.equal(row.unfunded_deficit, 0);
    assert.equal(row.sold, 0);
  }
});

test('surplus and zero-expense months may continue after principal reaches zero', () => {
  const { simulate } = loadDrawdownApi();
  const result = simulate(scenario({ buffer_initial: 100, floor: 100, investments_initial: 0,
    external_income: 10, expense: 0, num_periods: 3 }), [
    { id: 'external-2', at_month: 2, start: { external_income: 0 }, end: {} },
  ]);
  assert.equal(result.terminatedReason, 'horizon');
  assert.deepEqual(Array.from(result.rows, row => row.buffer), [110, 110, 110]);
});

test('partial expense payment protects the floor and conserves cash and principal', () => {
  const { simulate } = loadDrawdownApi();
  const result = simulate(scenario({ buffer_initial: 100, floor: 100,
    investments_initial: 50, expense: 100, sale_tax_rate: 0.2 }), []);
  const row = result.rows[0];
  assert.equal(result.terminatedReason, 'reserve_failure');
  assert.equal(row.expense_paid, 40);
  assert.equal(row.unfunded_expense, 60);
  assert.equal(row.unfunded_reserve, 0);
  assert.equal(row.unfunded_deficit, 60);
  assert.equal(row.buffer, 100);
  assert.equal(row.sold, row.sale_tax_paid + row.net_sale_proceeds);
  assert.equal(row.investments, 50 - row.sold);
  assert.equal(row.buffer, 100 + row.net_income + row.net_sale_proceeds - row.expense_paid);
  assert.equal(row.expense, row.expense_paid + row.unfunded_expense);
});

test('initially underfunded or raised floor reports the actual reserve gap', () => {
  const { simulate } = loadDrawdownApi();
  const initial = simulate(scenario({ buffer_initial: 20, floor: 100,
    investments_initial: 0, expense: 0 }), []);
  assert.equal(initial.rows[0].buffer, 20);
  assert.equal(initial.rows[0].unfunded_reserve, 80);
  assert.equal(initial.terminatedReason, 'reserve_failure');

  const raised = simulate(scenario({ buffer_initial: 100, floor: 50,
    investments_initial: 0, expense: 0 }), [
    { id: 'floor-1', at_month: 1, start: { floor: 120 }, end: {} },
  ]);
  assert.equal(raised.rows[0].buffer, 100);
  assert.equal(raised.rows[0].unfunded_reserve, 20);
  assert.equal(raised.terminatedReason, 'reserve_failure');
});

test('an exact final sale can exhaust principal without causing failure', () => {
  const { simulate } = loadDrawdownApi();
  const result = simulate(scenario({ buffer_initial: 100, floor: 100,
    investments_initial: 10, expense: 10, num_periods: 2 }), [
    { id: 'expense-2', at_month: 2, start: { expense: 0 }, end: {} },
  ]);
  assert.equal(result.rows[0].investments, 0);
  assert.equal(result.rows[0].unfunded_deficit, 0);
  assert.equal(result.terminatedReason, 'horizon');
});

test('income ledger retains negative raw income through zero and later recovery', () => {
  const { createIncomeLedger, applyPrincipalEvent, effectiveIncome } = loadDrawdownApi();
  const ledger = createIncomeLedger(1000, 10);
  applyPrincipalEvent(ledger, -600, 2);
  assert.equal(ledger.principal, 400);
  assert.equal(ledger.rawIncome, -2);
  assert.equal(effectiveIncome(ledger), 0);
  applyPrincipalEvent(ledger, 150, 2);
  assert.equal(ledger.rawIncome, 1);
  assert.equal(effectiveIncome(ledger), 1);
  applyPrincipalEvent(ledger, 450, 2);
  assert.equal(ledger.rawIncome, 10);
  applyPrincipalEvent(ledger, -1000, 0.5);
  assert.equal(ledger.principal, 0);
  assert.equal(effectiveIncome(ledger), 0);
  assert.equal(ledger.yieldRate, 0.01);
  applyPrincipalEvent(ledger, 200, 1);
  assert.equal(effectiveIncome(ledger), 7);
});

test('income ledger applies each event modifier and explicit reset clears loss', () => {
  const { createIncomeLedger, applyPrincipalEvent, resetIncomeLedger, effectiveIncome } = loadDrawdownApi();
  const ledger = createIncomeLedger(1000, 10);
  applyPrincipalEvent(ledger, -100, 2);
  assert.equal(effectiveIncome(ledger), 8);
  applyPrincipalEvent(ledger, -100, 1);
  assert.equal(effectiveIncome(ledger), 7);
  applyPrincipalEvent(ledger, -100, 0);
  assert.equal(effectiveIncome(ledger), 7);
  resetIncomeLedger(ledger, 16);
  assert.equal(ledger.yieldRate, 16 / 700);
  assert.equal(effectiveIncome(ledger), 16);
  applyPrincipalEvent(ledger, -700, 2);
  assert.equal(ledger.rawIncome, -16);
  resetIncomeLedger(ledger, 0);
  assert.equal(ledger.rawIncome, 0);
  assert.equal(ledger.yieldRate, 0);
});

test('zero-principal reset clears the ledger and a later valuation cannot restore old income', () => {
  const { createIncomeLedger, applyPrincipalEvent, resetIncomeLedger, effectiveIncome } = loadDrawdownApi();
  const ledger = createIncomeLedger(100, 10);
  applyPrincipalEvent(ledger, -100, 1);
  assert.equal(ledger.yieldRate, 0.1);
  resetIncomeLedger(ledger, 0);
  assert.equal(ledger.rawIncome, 0);
  assert.equal(ledger.yieldRate, 0);
  assert.throws(() => resetIncomeLedger(ledger, 1), /zero principal/i);
  applyPrincipalEvent(ledger, 100, 2);
  assert.equal(effectiveIncome(ledger), 0);
});

test('sale income reduction locks the modifier in effect at each sale', () => {
  const { simulate } = loadDrawdownApi();
  const params = scenario({ buffer_initial: 100, floor: 100, investments_initial: 1000,
    investment_income: 10, expense: 110, modifier: 2, num_periods: 2 });
  const rows = simulate(params, [{ id: 'change-2', at_month: 2, start: { modifier: 1, expense: 0 }, end: {} }]).rows;
  assert.equal(rows[0].sold, 100);
  assert.equal(rows[1].investment_income, 8);
  const one = simulate({ ...params, modifier: 1 }, [
    { id: 'expense-2', at_month: 2, start: { expense: 0 }, end: {} },
  ]).rows;
  assert.equal(one[1].investment_income, 9);
});

test('material subcent reserve deficit fails while roundoff does not sell', () => {
  const { simulate } = loadDrawdownApi();
  const subcent = simulate(scenario({ buffer_initial: 100, floor: 100,
    investments_initial: 0, expense: 0.000001 }), []);
  assert.equal(subcent.terminatedReason, 'reserve_failure');
  assert.equal(subcent.rows[0].unfunded_expense, 0.000001);
  const roundoff = simulate(scenario({ buffer_initial: 100, floor: 100,
    investments_initial: 10, external_income: 0.3, expense: 0.1 + 0.2 }), []);
  assert.equal(roundoff.rows[0].sold, 0);
  assert.equal(roundoff.terminatedReason, 'horizon');
});

test('unrepresentable monetary precision returns a numerical range issue', () => {
  const { simulate } = loadDrawdownApi();
  const result = simulate(scenario({ buffer_initial: 1e12, floor: 1e12 }), []);
  assert.equal(result.terminatedReason, 'invalid');
  assert.equal(result.rows.length, 0);
  assert.ok(result.issues.some(issue => issue.field === 'model'));
});

test('large principal does not hide a material cash shortage', () => {
  const { simulate } = loadDrawdownApi();
  const result = simulate(scenario({ buffer_initial: 100, floor: 100,
    investments_initial: 1e9, expense: 1e-6, num_periods: 1 }), []);
  assert.equal(result.terminatedReason, 'horizon');
  const row = result.rows[0];
  assert.ok(Math.abs(row.sold - 1e-6) < 1e-12);
  assert.ok(Math.abs(row.expense_paid - 1e-6) < 1e-12);
  assert.ok(row.unfunded_deficit < 1e-12);
  assert.equal(row.buffer, 100);
});

test('overflowing initial income yield returns no nonfinite rows', () => {
  const { simulate } = loadDrawdownApi();
  const result = simulate(scenario({ investments_initial: 1e-320,
    investment_income: 1 }), []);
  assert.equal(result.terminatedReason, 'invalid');
  assert.equal(result.rows.length, 0);
  assert.ok(result.issues.some(issue => issue.field === 'model'));
});

test('same-pin income reset cannot hide an overflowing principal event', () => {
  const { simulate } = loadDrawdownApi();
  const result = simulate(scenario({ buffer_initial: 100, floor: 100,
    investments_initial: 1, investment_income: 1e100,
    modifier: 1e308, expense: 0, num_periods: 1 }), [
    { id: 'zero-1', at_month: 1, start: {}, end: { investments: 0, investment_income: 0 } },
  ]);
  assert.equal(result.terminatedReason, 'invalid');
  assert.equal(result.rows.length, 0);
  assert.ok(result.issues.some(issue => issue.field === 'model' && issue.month === 1));
});

test('absolute principal pin lands on its exact target despite a large prior balance', () => {
  const { simulate } = loadDrawdownApi();
  const result = simulate(scenario({ buffer_initial: 100, floor: 100,
    investments_initial: 1e20, investment_income: 0,
    expense: 0, num_periods: 1 }), [
    { id: 'principal-1', at_month: 1, start: {}, end: { investments: 1 } },
  ]);
  assert.equal(result.terminatedReason, 'horizon');
  assert.equal(result.rows[0].investments, 1);
});

test('sale cannot credit cash when gross principal decrement is unrepresentable', () => {
  const { simulate } = loadDrawdownApi();
  const result = simulate(scenario({ buffer_initial: 100, floor: 100,
    investments_initial: 1e12, investment_income: 0,
    expense: 1e-6, num_periods: 1 }), []);
  assert.equal(result.terminatedReason, 'invalid');
  assert.equal(result.rows.length, 0);
  assert.ok(result.issues.some(issue => issue.field === 'model' && issue.month === 1));
});
