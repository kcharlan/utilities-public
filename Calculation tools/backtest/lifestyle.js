'use strict';

/* Spending presentation models: pure inputs, formatted outputs. */
(function (root, factory) {
  const node = typeof module !== 'undefined' && module.exports;
  const format = node ? require('./format.js') : root.MarketAtlasFormat;
  if (!format) throw new Error('lifestyle.js requires format.js to be loaded first');
  const stats = node ? require('./stats.js') : root.MarketAtlasStats;
  if (!stats) throw new Error('lifestyle.js requires stats.js to be loaded first');
  const views = node ? require('./views.js') : root.MarketAtlasViews;
  if (!views) throw new Error('lifestyle.js requires views.js to be loaded first');
  const api = factory(format, stats, views);
  root.MarketAtlasLifestyle = api;
  if (node) module.exports = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function (format, stats, views) {
  const { fmtMoney, fmtMoneyCompact, fmtPct, fmtPctConcise, fmtCount } = format;
  const { comparisonTolerance, atOrBelow, extremeBy, resolveNeed, needProfile } = stats;
  const equal = (a, b) => Number.isFinite(a) && Number.isFinite(b)
    && Math.abs(a - b) <= comparisonTolerance(a, b);
  const yearText = year => Number.isSafeInteger(year) ? String(year) : '—';
  const cell = (label, value, detail, className = '') => ({ label, value, detail, className });

  function windowLifestyleCells(metrics, needDollars) {
    const spending = metrics?.spending;
    if (!spending) return [cell('Spending floor', '—', ''), cell('Spending range', '—', ''),
      cell('Typical year', '—', ''), cell('Below your need', '—', 'set a need in § 05')];
    const need = needProfile(spending, needDollars);
    const reached = spending.floorFirstIndex === null ? '—' : yearText(spending.startYear + spending.floorFirstIndex);
    const index = spending.floorFirstIndex === null ? null : spending.floorFirstIndex + 1;
    let floorDetail = spending.failed
      ? `depleted ${yearText(metrics.failureYear)} · ${fmtCount(spending.unfundedYears)} unfunded yrs · last partial ${fmtMoney(spending.lastPartial)} · funded floor ${fmtMoney(spending.fundedFloor)}`
      : `${fmtPctConcise(spending.floorRatio, 0)} of year 1 · reached ${reached} (year ${fmtCount(index)}) · held ${fmtCount(spending.floorHeldYears)} yrs`;
    if (spending.partial) floorDetail += ` · ${fmtCount(spending.pathLength)} of ${fmtCount(spending.horizon)} yrs observed`;
    return [
      cell(spending.partial ? 'Floor to date' : 'Spending floor', fmtMoney(spending.floor), floorDetail, spending.failed ? 'warning' : ''),
      cell('Spending range', `${fmtMoneyCompact(spending.floor)}–${fmtMoneyCompact(spending.ceiling).replace(/^\$/, '')}`,
        `deepest cut ${fmtPctConcise(spending.deepestCut, 0)} from peak`),
      cell('Typical year', fmtMoney(spending.median), `median · ${fmtMoney(spending.average)} average · ${fmtMoney(spending.total)} total`),
      cell('Below your need', need ? `${fmtCount(need.yearsBelow)} of ${fmtCount(spending.pathLength)} yrs` : '—',
        need ? `under ${fmtMoney(need.need)} (${fmtPctConcise(need.needRatio, 0)} of yr 1) · longest run ${fmtCount(need.longestBelowRun)} · shortfall ${fmtCount(need.shortfallYears, 2)} yrs of spending` : 'set a need in § 05'),
    ];
  }

  function formatVolatilityRange(summary) {
    return Number.isFinite(summary.spendingVolatilityMin)
      ? `${fmtPct(summary.spendingVolatilityMin)}–${fmtPct(summary.spendingVolatilityMax)}` : '—';
  }

  function sweepSolvencyCells(summary, strategy) {
    const worstDetail = Number.isSafeInteger(summary.worstFailureYear)
      ? `failed in ${yearText(summary.worstFailureYear)}`
      : summary.noSurvivingRateCount > 0 ? 'no rate survives' : 'lowest sustainable rate / wealth';
    const counts = `${fmtCount(summary.survivedCount)} of ${fmtCount(summary.completeCount)}`;
    return [
      cell('Survived', fmtPct(summary.survivedRate, 1),
        `${counts}${strategy?.canDeplete === false ? ' · cannot deplete by construction' : ' complete windows'} · ${fmtCount(summary.partialCount)} held out`, views.survivalClassName(summary)),
      cell('Worst solvency start', yearText(summary.worstStartYear), worstDetail, Number.isSafeInteger(summary.worstFailureYear) ? 'warning' : ''),
      cell('Terminal wealth · real', fmtMoneyCompact(summary.medianTerminalWealthReal),
        `median · worst ${fmtMoneyCompact(summary.worstTerminalWealthReal)} · spend volatility ${formatVolatilityRange(summary)}`),
    ];
  }

  function sweepLifestyleCells(summary) {
    const l = summary.lifestyle;
    let floorDetail = '—';
    if (l?.completeCount) {
      floorDetail = l.failedCount > 0
        ? `${fmtCount(l.failedCount)} failed · earliest ${yearText(l.worstFloorStartYear)} start · ${l.survivorsUniform
          ? `survivors all at ${fmtPctConcise(l.worstSurvivingRatio, 0)} of yr 1`
          : `worst surviving ${fmtMoney(l.worstSurvivingFloor)}`}`
        : `${fmtPctConcise(l.worstFloorRatio, 0)} of yr 1 · ${yearText(l.worstFloorStartYear)} start`;
    }
    return [
      cell('Worst floor', fmtMoney(l?.worstFloor), floorDetail, l?.failedCount > 0 ? 'warning' : ''),
      cell('Typical floor', fmtPctConcise(l?.medianFloorRatio, 0), "median window's floor, of yr 1"),
      cell('Deepest cut', fmtPctConcise(l?.deepestCut, 0), `real peak→trough · ${yearText(l?.deepestCutStartYear)} start`),
      cell('Lifestyle-worst start', yearText(l?.worstShortfallStartYear),
        l?.worstShortfallStartYear != null ? `largest shortfall below need · ${fmtCount(l.worstShortfallYears, 2)} yrs of spending`
          : l?.longestBelowNeedRun != null ? 'no year below need' : 'set a need'),
    ];
  }

  function sweepSummaryRows(series, needDollars) {
    const rows = [
      ['survival', 'Survived · complete only', item => `${fmtPct(item.summary.survivedRate, 1)} · ${fmtCount(item.summary.survivedCount)}/${fmtCount(item.summary.completeCount)}`],
      ['partial', 'Partial windows held out', item => fmtCount(item.summary.partialCount)],
      ['worst', 'Worst opening · failure year', item => `${yearText(item.summary.worstStartYear)}${item.summary.worstFailureYear ? ` · failed ${yearText(item.summary.worstFailureYear)}` : ''}`],
      ['median', 'Median terminal wealth · real', item => fmtMoney(item.summary.medianTerminalWealthReal)],
      ['terminalWorst', 'Worst terminal wealth · real', item => fmtMoney(item.summary.worstTerminalWealthReal)],
      ['volatility', 'Spending volatility range', item => `${formatVolatilityRange(item.summary)} · ${fmtCount(item.summary.spendingVolatilityUndefinedCount)} undefined`],
      ['safeFloor', 'Minimum sustainable rate', item => !item.strategy.supportsMaxSafeRate ? 'Not supported'
        : item.summary.noSurvivingRateCount > 0 ? 'No rate survives'
          : Number.isFinite(item.summary.minimumSafeRate) ? fmtPct(item.summary.minimumSafeRate, 2) : 'Unavailable'],
      ['worstFloor', 'Worst floor · all windows', item => fmtMoney(item.summary.lifestyle?.worstFloor)],
      ['failed', 'Failed windows', item => fmtCount(item.summary.lifestyle?.failedCount)],
      ['survivingFloor', 'Worst surviving floor', item => `${fmtMoney(item.summary.lifestyle?.worstSurvivingFloor)}${item.summary.lifestyle?.survivorsUniform ? ' · every survivor' : ''}`],
      ['p10Floor', '10th-percentile floor · all windows', item => fmtMoney(item.summary.lifestyle?.p10Floor)],
      ['medianFloor', 'Median floor · all windows', item => fmtMoney(item.summary.lifestyle?.medianFloor)],
      ['typical', 'Median typical year', item => fmtMoney(item.summary.lifestyle?.medianTypicalSpending)],
      ['deepestCut', 'Deepest real cut (from peak)', item => fmtPctConcise(item.summary.lifestyle?.deepestCut, 0)],
      ['longestBelowNeed', 'Longest unbroken run below need', item => Number.isFinite(needDollars)
        ? fmtCount(item.summary.lifestyle?.longestBelowNeedRun) : '—'],
      ['lifestyleWorst', 'Lifestyle-worst start · shortfall', item => {
        const l = item.summary.lifestyle;
        return Number.isFinite(needDollars) && l?.worstShortfallStartYear != null
          ? `${yearText(l.worstShortfallStartYear)} · ${fmtCount(l.worstShortfallYears, 2)} yrs of spending` : '—';
      }],
    ];
    return rows.map(([key, label, value]) => ({ key, label, values: series.map(value) }));
  }

  function spendingStripModel(rows, spending, needDollars) {
    const need = needProfile(spending, needDollars)?.need ?? null;
    const deliveredLength = spending.pathLength - spending.unfundedYears;
    const points = spending.path.map((value, index) => ({ year: spending.startYear + index,
      value, funded: index < deliveredLength, notes: rows[index]?.notes ?? '' }));
    const markers = [];
    for (let index = 1; index < deliveredLength; index += 1) {
      const current = points[index].value;
      const prior = points[index - 1].value;
      if (equal(current, prior)) continue;
      const kind = current < prior ? 'cut' : 'raise';
      const raw = points[index].notes;
      const note = Array.isArray(raw) ? raw.filter(value => typeof value === 'string' && value.trim()).join(' · ')
        : typeof raw === 'string' ? raw.trim() : '';
      markers.push({ index, kind, note: note || `real spending ${kind === 'cut' ? 'fell' : 'rose'}` });
    }
    const max = extremeBy([spending.baseline, spending.ceiling, need], value => value, 'max');
    return { points, baseline: spending.baseline, floor: spending.floor, need, markers,
      showFloorRule: spending.floor > 0 && !equal(spending.floor, spending.ceiling),
      shadeAgainst: need ?? spending.baseline, yMax: (max?.value ?? 0) * 1.12 };
  }

  function ledgerFloorFlags(spending) {
    const values = spending.path.slice(0, spending.pathLength - spending.unfundedYears);
    const flat = equal(spending.floor, spending.ceiling);
    return values.map(value => !flat && atOrBelow(value, spending.floor));
  }

  function rangeSeriesIdentity(item) {
    // Explicit presentation overrides remain supported; app series carry configuration metadata.
    let label = typeof item.label === 'string' && item.label.trim() ? item.label : '';
    if (!label && item.configuration?.params && item.configuration?.options?.allocation) {
      const configured = views.configurationLabelModel(item.configuration, item.strategy);
      label = `${configured.title} · ${configured.details}`;
    }
    return { label: label || item.strategy?.name || item.configuration?.strategyId || 'Series',
      color: item.color || item.configuration?.color };
  }

  function spendingRangeModel(series, needDollars) {
    const kindOf = result => result.partial || result.metrics.partial ? 'partial'
      : result.metrics.success === false ? 'failed' : 'complete';
    const ordered = item => item.results.slice().sort((a, b) => a.startYear - b.startYear);
    if (series.length !== 1) return {
      mode: 'floorLines', yUnit: 'yearOnePct', yMax: 1.2,
      series: series.map(item => ({ ...rangeSeriesIdentity(item),
        points: ordered(item).map(result => ({ year: result.startYear,
          value: result.metrics.spending?.floorRatio ?? null, kind: kindOf(result),
          label: `${yearText(result.startYear)}: ${kindOf(result) === 'partial' ? 'floor to date' : 'floor'} ${fmtPctConcise(result.metrics.spending?.floorRatio, 0)} of year 1` })) })),
    };
    const item = series[0];
    const identity = rangeSeriesIdentity(item);
    const l = item.summary.lifestyle;
    const bars = ordered(item).map(result => {
      const s = result.metrics.spending;
      const kind = kindOf(result);
      return { year: result.startYear, floor: s?.floor ?? null, ceiling: s?.ceiling ?? null,
        median: s?.median ?? null, kind,
        label: `${identity.label} · ${yearText(result.startYear)}: ${kind === 'partial' ? 'floor to date' : kind === 'failed' ? 'failed · floor' : 'floor'} ${fmtMoney(s?.floor)} · ceiling ${fmtMoney(s?.ceiling)} · median ${fmtMoney(s?.median)}` };
    });
    const worst = l?.failedCount > 0 ? l.worstSurvivingFloor : l?.worstFloor;
    const rules = [
      { key: 'baseline', value: l?.baseline, label: `year 1 ${fmtMoney(l?.baseline)}` },
      { key: 'need', value: needDollars, label: `need ${fmtMoney(needDollars)}` },
      { key: 'worst', value: worst, label: l?.failedCount > 0
        ? `worst surviving floor ${fmtMoney(worst)} · ${fmtCount(l.failedCount)} failed at $0` : `worst floor ${fmtMoney(worst)}` },
      { key: 'p10', value: l?.p10Floor, label: `10th-percentile floor ${fmtMoney(l?.p10Floor)}` },
    ].filter(rule => Number.isFinite(rule.value));
    const max = extremeBy([...bars.map(bar => bar.ceiling), ...rules.map(rule => rule.value)], value => value, 'max');
    return { mode: 'bars', yUnit: 'dollars', ...identity, bars, rules, yMax: (max?.value ?? 0) * 1.12 };
  }

  function frontierPlan(strategy, params, paramKey, override) {
    const field = strategy.paramSchema?.find(candidate => candidate.key === paramKey);
    const error = message => ({ error: message });
    if (!field || field.type === 'select' || field.type === 'enum') return error('Choose a numeric parameter.');
    const current = params[paramKey] ?? field.default;
    const bounds = { min: Number.isFinite(field.min) ? field.min : -Infinity,
      max: Number.isFinite(field.max) ? field.max : Infinity };
    const fallback = { from: Math.max(bounds.min, field.default * .5), to: Math.min(bounds.max, field.default * 1.5) };
    fallback.step = (fallback.to - fallback.from) / 20;
    if (!field.frontierRange && Number.isFinite(field.step) && field.step > 0) {
      const origin = Number.isFinite(field.min) ? field.min : 0;
      const nearest = value => origin + Math.round((value - origin) / field.step) * field.step;
      fallback.from = nearest(fallback.from);
      fallback.to = nearest(fallback.to);
      fallback.step = Math.max(field.step, Math.round((fallback.to - fallback.from) / 20 / field.step) * field.step);
    }
    const range = { ...(field.frontierRange || fallback), ...(override || {}) };
    const { from, to, step } = range;
    if (![from, to, step, current].every(Number.isFinite)) return error('Range and current value must be finite.');
    if (from > to) return error('Range start must not exceed its end.');
    if (from < bounds.min - comparisonTolerance(from, bounds.min) || to > bounds.max + comparisonTolerance(to, bounds.max)
      || current < bounds.min - comparisonTolerance(current, bounds.min) || current > bounds.max + comparisonTolerance(current, bounds.max)) return error('Values must be within the parameter bounds.');
    if (step < 0 || (step === 0 && (!equal(from, to) || override))) return error('Step must be positive.');
    if (override && field.type === 'number' && Number.isInteger(field.step) && field.step > 0
      && ['from', 'to', 'step'].some(key => Object.hasOwn(override, key) && !Number.isInteger(override[key]))) {
      return error('Integer parameter ranges must use whole numbers.');
    }
    if (override && Number.isFinite(field.step) && field.step > 0) {
      const origin = Number.isFinite(field.min) ? field.min : 0;
      for (const key of ['from', 'to', 'step']) {
        if (!Object.hasOwn(override, key)) continue;
        const value = key === 'step' ? override[key] : override[key] - origin;
        const nearest = Math.round(value / field.step) * field.step;
        if (!equal(value, nearest)) return error(`Range ${key} must follow the parameter increment.`);
      }
    }
    const values = [];
    if (equal(from, to)) values.push(Math.round(from * 1e10) / 1e10);
    else {
      for (let k = 0; ; k += 1) {
        const value = from + k * step;
        if (value > to + comparisonTolerance(value, to)) break;
        if (k >= 41) return error('Choose at most 41 generated values.');
        const rounded = Math.round(value * 1e10) / 1e10;
        if (!values.some(candidate => equal(candidate, rounded))) values.push(rounded);
      }
    }
    if (!values.some(value => equal(value, current))) values.push(current);
    values.sort((a, b) => a - b);
    return { key: field.key, label: field.label || field.key, isPercent: field.type === 'percent', range: { from, to, step }, values };
  }

  function frontierModel(perSeries) {
    const firstBalance = perSeries[0]?.startingBalance;
    const sameBalance = perSeries.every(item => equal(item.startingBalance, firstBalance));
    const windowCount = perSeries[0]?.points[0]?.lifestyle?.completeCount ?? 0;
    const series = perSeries.map(item => {
      const normalize = value => Number.isFinite(value)
        ? sameBalance ? value : item.startingBalance > 0 ? value / item.startingBalance : null : null;
      return { label: item.label, color: item.color, startingBalance: item.startingBalance,
        points: item.points.map(point => ({ value: point.value,
          worstFloor: normalize(point.lifestyle?.worstFloor), medianFloor: normalize(point.lifestyle?.medianFloor),
          failedCount: point.lifestyle?.failedCount ?? null,
          worstFloorStartYear: point.lifestyle?.worstFloorStartYear ?? null })) };
    });
    const scale = extremeBy(series.flatMap(item => item.points.flatMap(point => [point.worstFloor, point.medianFloor])), value => value, 'max');
    return { yUnit: sameBalance ? 'dollars' : 'startingBalancePct', windowCount,
      isPercent: Boolean(perSeries[0]?.isPercent), label: perSeries[0]?.paramLabel || '',
      yMax: (scale?.value ?? 0) * 1.12, series };
  }

  function needReadout(needState, liveBaseline) {
    const dollars = resolveNeed(needState, liveBaseline);
    return { dollars, amountText: fmtMoney(dollars),
      percentText: fmtPctConcise(dollars != null && liveBaseline > 0 ? dollars / liveBaseline : null),
      followsConfiguration: needState?.anchor === 'percent' };
  }

  function horizonCaveat(strategy) {
    return strategy.paramSchema?.some(field => field.key === 'preservationCutoffYears')
      ? 'Guyton–Klinger spending paths can differ by horizon because the capital-preservation cutoff depends on years remaining.' : '';
  }

  return Object.freeze({ windowLifestyleCells, sweepSolvencyCells, sweepLifestyleCells,
    formatVolatilityRange, sweepSummaryRows, spendingStripModel, ledgerFloorFlags,
    spendingRangeModel, frontierPlan, frontierModel, needReadout, horizonCaveat });
}));
