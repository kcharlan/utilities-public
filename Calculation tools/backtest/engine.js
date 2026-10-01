(function (root) {
  'use strict';

  const stats = (typeof module !== 'undefined' && module.exports)
    ? require('./stats.js')
    : root.MarketAtlasStats;
  if (!stats) throw new Error('engine.js requires stats.js to be loaded first');
  const { comparisonTolerance, spendingProfile } = stats;

  const ASSETS = ['stock', 'bond', 'bill'];
  const RETURN_COLUMNS = {
    stock: 'stock_tr',
    bond: 'bond10_tr',
    bill: 'tbill_tr',
  };
  const SUM_TOLERANCE = 1e-9;

  function assertFiniteNumber(value, name) {
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      throw new TypeError(`${name} must be a finite number`);
    }
  }

  function isPlainObject(value) {
    if (value === null || typeof value !== 'object') return false;
    const prototype = Object.getPrototypeOf(value);
    return prototype === Object.prototype || prototype === null;
  }

  function cloneAndFreeze(value, name, ancestors = new WeakSet()) {
    if (value === null || typeof value !== 'object') return value;
    if (ancestors.has(value)) throw new TypeError(`${name} contains a cyclic reference`);
    ancestors.add(value);
    try {
      if (Array.isArray(value)) {
        return Object.freeze(value.map((entry, index) => cloneAndFreeze(entry, `${name}[${index}]`, ancestors)));
      }
      if (!isPlainObject(value)) {
        throw new TypeError(`${name} must contain only plain objects, arrays, and primitive values`);
      }
      const copy = {};
      for (const [key, entry] of Object.entries(value)) {
        copy[key] = cloneAndFreeze(entry, `${name}.${key}`, ancestors);
      }
      return Object.freeze(copy);
    } finally {
      ancestors.delete(value);
    }
  }

  function validateAllocation(allocation, name = 'allocation') {
    if (!allocation || typeof allocation !== 'object') {
      throw new TypeError(`${name} must contain stock, bond, and bill weights`);
    }

    let sum = 0;
    for (const asset of ASSETS) {
      const weight = allocation[asset];
      assertFiniteNumber(weight, `${name}.${asset}`);
      if (weight < 0 || weight > 1) {
        throw new RangeError(`${name}.${asset} must be between 0 and 1`);
      }
      sum += weight;
    }

    if (Math.abs(sum - 1) > SUM_TOLERANCE) {
      throw new RangeError(`${name} weights must sum to 1`);
    }
  }

  function normalizeOptions(options, sequenceLength) {
    if (!options || typeof options !== 'object') {
      throw new TypeError('options are required');
    }

    const normalized = {
      startingBalance: options.startingBalance,
      allocation: options.allocation,
      feeRate: options.feeRate === undefined ? 0 : options.feeRate,
      taxRate: options.taxRate === undefined ? 0 : options.taxRate,
      rebalance: options.rebalance === undefined ? 'annual' : options.rebalance,
      horizon: options.horizon === undefined ? sequenceLength : options.horizon,
    };

    assertFiniteNumber(normalized.startingBalance, 'startingBalance');
    if (normalized.startingBalance <= 0) {
      throw new RangeError('startingBalance must be greater than 0');
    }
    validateAllocation(normalized.allocation);

    assertFiniteNumber(normalized.feeRate, 'feeRate');
    if (normalized.feeRate < 0 || normalized.feeRate > 1) {
      throw new RangeError('feeRate must be between 0 and 1');
    }

    assertFiniteNumber(normalized.taxRate, 'taxRate');
    if (normalized.taxRate < 0 || normalized.taxRate > 0.95) {
      throw new RangeError('taxRate must be between 0 and 0.95');
    }

    if (normalized.rebalance !== 'annual' && normalized.rebalance !== 'none') {
      throw new RangeError("rebalance must be 'annual' or 'none'");
    }
    if (!Number.isInteger(normalized.horizon) || normalized.horizon < 0) {
      throw new RangeError('horizon must be a non-negative integer');
    }

    normalized.allocation = cloneAndFreeze(normalized.allocation, 'options.allocation');
    return Object.freeze(normalized);
  }

  function copyBalances(balances) {
    return {
      stock: balances.stock,
      bond: balances.bond,
      bill: balances.bill,
    };
  }

  function sumBalances(balances) {
    const total = balances.stock + balances.bond + balances.bill;
    assertFiniteNumber(total, 'portfolio total after arithmetic');
    return total;
  }

  function assertFiniteBalances(balances, stage) {
    for (const asset of ASSETS) {
      assertFiniteNumber(balances[asset], `${asset} balance ${stage}`);
      if (balances[asset] < 0) throw new RangeError(`${asset} balance ${stage} must not be negative`);
    }
    sumBalances(balances);
  }

  function initialBalances(total, allocation) {
    const balances = {
      stock: total * allocation.stock,
      bond: total * allocation.bond,
      bill: total * allocation.bill,
    };
    assertFiniteBalances(balances, 'at initialization');
    return balances;
  }

  function validateDollarTargetPlan(plan, name) {
    if (!isPlainObject(plan)) throw new TypeError(`${name} must be a plain object`);
    if (!isPlainObject(plan.dollarTargets)) {
      throw new TypeError(`${name}.dollarTargets must be a plain object`);
    }
    for (const [asset, amount] of Object.entries(plan.dollarTargets)) {
      if (!ASSETS.includes(asset)) throw new RangeError(`${name}.dollarTargets contains unknown asset: ${asset}`);
      assertFiniteNumber(amount, `${name}.dollarTargets.${asset}`);
      if (amount < 0) throw new RangeError(`${name}.dollarTargets.${asset} must be non-negative`);
    }
    if (!ASSETS.includes(plan.remainderAsset)) {
      throw new RangeError(`${name}.remainderAsset must be stock, bond, or bill`);
    }
    if (Object.prototype.hasOwnProperty.call(plan.dollarTargets, plan.remainderAsset)) {
      throw new RangeError(`${name}.remainderAsset must not also be a dollar target`);
    }
    return plan;
  }

  function balancesFromDollarTargets(total, plan, name) {
    validateDollarTargetPlan(plan, name);
    const balances = { stock: 0, bond: 0, bill: 0 };
    const targetAssets = ASSETS.filter((asset) => (
      Object.prototype.hasOwnProperty.call(plan.dollarTargets, asset)
    ));
    const requestedTotal = targetAssets.reduce((sum, asset) => sum + plan.dollarTargets[asset], 0);
    assertFiniteNumber(requestedTotal, `${name}.dollarTargets total after arithmetic`);
    const scale = requestedTotal > total && requestedTotal > 0 ? total / requestedTotal : 1;
    let assigned = 0;
    for (let index = 0; index < targetAssets.length; index += 1) {
      const asset = targetAssets[index];
      const isLastCappedTarget = scale < 1 && index === targetAssets.length - 1;
      const amount = isLastCappedTarget
        ? total - assigned
        : plan.dollarTargets[asset] * scale;
      balances[asset] = amount;
      assigned += amount;
    }
    balances[plan.remainderAsset] = Math.max(0, total - assigned);
    assertFiniteBalances(balances, `after applying ${name}`);
    return balances;
  }

  function validateWithdrawalSource(source) {
    if (source === undefined || source === 'proportional') return 'proportional';
    if (!Array.isArray(source) || source.length === 0) {
      throw new TypeError("withdrawFrom must be 'proportional' or a non-empty asset priority array");
    }
    const seen = new Set();
    for (const asset of source) {
      if (!ASSETS.includes(asset)) throw new RangeError(`unknown withdrawal asset: ${asset}`);
      if (seen.has(asset)) throw new RangeError(`duplicate withdrawal asset: ${asset}`);
      seen.add(asset);
    }
    return source;
  }

  function floatingTolerance(value) {
    return Number.EPSILON * 8 * Math.max(Number.MIN_VALUE, Math.abs(value));
  }

  function withdraw(balances, requestedAmount, source) {
    const available = sumBalances(balances);
    const actualAmount = Math.min(requestedAmount, available);
    const byAsset = { stock: 0, bond: 0, bill: 0 };

    if (actualAmount === 0) return { actualAmount, byAsset };

    if (requestedAmount > available || (requestedAmount === available && source === 'proportional')) {
      for (const asset of ASSETS) {
        byAsset[asset] = balances[asset];
        balances[asset] = 0;
      }
      return { actualAmount, byAsset };
    }

    if (source === 'proportional') {
      const fundedAssets = ASSETS.filter((asset) => balances[asset] > 0);
      let assigned = 0;
      for (const asset of fundedAssets) {
        const amount = actualAmount * balances[asset] / available;
        byAsset[asset] = amount;
        balances[asset] -= amount;
        assigned += amount;
      }
      const residual = actualAmount - assigned;
      const residualAsset = fundedAssets.reduce((largest, asset) => (
        balances[asset] > balances[largest] ? asset : largest
      ));
      byAsset[residualAsset] += residual;
      balances[residualAsset] -= residual;
      assertFiniteBalances(balances, 'after withdrawal');
      return { actualAmount, byAsset };
    }

    let remaining = actualAmount;
    let lastFundedAsset = null;
    const residualTolerance = floatingTolerance(actualAmount);
    for (const asset of source) {
      if (remaining <= residualTolerance) break;
      const amount = remaining + residualTolerance >= balances[asset]
        ? balances[asset]
        : remaining;
      balances[asset] -= amount;
      byAsset[asset] = amount;
      remaining -= amount;
      if (amount > 0) lastFundedAsset = asset;
    }
    const assigned = ASSETS.reduce((sum, asset) => sum + byAsset[asset], 0);
    const residual = actualAmount - assigned;
    if (lastFundedAsset !== null && Math.abs(residual) <= residualTolerance) {
      byAsset[lastFundedAsset] += residual;
      balances[lastFundedAsset] -= residual;
      remaining = 0;
    }
    const exactTotal = requestedAmount === available;
    const sourceCouldNotFund = exactTotal
      ? sumBalances(balances) > residualTolerance
      : remaining > residualTolerance;
    if (sourceCouldNotFund) {
      throw new RangeError('withdrawFrom priority must include enough portfolio assets to fund the withdrawal');
    }
    assertFiniteBalances(balances, 'after withdrawal');
    return { actualAmount, byAsset };
  }

  function applyReturns(balances, yearRow) {
    const balanceBeforeReturns = sumBalances(balances);
    const rates = {};
    const amounts = {};
    for (const asset of ASSETS) {
      const rate = yearRow[RETURN_COLUMNS[asset]];
      rates[asset] = rate;
      const missing = rate === null || rate === undefined;
      if (missing && balances[asset] !== 0) {
        throw new TypeError(`${RETURN_COLUMNS[asset]} for year ${yearRow.year} must be finite for a funded asset`);
      }
      if (!missing) {
        assertFiniteNumber(rate, `${RETURN_COLUMNS[asset]} for year ${yearRow.year}; return must be finite and at least -1`);
        if (rate < -1) {
          throw new RangeError(`${RETURN_COLUMNS[asset]} for year ${yearRow.year} must be finite and at least -1`);
        }
      }
      const effectiveRate = missing ? 0 : rate;
      amounts[asset] = balances[asset] * effectiveRate;
      assertFiniteNumber(amounts[asset], `${asset} return amount after arithmetic`);
      balances[asset] += amounts[asset];
    }
    assertFiniteBalances(balances, 'after returns');
    const totalReturnAmount = ASSETS.reduce((total, asset) => total + amounts[asset], 0);
    assertFiniteNumber(totalReturnAmount, 'total portfolio return amount after arithmetic');
    const portfolioReturn = balanceBeforeReturns === 0
      ? 0
      : totalReturnAmount / balanceBeforeReturns;
    assertFiniteNumber(portfolioReturn, 'total portfolio return after arithmetic');
    return { rates, amounts, portfolioReturn };
  }

  function chargeFees(balances, feeRate) {
    const fees = {};
    for (const asset of ASSETS) {
      fees[asset] = balances[asset] * feeRate;
      assertFiniteNumber(fees[asset], `${asset} fee after arithmetic`);
      balances[asset] -= fees[asset];
    }
    assertFiniteBalances(balances, 'after fees');
    return fees;
  }

  function rebalance(balances, allocation) {
    validateAllocation(allocation, 'rebalanceTo');
    const total = sumBalances(balances);
    for (const asset of ASSETS) balances[asset] = total * allocation[asset];
    assertFiniteBalances(balances, 'after rebalancing');
  }

  function populationStandardDeviation(values) {
    if (values.length === 0) return 0;
    const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
    const variance = values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / values.length;
    return Math.sqrt(variance);
  }

  function buildMetrics(rows, requestedHorizon, sequenceLength, startingBalance, endingCpiIndex, failureYear, completedYears) {
    let peakRealBalance = startingBalance;
    let maxDrawdownReal = 0;
    const partial = failureYear === null && sequenceLength < requestedHorizon;
    const realSpending = rows.map(row => row.withdrawalReal);
    const spending = spendingProfile({
      realSpending,
      baseline: rows[0]?.requestedWithdrawalNominal ?? 0,
      horizon: requestedHorizon,
      failed: failureYear !== null,
      partial,
      startYear: rows[0]?.year ?? null,
    });
    const minRealSpending = spending.deliveredMin;
    const minRealSpendingYear = spending.deliveredMinIndex === null
      ? null
      : rows[spending.deliveredMinIndex].year;

    for (const row of rows) {
      if (!row.failed) {
        peakRealBalance = Math.max(peakRealBalance, row.endTotalReal);
        const drawdown = peakRealBalance === 0 ? 0 : 1 - row.endTotalReal / peakRealBalance;
        maxDrawdownReal = Math.max(maxDrawdownReal, drawdown);
      } else {
        maxDrawdownReal = 1;
      }
    }

    const spendingChanges = [];
    let undefinedSpendingChange = false;
    for (let index = 1; index < realSpending.length; index += 1) {
      const prior = realSpending[index - 1];
      const current = realSpending[index];
      if (prior === 0) {
        undefinedSpendingChange = true;
      } else {
        spendingChanges.push(current / prior - 1);
      }
    }

    const terminalWealthNominal = rows.length === 0 ? startingBalance : rows[rows.length - 1].endTotal;
    const terminalWealthReal = terminalWealthNominal / endingCpiIndex;
    const spendingVolatility = undefinedSpendingChange
      ? null
      : populationStandardDeviation(spendingChanges);
    const totalWithdrawnReal = realSpending.reduce((sum, value) => sum + value, 0);
    for (const [name, value] of Object.entries({
      terminalWealthNominal,
      terminalWealthReal,
      maxDrawdownReal,
      totalWithdrawnReal,
    })) {
      assertFiniteNumber(value, `metric ${name}`);
    }
    if (spendingVolatility !== null) assertFiniteNumber(spendingVolatility, 'metric spendingVolatility');

    return {
      success: failureYear === null,
      failureYear,
      yearsCompleted: completedYears,
      horizon: requestedHorizon,
      partial,
      terminalWealthNominal,
      terminalWealthReal,
      maxDrawdownReal,
      minRealSpending,
      minRealSpendingYear,
      spending,
      spendingVolatility,
      totalWithdrawnReal,
    };
  }

  function validateDecision(decision) {
    if (!isPlainObject(decision)) throw new TypeError('strategy decision must be a plain object');
    if (decision.notes !== undefined && typeof decision.notes !== 'string') {
      throw new TypeError('strategy decision notes must be a string');
    }
    if (decision.noteWithdrawalSources !== undefined
      && typeof decision.noteWithdrawalSources !== 'boolean') {
      throw new TypeError('noteWithdrawalSources must be a boolean');
    }
    if (decision.rebalanceNote !== undefined && typeof decision.rebalanceNote !== 'string') {
      throw new TypeError('rebalanceNote must be a string');
    }
    if (decision.rebalanceTo !== undefined && decision.rebalanceTo !== null) {
      if (!isPlainObject(decision.rebalanceTo)) {
        throw new TypeError('rebalanceTo must be undefined, null, or a valid allocation object');
      }
      validateAllocation(decision.rebalanceTo, 'rebalanceTo');
    }
    if (decision.rebalanceToDollars !== undefined && decision.rebalanceToDollars !== null) {
      validateDollarTargetPlan(decision.rebalanceToDollars, 'rebalanceToDollars');
    }
    if (decision.rebalanceTo !== undefined && decision.rebalanceTo !== null
      && decision.rebalanceToDollars !== undefined && decision.rebalanceToDollars !== null) {
      throw new RangeError('strategy decision may specify only one rebalance method');
    }
    return decision;
  }

  function withdrawalFundingNote(byAsset, source) {
    const labels = { stock: 'stock', bond: 'bonds', bill: 'bills' };
    const sourceOrder = source === 'proportional'
      ? ASSETS
      : [...source, ...ASSETS.filter((asset) => !source.includes(asset))];
    const funded = sourceOrder
      .filter((asset) => byAsset[asset] > 0)
      .map((asset) => labels[asset]);
    if (funded.length === 0) return '';
    if (funded.length === 1) return `withdrawal funded by ${funded[0]}`;
    if (funded.length === 2) return `withdrawal funded by ${funded[0]} and ${funded[1]}`;
    return `withdrawal funded by ${funded[0]}, ${funded[1]}, and ${funded[2]}`;
  }

  function normalizeSkippedReturn(value) {
    return typeof value === 'number' && Number.isFinite(value) && value >= -1 ? value : null;
  }

  function resolveStrategyAssets(strategy, params) {
    if (!strategy || typeof strategy !== 'object') {
      throw new TypeError('strategy metadata is required');
    }

    let assets;
    if (typeof strategy.resolveAssets === 'function') {
      assets = strategy.resolveAssets(params);
    } else if (typeof strategy.assets === 'function') {
      assets = strategy.assets(params);
    } else {
      assets = strategy.assets;
    }

    if (!Array.isArray(assets) || assets.length === 0) {
      throw new TypeError('strategy assets must resolve to a non-empty array');
    }
    const seen = new Set();
    for (const asset of assets) {
      if (!ASSETS.includes(asset)) throw new RangeError(`unknown strategy asset: ${asset}`);
      if (seen.has(asset)) throw new RangeError(`duplicate strategy asset: ${asset}`);
      seen.add(asset);
    }
    return assets.slice();
  }

  function longestContiguousRange(years) {
    let bestFirst = null;
    let bestLast = null;
    let currentFirst = null;
    let currentLast = null;

    for (const year of years) {
      if (currentFirst === null || year !== currentLast + 1) currentFirst = year;
      currentLast = year;
      const currentLength = currentLast - currentFirst + 1;
      const bestLength = bestFirst === null ? 0 : bestLast - bestFirst + 1;
      if (currentLength > bestLength) {
        bestFirst = currentFirst;
        bestLast = currentLast;
      }
    }

    return { first: bestFirst, last: bestLast };
  }

  function availableYearRange(strategy, params = {}, rows, options = {}) {
    if (!isPlainObject(params)) throw new TypeError('params must be a plain object');
    if (!Array.isArray(rows)) throw new TypeError('rows must be an array');
    if (!isPlainObject(options)) throw new TypeError('options must be a plain object');

    const runParams = cloneAndFreeze(params, 'params');
    const rangeOptions = cloneAndFreeze(options, 'options');
    let activeAssets = resolveStrategyAssets(strategy, runParams);
    const allocation = rangeOptions.allocation === undefined
      ? runParams.allocation
      : rangeOptions.allocation;
    if (allocation !== undefined) {
      validateAllocation(allocation);
      if (typeof strategy.initialAllocation !== 'function') {
        const allocatedAssets = ASSETS.filter((asset) => allocation[asset] > 0);
        const hasDynamicAssets = typeof strategy.resolveAssets === 'function'
          || typeof strategy.assets === 'function';
        const usedAssets = hasDynamicAssets
          ? new Set([...allocatedAssets, ...activeAssets])
          : new Set(allocatedAssets);
        activeAssets = ASSETS.filter((asset) => usedAssets.has(asset));
      }
    }

    const seenYears = new Set();
    const usableYears = [];
    const unavailableAssets = new Set();
    for (let index = 0; index < rows.length; index += 1) {
      const row = rows[index];
      if (!isPlainObject(row)) throw new TypeError(`rows[${index}] must be a plain object`);
      if (!Number.isSafeInteger(row.year)) throw new TypeError(`rows[${index}].year must be a safe integer`);
      if (seenYears.has(row.year)) throw new RangeError(`rows contain duplicate year ${row.year}`);
      seenYears.add(row.year);

      const cpiChange = row.cpi_change;
      let usable = typeof cpiChange === 'number' && Number.isFinite(cpiChange) && cpiChange > -1;
      for (const asset of activeAssets) {
        const assetReturn = row[RETURN_COLUMNS[asset]];
        if (typeof assetReturn !== 'number' || !Number.isFinite(assetReturn) || assetReturn < -1) {
          unavailableAssets.add(asset);
          usable = false;
        }
      }
      if (usable) usableYears.push(row.year);
    }

    usableYears.sort((left, right) => left - right);
    const range = longestContiguousRange(usableYears);
    return {
      ...range,
      excludedAssets: ASSETS.filter((asset) => unavailableAssets.has(asset)),
    };
  }

  function validatePositiveSafeInteger(value, name) {
    if (!Number.isSafeInteger(value) || value <= 0) {
      throw new RangeError(`${name} must be a positive safe integer`);
    }
  }

  function prepareSweep(rows, strategy, params, options, horizon) {
    validatePositiveSafeInteger(horizon, 'horizon');
    if (!isPlainObject(options)) throw new TypeError('options must be a plain object');
    const runOptions = normalizeOptions({ ...options, horizon }, horizon);
    const range = availableYearRange(strategy, params, rows, runOptions);
    if (range.first === null) return { range, rowsByYear: new Map(), runOptions };
    return {
      range,
      rowsByYear: new Map(rows.map((row) => [row.year, row])),
      runOptions,
    };
  }

  function sequenceFromStart(rowsByYear, startYear, lastYear, horizon) {
    const sequence = [];
    const endYear = Math.min(lastYear, startYear + horizon - 1);
    for (let year = startYear; year <= endYear; year += 1) {
      sequence.push(rowsByYear.get(year));
    }
    return sequence;
  }

  function sweepStartYears(rows, horizon, strategy, params = {}, options) {
    const { range, rowsByYear, runOptions } = prepareSweep(
      rows,
      strategy,
      params,
      options,
      horizon,
    );
    if (range.first === null) return [];

    const results = [];
    for (let startYear = range.first; startYear <= range.last; startYear += 1) {
      const sequence = sequenceFromStart(rowsByYear, startYear, range.last, horizon);
      const metrics = simulate(sequence, strategy, params, runOptions).metrics;
      results.push({ startYear, metrics, partial: metrics.partial });
    }
    return results;
  }

  function sweepGrid(rows, horizons, strategy, params = {}, options) {
    if (!Array.isArray(horizons) || horizons.length === 0) {
      throw new RangeError('horizons must be a non-empty array');
    }
    const seen = new Set();
    for (const horizon of horizons) {
      validatePositiveSafeInteger(horizon, 'horizon');
      if (seen.has(horizon)) throw new RangeError(`horizons contain duplicate horizon ${horizon}`);
      seen.add(horizon);
    }
    const sortedHorizons = horizons.slice().sort((left, right) => left - right);
    const maximumHorizon = sortedHorizons[sortedHorizons.length - 1];
    const { range, rowsByYear, runOptions } = prepareSweep(
      rows,
      strategy,
      params,
      options,
      maximumHorizon,
    );
    if (range.first === null) return [];

    const results = [];
    for (let startYear = range.first; startYear <= range.last; startYear += 1) {
      for (const horizon of sortedHorizons) {
        const sequence = sequenceFromStart(rowsByYear, startYear, range.last, horizon);
        const metrics = simulate(
          sequence,
          strategy,
          params,
          { ...runOptions, horizon },
        ).metrics;
        results.push({ startYear, horizon, metrics, partial: metrics.partial });
      }
    }
    return results;
  }

  function validateMaxSafeRateMetadata(strategy) {
    if (!strategy || typeof strategy !== 'object') {
      throw new TypeError('strategy metadata is required');
    }
    if (typeof strategy.supportsMaxSafeRate !== 'boolean') {
      throw new TypeError('strategy supportsMaxSafeRate must be a boolean');
    }
    if (!strategy.supportsMaxSafeRate) {
      if (strategy.rateParamKey !== undefined && strategy.rateParamKey !== null) {
        throw new TypeError('unsupported max-safe-rate strategy must not define rateParamKey');
      }
      if (strategy.safeRateSearch !== undefined && strategy.safeRateSearch !== null) {
        throw new TypeError('unsupported max-safe-rate strategy must not define safeRateSearch');
      }
      return null;
    }

    const rateParamKey = strategy.rateParamKey;
    if (typeof rateParamKey !== 'string'
      || rateParamKey.length === 0
      || rateParamKey !== rateParamKey.trim()) {
      throw new TypeError('strategy rateParamKey must be a trimmed non-empty string');
    }
    if (!Array.isArray(strategy.paramSchema)
      || !strategy.paramSchema.some((field) => isPlainObject(field) && field.key === rateParamKey)) {
      throw new TypeError('strategy rateParamKey must match a paramSchema key');
    }
    if (strategy.safeRateSearch !== 'monotonic' && strategy.safeRateSearch !== 'adaptive') {
      throw new TypeError("strategy safeRateSearch must be 'monotonic' or 'adaptive'");
    }
    return { rateParamKey, safeRateSearch: strategy.safeRateSearch };
  }

  function normalizeSafeRateSearchOptions(searchOptions) {
    if (!isPlainObject(searchOptions)) {
      throw new TypeError('searchOptions must be a plain object');
    }
    const adaptiveStep = searchOptions.adaptiveStep === undefined
      ? 0.0001
      : searchOptions.adaptiveStep;
    if (typeof adaptiveStep !== 'number'
      || !Number.isFinite(adaptiveStep)
      || adaptiveStep < 0.0001
      || adaptiveStep > 0.01) {
      throw new RangeError('adaptiveStep must be a finite number between 0.0001 and 0.01');
    }
    const intervalCount = 0.20 / adaptiveStep;
    const roundedIntervalCount = Math.round(intervalCount);
    const intervalTolerance = Number.EPSILON * 8 * Math.max(1, Math.abs(intervalCount));
    if (Math.abs(intervalCount - roundedIntervalCount) > intervalTolerance) {
      throw new RangeError('adaptiveStep must divide 0.20 into an integral number of intervals');
    }
    return Object.freeze({ adaptiveStep, intervalCount: roundedIntervalCount });
  }

  function maxSafeRate(yearSequence, strategy, params = {}, options, searchOptions = {}) {
    const metadata = validateMaxSafeRateMetadata(strategy);
    const normalizedSearch = normalizeSafeRateSearchOptions(searchOptions);
    if (metadata === null) return null;
    if (!Array.isArray(yearSequence)) throw new TypeError('yearSequence must be an array');
    if (!isPlainObject(params)) throw new TypeError('params must be a plain object');
    const runOptions = normalizeOptions(options, yearSequence.length);
    if (runOptions.horizon === 0 || runOptions.horizon > yearSequence.length) return null;

    function survives(rate) {
      const candidateParams = { ...params, [metadata.rateParamKey]: rate };
      const metrics = runSimulation(yearSequence, strategy, candidateParams, runOptions, 'solvency').metrics;
      return metrics.success && !metrics.partial;
    }

    if (survives(0.20)) return 0.20;

    if (metadata.safeRateSearch === 'adaptive') {
      for (let interval = normalizedSearch.intervalCount - 1; interval >= 0; interval -= 1) {
        const sampledRate = interval * normalizedSearch.adaptiveStep;
        if (!survives(sampledRate)) continue;

        let survivingRate = sampledRate;
        let failingRate = (interval + 1) * normalizedSearch.adaptiveStep;
        for (let iteration = 0; iteration < 40; iteration += 1) {
          const candidateRate = (survivingRate + failingRate) / 2;
          if (survives(candidateRate)) survivingRate = candidateRate;
          else failingRate = candidateRate;
        }
        return survivingRate;
      }
      return null;
    }

    if (!survives(0)) return null;
    let survivingRate = 0;
    let failingRate = 0.20;
    for (let iteration = 0; iteration < 40; iteration += 1) {
      const candidateRate = (survivingRate + failingRate) / 2;
      if (survives(candidateRate)) survivingRate = candidateRate;
      else failingRate = candidateRate;
    }
    return survivingRate;
  }

  function initializeStrategyPortfolio(strategy, params, options, sequenceLength) {
    if (!strategy || typeof strategy.init !== 'function') {
      throw new TypeError('strategy must provide init()');
    }
    if (!isPlainObject(params)) throw new TypeError('params must be a plain object');
    const runOptions = normalizeOptions(options, sequenceLength);
    const runParams = cloneAndFreeze(params, 'params');
    const state = strategy.init(runParams, runOptions);
    let balances;
    if (typeof strategy.initialAllocation === 'function') {
      const initialContext = Object.freeze({
        startingBalance: runOptions.startingBalance,
        options: runOptions,
        params: runParams,
      });
      const initialPlan = strategy.initialAllocation(state, initialContext);
      if (isPlainObject(initialPlan) && initialPlan.dollarTargets !== undefined) {
        balances = balancesFromDollarTargets(
          runOptions.startingBalance,
          initialPlan,
          'initialAllocation',
        );
      } else {
        validateAllocation(initialPlan, 'initialAllocation');
        balances = initialBalances(runOptions.startingBalance, initialPlan);
      }
    } else {
      balances = initialBalances(runOptions.startingBalance, runOptions.allocation);
    }
    return { runOptions, runParams, state, balances };
  }

  function resolveInitialAllocation(strategy, params = {}, options) {
    const initialized = initializeStrategyPortfolio(strategy, params, options, 0);
    const total = initialized.runOptions.startingBalance;
    return {
      stock: initialized.balances.stock / total,
      bond: initialized.balances.bond / total,
      bill: initialized.balances.bill / total,
    };
  }

  function simulate(yearSequence, strategy, params = {}, options) {
    return runSimulation(yearSequence, strategy, params, options, 'full');
  }

  function runSimulation(yearSequence, strategy, params, options, detail) {
    if (!Array.isArray(yearSequence)) throw new TypeError('yearSequence must be an array');
    if (!strategy || typeof strategy.init !== 'function' || typeof strategy.step !== 'function') {
      throw new TypeError('strategy must provide init() and step()');
    }

    const initialized = initializeStrategyPortfolio(strategy, params, options, yearSequence.length);
    const { runOptions, runParams, state } = initialized;
    let { balances } = initialized;
    const sequence = yearSequence.slice(0, runOptions.horizon);
    const rows = [];
    let cpiIndex = 1;
    let failureYear = null;
    let completedYears = 0;

    for (let index = 0; index < sequence.length; index += 1) {
      const yearRow = cloneAndFreeze(sequence[index], `yearSequence[${index}]`);
      const startBalances = copyBalances(balances);
      const startTotal = sumBalances(startBalances);
      const context = Object.freeze({
        balances: Object.freeze(copyBalances(startBalances)),
        total: startTotal,
        yearRow,
        index,
        cpiIndex,
        horizon: runOptions.horizon,
        yearsRemaining: runOptions.horizon - index,
        options: runOptions,
        params: runParams,
      });
      const decision = validateDecision(strategy.step(state, context));

      const requestedWithdrawal = decision.withdrawal === undefined ? 0 : decision.withdrawal;
      assertFiniteNumber(requestedWithdrawal, 'strategy withdrawal');
      if (requestedWithdrawal < 0) throw new RangeError('strategy withdrawal must not be negative');
      const requestedGrossWithdrawal = requestedWithdrawal / (1 - runOptions.taxRate);
      assertFiniteNumber(requestedGrossWithdrawal, 'gross withdrawal after tax arithmetic');
      const source = validateWithdrawalSource(decision.withdrawFrom);
      const withdrawalResult = withdraw(balances, requestedGrossWithdrawal, source);
      const failed = requestedGrossWithdrawal > startTotal;
      const actualWithdrawalNominal = withdrawalResult.actualAmount * (1 - runOptions.taxRate);
      const taxPaid = withdrawalResult.actualAmount - actualWithdrawalNominal;
      assertFiniteNumber(actualWithdrawalNominal, 'nominal withdrawal after arithmetic');
      assertFiniteNumber(taxPaid, 'tax paid after arithmetic');
      const withdrawalReal = actualWithdrawalNominal / cpiIndex;
      assertFiniteNumber(withdrawalReal, 'real withdrawal after arithmetic');
      const strategyNotes = decision.notes === undefined ? '' : decision.notes;
      const sourceNotes = decision.noteWithdrawalSources
        ? withdrawalFundingNote(withdrawalResult.byAsset, source)
        : '';

      const baseRow = {
        year: yearRow.year,
        quality: yearRow.quality,
        cpiIndex,
        startBalances,
        startTotal,
        requestedWithdrawalNominal: requestedWithdrawal,
        requestedGrossWithdrawal,
        withdrawalNominal: actualWithdrawalNominal,
        withdrawalReal,
        grossWithdrawal: withdrawalResult.actualAmount,
        taxPaid,
        withdrawalsByAsset: withdrawalResult.byAsset,
        notes: [strategyNotes, sourceNotes].filter(Boolean).join('; '),
        failed,
      };

      if (failed) {
        failureYear = yearRow.year;
        const skippedReturns = {
          stock: normalizeSkippedReturn(yearRow.stock_tr),
          bond: normalizeSkippedReturn(yearRow.bond10_tr),
          bill: normalizeSkippedReturn(yearRow.tbill_tr),
        };
        rows.push({
          ...baseRow,
          returns: skippedReturns,
          returnRates: skippedReturns,
          returnAmounts: { stock: 0, bond: 0, bill: 0 },
          portfolioReturn: null,
          balancesAfterReturns: copyBalances(balances),
          fees: { stock: 0, bond: 0, bill: 0 },
          endBalances: copyBalances(balances),
          endTotal: 0,
          endTotalReal: 0,
          endCpiIndex: null,
        });
        break;
      }

      const returnResult = applyReturns(balances, yearRow);
      const balancesAfterReturns = copyBalances(balances);
      const fees = chargeFees(balances, runOptions.feeRate);
      let explicitRebalanceExecuted = false;
      if (decision.rebalanceToDollars !== undefined && decision.rebalanceToDollars !== null) {
        balances = balancesFromDollarTargets(
          sumBalances(balances),
          decision.rebalanceToDollars,
          'rebalanceToDollars',
        );
        explicitRebalanceExecuted = true;
      } else if (decision.rebalanceTo !== undefined && decision.rebalanceTo !== null) {
        rebalance(balances, decision.rebalanceTo);
        explicitRebalanceExecuted = true;
      } else if (decision.rebalanceTo === undefined && runOptions.rebalance === 'annual') {
        rebalance(balances, runOptions.allocation);
      }
      if (explicitRebalanceExecuted && decision.rebalanceNote) {
        baseRow.notes = [baseRow.notes, decision.rebalanceNote].filter(Boolean).join('; ');
      }

      const endBalances = copyBalances(balances);
      const endTotal = sumBalances(endBalances);
      assertFiniteNumber(yearRow.cpi_change, `cpi_change for year ${yearRow.year}`);
      if (yearRow.cpi_change < -1) {
        throw new RangeError(`cpi_change for year ${yearRow.year} must be at least -1`);
      }
      const endingYearCpiIndex = cpiIndex * (1 + yearRow.cpi_change);
      assertFiniteNumber(endingYearCpiIndex, `ending CPI index for year ${yearRow.year}`);
      if (endingYearCpiIndex <= 0) throw new RangeError(`CPI index must remain greater than 0 in year ${yearRow.year}`);
      const endTotalReal = endTotal / endingYearCpiIndex;
      assertFiniteNumber(endTotalReal, `real ending total for year ${yearRow.year}`);
      const completedRow = {
        ...baseRow,
        returns: returnResult.rates,
        returnRates: returnResult.rates,
        returnAmounts: returnResult.amounts,
        portfolioReturn: returnResult.portfolioReturn,
        balancesAfterReturns,
        fees,
        endBalances,
        endTotal,
        endTotalReal,
        endCpiIndex: endingYearCpiIndex,
      };
      rows.push(completedRow);
      if (typeof strategy.afterYear === 'function') {
        strategy.afterYear(state, cloneAndFreeze(completedRow, 'strategy afterYear row'), context);
      }
      cpiIndex = endingYearCpiIndex;
      completedYears += 1;
    }

    if (detail === 'solvency') {
      return {
        rows: null,
        metrics: {
          success: failureYear === null,
          partial: failureYear === null && yearSequence.length < runOptions.horizon,
        },
      };
    }

    return {
      rows,
      metrics: buildMetrics(
        rows,
        runOptions.horizon,
        yearSequence.length,
        runOptions.startingBalance,
        cpiIndex,
        failureYear,
        completedYears,
      ),
    };
  }

  function fixedRealWithdrawal(state, cpiIndex) {
    return state.baseWithdrawal * cpiIndex;
  }

  function initializeFixedReal(params, options) {
    const initialRate = params.initialRate === undefined ? 0.04 : params.initialRate;
    assertFiniteNumber(initialRate, 'initialRate');
    if (initialRate < 0 || initialRate > 0.20) {
      throw new RangeError('initialRate must be between 0 and 0.2');
    }
    return {
      initialRate,
      baseWithdrawal: initialRate * options.startingBalance,
    };
  }

  const fixedReal = {
    id: 'fixedReal',
    canDeplete: true,
    frontierParamKey: 'initialRate',
    name: 'Fixed real (4% rule)',
    assets: ['stock', 'bond', 'bill'],
    supportsMaxSafeRate: true,
    rateParamKey: 'initialRate',
    safeRateSearch: 'monotonic',
    paramSchema: [{
      key: 'initialRate',
      label: 'Initial withdrawal rate',
      type: 'percent',
      default: 0.04,
      min: 0,
      max: 0.20,
      step: 0.001,
      hint: 'First-year spending as a percentage of the starting portfolio.',
      frontierRange: Object.freeze({ from: 0.02, to: 0.08, step: 0.0025 }),
    }],
    init(params, options) {
      return initializeFixedReal(params, options);
    },
    step(state, ctx) {
      return {
        withdrawal: fixedRealWithdrawal(state, ctx.cpiIndex),
        withdrawFrom: 'proportional',
        rebalanceTo: undefined,
        notes: '',
      };
    },
  };

  function validateBarbellReserveConfig(params) {
    const reserveYears = params.reserveYears === undefined ? 3 : params.reserveYears;
    const reserveMix = params.reserveMix === undefined ? 'bills' : params.reserveMix;
    assertFiniteNumber(reserveYears, 'reserveYears');
    if (reserveYears < 0 || reserveYears > 100) {
      throw new RangeError('reserveYears must be between 0 and 100');
    }
    if (!['bills', 'bonds', 'split'].includes(reserveMix)) {
      throw new RangeError("reserveMix must be 'bills', 'bonds', or 'split'");
    }
    return { reserveYears, reserveMix };
  }

  function barbellReserveAssets(reserveMix) {
    if (reserveMix === 'bills') return ['bill'];
    if (reserveMix === 'bonds') return ['bond'];
    return ['bill', 'bond'];
  }

  function barbellDollarTargets(reserveTarget, reserveMix) {
    let dollarTargets;
    if (reserveMix === 'bills') dollarTargets = { bill: reserveTarget };
    else if (reserveMix === 'bonds') dollarTargets = { bond: reserveTarget };
    else dollarTargets = { bond: reserveTarget / 2, bill: reserveTarget / 2 };
    return { dollarTargets, remainderAsset: 'stock' };
  }

  const barbell = {
    id: 'barbell',
    canDeplete: true,
    frontierParamKey: 'initialRate',
    name: 'Barbell reserve',
    supportsMaxSafeRate: true,
    rateParamKey: 'initialRate',
    safeRateSearch: 'adaptive',
    paramSchema: [
      {
        key: 'initialRate',
        label: 'Initial withdrawal rate',
        type: 'percent',
        default: 0.04,
        min: 0,
        max: 0.20,
        step: 0.001,
        hint: 'First-year spending as a percentage of the starting portfolio.',
        frontierRange: Object.freeze({ from: 0.02, to: 0.08, step: 0.0025 }),
      },
      {
        key: 'reserveYears',
        frontierRange: Object.freeze({ from: 0, to: 10, step: 1 }),
        label: 'Reserve years',
        type: 'number',
        default: 3,
        min: 0,
        max: 100,
        step: 1,
        hint: 'Years of current nominal spending targeted in the reserve sleeves.',
      },
      {
        key: 'reserveMix',
        label: 'Reserve mix',
        type: 'select',
        default: 'bills',
        options: ['bills', 'bonds', 'split'],
        hint: 'Hold the reserve in bills, bonds, or a 50/50 split.',
      },
      {
        key: 'spendRule',
        label: 'Spending source',
        type: 'select',
        default: 'reserve_after_down',
        options: ['reserve_after_down', 'reserve_first'],
        hint: 'Use reserves after a down stock year or before stocks every year.',
      },
      {
        key: 'refillRule',
        label: 'Reserve refill',
        type: 'select',
        default: 'after_up_years',
        options: ['after_up_years', 'annual'],
        hint: 'Refill after positive stock years or after every completed year.',
      },
    ],
    resolveAssets(params) {
      const { reserveYears, reserveMix } = validateBarbellReserveConfig(params);
      return reserveYears === 0
        ? ['stock']
        : ASSETS.filter((asset) => asset === 'stock' || barbellReserveAssets(reserveMix).includes(asset));
    },
    init(params, options) {
      const fixedRealState = initializeFixedReal(params, options);
      const { reserveYears, reserveMix } = validateBarbellReserveConfig(params);
      const spendRule = params.spendRule === undefined ? 'reserve_after_down' : params.spendRule;
      const refillRule = params.refillRule === undefined ? 'after_up_years' : params.refillRule;
      if (!['reserve_after_down', 'reserve_first'].includes(spendRule)) {
        throw new RangeError("spendRule must be 'reserve_after_down' or 'reserve_first'");
      }
      if (!['after_up_years', 'annual'].includes(refillRule)) {
        throw new RangeError("refillRule must be 'after_up_years' or 'annual'");
      }
      return {
        ...fixedRealState,
        reserveYears,
        reserveMix,
        spendRule,
        refillRule,
        priorStockReturn: null,
      };
    },
    initialAllocation(state) {
      return barbellDollarTargets(
        state.reserveYears * state.baseWithdrawal,
        state.reserveMix,
      );
    },
    step(state, ctx) {
      const withdrawal = fixedRealWithdrawal(state, ctx.cpiIndex);
      if (state.reserveYears === 0) {
        return {
          withdrawal,
          withdrawFrom: ['stock'],
          rebalanceTo: null,
          notes: '',
        };
      }
      const reserveAssets = barbellReserveAssets(state.reserveMix);
      const useReserveFirst = state.spendRule === 'reserve_first'
        || (state.spendRule === 'reserve_after_down' && state.priorStockReturn < 0);
      const withdrawFrom = useReserveFirst
        ? [...reserveAssets, 'stock']
        : ['stock', ...reserveAssets];
      const notes = [];

      let rebalanceTo = null;
      let rebalanceToDollars;
      let rebalanceNote;
      if (ctx.index === 0) {
        notes.push('initial reserve established');
      } else {
        const shouldRefill = state.refillRule === 'annual'
          || (state.refillRule === 'after_up_years' && state.priorStockReturn > 0);
        if (shouldRefill) {
          rebalanceTo = undefined;
          rebalanceToDollars = barbellDollarTargets(
            state.reserveYears * withdrawal,
            state.reserveMix,
          );
          rebalanceNote = 'reserve refilled';
        }
      }

      return {
        withdrawal,
        withdrawFrom,
        rebalanceTo,
        rebalanceToDollars,
        rebalanceNote,
        noteWithdrawalSources: true,
        notes: notes.join('; '),
      };
    },
    afterYear(state, row) {
      state.priorStockReturn = row.returnRates.stock;
    },
  };

  const fixedPercent = {
    id: 'fixedPercent',
    canDeplete: false,
    frontierParamKey: 'rate',
    name: 'Fixed percentage',
    assets: ['stock', 'bond', 'bill'],
    supportsMaxSafeRate: false,
    rateParamKey: null,
    safeRateSearch: null,
    paramSchema: [{
      key: 'rate',
      label: 'Annual distribution rate',
      type: 'percent',
      default: 0.04,
      min: 0,
      max: 0.20,
      step: 0.001,
      hint: 'Gross portfolio distribution each year; after-tax spending is net of the configured tax.',
      frontierRange: Object.freeze({ from: 0.02, to: 0.08, step: 0.0025 }),
    }],
    init(params) {
      const rate = params.rate === undefined ? 0.04 : params.rate;
      assertFiniteNumber(rate, 'rate');
      if (rate < 0 || rate > 0.20) {
        throw new RangeError('rate must be between 0 and 0.2');
      }
      return { rate };
    },
    step(state, ctx) {
      return {
        withdrawal: state.rate * ctx.total * (1 - ctx.options.taxRate),
        withdrawFrom: 'proportional',
        rebalanceTo: undefined,
        notes: '',
      };
    },
  };

  function formatAdjustmentPercent(adjustment) {
    const percent = adjustment * 100;
    if (percent === 0) return 0;
    return Number(percent.toPrecision(12));
  }

  function meaningfullyGreaterThan(left, right) {
    return left - right > comparisonTolerance(left, right);
  }

  function meaningfullyLessThan(left, right) {
    return right - left > comparisonTolerance(left, right);
  }

  const guytonKlinger = {
    id: 'guytonKlinger',
    canDeplete: true,
    frontierParamKey: 'initialRate',
    name: 'Guyton-Klinger guardrails',
    assets: ['stock', 'bond', 'bill'],
    supportsMaxSafeRate: true,
    rateParamKey: 'initialRate',
    safeRateSearch: 'adaptive',
    paramSchema: [
      {
        key: 'initialRate',
        label: 'Initial withdrawal rate',
        type: 'percent',
        default: 0.04,
        min: 0,
        max: 0.20,
        step: 0.001,
        hint: 'First-year spending as a percentage of the starting portfolio.',
        frontierRange: Object.freeze({ from: 0.02, to: 0.08, step: 0.0025 }),
      },
      {
        key: 'guardrail',
        label: 'Guardrail band',
        type: 'percent',
        default: 0.20,
        min: 0,
        max: 1,
        step: 0.01,
        hint: 'Distance above or below the initial withdrawal rate that triggers an adjustment.',
      },
      {
        key: 'adjustment',
        label: 'Guardrail adjustment',
        type: 'percent',
        default: 0.10,
        min: 0,
        max: 1,
        step: 0.01,
        hint: 'Percentage cut or increase applied when a guardrail triggers.',
      },
      {
        key: 'preservationCutoffYears',
        frontierRange: Object.freeze({ from: 0, to: 30, step: 1 }),
        label: 'Capital preservation cutoff',
        type: 'number',
        default: 15,
        min: 0,
        max: 100,
        step: 1,
        hint: 'Disable capital-preservation cuts when this many or fewer years remain.',
      },
    ],
    init(params, options) {
      const fixedRealState = initializeFixedReal(params, options);
      const { initialRate } = fixedRealState;
      const guardrail = params.guardrail === undefined ? 0.20 : params.guardrail;
      const adjustment = params.adjustment === undefined ? 0.10 : params.adjustment;
      const preservationCutoffYears = params.preservationCutoffYears === undefined
        ? 15
        : params.preservationCutoffYears;

      assertFiniteNumber(guardrail, 'guardrail');
      if (guardrail < 0 || guardrail > 1) {
        throw new RangeError('guardrail must be between 0 and 1');
      }
      assertFiniteNumber(adjustment, 'adjustment');
      if (adjustment < 0 || adjustment > 1) {
        throw new RangeError('adjustment must be between 0 and 1');
      }
      if (!Number.isInteger(preservationCutoffYears)) {
        throw new TypeError('preservationCutoffYears must be an integer');
      }
      if (preservationCutoffYears < 0 || preservationCutoffYears > 100) {
        throw new RangeError('preservationCutoffYears must be between 0 and 100');
      }

      return {
        initialRate,
        guardrail,
        adjustment,
        preservationCutoffYears,
        currentWithdrawal: fixedRealState.baseWithdrawal,
        priorInflation: null,
        priorPortfolioReturn: null,
      };
    },
    step(state, ctx) {
      if (ctx.index === 0) {
        return {
          withdrawal: state.currentWithdrawal,
          withdrawFrom: 'proportional',
          rebalanceTo: undefined,
          notes: '',
        };
      }

      if (ctx.total === 0) {
        return {
          withdrawal: state.currentWithdrawal,
          withdrawFrom: 'proportional',
          rebalanceTo: undefined,
          notes: '',
        };
      }

      const notes = [];
      const rateBeforeInflation = state.currentWithdrawal / ctx.total;
      const skipInflation = state.priorPortfolioReturn < 0
        && meaningfullyGreaterThan(rateBeforeInflation, state.initialRate);
      if (skipInflation) {
        notes.push('inflation raise skipped');
      } else {
        state.currentWithdrawal *= 1 + state.priorInflation;
      }

      const upperGuardrail = state.initialRate * (1 + state.guardrail);
      const lowerGuardrail = state.initialRate * (1 - state.guardrail);
      const capitalPreservation = meaningfullyGreaterThan(rateBeforeInflation, upperGuardrail);
      const prosperity = meaningfullyLessThan(rateBeforeInflation, lowerGuardrail);
      if (capitalPreservation && prosperity) {
        throw new Error('Guyton-Klinger guardrails must be mutually exclusive');
      }

      const adjustmentPercent = formatAdjustmentPercent(state.adjustment);
      if (capitalPreservation && ctx.yearsRemaining > state.preservationCutoffYears) {
        state.currentWithdrawal *= 1 - state.adjustment;
        notes.push(`capital preservation −${adjustmentPercent}%`);
      } else if (prosperity) {
        state.currentWithdrawal *= 1 + state.adjustment;
        notes.push(`prosperity +${adjustmentPercent}%`);
      }

      return {
        withdrawal: state.currentWithdrawal,
        withdrawFrom: 'proportional',
        rebalanceTo: undefined,
        notes: notes.join('; '),
      };
    },
    afterYear(state, row, ctx) {
      state.currentWithdrawal = row.withdrawalNominal;
      state.priorInflation = ctx.yearRow.cpi_change;
      state.priorPortfolioReturn = row.portfolioReturn;
    },
  };

  const BacktestEngine = {
    simulate,
    resolveInitialAllocation,
    availableYearRange,
    sweepStartYears,
    sweepGrid,
    maxSafeRate,
    STRATEGIES: { fixedReal, fixedPercent, guytonKlinger, barbell },
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = BacktestEngine;
  } else {
    root.BacktestEngine = BacktestEngine;
  }
}(globalThis));
