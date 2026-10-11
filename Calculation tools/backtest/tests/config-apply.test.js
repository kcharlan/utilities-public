'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { createConfigurationApplier } = require('../views.js');

/* The applier takes its collaborators as arguments, so the test simply builds a
   fake world and constructs it. This replaced a harness that sliced the function
   out of app.js by comment markers and ran it in a VM sandbox with a hand-built
   global environment. */
function loadApplyController() {
  const controls = {
    'strategy-select': { value: 'fixedReal' },
    'starting-balance': { value: '1000000' },
    'fee-rate': { value: '0' },
    'tax-rate': { value: '0' },
    'bill-series': { value: 'damodaran' },
    'allocation-stock': { value: '55' },
    'allocation-bond': { value: '45' },
    'allocation-bill': { value: '0' },
  };
  const strategies = {
    fixedReal: { id: 'fixedReal' },
    barbell: { id: 'barbell', initialAllocation() {} },
  };
  const state = {
    strategyId: 'fixedReal',
    strategyParams: { fixedReal: {}, barbell: {} },
    allocationManaged: false,
    manualAllocationValues: { stock: '60', bond: '40', bill: '0' },
  };
  const opened = [];

  function saveManualAllocation() {
    for (const asset of ['stock', 'bond', 'bill']) {
      state.manualAllocationValues[asset] = controls[`allocation-${asset}`].value;
    }
  }

  function updateAllocationMode() {
    const managed = Boolean(strategies[state.strategyId].initialAllocation);
    if (managed && !state.allocationManaged) saveManualAllocation();
    if (!managed && state.allocationManaged) {
      for (const asset of ['stock', 'bond', 'bill']) {
        controls[`allocation-${asset}`].value = state.manualAllocationValues[asset];
      }
    }
    state.allocationManaged = managed;
    if (managed) {
      controls['allocation-stock'].value = '70';
      controls['allocation-bond'].value = '15';
      controls['allocation-bill'].value = '15';
    }
  }

  const applier = createConfigurationApplier({
    getStrategies: () => strategies,
    state,
    byId: (id) => controls[id],
    rememberVisibleParams() {},
    saveManualAllocation,
    strategyManagesAllocation: (strategy) => Boolean(strategy && strategy.initialAllocation),
    renderSidebar() {},
    updateHeatmapMetricAvailability() {},
    updateAllocationMode,
    updateYearRange() {},
    openWindow(startYear, horizon) {
      opened.push({
        startYear,
        horizon,
        strategyId: state.strategyId,
        params: { ...state.strategyParams[state.strategyId] },
      });
      return opened[opened.length - 1];
    },
  });

  // `context` keeps the existing assertions readable without rewriting them.
  const context = {
    applyConfigurationToControls: applier.applyConfigurationToControls,
    openRenderedHeatmapWindow: applier.openRenderedHeatmapWindow,
    AppState: state,
    updateAllocationMode,
  };
  return { context, controls, opened };
}

test('applying a managed snapshot preserves outgoing manual weights for later restoration', () => {
  const { context, controls } = loadApplyController();
  const applied = context.applyConfigurationToControls({
    strategyId: 'barbell',
    params: { reserveYears: 3, reserveMix: 'split' },
    options: {
      startingBalance: 1_000_000,
      allocation: { stock: 0.70, bond: 0.15, bill: 0.15 },
      feeRate: 0,
      taxRate: 0,
    },
  });
  assert.equal(applied, true);
  assert.deepEqual({ ...context.AppState.manualAllocationValues }, { stock: '55', bond: '45', bill: '0' });
  assert.deepEqual(
    [controls['allocation-stock'].value, controls['allocation-bond'].value, controls['allocation-bill'].value],
    ['70', '15', '15'],
  );

  context.AppState.strategyId = 'fixedReal';
  context.updateAllocationMode();
  assert.deepEqual(
    [controls['allocation-stock'].value, controls['allocation-bond'].value, controls['allocation-bill'].value],
    ['55', '45', '0'],
  );
});

test('retained heatmap cells restore the immutable rendered configuration before opening', () => {
  const { context, controls, opened } = loadApplyController();
  const renderedConfiguration = Object.freeze({
    strategyId: 'fixedReal',
    params: Object.freeze({ initialRate: 0.04 }),
    options: Object.freeze({
      startingBalance: 750_000,
      allocation: Object.freeze({ stock: 0.5, bond: 0.5, bill: 0 }),
      feeRate: 0.002,
      taxRate: 0.1,
    }),
  });
  context.AppState.strategyId = 'barbell';
  context.AppState.strategyParams.barbell = { reserveYears: 4 };
  controls['strategy-select'].value = 'barbell';
  const openedWindow = context.openRenderedHeatmapWindow(renderedConfiguration, 1966, 30);
  assert.equal(context.AppState.strategyId, 'fixedReal');
  assert.equal(context.AppState.strategyParams.fixedReal.initialRate, 0.04);
  assert.equal(controls['starting-balance'].value, '750000');
  assert.deepEqual(openedWindow, { startYear: 1966, horizon: 30, strategyId: 'fixedReal', params: { initialRate: 0.04 } });
  assert.deepEqual(opened, [openedWindow]);
});


test('the applier refuses to construct without every collaborator', () => {
  // A missing dependency used to surface as a ReferenceError deep inside a render;
  // constructing explicitly makes it a loud failure at wiring time instead.
  assert.throws(() => createConfigurationApplier({}), /requires getStrategies/);
  assert.throws(() => createConfigurationApplier(null), /requires getStrategies/);
  const complete = {
    getStrategies: () => ({}), state: {}, byId: () => ({}), rememberVisibleParams() {},
    saveManualAllocation() {}, strategyManagesAllocation: () => false, renderSidebar() {},
    updateHeatmapMetricAvailability() {}, updateAllocationMode() {}, updateYearRange() {},
    openWindow: () => null,
  };
  for (const missing of Object.keys(complete)) {
    const partial = { ...complete };
    delete partial[missing];
    assert.throws(() => createConfigurationApplier(partial), new RegExp(`requires ${missing}`));
  }
  assert.equal(typeof createConfigurationApplier(complete).applyConfigurationToControls, 'function');
});

test('an unknown strategy id is rejected rather than half-applied', () => {
  const { context, controls } = loadApplyController();
  const before = controls['starting-balance'].value;
  const applied = context.applyConfigurationToControls({
    strategyId: 'doesNotExist',
    params: {},
    options: { startingBalance: 1, allocation: { stock: 1, bond: 0, bill: 0 }, feeRate: 0, taxRate: 0 },
  });
  assert.equal(applied, false);
  assert.equal(controls['starting-balance'].value, before, 'no control may be touched on rejection');
});

test('pinned configurations restore their bill series and legacy snapshots restore the default', () => {
  const { context, controls } = loadApplyController();
  const configuration = { strategyId: 'fixedReal', params: {}, options: {
    startingBalance: 1000, allocation: { stock: 1, bond: 0, bill: 0 }, feeRate: 0, taxRate: 0,
    billSeries: 'dtb3',
  } };
  assert.equal(context.applyConfigurationToControls(configuration), true);
  assert.equal(controls['bill-series'].value, 'dtb3');
  delete configuration.options.billSeries;
  context.applyConfigurationToControls(configuration);
  assert.equal(controls['bill-series'].value, 'damodaran');
});

test('configuration labels distinguish DTB3 while preserving default labels', () => {
  const { configurationLabelModel, sweepConfigurationKey } = require('../views.js');
  const configuration = { strategyId: 'fixedReal', params: {}, options: {
    startingBalance: 1000, allocation: { stock: 1, bond: 0, bill: 0 }, feeRate: 0, taxRate: 0,
  } };
  const original = configurationLabelModel(configuration, { name: 'Invented strategy' });
  const defaultSeries = { ...configuration, options: { ...configuration.options, billSeries: 'damodaran' } };
  assert.deepEqual(configurationLabelModel(defaultSeries, { name: 'Invented strategy' }), original);
  const daily = { ...configuration, options: { ...configuration.options, billSeries: 'dtb3' } };
  assert.match(configurationLabelModel(daily, { name: 'Invented strategy' }).details, /FRED DTB3/);
  assert.notEqual(sweepConfigurationKey(defaultSeries, 1, 2400, 'invented'), sweepConfigurationKey(daily, 1, 2400, 'invented'));
});

test('result caching separates otherwise identical configurations by T-bill series', () => {
  const { createLruCache, sweepConfigurationKey, marketGeneration } = require('../views.js');
  const engine = require('../engine.js');
  const data = { generated: '2400-01-01', sources: {}, rows: [{ year: 2400,
    stock_tr: 0, bond10_tr: 0, tbill_tr: 0, tbill_dtb3_tr: 0.1, cpi_change: 0, quality: 'invented' }] };
  const cache = createLruCache(2);
  const totals = [];
  for (const billSeries of ['damodaran', 'dtb3', 'damodaran']) {
    const configuration = { strategyId: 'fixedPercent', params: { rate: 0 }, options: {
      startingBalance: 1000, allocation: { stock: 0, bond: 0, bill: 1 }, feeRate: 0, taxRate: 0, billSeries,
    } };
    const key = sweepConfigurationKey(configuration, 1, 2400, marketGeneration(data.rows, data.generated));
    if (!cache.has(key)) cache.set(key, engine.simulate(data.rows, engine.STRATEGIES.fixedPercent,
      configuration.params, { ...configuration.options, horizon: 1 }));
    totals.push(cache.get(key).metrics.terminalWealthNominal);
  }
  assert.deepEqual(totals, [1000, 1100, 1000]);
});
