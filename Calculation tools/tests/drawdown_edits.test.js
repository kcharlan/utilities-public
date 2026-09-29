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
  const year = aggregateForView(monthly, 'years', 12)[0];
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

function annualScenario(overrides = {}, pins = []) {
  const { state } = loadDrawdownApi();
  return { params: { ...state.params, buffer_initial: 1000, floor: 0,
    investments_initial: 1000, investment_income: 0, external_income: 0,
    expense: 0, inflation: 0, tax_rate: 0, sale_tax_rate: 0,
    modifier: 1, unit: 'months', num_periods: 12, ...overrides }, pins, revision: 4 };
}

test('annual expense inversion respects inflation, later resets, and planned horizon', async () => {
  const { solveAnnualTarget, simulate } = loadDrawdownApi();
  for (const [inflation, expected] of [[0, 10], [0.03, 9.865079089214396], [-1, 120]]) {
    const scenario = annualScenario({ inflation });
    const before = JSON.stringify(scenario);
    const result = await solveAnnualTarget(scenario, { first_month: 1, last_month: 12 }, 'expense', 120);
    assert.equal(result.status, 'solved');
    assert.ok(Math.abs(result.monthlyValue - expected) < 1e-8);
    assert.ok(Math.abs(result.verifiedTotal - 120) <= 1e-6);
    assert.equal(JSON.stringify(scenario), before);
    assert.equal(simulate(result.scenario.params, result.scenario.pins).rows.length, 12);
  }
  const reset = annualScenario({}, [{ id: 'reset', at_month: 7, start: { expense: 20 }, end: {} }]);
  assert.equal((await solveAnnualTarget(reset, { first_month: 1, last_month: 12 }, 'expense', 100)).status, 'infeasible');
  const partial = annualScenario({ num_periods: 8 });
  const solved = await solveAnnualTarget(partial, { first_month: 1, last_month: 8 }, 'expense', 80);
  assert.equal(solved.status, 'solved');
  assert.equal(solved.monthlyValue, 10);
});

test('annual income inversion verifies a full funded span and keeps original pins', async () => {
  const { solveAnnualTarget, simulate } = loadDrawdownApi();
  const scenario = annualScenario({ expense: 0 });
  const before = JSON.stringify(scenario);
  const solved = await solveAnnualTarget(scenario, { first_month: 1, last_month: 12 }, 'investment_income', 120);
  assert.equal(solved.status, 'solved');
  assert.ok(Math.abs(solved.monthlyValue - 10) <= 1e-6);
  assert.ok(Math.abs(solved.verifiedTotal - 120) <= 1e-6);
  assert.equal(JSON.stringify(scenario), before);
  assert.equal(solved.scenario.pins[0].annual_edits.investment_income.last_month, 12);
  assert.equal(simulate(solved.scenario.params, solved.scenario.pins).rows.length, 12);
  const zeroPrincipal = annualScenario({ investments_initial: 0, investment_income: 0 });
  assert.equal((await solveAnnualTarget(zeroPrincipal, { first_month: 1, last_month: 12 }, 'investment_income', 120)).status, 'infeasible');
});

test('annual income inversion covers sales, tax, modifiers, inflation, valuations, and later pins', async () => {
  const { annualIncomeContext, evaluateAnnualIncomeCandidate, solveAnnualTarget, simulate } = loadDrawdownApi();
  const fixtures = [
    ['sales', { buffer_initial:0, expense:12 }, []],
    ['sale tax', { buffer_initial:0, expense:12, sale_tax_rate:0.2 }, []],
    ['modifier high', { buffer_initial:0, expense:12, sale_tax_rate:0.2, modifier:1.4 }, []],
    ['modifier low', { buffer_initial:0, expense:12, sale_tax_rate:0.2, modifier:0.6 }, []],
    ['inflation', { buffer_initial:0, expense:12, inflation:0.03 }, []],
    ['income reset', { buffer_initial:0, expense:12 },
      [{ id:'reset',at_month:7,start:{ investment_income:4 },end:{} }]],
    ['valuation recovery', { buffer_initial:0, expense:12 },
      [{ id:'valuation',at_month:4,start:{},end:{ investments:1200 } }]],
    ['floor and expense pin', { buffer_initial:30, floor:20, expense:12 },
      [{ id:'later',at_month:5,start:{floor:25,expense:10},end:{} }]],
  ];
  for (const [name, overrides, pins] of fixtures) {
    const scenario = annualScenario(overrides,pins);
    const span = { first_month:1,last_month:12 };
    const before = JSON.stringify(scenario);
    const context = annualIncomeContext(scenario,span,0);
    const target = evaluateAnnualIncomeCandidate(context,8);
    assert.equal(target.funded,true,name);
    const answer = await solveAnnualTarget(scenario,span,'investment_income',target.total);
    assert.equal(answer.status,'solved',`${name}: ${JSON.stringify(answer)}`);
    assert.ok(Math.abs(answer.verifiedTotal-target.total) <= 1e-6,name);
    assert.ok(answer.subdivisions <= 8192,name);
    assert.equal(JSON.stringify(scenario),before,name);
    assert.equal(simulate(answer.scenario.params,answer.scenario.pins).rows.length,12,name);
    for (const pin of pins) assert.equal(JSON.stringify(answer.scenario.pins.find(item=>item.id===pin.id)),JSON.stringify(pin),name);
  }
});

test('annual income repairs a failure-truncated planned year rather than targeting eight emitted months', async () => {
  const { simulate, solveAnnualTarget, annualIncomeContext, evaluateAnnualIncomeCandidate } = loadDrawdownApi();
  const scenario = annualScenario({ buffer_initial:0, investments_initial:90, expense:12 });
  const baseline = simulate(scenario.params,scenario.pins);
  assert.equal(baseline.rows.length,8);
  assert.equal(baseline.plannedLastMonth,12);
  const span = { first_month:1,last_month:12 };
  const target = evaluateAnnualIncomeCandidate(annualIncomeContext(scenario,span,0),9);
  assert.equal(target.funded,true);
  const answer = await solveAnnualTarget(scenario,span,'investment_income',target.total);
  assert.equal(answer.status,'solved');
  assert.equal(answer.result.rows.length,12);
  assert.ok(answer.subdivisions < 8192);
  assert.equal(answer.scenario.pins[0].annual_edits.investment_income.last_month,12);
  const short = annualScenario({ buffer_initial:0, investments_initial:90, expense:12, num_periods:8 });
  const eight = await solveAnnualTarget(short,{ first_month:1,last_month:8 },'investment_income',96);
  assert.equal(eight.status,'solved');
  assert.equal(eight.scenario.pins[0].annual_edits.investment_income.last_month,8);
});

test('annual edits preserve previous provenance without imposing a live target', async () => {
  const { solveAnnualTarget,simulate } = loadDrawdownApi();
  const scenario = annualScenario({ buffer_initial:0, investments_initial:1000, expense:0 });
  const span = { first_month:1,last_month:12 };
  const income = await solveAnnualTarget(scenario,span,'investment_income',120);
  assert.equal(income.status,'solved');
  const expense = await solveAnnualTarget(income.scenario,span,'expense',240);
  assert.equal(expense.status,'solved');
  const pin = expense.scenario.pins[0];
  assert.equal(pin.annual_edits.investment_income.target_total,120);
  assert.equal(pin.annual_edits.expense.target_total,240);
  const actualIncome = simulate(expense.scenario.params,expense.scenario.pins).rows.reduce((sum,row)=>sum+row.investment_income,0);
  assert.notEqual(actualIncome,120);
  assert.ok(Math.abs(expense.verifiedTotal-240)<=1e-6);
});

test('annual proposal validates later pins while allowing later reserve failure', async () => {
  const { solveAnnualTarget } = loadDrawdownApi();
  const span = {first_month:1,last_month:12};
  const invalidLater = annualScenario({num_periods:24,floor:100},[
    {id:'later',at_month:13,start:{},end:{buffer:0}},
  ]);
  assert.equal((await solveAnnualTarget(invalidLater,span,'expense',120)).status,'invalid');
  const laterFailure = annualScenario({num_periods:24,buffer_initial:120,investments_initial:0});
  const solved = await solveAnnualTarget(laterFailure,span,'expense',120);
  assert.equal(solved.status,'solved');
  assert.equal(solved.result.terminatedReason,'reserve_failure');
  assert.ok(solved.result.rows.length > 12);
  assert.equal((await solveAnnualTarget(laterFailure,span,'expense',120,{throughMonth:8})).status,'invalid');
});

test('income solver handles zero targets, zero principal, and proven insufficient funding', async () => {
  const { solveAnnualTarget } = loadDrawdownApi();
  const span = { first_month:1,last_month:12 };
  assert.equal((await solveAnnualTarget(annualScenario(),span,'investment_income',0)).status,'solved');
  assert.equal((await solveAnnualTarget(annualScenario({ investments_initial:0 }),span,'investment_income',0)).status,'solved');
  assert.equal((await solveAnnualTarget(annualScenario({ investments_initial:0 }),span,'investment_income',10)).status,'infeasible');
  assert.equal((await solveAnnualTarget(annualScenario({ buffer_initial:0,expense:2000 }),span,'investment_income',10)).status,'infeasible');
  assert.equal((await solveAnnualTarget(annualScenario({ buffer_initial:0,investments_initial:0 }),span,'expense',120)).status,'infeasible');
  assert.equal((await solveAnnualTarget(annualScenario(),span,'expense',1e20)).status,'invalid');
  assert.equal((await solveAnnualTarget(annualScenario(),span,'investment_income',120,
    { signal:{ aborted:true } })).status,'cancelled');
  assert.equal((await solveAnnualTarget(annualScenario(),span,'expense',120,
    { signal:{ aborted:true } })).status,'cancelled');
});

test('trial candidates never consume live adjustment ids or mutate the scenario', async () => {
  const { solveAnnualTarget,applyEditTransaction } = loadDrawdownApi();
  const scenario = annualScenario({ buffer_initial:0,expense:2000 });
  const before = JSON.stringify(scenario);
  await solveAnnualTarget(scenario,{first_month:1,last_month:12},'investment_income',10);
  assert.equal(JSON.stringify(scenario),before);
  const edit = applyEditTransaction(scenario,{type:'set',at_month:2,phase:'start',field:'expense',value:100});
  assert.equal(edit.ok,true);
  assert.equal(edit.scenario.pins[0].id,'adjustment-1');
});

test('solving a later annual group leaves the unchanged prefix byte-equivalent', async () => {
  const { annualIncomeContext,evaluateAnnualIncomeCandidate,solveAnnualTarget,simulate } = loadDrawdownApi();
  const scenario = annualScenario({ buffer_initial:0,investments_initial:2000,
    investment_income:8,expense:12,num_periods:24 },
  [{ id:'earlier',at_month:5,start:{expense:10},end:{} }]);
  const span = { first_month:13,last_month:24 };
  const prefix = simulate(scenario.params,scenario.pins).rows.slice(0,12).map(row=>JSON.stringify(row));
  const target = evaluateAnnualIncomeCandidate(annualIncomeContext(scenario,span,0),9);
  assert.equal(target.funded,true);
  assert.equal(target.simulatedMonths,12);
  const answer = await solveAnnualTarget(scenario,span,'investment_income',target.total);
  assert.equal(answer.status,'solved');
  assert.deepEqual(answer.result.rows.slice(0,12).map(row=>JSON.stringify(row)),prefix);
  assert.equal(JSON.stringify(answer.scenario.pins.find(pin=>pin.id==='earlier')),JSON.stringify(scenario.pins[0]));
});

test('trial checkpoint input rejects malformed runtime state without throwing', () => {
  const { simulate } = loadDrawdownApi();
  const scenario = annualScenario();
  assert.equal(simulate(scenario.params,scenario.pins,{startMonth:2,throughMonth:12,resumeState:{}}).terminatedReason,'invalid');
});

test('annual income enclosure contains scalar trials over a sale boundary', () => {
  const { annualIncomeContext, evaluateAnnualIncomeCandidate, encloseAnnualIncomeCandidates } = loadDrawdownApi();
  const context = annualIncomeContext(annualScenario({ buffer_initial: 0, expense: 12, investments_initial: 100,
    modifier: 1.4, sale_tax_rate: 0.2 }), { first_month: 1, last_month: 12 }, 120);
  const enclosure = encloseAnnualIncomeCandidates(context, [8, 16]);
  for (let x = 8; x <= 16; x += 0.25) {
    const candidate = evaluateAnnualIncomeCandidate(context, x);
    if (candidate.funded) assert.ok(enclosure.total[0] <= candidate.total && candidate.total <= enclosure.total[1], `${x}`);
  }
});

test('income enclosure gates payment at zero principal without erasing raw income', () => {
  const { annualIncomeContext, evaluateAnnualIncomeCandidate, encloseAnnualIncomeCandidates } = loadDrawdownApi();
  const scenario = annualScenario({ buffer_initial: 1000, investments_initial: 1000, modifier: 0 },
    [{ id: 'zero', at_month: 1, start: {}, end: { investments: 0 } }]);
  const context = annualIncomeContext(scenario, { first_month: 1, last_month: 12 }, 10);
  const scalar = evaluateAnnualIncomeCandidate(context, 10);
  const singleton = encloseAnnualIncomeCandidates(context, [10,10]);
  assert.equal(scalar.funded, true);
  assert.equal(scalar.total, 10);
  assert.ok(singleton.total[0] <= 10 && singleton.total[1] >= 10, JSON.stringify(singleton));
  const mixed = encloseAnnualIncomeCandidates(context, [0,10]);
  for (const x of [0,1,5,10]) {
    const trial = evaluateAnnualIncomeCandidate(context,x);
    assert.ok(mixed.total[0] <= trial.total && trial.total <= mixed.total[1]);
  }
});

test('income enclosure covers zero-principal recovery and mixed principal candidates', () => {
  const { annualIncomeContext,evaluateAnnualIncomeCandidate,encloseAnnualIncomeCandidates } = loadDrawdownApi();
  const scenario = annualScenario({ buffer_initial:1000,investments_initial:100,modifier:0 },[
    { id:'zero',at_month:1,start:{},end:{investments:0} },
    { id:'recover',at_month:6,start:{},end:{investments:100} },
  ]);
  const context = annualIncomeContext(scenario,{first_month:1,last_month:12},70);
  const bound = encloseAnnualIncomeCandidates(context,[9,11]);
  for(const x of [9,10,11]) {
    const trial = evaluateAnnualIncomeCandidate(context,x);
    assert.equal(trial.funded,true);
    assert.ok(bound.total[0] <= trial.total && trial.total <= bound.total[1]);
  }
  assert.equal(evaluateAnnualIncomeCandidate(context,10).total,70);
  const crossing = annualIncomeContext(annualScenario({buffer_initial:0,investments_initial:10,expense:12}),
    {first_month:1,last_month:12},144);
  const mixed = encloseAnnualIncomeCandidates(crossing,[0,12]);
  const valid = evaluateAnnualIncomeCandidate(crossing,12);
  assert.equal(valid.funded,true);
  assert.ok(mixed.total[0] <= valid.total && valid.total <= mixed.total[1]);
});

test('certain positive sales contract singleton income enclosure', () => {
  const { annualIncomeContext, evaluateAnnualIncomeCandidate, encloseAnnualIncomeCandidates } = loadDrawdownApi();
  const scenario = annualScenario({ buffer_initial: 0, floor: 0, investments_initial: 1000,
    expense: 12, modifier: 1.4, sale_tax_rate: 0.2 });
  const context = annualIncomeContext(scenario, { first_month: 1, last_month: 12 }, 92);
  const scalar = evaluateAnnualIncomeCandidate(context,8);
  const singleton = encloseAnnualIncomeCandidates(context,[8,8]);
  assert.equal(scalar.funded, true);
  assert.ok(singleton.total[0] <= scalar.total && scalar.total <= singleton.total[1]);
  assert.ok(singleton.total[1]-singleton.total[0] < 1e-6, JSON.stringify(singleton));
  for (const width of [2,0.5,0.01,0.0001]) {
    const bounded = encloseAnnualIncomeCandidates(context,[8-width,8+width]);
    for (const x of [8-width,8,8+width]) {
      const trial = evaluateAnnualIncomeCandidate(context,x);
      if (trial.funded) assert.ok(bounded.total[0] <= trial.total && trial.total <= bounded.total[1]);
    }
  }
});

test('fully funded sale restores the cash floor without interval dependency explosion', () => {
  const { annualIncomeContext, evaluateAnnualIncomeCandidate, encloseAnnualIncomeCandidates } = loadDrawdownApi();
  const scenario = annualScenario({ buffer_initial: 0, floor: 0, investments_initial: 90,
    expense: 12, modifier: 1, sale_tax_rate: 0 });
  const context = annualIncomeContext(scenario, { first_month: 1, last_month: 12 }, 80);
  const scalar = evaluateAnnualIncomeCandidate(context,8.99789);
  const enclosed = encloseAnnualIncomeCandidates(context,[8.99789,8.99799]);
  assert.equal(scalar.funded,true);
  assert.ok(enclosed.total[0] <= scalar.total && scalar.total <= enclosed.total[1]);
  assert.ok(enclosed.total[1]-enclosed.total[0] < 0.01, JSON.stringify(enclosed));
});

test('deterministic scalar sweep stays inside model enclosures across narrow sale boundaries', () => {
  const { annualIncomeContext,evaluateAnnualIncomeCandidate,encloseAnnualIncomeCandidates } = loadDrawdownApi();
  const scenario = annualScenario({buffer_initial:0,investments_initial:90,expense:12,
    modifier:1.2,sale_tax_rate:0.15,inflation:0.03});
  const context = annualIncomeContext(scenario,{first_month:1,last_month:12},80);
  for(const [lo,hi] of [[0,12],[7.5,9.5],[8,8.01],[8.99789,8.99799],[11.999,12]]) {
    const bound = encloseAnnualIncomeCandidates(context,[lo,hi]);
    for(const x of [lo,lo+(hi-lo)/4,(lo+hi)/2,lo+3*(hi-lo)/4,hi]) {
      const trial = evaluateAnnualIncomeCandidate(context,x);
      if(trial.funded) assert.ok(bound.total[0]<=trial.total && trial.total<=bound.total[1],
        `${lo}-${hi} x=${x}: ${trial.total} outside ${bound.total}`);
    }
  }
});

test('income enclosure and inversion use scalar normalization for later tax pins', async () => {
  const { annualIncomeContext,evaluateAnnualIncomeCandidate,encloseAnnualIncomeCandidates,
    solveAnnualTarget } = loadDrawdownApi();
  for (const field of ['tax_rate','sale_tax_rate']) for (const raw of [-1,2,100,' ','Infinity']) {
    const scenario = annualScenario({buffer_initial:0,investments_initial:1000,
      investment_income:0,expense:12,modifier:1,tax_rate:0,sale_tax_rate:0},[
      {id:'tax',at_month:2,start:{[field]:raw},end:{}},
    ]);
    const span = {first_month:1,last_month:12};
    const x = field === 'sale_tax_rate' && raw > 1 ? 12 : 8;
    const context = annualIncomeContext(scenario,span,0);
    const scalar = evaluateAnnualIncomeCandidate(context,x);
    assert.equal(scalar.funded,true,`${field}=${raw}`);
    const interval = encloseAnnualIncomeCandidates(context,[x,x]);
    assert.equal(interval.possibleFunded,true,`${field}=${raw}`);
    assert.ok(interval.total[0] <= scalar.total && scalar.total <= interval.total[1],
      `${field}=${raw}: ${scalar.total} outside ${interval.total}`);
    const solved = await solveAnnualTarget(scenario,span,'investment_income',scalar.total);
    assert.equal(solved.status,'solved',`${field}=${raw}: ${JSON.stringify(solved)}`);
    assert.ok(Math.abs(solved.verifiedTotal-scalar.total)<=1e-6,`${field}=${raw}`);
  }
});

test('interval arithmetic encloses signed products, safe division, clamps, and unions', () => {
  const { intervalArithmetic: I } = loadDrawdownApi();
  for (const [a, b] of [ [[-3,2],[-5,7]], [[1e-300,2e-300],[-4,9]], [[-8,-2],[-4,-0.1]] ]) {
    const product = I.mul(a,b);
    for (const x of [a[0],(a[0]+a[1])/2,a[1]]) for (const y of [b[0],(b[0]+b[1])/2,b[1]]) {
      assert.ok(product[0] <= x*y && x*y <= product[1]);
      if (!(b[0] <= 0 && b[1] >= 0)) {
        const quotient = I.div(a,b);
        assert.ok(quotient[0] <= x/y && x/y <= quotient[1]);
      }
    }
  }
  assert.equal(I.div([1,2],[-Number.MIN_VALUE,Number.MIN_VALUE]), null);
  assert.ok(I.adjacent(0,-1) < 0 && I.adjacent(0,1) > 0);
  assert.ok(I.adjacent(Number.MAX_VALUE,1) === Infinity);
  assert.deepEqual(Array.from(I.max([0,2],[1,3])), [1,3]);
  assert.deepEqual(Array.from(I.min([0,2],[1,3])), [0,2]);
  assert.deepEqual(Array.from(I.hull([-2,-1],[1,2])), [-2,2]);
});

test('generic search certifies analytic linear feasible-band distance from either side', async () => {
  const { searchAnnualIncome } = loadDrawdownApi();
  const rho = 1e-9, tau = 1e-9;
  for (const current of [0,10,3]) {
    const solved = await searchAnnualIncome({ evaluate: x => ({ total:x, funded:true }),
      enclose: ([lo,hi]) => ({ total:[lo,hi], possibleFunded:true }),
      domain:[0,10],current,target:3 });
    assert.equal(solved.status,'solved');
    const optimum = current < 3-rho ? 3-rho : current > 3+rho ? 3+rho : current;
    assert.ok(Math.abs(solved.x-current) <= Math.abs(optimum-current)+tau+1e-12);
    assert.ok(Math.abs(solved.total-3) <= rho);
  }
});

test('generic search selects nearest separated root from left, right, and between', async () => {
  const { searchAnnualIncome } = loadDrawdownApi();
  const parabola = x => (x-2)*(x-8);
  const enclosure = ([lo,hi]) => {
    const values = [parabola(lo),parabola(hi)];
    if (lo <= 5 && hi >= 5) values.push(-9);
    return { total: [Math.min(...values),Math.max(...values)], possibleFunded: true };
  };
  for (const [current,root] of [[0,2],[10,8],[5,2],[2.5,2],[7.5,8]]) {
    const two = await searchAnnualIncome({ evaluate: x => ({ total: parabola(x), funded: true }),
      enclose: enclosure, domain: [0,10], current, target: 0 });
    assert.equal(two.status, 'solved', `${current}`);
    assert.ok(Math.abs(two.x-root) < 1e-6, `${current}: ${two.x}`);
    assert.ok(Math.abs(two.total) <= 1e-9);
    const outerLeft = 5-Math.sqrt(9+1e-9), innerLeft = 5-Math.sqrt(9-1e-9);
    const innerRight = 5+Math.sqrt(9-1e-9), outerRight = 5+Math.sqrt(9+1e-9);
    const optimum = current <= outerLeft ? outerLeft : current >= outerRight ? outerRight :
      current < 5 ? innerLeft : current > 5 ? innerRight : innerLeft;
    assert.ok(Math.abs(two.x-current) <= Math.abs(optimum-current)+1e-9+1e-12,`${current}: ${two.x}`);
  }
});

test('generic search resolves tangent root without sign change', async () => {
  const { searchAnnualIncome } = loadDrawdownApi();
  const tangent = await searchAnnualIncome({ evaluate: x => ({ total: (x-3)**2, funded: true }),
    enclose: ([lo,hi]) => ({ total: [lo<=3&&hi>=3 ? 0 : Math.min((lo-3)**2,(hi-3)**2),
      Math.max((lo-3)**2,(hi-3)**2)], possibleFunded: true }), domain: [0,8], current: 0, target: 0 });
  assert.equal(tangent.status, 'solved');
  const rho = 1e-9, tau = 1e-9;
  const nearestFeasible = 3-Math.sqrt(rho);
  assert.ok(Math.abs(tangent.total) <= rho);
  assert.ok(Math.abs(tangent.x-nearestFeasible) <= tau,
    `${tangent.x} is farther than tau from the analytic feasible-band endpoint ${nearestFeasible}`);
});

test('generic search handles a flat feasible interval', async () => {
  const { searchAnnualIncome } = loadDrawdownApi();
  const flat = await searchAnnualIncome({ evaluate: x => ({ total: x>=2&&x<=4 ? 1 : 0, funded: true }),
    enclose: ([lo,hi]) => ({ total: [lo>=2&&hi<=4 ? 1 : 0, hi>=2&&lo<=4 ? 1 : 0], possibleFunded: true }),
    domain: [0,6], current: 3, target: 1 });
  assert.equal(flat.status, 'solved');
  assert.ok(flat.x >= 2 && flat.x <= 4);
  assert.ok(Math.abs(flat.x-3) <= 1e-9);
});

test('generic search ignores invalid holes and resolves lower-valued ties without drift', async () => {
  const { searchAnnualIncome } = loadDrawdownApi();
  const hole = await searchAnnualIncome({ evaluate:x=>({total:x,funded:x<2||x>4}),
    enclose:([lo,hi])=>({total:[lo,hi],possibleFunded:lo<2||hi>4}),
    domain:[0,6],current:3,target:4.5 });
  assert.equal(hole.status,'solved');
  assert.ok(Math.abs(hole.x-4.5) < 1e-6);
  const impossibleHole = await searchAnnualIncome({ evaluate:x=>({total:x,funded:x<2||x>4}),
    enclose:([lo,hi])=>({total:[lo,hi],possibleFunded:lo<2||hi>4}),
    domain:[0,6],current:3,target:3 });
  assert.equal(impossibleHole.status,'infeasible');
  const sampled = [];
  const drift = await searchAnnualIncome({ evaluate:x=>{sampled.push(x);return {total:1,funded:true};},
    enclose:()=>({total:[1,1],possibleFunded:true}),
    domain:[2,2+1.2e-9],current:3,target:1 });
  assert.equal(drift.status,'solved');
  assert.ok(sampled.length>=3);
  assert.ok(drift.x >= 2+0.7e-9, `${drift.x}`);
});

test('generic search cancellation and exhausted budget remain distinct from infeasibility', async () => {
  const { searchAnnualIncome } = loadDrawdownApi();
  const base = { evaluate: x => ({ total: x, funded: true }),
    enclose: () => ({ total: [-Infinity,Infinity], possibleFunded: true }),
    domain: [0,10], current: 0, target: 3 };
  assert.equal((await searchAnnualIncome({ ...base, options: { signal: { aborted: true } } })).status, 'cancelled');
  assert.equal((await searchAnnualIncome({ ...base, options: { maxSubdivisions: 1 } })).status, 'unresolved');
  assert.equal((await searchAnnualIncome({ ...base, options: { maxDepth: 1 } })).status, 'unresolved');
  let calls = 0;
  assert.equal((await searchAnnualIncome({ ...base,
    options:{ cancelled:()=>++calls>4 } })).status,'cancelled');
});
