'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { loadDrawdownApi } = require('./helpers/load_drawdown');

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
  const draft = { at_month: 1, overrides: { tax_rate: 'Infinity', sale_tax_rate: -1, expense: '  ' } };
  const invalid = validatePinDraft(draft, { baseline });
  assert.equal(invalid.ok, false);
  assert.ok(invalid.issues.some(issue => issue.field === 'expense'));
  assert.equal(draft.overrides.tax_rate, 'Infinity');
  const valid = validatePinDraft({ at_month: 1, overrides: { tax_rate: 'Infinity', sale_tax_rate: 2 } }, { baseline });
  assert.equal(valid.ok, true);
  assert.equal(valid.value.overrides.tax_rate, 0.25);
  assert.equal(valid.value.overrides.sale_tax_rate, 1);
  assert.equal(validatePinDraft({ at_month: 1, overrides: { investments: 0, investment_income: 1 } }, { baseline }).ok, false);
  assert.equal(validatePinDraft({ at_month: 1, overrides: { investments: 0 } },
    { baseline: { investments: 100, investment_income: 2 } }).ok, true);
});

test('blank pin money remains invalid through collection', () => {
  const { collectPinOverrides, validatePinDraft } = loadDrawdownApi();
  const input = {
    value: '  ',
    getAttribute(name) { return name === 'data-key' ? 'expense' : null; },
    closest() { return { getAttribute(name) { return name === 'data-baseline' ? '0' : 'money'; } }; },
  };
  const overrides = collectPinOverrides([input], new Set(['expense']));
  assert.equal(overrides.expense, '');
  const result = validatePinDraft({ at_month: 1, overrides }, { baseline: { expense: 0 } });
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
  state.pins = [{ at_month: 1, overrides: { investment_income: 2 } }];
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
  const overrides = { expense: 3 };
  const pins = [{ at_month: 1, overrides }];
  const previousRevision = state.revision;
  acceptPins(pins);
  assert.equal(state.revision, previousRevision + 1);
  overrides.expense = 9;
  pins[0].at_month = 2;
  assert.equal(state.pins[0].at_month, 1);
  assert.equal(state.pins[0].overrides.expense, 3);
});

test('invalid pin transaction leaves the accepted scenario and revision intact', () => {
  const { state, tryAcceptPins } = loadDrawdownApi();
  Object.assign(state.params, { investments_initial: 100, investment_income: 2, num_periods: 2 });
  const previous = JSON.stringify(state.pins);
  const revision = state.revision;
  const result = tryAcceptPins([{ at_month: 1, overrides: { investments: 0, investment_income: 1 } }]);
  assert.equal(result.ok, false);
  assert.ok(result.issues.some(issue => issue.field === 'investment_income'));
  assert.equal(JSON.stringify(state.pins), previous);
  assert.equal(state.revision, revision);
});
