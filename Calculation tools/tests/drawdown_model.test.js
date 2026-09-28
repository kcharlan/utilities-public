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

test('explicit simulation has its own scenario, cap, and independent snapshots', () => {
  const { state, simulate } = loadDrawdownApi();
  const params = Object.freeze(scenario({ num_periods: 2 }));
  const overrides = Object.freeze({ expense: 1 });
  const pins = Object.freeze([Object.freeze({ at_month: 2, overrides })]);
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
  assert.equal(pins[0].overrides.expense, 1);
  assert.notStrictEqual(result.rows[0].pre_state, result.rows[0].effective_state);
  assert.notStrictEqual(result.rows[0].effective_state, result.rows[1].pre_state);
  assert.notStrictEqual(result.rows[1].overrides_applied, overrides);
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
    [() => simulate(scenario(), [{ at_month: Symbol('invalid-month'), overrides: {} }]), 'at_month'],
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
    const result = simulate(scenario(), [{ at_month: month, overrides: { expense: 1 } }]);
    assert.equal(result.terminatedReason, 'invalid');
    assert.ok(result.issues.some(issue => issue.field === 'at_month'));
  }
  const result = simulate(scenario({ investments_initial: 0, investment_income: 1 }), []);
  assert.equal(result.terminatedReason, 'invalid');
  assert.ok(result.issues.some(issue => issue.field === 'investment_income'));
});

test('a principal pin cannot retain positive income at zero principal', () => {
  const { simulate } = loadDrawdownApi();
  const result = simulate(scenario({ investments_initial: 100, investment_income: 2 }), [
    { at_month: 1, overrides: { investments: 0 } },
  ]);
  assert.equal(result.terminatedReason, 'invalid');
  assert.equal(result.rows.length, 0);
  assert.ok(result.issues.some(issue => issue.field === 'investment_income' && issue.month === 1));
});

test('an invalid pin tax inherits the active rate at its own month', () => {
  const { simulate } = loadDrawdownApi();
  const rows = simulate(scenario({ num_periods: 3, external_income: 10 }), [
    { at_month: 1, overrides: { tax_rate: 0.5 } },
    { at_month: 2, overrides: { tax_rate: 'Infinity' } },
  ]).rows;
  assert.equal(rows[1].effective_state.tax_rate, 0.5);
  assert.equal(rows[1].overrides_applied.tax_rate, 0.5);
});

test('a reserve shortfall is a scenario outcome rather than malformed input', () => {
  const { simulate } = loadDrawdownApi();
  const result = simulate(scenario({ buffer_initial: 0, floor: 100, investments_initial: 0, expense: 1 }), []);
  assert.notEqual(result.terminatedReason, 'invalid');
  assert.deepEqual(JSON.parse(JSON.stringify(result.issues)), []);
  assert.equal(result.terminatedAtMonth, 1);
});
