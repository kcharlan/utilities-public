'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { loadDrawdownApi } = require('./helpers/load_drawdown');

test('transactions retain identity and unrelated fields while moving or editing', () => {
  const { state, applyEditTransaction } = loadDrawdownApi();
  Object.assign(state.params, { buffer_initial: 1000, floor: 0, expense: 0, investment_income: 0,
    external_income: 0, investments_initial: 1000, inflation: 0, tax_rate: 0, sale_tax_rate: 0, num_periods: 12 });
  const scenario = { params: state.params, pins: [
    { id: 'a', at_month: 8, start: { expense: 1 }, end: { investments: 800 }, annual_edits: {
      expense: { target_total: 12, first_month: 1, last_month: 12, resolved_monthly_value: 1 } } },
    { id: 'b', at_month: 9, start: { modifier: 2 }, end: {} },
  ], revision: 2 };
  const before = JSON.stringify(scenario);
  const moved = applyEditTransaction(scenario, { type: 'move', id: 'a', at_month: 7 });
  assert.equal(moved.ok, true);
  assert.equal(moved.scenario.pins[0].id, 'a');
  assert.equal(moved.scenario.pins[0].at_month, 7);
  assert.equal(moved.scenario.pins[0].annual_edits, undefined);
  assert.equal(moved.scenario.pins[0].end.investments, 800);
  assert.equal(JSON.stringify(scenario), before);
  const toFirst = applyEditTransaction(scenario, { type: 'move', id: 'a', at_month: 1 });
  assert.equal(toFirst.ok, true);
  assert.equal(toFirst.scenario.pins[0].at_month, 1);
  assert.equal(toFirst.scenario.pins[0].id, 'a');
  const collision = applyEditTransaction(scenario, { type: 'move', id: 'a', at_month: 9 });
  assert.equal(collision.ok, false);
  assert.equal(JSON.stringify(scenario), before);
  const edited = applyEditTransaction(scenario, { type: 'set', id: 'a', phase: 'end', field: 'buffer', value: 0 });
  assert.equal(edited.ok, true);
  assert.equal(edited.scenario.pins[0].end.buffer, 0);
  assert.equal(edited.scenario.pins[0].start.expense, 1);
  assert.equal(edited.scenario.pins[1].start.modifier, 2);
});

test('end-income no-override baseline retains same-record valuation', () => {
  const { state, simulate, prepareCellEdit } = loadDrawdownApi();
  Object.assign(state.params, { buffer_initial: 100, floor: 100, investments_initial: 1000,
    investment_income: 100, expense: 200, external_income: 0, inflation: 0,
    tax_rate: 0, sale_tax_rate: 0, modifier: 1, num_periods: 2 });
  const pins = [{ id: 'both', at_month: 1, start: {}, end: { investments: 800, investment_income: 40 } }];
  const row = simulate(state.params, pins).rows[0];
  const context = prepareCellEdit(row, 'end.investment_income', { params: state.params, pins, revision: 7 });
  assert.equal(context.phase, 'end');
  assert.equal(context.currentExactValue, 40);
  assert.equal(context.noOverrideBaseline, 80);
  assert.equal(context.revision, 7);
});

test('yearly edit context routes flows to first month and balances to last month', () => {
  const { state, simulate, aggregateForView, prepareCellEdit } = loadDrawdownApi();
  Object.assign(state.params, { buffer_initial: 100, floor: 0, investments_initial: 1000,
    investment_income: 0, expense: 0, external_income: 0, inflation: 0,
    tax_rate: 0, sale_tax_rate: 0, num_periods: 1, unit: 'years' });
  const monthly = simulate(state.params, []).rows;
  const year = aggregateForView(monthly, 'years')[0];
  assert.equal(prepareCellEdit(year, 'expense', { params: state.params, pins: [] }).month, 1);
  assert.equal(prepareCellEdit(year, 'investment_income', { params: state.params, pins: [] }).month, 1);
  assert.equal(prepareCellEdit(year, 'buffer', { params: state.params, pins: [] }).month, 12);
  assert.equal(prepareCellEdit(year, 'investments', { params: state.params, pins: [] }).month, 12);
});

test('removing the last field prunes a pin, while explicit zero is retained', () => {
  const { state, applyEditTransaction } = loadDrawdownApi();
  const original = { params: state.params, pins: [{ id: 'zero', at_month: 1,
    start: { external_income: 0 }, end: {} }], revision: 0 };
  const retained = applyEditTransaction(original, { type: 'set', id: 'zero', phase: 'start', field: 'expense', value: 0 });
  assert.equal(retained.ok, true);
  assert.equal(retained.scenario.pins[0].start.expense, 0);
  const one = applyEditTransaction(original, { type: 'remove-field', id: 'zero', phase: 'start', field: 'external_income' });
  assert.equal(one.ok, true);
  assert.equal(one.scenario.pins.length, 0);
});

test('unreachable adjustment can be moved, edited, and removed without changing earlier rows', () => {
  const { state, simulate, applyEditTransaction } = loadDrawdownApi();
  Object.assign(state.params, { buffer_initial: 100, floor: 100, investments_initial: 0,
    investment_income: 0, external_income: 0, expense: 10, inflation: 0,
    tax_rate: 0, sale_tax_rate: 0, num_periods: 12 });
  const scenario = { params: state.params, pins: [{ id: 'later', at_month: 8,
    start: { investment_income: 10 }, end: { buffer: 1 } }], revision: 0 };
  const first = simulate(scenario.params, scenario.pins).rows[0];
  const edited = applyEditTransaction(scenario, { type: 'set', id: 'later', phase: 'end', field: 'buffer', value: 100 });
  assert.equal(edited.ok, true);
  assert.equal(JSON.stringify(edited.result.rows[0]), JSON.stringify(first));
  const moved = applyEditTransaction(scenario, { type: 'move', id: 'later', at_month: 1 });
  assert.equal(moved.ok, false, 'the now-reachable invalid income is checked');
  const removed = applyEditTransaction(scenario, { type: 'remove', id: 'later' });
  assert.equal(removed.ok, true);
  assert.equal(removed.scenario.pins.length, 0);
});

test('editing a later closing adjustment leaves prior monthly rows byte-equivalent', () => {
  const { state, simulate, applyEditTransaction } = loadDrawdownApi();
  Object.assign(state.params, { buffer_initial: 100, floor: 100, investments_initial: 1000,
    investment_income: 100, external_income: 0, expense: 50, inflation: 0,
    tax_rate: 0, sale_tax_rate: 0, modifier: 1, num_periods: 12 });
  const scenario = { params: state.params, pins: [{ id: 'late', at_month: 8,
    start: {}, end: { investments: 700 } }], revision: 0 };
  const before = Array.from(simulate(scenario.params, scenario.pins).rows.slice(0, 7), row => JSON.stringify(row));
  const edited = applyEditTransaction(scenario, { type: 'set', id: 'late', phase: 'end', field: 'investments', value: 600 });
  assert.equal(edited.ok, true);
  assert.deepEqual(Array.from(edited.result.rows.slice(0, 7), row => JSON.stringify(row)), before);
});

test('money and modifier validation reject blank, negative, and nonfinite drafts', () => {
  const { state, validateParams } = loadDrawdownApi();
  for (const [field, value] of [
    ['expense', ''], ['expense', '   '], ['expense', -1],
    ['expense', Infinity], ['expense', 'Infinity'], ['modifier', -0.1],
  ]) {
    const result = validateParams({ ...state.params, [field]: value });
    assert.equal(result.ok, false, `${field}=${value}`);
    assert.ok(result.issues.some(issue => issue.field === field && issue.message));
  }
  assert.equal(validateParams({ ...state.params, expense: 0 }).ok, true);
});

test('pin drafts validate fields and normalize taxes against baselines', () => {
  const { validatePinDraft } = loadDrawdownApi();
  const baseline = { tax_rate: 0.25, sale_tax_rate: 0.15, investments: 0 };
  const draft = { id: 'draft', at_month: 1, start: { tax_rate: 'Infinity', sale_tax_rate: -1, expense: '  ' }, end: {} };
  const invalid = validatePinDraft(draft, { baseline });
  assert.equal(invalid.ok, false);
  assert.ok(invalid.issues.some(issue => issue.field === 'expense'));
  assert.equal(draft.start.tax_rate, 'Infinity');
  const valid = validatePinDraft({ id: 'valid', at_month: 1, start: { tax_rate: 'Infinity', sale_tax_rate: 2 }, end: {} }, { baseline });
  assert.equal(valid.ok, true);
  assert.equal(valid.value.start.tax_rate, 0.25);
  assert.equal(valid.value.start.sale_tax_rate, 1);
  assert.equal(validatePinDraft({ id: 'zero', at_month: 1, start: {}, end: { investments: 0, investment_income: 1 } }, { baseline }).ok, true);
  assert.equal(validatePinDraft({ id: 'principal', at_month: 1, start: {}, end: { investments: 0 } },
    { baseline: { investments: 100, investment_income: 2 } }).ok, true);
});

test('blank pin money remains invalid through collection', () => {
  const { collectPinFields, validatePinDraft } = loadDrawdownApi();
  const input = {
    value: '  ',
    getAttribute(name) { return name === 'data-key' ? 'expense' : null; },
    closest() { return { getAttribute(name) { return name === 'data-baseline' ? '0' : 'money'; } }; },
  };
  const overrides = collectPinFields([input], new Set(['expense']));
  assert.equal(overrides.expense, '');
  const result = validatePinDraft({ id: 'blank', at_month: 1, start: overrides, end: {} }, { baseline: { expense: 0 } });
  assert.equal(result.ok, false);
  assert.ok(result.issues.some(issue => issue.field === 'expense'));
});

test('sidebar validation is atomic and marks the accepted result stale', () => {
  const controls = new Map();
  for (const [id, value] of Object.entries({
    'buffer-initial': '100', floor: '0', 'external-income': '0',
    'investments-initial': '100', 'investment-income': '0', modifier: '1',
    expense: '0', inflation: '0', 'tax-rate': '25', 'sale-tax-rate': '15', periods: '2',
  })) controls.set(id, { value, setAttribute() {}, removeAttribute() {} });
  controls.set('scenario-status', { textContent: '', hidden: true });
  controls.set('export-csv', { disabled: false });
  const { state, readParams } = loadDrawdownApi({ document: { getElementById(id) { return controls.get(id); } } });
  Object.assign(state.params, { buffer_initial: 100, expense: 0 });
  controls.get('buffer-initial').value = '200';
  controls.get('periods').value = '0.5';
  const previous = JSON.stringify(state.params);
  const invalid = readParams();
  assert.equal(invalid.ok, false);
  assert.equal(JSON.stringify(state.params), previous);
  assert.equal(state.stale, true);
  assert.equal(controls.get('export-csv').disabled, true);
  assert.match(controls.get('scenario-status').textContent, /period/i);
  controls.get('periods').value = '2';
  const accepted = readParams();
  assert.equal(accepted.ok, true);
  assert.equal(state.params.buffer_initial, 200);
  assert.equal(state.stale, false);
  assert.equal(controls.get('export-csv').disabled, false);
});

test('sidebar draft cannot invalidate an existing pin while changing accepted params', () => {
  const controls = new Map();
  for (const [id, value] of Object.entries({
    'buffer-initial': '100', floor: '0', 'external-income': '0',
    'investments-initial': '100', 'investment-income': '0', modifier: '1',
    expense: '0', inflation: '0', 'tax-rate': '25', 'sale-tax-rate': '15', periods: '2',
  })) controls.set(id, {
    value,
    invalid: false,
    setAttribute(name) { if (name === 'aria-invalid') this.invalid = true; },
    removeAttribute(name) { if (name === 'aria-invalid') this.invalid = false; },
  });
  controls.set('scenario-status', { textContent: '', hidden: true });
  controls.set('export-csv', { disabled: false });
  const { state, readParams, simulate } = loadDrawdownApi({
    document: { getElementById(id) { return controls.get(id); } },
  });
  Object.assign(state.params, { investments_initial: 100, investment_income: 0, num_periods: 2 });
  state.pins = [{ id: 'income', at_month: 1, start: { investment_income: 2 }, end: {} }];
  assert.equal(simulate().terminatedReason, 'horizon');
  const before = JSON.stringify(state.params);
  const revision = state.revision;
  controls.get('investments-initial').value = '0';
  const rejected = readParams();
  assert.equal(rejected.ok, false);
  assert.ok(rejected.issues.some(issue => issue.field === 'investment_income' && issue.month === 1));
  assert.equal(JSON.stringify(state.params), before);
  assert.equal(state.revision, revision);
  assert.equal(state.stale, true);
  assert.equal(controls.get('export-csv').disabled, true);
  assert.match(controls.get('scenario-status').textContent, /adjustment.*month 1/i);
  assert.equal(controls.get('investment-income').invalid, false);
});

test('accepted pin changes own their values and advance the scenario revision', () => {
  const { state, acceptPins } = loadDrawdownApi();
  const start = { expense: 3 };
  const pins = [{ id: 'expense', at_month: 1, start, end: {} }];
  const previousRevision = state.revision;
  acceptPins(pins);
  assert.equal(state.revision, previousRevision + 1);
  start.expense = 9;
  pins[0].at_month = 2;
  assert.equal(state.pins[0].at_month, 1);
  assert.equal(state.pins[0].start.expense, 3);
});

test('invalid pin transaction leaves the accepted scenario and revision intact', () => {
  const { state, tryAcceptPins } = loadDrawdownApi();
  Object.assign(state.params, { investments_initial: 100, investment_income: 2, num_periods: 2 });
  const previous = JSON.stringify(state.pins);
  const revision = state.revision;
  const result = tryAcceptPins([{ id: 'invalid', at_month: 1, start: {}, end: { investments: 0, investment_income: 1 } }]);
  assert.equal(result.ok, false);
  assert.ok(result.issues.some(issue => issue.field === 'investment_income'));
  assert.equal(JSON.stringify(state.pins), previous);
  assert.equal(state.revision, revision);
});
