'use strict';

/* Shared spending definitions and tolerance-aware statistics. */
(function (root, factory) {
  const api = factory();
  root.MarketAtlasStats = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  function comparisonTolerance(left, right) {
    return Number.EPSILON * 8 * Math.max(1, Math.abs(left), Math.abs(right));
  }

  function atOrBelow(value, level) {
    return value - level <= comparisonTolerance(value, level);
  }

  function extremeBy(items, valueOf, direction) {
    let hit = null;
    items.forEach((item, index) => {
      const value = valueOf(item, index);
      if (!Number.isFinite(value)) return;
      const improvement = hit === null ? Infinity
        : direction === 'min' ? hit.value - value : value - hit.value;
      if (hit === null || improvement > comparisonTolerance(value, hit.value)) {
        hit = { item, index, value };
      }
    });
    return hit;
  }

  function longestRun(items, predicate) {
    let longest = 0;
    let run = 0;
    items.forEach((item, index) => {
      run = predicate(item, index) ? run + 1 : 0;
      longest = Math.max(longest, run);
    });
    return longest;
  }

  function median(values) {
    const ordered = values.filter(Number.isFinite).slice().sort((left, right) => left - right);
    if (!ordered.length) return null;
    const middle = Math.floor(ordered.length / 2);
    return ordered.length % 2 ? ordered[middle] : (ordered[middle - 1] + ordered[middle]) / 2;
  }

  function quantile(values, q) {
    const ordered = values.filter(Number.isFinite).slice().sort((left, right) => left - right);
    if (!ordered.length) return null;
    return ordered[Math.max(0, Math.min(ordered.length - 1, Math.ceil(q * ordered.length) - 1))];
  }

  function spendingProfile({ realSpending, baseline, horizon, failed, partial, startYear }) {
    const delivered = realSpending.slice();
    const unfundedYears = failed ? Math.max(0, horizon - delivered.length) : 0;
    const path = Object.freeze(delivered.concat(Array(unfundedYears).fill(0)));
    const deliveredMin = extremeBy(delivered, value => value, 'min');
    const funded = failed ? delivered.slice(0, -1) : delivered;
    const fundedMin = extremeBy(funded, value => value, 'min');
    const failureIndex = failed && delivered.length ? delivered.length - 1 : null;
    const floorHit = extremeBy(path, value => value, 'min');
    const floor = failed ? 0 : floorHit?.value ?? null;
    const floorFirstIndex = failed ? failureIndex : floorHit?.index ?? null;
    const floorHeldYears = failed ? unfundedYears : longestRun(path, value => atOrBelow(value, floor));
    const ceilingHit = extremeBy(path, value => value, 'max');
    let peak = -Infinity;
    const cuts = path.map(value => {
      peak = Math.max(peak, value);
      return peak > 0 ? 1 - value / peak : 0;
    });
    const cutHit = extremeBy(cuts, value => value, 'max');
    const total = path.reduce((sum, value) => sum + value, 0);
    const ratio = value => baseline > 0 && value != null ? value / baseline : null;
    return Object.freeze({
      baseline, horizon, failed, partial, startYear, path, pathLength: path.length,
      unfundedYears, floor, floorRatio: ratio(floor), floorFirstIndex, floorHeldYears,
      fundedFloor: fundedMin?.value ?? null,
      lastPartial: failureIndex === null ? null : delivered[failureIndex], failureIndex,
      ceiling: ceilingHit?.value ?? null, ceilingRatio: ratio(ceilingHit?.value),
      ceilingIndex: ceilingHit?.index ?? null,
      median: median(path), average: path.length ? total / path.length : null, total,
      deepestCut: failed ? 1 : cutHit?.value ?? null,
      deepestCutIndex: failed ? failureIndex : cutHit?.index ?? null,
      deliveredMin: deliveredMin?.value ?? null, deliveredMinIndex: deliveredMin?.index ?? null,
    });
  }

  function resolveNeed(state, liveBaseline) {
    if (!state) return null;
    if (state.anchor === 'dollars') {
      return Number.isFinite(state.amount) && state.amount >= 0 ? state.amount : null;
    }
    if (liveBaseline > 0 && Number.isFinite(state.ratio) && state.ratio >= 0) {
      return state.ratio * liveBaseline;
    }
    return null;
  }

  function needProfile(profile, needDollars) {
    if (!Number.isFinite(needDollars) || needDollars < 0) return null;
    const below = value => needDollars - value > comparisonTolerance(value, needDollars);
    let yearsBelow = 0;
    let shortfall = 0;
    profile.path.forEach(value => {
      if (below(value)) {
        yearsBelow += 1;
        shortfall += needDollars - value;
      }
    });
    return Object.freeze({
      need: needDollars, needRatio: profile.baseline > 0 ? needDollars / profile.baseline : null,
      yearsBelow, fractionBelow: profile.pathLength ? yearsBelow / profile.pathLength : null,
      longestBelowRun: longestRun(profile.path, below),
      shortfallYears: profile.baseline > 0 ? shortfall / profile.baseline : null,
    });
  }

  return Object.freeze({ comparisonTolerance, atOrBelow, extremeBy, longestRun, median, quantile,
    spendingProfile, resolveNeed, needProfile });
}));
