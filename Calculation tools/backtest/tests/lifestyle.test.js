'use strict';
const test = require('node:test');
const { getMarketRows } = require('./helpers/dataset.cjs');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const Stats = require('../stats.js');
const Views = require('../views.js');
const { STRATEGIES, simulate, sweepStartYears } = require('../engine.js');
const api = () => require('../lifestyle.js');
const profile = (values, options = {}) => Stats.spendingProfile({ realSpending: values, baseline: 100, horizon: values.length, failed: false, partial: false, startYear: 2000, ...options });
const entry = (year, spending, options = {}) => ({ startYear: year, metrics: { spending, success: !spending.failed, partial: spending.partial, terminalWealthReal: 1000, spendingVolatility: 0.1, ...options } });
const close = (actual, expected, tolerance = 1e-9) => assert.ok(Math.abs(actual - expected) <= tolerance * Math.max(1, Math.abs(expected)), `${actual} != ${expected}`);
const series = results => [{ label: 'A', color: 'var(--chart-stock)', results, summary: Views.summarizeSweep(results, false, 90), configuration: { options: { startingBalance: 1000 } }, strategy: STRATEGIES.fixedPercent }];

test('lifestyle module has a frozen namespace and explicit browser dependency errors', () => {
  assert.ok(Object.isFrozen(api()));
  const source = fs.readFileSync(require.resolve('../lifestyle.js'), 'utf8');
  for (const name of ['MarketAtlasFormat', 'MarketAtlasStats', 'MarketAtlasViews']) {
    const sandbox = { MarketAtlasFormat: require('../format.js'), MarketAtlasStats: Stats, MarketAtlasViews: Views };
    delete sandbox[name];
    assert.throws(() => vm.runInNewContext(source, sandbox), /requires/);
  }
});

test('window lifestyle cells use delivered floor reach, hold, range and need', () => {
  const spending = profile([100, 50, 50, 120]);
  const cells = api().windowLifestyleCells({ spending, failureYear: null }, 90);
  assert.deepEqual(cells.map(c => c.label), ['Spending floor', 'Spending range', 'Typical year', 'Below your need']);
  assert.equal(cells[0].value, '$50');
  assert.equal(cells[0].detail, '50% of year 1 · reached 2001 (year 2) · held 2 yrs');
  assert.equal(cells[1].value, '$50–120');
  assert.equal(cells[1].detail, 'deepest cut 50% from peak');
  assert.equal(cells[2].value, '$75');
  assert.equal(cells[2].detail, 'median · $80 average · $320 total');
  assert.equal(cells[3].value, '2 of 4 yrs');
  assert.match(cells[3].detail, /under \$90 \(90% of yr 1\) · longest run 2 · shortfall 0.8 yrs of spending/);
  assert.equal(api().windowLifestyleCells({ spending }, null)[3].detail, 'set a need in § 05');
});

test('failed and partial floor cells retain funding and observed-year context', () => {
  const failed = profile([100, 20], { failed: true, horizon: 4 });
  const floor = api().windowLifestyleCells({ spending: failed, failureYear: 2001 }, 90)[0];
  assert.equal(floor.value, '$0');
  assert.equal(floor.className, 'warning');
  assert.equal(floor.detail, 'depleted 2001 · 2 unfunded yrs · last partial $20 · funded floor $100');
  const partial = profile([100, 50], { partial: true, horizon: 4 });
  const cell = api().windowLifestyleCells({ spending: partial }, null)[0];
  assert.equal(cell.label, 'Floor to date');
  assert.match(cell.detail, /2 of 4 yrs observed/);
});

test('sweep lifestyle excludes partials, chooses earliest tolerance ties and summarizes need once per path', () => {
  const results = [entry(2002, profile([100, 50])), entry(2001, profile([100, 50 + 1e-14])), entry(2000, profile([100, 1], { partial: true }))];
  const l = Views.summarizeSweep(results, false, 90).lifestyle;
  assert.equal(l.completeCount, 2); assert.equal(l.worstFloorStartYear, 2001);
  assert.equal(l.worstSurvivingStartYear, 2001); assert.equal(l.survivorsUniform, true);
  assert.equal(l.deepestCutStartYear, 2001); assert.equal(l.worstShortfallStartYear, 2001);
  assert.equal(l.longestBelowNeedRun, 1); assert.equal(l.baselineUniform, true);
  assert.equal(l.p10Floor, 50); assert.equal(l.medianTypicalSpending, 75);
});

test('missing spending is compatible and zero-complete lifestyle has only null aggregates', () => {
  assert.equal(Views.summarizeSweep([{ metrics: { success: true } }], false).lifestyle, null);
  const l = Views.summarizeSweep([], false).lifestyle;
  assert.equal(l.completeCount, 0);
  for (const [key, value] of Object.entries(l)) if (key !== 'completeCount') assert.equal(value, null, key);
});

test('sweep cells combine solvency context, all-window floors and need state', () => {
  const results = [entry(2001, profile([100, 100])), entry(2002, profile([100, 25], { failed: true, horizon: 4 }))];
  const summary = Views.summarizeSweep(results, false, 90);
  const cells = api().sweepSolvencyCells(summary, { canDeplete: false });
  assert.equal(cells.length, 3); assert.equal(cells[1].label, 'Worst solvency start');
  assert.match(cells[0].detail, /1 of 2 · cannot deplete by construction · 0 held out/);
  assert.match(cells[2].detail, /spend volatility 10.0%–10.0%/);
  const lifestyle = api().sweepLifestyleCells(summary);
  assert.equal(lifestyle[0].value, '$0'); assert.match(lifestyle[0].detail, /1 failed · earliest 2002 start · survivors all at 100% of yr 1/);
  assert.equal(lifestyle[3].value, '2002');
  assert.equal(api().sweepLifestyleCells(Views.summarizeSweep([results[0]], false, 90))[3].detail, 'no year below need');
  assert.equal(api().sweepLifestyleCells(Views.summarizeSweep([results[0]], false))[3].detail, 'set a need');
});

test('volatility formatter and comparison rows preserve existing seven rows and append nine lifestyle rows', () => {
  const items = series([entry(2000, profile([100, 100]))]);
  assert.equal(api().formatVolatilityRange(items[0].summary), '10.0%–10.0%');
  assert.equal(api().formatVolatilityRange({ spendingVolatilityMin: null }), '—');
  const rows = api().sweepSummaryRows(items, 90);
  assert.equal(rows.length, 16);
  assert.deepEqual(rows.slice(0, 7).map(r => r.label), ['Survived · complete only', 'Partial windows held out', 'Worst opening · failure year', 'Median terminal wealth · real', 'Worst terminal wealth · real', 'Spending volatility range', 'Minimum sustainable rate']);
  assert.equal(rows[0].values[0], '100.0% · 1/1'); assert.equal(rows[6].values[0], 'Not supported');
  assert.equal(rows.find(r => r.label === 'Worst surviving floor').values[0], '$100 · every survivor');
});

test('strip model uses padded path, delivered transitions, note fallback and shared statistics', () => {
  const spending = profile([100, 50, 70], { failed: true, horizon: 5 });
  const model = api().spendingStripModel([{ notes: '' }, { notes: '<script>' }, { notes: '' }], spending, 90);
  assert.deepEqual(model.points.map(p => p.year), [2000, 2001, 2002, 2003, 2004]);
  assert.deepEqual(model.points.map(p => p.funded), [true, true, true, false, false]);
  assert.deepEqual(model.markers, [{ index: 1, kind: 'cut', note: '<script>' }, { index: 2, kind: 'raise', note: 'real spending rose' }]);
  assert.equal(model.showFloorRule, false); assert.equal(model.shadeAgainst, 90); close(model.yMax, 112);
  const flat = api().spendingStripModel([], profile([100, 100]), null);
  assert.equal(flat.showFloorRule, false); assert.equal(flat.shadeAgainst, 100);
});

test('ledger floor flags cover delivered rows only and suppress flat floors', () => {
  assert.deepEqual(api().ledgerFloorFlags(profile([100, 50, 50])), [false, true, true]);
  assert.deepEqual(api().ledgerFloorFlags(profile([100, 100 - 1e-14])), [false, false]);
  assert.deepEqual(api().ledgerFloorFlags(profile([100, 20], { failed: true, horizon: 5 })), [false, false]);
});

test('range bars exclude partials from all rules and show surviving floor when failures exist', () => {
  const results = [entry(2000, profile([100, 70])), entry(2001, profile([100, 20], { failed: true, horizon: 4 })), entry(2002, profile([100, 1], { partial: true }))];
  const model = api().spendingRangeModel(series(results), 90);
  assert.equal(model.mode, 'bars'); assert.equal(model.yUnit, 'dollars');
  assert.deepEqual(model.bars.map(b => b.kind), ['complete', 'failed', 'partial']);
  assert.match(model.bars[2].label, /floor to date/);
  assert.equal(model.rules.find(r => r.key === 'worst').value, 70);
  assert.match(model.rules.find(r => r.key === 'worst').label, /worst surviving floor \$70 · 1 failed at \$0/);
  assert.equal(model.rules.find(r => r.key === 'p10').value, 0);
  const multi = api().spendingRangeModel([...series(results), ...series(results)], 90);
  assert.equal(multi.mode, 'floorLines'); assert.equal(multi.yMax, 1.2); assert.equal(multi.series[0].points[1].value, 0);
});

test('frontier plan preserves exact unsnapped 25-point metadata grid and inserts current values', () => {
  const f = api().frontierPlan(STRATEGIES.guytonKlinger, { initialRate: 0.04 }, 'initialRate');
  assert.equal(f.isPercent, true); assert.equal(f.values.length, 25);
  f.values.forEach((v, i) => close(v, .02 + i * .0025)); assert.ok(f.values.includes(.0575));
  assert.equal(api().frontierPlan(STRATEGIES.guytonKlinger, { initialRate: .041 }, 'initialRate').values.length, 26);
  assert.ok(api().frontierPlan(STRATEGIES.guytonKlinger, { initialRate: .01 }, 'initialRate').values.includes(.01));
});

test('frontier caps generated points before current insertion and handles invalid and zero ranges', () => {
  const f = (current, override) => api().frontierPlan(STRATEGIES.fixedReal, { initialRate: current }, 'initialRate', override);
  assert.equal(f(.0405, { from: .02, to: .06, step: .001 }).values.length, 42);
  assert.equal(f(.04, { from: .02, to: .06, step: .001 }).values.length, 41);
  assert.ok(f(.04, { from: .02, to: .061, step: .001 }).error);
  for (const override of [{ from: .1, to: .02, step: .001 }, { from: -1, to: .06, step: .001 }, { from: .02, to: .06, step: 0 }, { from: NaN, to: .06, step: .001 }]) assert.ok(f(.04, override).error);
  const strategy = { paramSchema: [{ key: 'guardrail', label: 'Guardrail', type: 'percent', default: .2, min: 0, max: 1, step: .001 }, { key: 'mix', type: 'select' }, { key: 'zero', type: 'number', default: 0, min: 0, max: 5, step: 1 }] };
  const defaultGrid = api().frontierPlan(strategy, { guardrail: .2 }, 'guardrail');
  assert.equal(defaultGrid.values.length, 21); close(defaultGrid.values[0], .1); close(defaultGrid.values.at(-1), .3);
  assert.ok(api().frontierPlan(strategy, {}, 'mix').error);
  assert.deepEqual(api().frontierPlan(strategy, {}, 'zero').values, [0]);
});

test('frontier model always uses all-window zero floors and normalizes differing balances', () => {
  const points = [{ value: .08, lifestyle: { completeCount: 69, worstFloor: 0, worstSurvivingFloor: 80000, medianFloor: 0, failedCount: 55, worstFloorStartYear: 1965 } }];
  const input = [{ label: 'A', color: 'var(--chart-stock)', startingBalance: 1e6, points, isPercent: true }];
  const model = api().frontierModel(input);
  assert.equal(model.yUnit, 'dollars'); assert.equal(model.windowCount, 69); assert.equal(model.isPercent, true);
  assert.equal(model.series[0].points[0].worstFloor, 0);
  const normalized = api().frontierModel([...input, { ...input[0], startingBalance: 2e6, points: [{ value: .04, lifestyle: { ...points[0].lifestyle, worstFloor: 20000 } }] }]);
  assert.equal(normalized.yUnit, 'startingBalancePct'); assert.equal(normalized.series[1].points[0].worstFloor, .01);
});

test('need readout resolves both anchors and caveat uses schema rather than strategy id', () => {
  assert.deepEqual(api().needReadout({ anchor: 'percent', ratio: .9 }, 40000), { dollars: 36000, amountText: '$36,000', percentText: '90%', followsConfiguration: true });
  assert.deepEqual(api().needReadout({ anchor: 'dollars', amount: 36000 }, 80000), { dollars: 36000, amountText: '$36,000', percentText: '45%', followsConfiguration: false });
  assert.equal(api().needReadout(null, 0).amountText, '—');
  assert.match(api().horizonCaveat({ paramSchema: [{ key: 'preservationCutoffYears' }] }), /horizon/i);
  assert.equal(api().horizonCaveat({ id: 'guytonKlinger', paramSchema: [] }), '');
});

const market = async () => (await getMarketRows()).filter(r => r.year >= 1928);
const options = { startingBalance: 1e6, allocation: { stock: .6, bond: .4, bill: 0 }, feeRate: 0, taxRate: 0, horizon: 30 };
for (const [strategyId, params, floor, startYear, failed, longest] of [
  ['guytonKlinger', { initialRate: .04 }, 21073.055650429807, 1968, 0, 24],
  ['fixedReal', { initialRate: .04 }, 0, 1965, 4, null],
  ['fixedPercent', { rate: .04 }, 16339.197517681008, 1966, 0, 26],
]) test(`real-data ${strategyId} lifestyle aggregates`, async () => {
  const l = Views.summarizeSweep(sweepStartYears(await market(), 30, STRATEGIES[strategyId], params, options), false, 36000).lifestyle;
  assert.equal(l.completeCount, 69); assert.equal(l.failedCount, failed); close(l.worstFloor, floor); assert.equal(l.worstFloorStartYear, startYear);
  if (longest !== null) assert.equal(l.longestBelowNeedRun, longest);
  if (strategyId === 'guytonKlinger') { close(l.worstFloorRatio, .5268, .0001); close(l.medianFloorRatio, .9286, .0005); close(l.deepestCut, .473, .001); assert.equal(l.deepestCutStartYear, 1968); assert.equal(l.worstShortfallStartYear, 1966); }
  if (strategyId === 'fixedReal') { close(l.worstSurvivingFloor, 40000); assert.equal(l.worstSurvivingStartYear, 1928); assert.equal(l.survivorsUniform, true); }
});

test('real-data GK 1966 window names the reached and held floor', async () => {
  const result = simulate((await market()).filter(r => r.year >= 1966).slice(0, 30), STRATEGIES.guytonKlinger, { initialRate: .04 }, options);
  assert.match(api().windowLifestyleCells(result.metrics, 36000)[0].detail, /57% of year 1 · reached 1978 \(year 13\) · held 14 yrs/);
});

test('meaningful dollar shortfall remains positive when divided by a large baseline', () => {
  const spending = profile([1], { baseline: 1e15 });
  const l = Views.summarizeSweep([entry(2000, spending)], false, 2).lifestyle;
  assert.equal(l.worstShortfallStartYear, 2000);
  assert.equal(l.worstShortfallYears, 1e-15);
});

test('frontier model supplies its spending scale through shared statistics', () => {
  const model = api().frontierModel([{ label: 'A', startingBalance: 1000, points: [{ value: .04, lifestyle: { completeCount: 1, worstFloor: 50, medianFloor: 100, failedCount: 0 } }] }]);
  close(model.yMax, 112);
});

test('frontier user override rejects off-increment values and strictly reversed bounds', () => {
  const plan = override => api().frontierPlan(STRATEGIES.fixedReal, { initialRate: .04 }, 'initialRate', override);
  assert.ok(plan({ from: .0205, to: .06, step: .001 }).error);
  assert.ok(plan({ from: .02, to: .06, step: .0005 }).error);
  assert.ok(plan({ from: .04 + Number.EPSILON, to: .04, step: .001 }).error);
});

test('every numeric default frontier value initializes its strategy successfully', () => {
  const options = { startingBalance:1_000_000, horizon:30, allocation:{stock:.6,bond:.4,bill:0},feeRate:0,taxRate:0 };
  for (const strategy of Object.values(STRATEGIES)) {
    const params = Object.fromEntries(strategy.paramSchema.map(field=>[field.key,field.default]));
    for (const field of strategy.paramSchema.filter(field=>field.type!=='select' && field.type!=='enum')) {
      const plan = api().frontierPlan(strategy,params,field.key);
      assert.equal(plan.error, undefined, `${strategy.id}/${field.key} has a valid default plan`);
      for (const value of plan.values) assert.doesNotThrow(()=>strategy.init({...params,[field.key]:value},options), `${strategy.id}/${field.key}=${value}`);
    }
  }
  const cutoff = api().frontierPlan(STRATEGIES.guytonKlinger,{},'preservationCutoffYears');
  assert.deepEqual(cutoff.values,Array.from({length:31},(_,index)=>index));
  assert.deepEqual(cutoff.range,{from:0,to:30,step:1});
  assert.deepEqual(api().frontierPlan(STRATEGIES.barbell,{},'reserveYears').values,Array.from({length:11},(_,index)=>index));
  assert.equal(api().frontierPlan(STRATEGIES.guytonKlinger,{},'guardrail').values.length,21);
  assert.equal(api().frontierPlan(STRATEGIES.guytonKlinger,{},'adjustment').values.length,11);
});

test('numeric fallback follows the field lattice without changing explicit rate grids', () => {
  const strategy = {paramSchema:[{key:'years',type:'number',default:15,min:0,max:100,step:1}]};
  const plan = api().frontierPlan(strategy,{},'years');
  assert.deepEqual(plan.range,{from:8,to:23,step:1});
  assert.deepEqual(plan.values,Array.from({length:16},(_,index)=>index+8));
  const shifted = {paramSchema:[{key:'count',type:'number',default:6,min:2,max:20,step:2}]};
  assert.deepEqual(api().frontierPlan(shifted,{},'count').range,{from:4,to:10,step:2});
  for (const override of [{from:.5},{to:22.5},{step:.5}]) assert.ok(api().frontierPlan(strategy,{},'years',override).error);
  const explicit = api().frontierPlan(STRATEGIES.guytonKlinger,{},'initialRate');
  assert.deepEqual(explicit.range,{from:.02,to:.08,step:.0025});
  assert.ok(explicit.values.includes(.0575));
});

test('a positive shortfall prevents null summary even when the earliest tolerance tie is zero', () => {
  const l = Views.summarizeSweep([entry(2000, profile([2], { baseline: 1e15 })), entry(2001, profile([1], { baseline: 1e15 }))], false, 2).lifestyle;
  assert.equal(l.worstShortfallStartYear, 2000);
  assert.equal(l.worstShortfallYears, 0);
});
