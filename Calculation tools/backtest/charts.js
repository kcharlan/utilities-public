'use strict';

/* Accessible SVG builders consume presentation models without shared state. */
(function (root, factory) {
  const node = typeof module !== 'undefined' && module.exports;
  const format = node ? require('./format.js') : root.MarketAtlasFormat;
  if (!format) throw new Error('charts.js requires format.js to be loaded first');
  const api = factory(format);
  root.MarketAtlasCharts = api;
  if (node) module.exports = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function (format) {
  const { escapeHtml, fmtMoney, fmtMoneyCompact, fmtPctConcise, fmtCount } = format;
  const e = escapeHtml;
  const n = value => Number.isFinite(value) ? Number(value.toFixed(3)) : 0;
  const paint = (value, fallback = 'var(--chart-stock)') => typeof value === 'string'
    && /^var\(--[a-z0-9-]+\)$/.test(value) ? value : fallback;
  const text = (x, y, value, attrs = '') => `<text x="${n(x)}" y="${n(y)}" fill="var(--chart-label)" ${attrs}>${e(value)}</text>`;
  const line = (x1, y1, x2, y2, color, attrs = '') => `<line x1="${n(x1)}" y1="${n(y1)}" x2="${n(x2)}" y2="${n(y2)}" stroke="${paint(color)}" ${attrs}/>`;
  const svg = (className, width, height, title, desc, body) => `<svg class="${className}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${e(title)}"><title>${e(title)}</title><desc>${e(desc)}</desc>${body}</svg>`;

  function spendingStripSvg(model) {
    const W = 1000, H = 170;
    const pad = { left: 60, right: 40, top: 20, bottom: 35 };
    const points = model.points || [];
    const xw = (W - pad.left - pad.right) / Math.max(1, points.length);
    const x = index => pad.left + index * xw;
    const ymax = Math.max(1, Number.isFinite(model.yMax) ? model.yMax : 1);
    const y = value => H - pad.bottom - (Number.isFinite(value) ? value : 0) / ymax * (H - pad.top - pad.bottom);
    let body = '<defs><pattern id="spending-unfunded" patternUnits="userSpaceOnUse" width="8" height="8"><path d="M-2 2L2-2M0 8L8 0M6 10L10 6" stroke="var(--chart-fail)" stroke-width="1"/></pattern></defs>';
    points.forEach((point, index) => {
      if (Number.isFinite(model.shadeAgainst) && point.value < model.shadeAgainst) {
        body += `<rect x="${n(x(index))}" y="${n(y(model.shadeAgainst))}" width="${n(xw)}" height="${n(y(point.value) - y(model.shadeAgainst))}" fill="var(--tint-failure)"/>`;
      }
      if (!point.funded) body += `<rect class="unfunded-year" x="${n(x(index))}" y="${pad.top}" width="${n(xw)}" height="${H - pad.top - pad.bottom}" style="fill:url(#spending-unfunded)"/>`;
    });
    const rule = (value, label, color, dash) => Number.isFinite(value)
      ? line(pad.left, y(value), W - pad.right, y(value), color, `stroke-dasharray="${dash}"`)
        + text(W - pad.right, y(value) - 4, label, 'text-anchor="end"') : '';
    body += rule(model.baseline, `year 1 ${fmtMoneyCompact(model.baseline)}`, 'var(--chart-label)', '6 4');
    if (model.showFloorRule) body += rule(model.floor, `floor ${fmtMoneyCompact(model.floor)}`, 'var(--chart-fail)', '6 4');
    body += rule(model.need, `need ${fmtMoneyCompact(model.need)}`, 'var(--chart-seam)', '2 4');
    if (points.length) {
      const path = points.map((point, index) => `${index === 0 ? 'M' : 'L'}${n(x(index))},${n(y(point.value))}H${n(x(index + 1))}`).join('');
      body += `<path d="${path}" style="fill:none" stroke="var(--chart-stock)" stroke-width="2"/>`;
    }
    for (const marker of model.markers || []) {
      const point = points[marker.index];
      if (!point) continue;
      const note = `${point.year}: ${marker.note}`;
      body += `<text class="spending-marker" x="${n(x(marker.index) + xw / 2)}" y="${n(y(point.value) - 9)}" fill="${marker.kind === 'cut' ? 'var(--chart-fail)' : 'var(--chart-stock)'}" tabindex="0" role="img" aria-label="${e(note)}" text-anchor="middle"><title>${e(note)}</title>${marker.kind === 'cut' ? '▼' : '▲'}</text>`;
    }
    const indexes = [...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])];
    indexes.forEach(index => { if (points[index]) body += text(x(index) + xw / 2, H - 12, points[index].year, 'text-anchor="middle"'); });
    body += text(pad.left - 8, pad.top, fmtMoneyCompact(ymax), 'text-anchor="end"');
    body += text(pad.left - 8, H - pad.bottom, '$0', 'text-anchor="end"');
    return svg('spending-strip', W, H, 'Real spending through the passage',
      'Annual delivered real spending. Dashed year-one baseline, dotted spending need, and hatching for unfunded years. Focus change markers for their notes.', body);
  }

  function spendingRangeSvg(model, colors = []) {
    const W = 1000, H = 320;
    const pad = { left: 75, right: 45, top: 30, bottom: 45 };
    const multi = model.mode === 'floorLines';
    const all = multi ? (model.series || []).flatMap(item => item.points || []) : model.bars || [];
    const years = [...new Set(all.map(point => point.year).filter(Number.isFinite))].sort((a, b) => a - b);
    const xw = (W - pad.left - pad.right) / Math.max(1, years.length);
    const x = year => pad.left + (years.indexOf(year) + .5) * xw;
    const ymax = Math.max(.01, Number.isFinite(model.yMax) && model.yMax > 0 ? model.yMax : 1);
    const y = value => H - pad.bottom - value / ymax * (H - pad.top - pad.bottom);
    const axisFormat = multi ? value => fmtPctConcise(value, 0) : fmtMoneyCompact;
    let body = '';
    for (let k = 0; k <= 4; k += 1) {
      const value = ymax * k / 4;
      body += line(pad.left, y(value), W - pad.right, y(value), 'var(--chart-grid)');
      body += text(pad.left - 10, y(value) + 4, axisFormat(value), 'text-anchor="end"');
    }
    const mark = (tag, point, seriesIndex, attributes, color, label) => `<${tag} class="sweep-point" tabindex="0" role="button" data-series-index="${seriesIndex}" data-start-year="${e(point.year)}" ${attributes} fill="${paint(color)}"${point.kind === 'partial' ? ' opacity="0.45"' : ''} aria-label="${e(label)}"><title>${e(label)}</title></${tag}>`;
    const colorFor = (point, color) => point.kind === 'failed' ? 'var(--chart-fail)' : point.kind === 'partial' ? 'var(--chart-seam)' : paint(color);
    if (!multi) {
      const width = Math.max(2, .55 * xw);
      for (const point of model.bars || []) {
        if (![point.floor, point.ceiling, point.median].every(Number.isFinite)) continue;
        const label = point.label || `${point.year}: floor ${fmtMoney(point.floor)} · ceiling ${fmtMoney(point.ceiling)} · median ${fmtMoney(point.median)}`;
        const height = Math.max(3, y(point.floor) - y(point.ceiling));
        body += mark('rect', point, 0, `x="${n(x(point.year) - width / 2)}" y="${n(y(point.ceiling) - (height === 3 ? 1.5 : 0))}" width="${n(width)}" height="${n(height)}"`, colorFor(point, model.color || colors[0]), label);
        body += line(x(point.year) - width / 2, y(point.median), x(point.year) + width / 2, y(point.median), 'var(--chart-bg)', 'stroke-width="2"');
      }
      const rules = (model.rules || []).filter(rule => Number.isFinite(rule.value));
      const visibleRules = rules.filter(rule => rule.key !== 'p10'
        || !rules.some(other => other !== rule && Math.abs(y(other.value) - y(rule.value)) < 14));
      // Annotation positions can move; reference lines retain their exact data Y.
      // Pack from the top, then pull upward from the bottom to fit edge clusters.
      const annotations = visibleRules.map(rule => ({ rule, labelY: y(rule.value) - 5 }))
        .sort((a, b) => a.labelY - b.labelY);
      for (let index = 0; index < annotations.length; index += 1) {
        annotations[index].labelY = Math.max(pad.top - 10, annotations[index].labelY,
          index ? annotations[index - 1].labelY + 16 : -Infinity);
      }
      for (let index = annotations.length - 1; index >= 0; index -= 1) {
        annotations[index].labelY = Math.min(H - pad.bottom - 5, annotations[index].labelY,
          index + 1 < annotations.length ? annotations[index + 1].labelY - 16 : Infinity);
      }
      const labelPositions = new Map(annotations.map(item => [item.rule, item.labelY]));
      for (const rule of visibleRules) {
        const color = rule.key === 'need' ? 'var(--chart-seam)' : rule.key === 'worst' ? 'var(--chart-fail)' : 'var(--chart-label)';
        body += line(pad.left, y(rule.value), W - pad.right, y(rule.value), color, 'stroke-dasharray="5 4"');
        body += text(W - pad.right, labelPositions.get(rule), rule.label, 'text-anchor="end"');
      }
    } else {
      (model.series || []).forEach((item, seriesIndex) => {
        let segment = [];
        const flush = () => {
          if (segment.length) body += `<polyline points="${segment.join(' ')}" style="fill:none" stroke="${paint(item.color || colors[seriesIndex])}" stroke-width="2"/>`;
          segment = [];
        };
        for (const point of item.points || []) {
          if (!Number.isFinite(point.value) || point.kind === 'partial') flush();
          else segment.push(`${n(x(point.year))},${n(y(point.value))}`);
          if (!Number.isFinite(point.value)) continue;
          const label = `${item.label || ''} · ${point.label || `${point.year}: ${point.kind === 'partial' ? 'floor to date' : 'floor'} ${fmtPctConcise(point.value, 0)} of year 1`}`;
          body += mark('circle', point, seriesIndex, `cx="${n(x(point.year))}" cy="${n(y(point.value))}" r="3.5"`, colorFor(point, item.color || colors[seriesIndex]), label);
        }
        flush();
      });
    }
    [...new Set([0, Math.floor((years.length - 1) / 2), years.length - 1])].forEach(index => {
      if (years[index] != null) body += text(x(years[index]), H - 17, years[index], 'text-anchor="middle"');
    });
    return svg('sweep-chart', W, H, multi ? 'Spending floor by start year · % of year 1' : 'Real spending range by start year',
      'Each mark is a historical start year. Failed windows include zero spending after depletion; partial windows show floor to date and are held out of summary rules. Activate a mark to inspect its passage.', body);
  }

  function frontierSvg(model) {
    // Keep the 155-unit legend separate from the plot: centered endpoint counts
    // need a gutter before the swatch, including its stroke and three-digit text.
    // Wrap complete identities and reserve room for every row.
    const countLabels = (model.series || []).map(item => {
      const lines = [''];
      for (const word of `${item.label || ''} · failed`.split(/\s+/)) {
        const last = lines.length - 1;
        if (lines[last] && lines[last].length + word.length + 1 > 22) lines.push(word);
        else lines[last] += (lines[last] ? ' ' : '') + word;
      }
      return lines;
    });
    const countRowPitch = Math.max(25, ...countLabels.map(lines => lines.length * 15 + 8));
    const W = 1000, H = 330 + (model.series || []).length * countRowPitch;
    const countLabelX = W - 155, countSwatchX = countLabelX - 10;
    const countGutter = 25;
    const pad = { left: 80, right: W - countSwatchX + countGutter, top: 30, bottom: 85 + (model.series || []).length * countRowPitch };
    const all = (model.series || []).flatMap(item => item.points || []);
    const values = [...new Set(all.map(point => point.value).filter(Number.isFinite))].sort((a, b) => a - b);
    const xmin = values[0] ?? 0, xmax = values.at(-1) ?? 1;
    const x = value => pad.left + (xmax === xmin ? .5 : (value - xmin) / (xmax - xmin)) * (W - pad.left - pad.right);
    const ymax = Number.isFinite(model.yMax) && model.yMax > 0 ? model.yMax
      : model.yUnit === 'dollars' ? 1 : .01;
    const y = value => H - pad.bottom - value / ymax * (H - pad.top - pad.bottom);
    const yformat = model.yUnit === 'dollars' ? fmtMoneyCompact : value => fmtPctConcise(value, 0);
    const xformat = model.isPercent ? value => fmtPctConcise(value) : value => fmtCount(value, 4);
    let body = '';
    for (let k = 0; k <= 4; k += 1) {
      const value = ymax * k / 4;
      body += line(pad.left, y(value), W - pad.right, y(value), 'var(--chart-grid)');
      body += text(pad.left - 10, y(value) + 4, yformat(value), 'text-anchor="end"');
    }
    (model.series || []).forEach((item, seriesIndex) => {
      const color = paint(item.color);
      for (const [field, dashed] of [['worstFloor', false], ['medianFloor', true]]) {
        let segment = [];
        const flush = () => {
          if (segment.length) body += `<polyline points="${segment.join(' ')}" style="fill:none" stroke="${color}" stroke-width="2"${dashed ? ' stroke-dasharray="6 4"' : ''}/>`;
          segment = [];
        };
        for (const point of item.points || []) {
          if (!Number.isFinite(point[field]) || !Number.isFinite(point.value)) flush();
          else segment.push(`${n(x(point.value))},${n(y(point[field]))}`);
        }
        flush();
      }
      for (const point of item.points || []) {
        if (!Number.isFinite(point.worstFloor) || !Number.isFinite(point.value)) continue;
        const money = value => model.yUnit === 'dollars' ? fmtMoney(value)
          : Number.isFinite(item.startingBalance) && Number.isFinite(value) ? fmtMoney(value * item.startingBalance) : fmtPctConcise(value);
        const note = `${item.label ? `${item.label} · ` : ''}${xformat(point.value)}: worst ${money(point.worstFloor)} (${point.worstFloorStartYear ?? '—'}) · median ${money(point.medianFloor)} · ${fmtCount(point.failedCount)} of ${fmtCount(model.windowCount)} failed`;
        body += `<circle class="frontier-point" cx="${n(x(point.value))}" cy="${n(y(point.worstFloor))}" r="3.5" fill="${color}" tabindex="0" role="img" aria-label="${e(note)}"><title>${e(note)}</title></circle>`;
        if (point.failedCount > 0) body += `<circle class="failure-ring" cx="${n(x(point.value))}" cy="${n(y(point.worstFloor))}" r="6" style="fill:none" stroke="var(--chart-fail)" stroke-width="2"/>`;
        body += text(x(point.value), H - pad.bottom + 58 + seriesIndex * countRowPitch,
          point.failedCount > 0 ? fmtCount(point.failedCount) : '·', 'text-anchor="middle"');
      }
      const countY = H - pad.bottom + 58 + seriesIndex * countRowPitch;
      body += line(countSwatchX, countY - 8, countSwatchX, countY + 4,
        item.color, 'class="frontier-count-swatch" stroke-width="3"');
      countLabels[seriesIndex].forEach((label, index) => {
        body += text(countLabelX, countY + index * 15, label,
          'class="frontier-count-label" font-size="12"');
      });
    });
    values.forEach((value, index) => {
      if (values.length <= 10 || index === 0 || index === values.length - 1 || index % Math.ceil(values.length / 7) === 0) {
        body += text(x(value), H - pad.bottom + 22, xformat(value), 'text-anchor="middle"');
      }
    });
    body += text((pad.left + W - pad.right) / 2, H - pad.bottom + 41, model.paramLabel || model.label || 'Parameter', 'text-anchor="middle"');
    return svg('frontier-chart', W, H, 'Spending floor frontier',
      `Solid lines show the worst floor across every complete window, counting failures at zero. Dashed lines show the median floor. Failure counts appear below the parameter axis. Units: ${model.yUnit === 'dollars' ? 'real dollars' : 'percent of starting balance'}.`, body);
  }

  return Object.freeze({ spendingStripSvg, spendingRangeSvg, frontierSvg });
}));
