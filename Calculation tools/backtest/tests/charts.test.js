'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const api = () => require('../charts.js');
const check = svg => {
  assert.match(svg, /role="img"/); assert.match(svg, /<title[ >]/); assert.match(svg, /<desc[ >]/);
  assert.doesNotMatch(svg, /NaN|undefined|<script>/);
  for (const [, paint] of svg.matchAll(/(?:fill|stroke)="([^"]+)"/g)) assert.match(paint, /^var\(--[a-z0-9-]+\)$/);
};
test('charts exports a frozen namespace and requires Format in browser', () => {
  assert.ok(Object.isFrozen(api()));
  assert.throws(() => vm.runInNewContext(fs.readFileSync(require.resolve('../charts.js'), 'utf8'), {}), /requires format/);
});
test('spending strip uses one slot per path year, hatches padding and escapes marker notes', () => {
  const model = { points: Array.from({ length: 30 }, (_, i) => ({ year: 2000 + i, value: i < 25 ? 100 - i : 0, funded: i < 25, notes: '' })), baseline: 100, floor: 76, need: 90, showFloorRule: true, shadeAgainst: 90, yMax: 112, markers: [{ index: 1, kind: 'cut', note: '<script>' }, { index: 2, kind: 'raise', note: 'rose & grew' }] };
  const svg = api().spendingStripSvg(model); check(svg);
  assert.match(svg, /viewBox="0 0 1000 170"/);
  assert.equal((svg.match(/class="unfunded-year"/g) || []).length, 5);
  assert.equal((svg.match(/class="spending-marker"/g) || []).length, 2);
  assert.match(svg, /2001: &lt;script&gt;/); assert.match(svg, /2029/);
  assert.match(svg, /stroke="var\(--chart-stock\)"/);
  assert.match(svg, /fill="var\(--tint-failure\)"/);
  const slots = [...svg.matchAll(/class="unfunded-year" x="([\d.]+)"[^>]+width="([\d.]+)"/g)];
  assert.equal(slots.length, 5); assert.ok(Number(slots.at(-1)[1]) + Number(slots.at(-1)[2]) > 959);
});
test('range bars have accessible delegated marks, minimum heights and escaped labels', () => {
  const model = { mode: 'bars', yUnit: 'dollars', yMax: 150, bars: [{ year: 2000, floor: 50, ceiling: 100, median: 75, kind: 'complete', label: '<script>' }, { year: 2001, floor: 0, ceiling: 0, median: 0, kind: 'failed', label: 'failed' }, { year: 2002, floor: 75, ceiling: 125, median: 100, kind: 'partial', label: 'floor to date' }], rules: [{ key: 'baseline', value: 100, label: 'baseline $100' }, { key: 'p10', value: 100, label: 'p10 overlapping' }] };
  const svg = api().spendingRangeSvg(model, ['var(--chart-stock)']); check(svg);
  assert.match(svg, /Real spending range by start year/); assert.equal((svg.match(/class="sweep-point"/g) || []).length, 3);
  assert.equal((svg.match(/role="button"/g) || []).length, 3);
  assert.match(svg, /data-series-index="0" data-start-year="2001"/);
  assert.match(svg, /height="3"/); assert.match(svg, /&lt;script&gt;/); assert.doesNotMatch(svg, /p10 overlapping/);
  assert.match(svg, /opacity="0.45"/); assert.match(svg, /class="sweep-chart"/);
});
test('floor-line comparison keeps failure and partial marks with delegated series indexes', () => {
  const model = { mode: 'floorLines', yMax: 1.2, series: [{ label: 'A <script>', color: 'var(--chart-stock)', points: [{ year: 2000, value: .5, kind: 'complete' }, { year: 2001, value: 0, kind: 'failed' }, { year: 2002, value: .8, kind: 'partial' }] }, { label: 'B', color: 'var(--chart-bond)', points: [{ year: 2000, value: .7, kind: 'complete' }] }] };
  const svg = api().spendingRangeSvg(model, []); check(svg);
  assert.match(svg, /Spending floor by start year · % of year 1/); assert.equal((svg.match(/class="sweep-point"/g) || []).length, 4); assert.match(svg, /data-series-index="1"/);
});
test('frontier has worst and median lines, failure rings and focusable escaped tooltips', () => {
  const model = { yUnit: 'dollars', windowCount: 69, isPercent: true, label: 'Rate <script>', series: [{ label: 'A <script>', color: 'var(--chart-stock)', points: [{ value: .04, worstFloor: 40000, medianFloor: 40000, failedCount: 0, worstFloorStartYear: 1928 }, { value: .08, worstFloor: 0, medianFloor: 0, failedCount: 55, worstFloorStartYear: 1965 }] }] };
  const svg = api().frontierSvg(model); check(svg);
  assert.match(svg, /class="frontier-chart"/); assert.match(svg, /stroke-dasharray/);
  assert.equal((svg.match(/class="frontier-point"/g) || []).length, 2);
  assert.match(svg, /4%: worst \$40,000 \(1928\) · median \$40,000 · 0 of 69 failed/);
  assert.match(svg, /&lt;script&gt;/); assert.match(svg, /class="failure-ring"/);
  assert.doesNotMatch(svg, /role="button"/);
  check(api().frontierSvg({ ...model, yUnit: 'startingBalancePct', series: [{ ...model.series[0], points: [{ value: .04, worstFloor: .02, medianFloor: .04, failedCount: 0, worstFloorStartYear: 1928 }] }] }));
});

test('frontier count rows retain complete series identities and point tooltips name their configuration', () => {
  const labels = ['Live · Guyton-Klinger guardrails', 'Pinned 1 · Fixed real (4% rule)', 'Pinned 2 · Barbell'];
  const model = {yUnit:'dollars',windowCount:69,isPercent:true,yMax:40000,
    series: labels.map((label,index)=>({label,color:`var(--series-${index+1})`,points:[{value:.04,worstFloor:20000,medianFloor:30000,failedCount:0}]}))};
  const svg = api().frontierSvg(model);
  for (const label of labels) assert.ok(svg.includes(`aria-label="${label} · 4%:`), 'point identity remains complete');
  const legend = [...svg.matchAll(/<text[^>]*class="frontier-count-label"[^>]*>([^<]*)<\/text>/g)].map(match=>match[1]);
  assert.ok(legend.length > labels.length, 'count identities wrap into readable lines');
  assert.ok(legend.every(line=>line.length<=22), 'count labels fit the reserved SVG margin');
  const joined = legend.join(' ');
  for (const label of labels) assert.ok(joined.includes(label), 'wrapping preserves every identity word');
  for (let index=1;index<=3;index++) assert.match(svg,new RegExp(`<line(?=[^>]*class="frontier-count-swatch")(?=[^>]*stroke="var\\(--series-${index}\\)")[^>]*>`));
});
test('empty SVG models remain finite accessible drawings', () => {
  check(api().spendingStripSvg({ points: [], markers: [], baseline: null, floor: null, need: null, yMax: 0 }));
  check(api().spendingRangeSvg({ mode: 'bars', bars: [], rules: [], yMax: 0 }, []));
  check(api().frontierSvg({ yUnit: 'dollars', series: [], windowCount: 0 }));
});

test('series palette accepts numbered CSS tokens while rejecting raw or injected paint', () => {
  const model = { mode: 'bars', yMax: 100, bars: [{ year: 2000, floor: 50, ceiling: 100, median: 75, kind: 'complete' }], rules: [] };
  assert.match(api().spendingRangeSvg(model, ['var(--series-2)']), /fill="var\(--series-2\)"/);
  assert.doesNotMatch(api().spendingRangeSvg(model, ['#ffffff']), /#ffffff/);
  assert.doesNotMatch(api().spendingRangeSvg(model, ['var(--bad)" onload="alert(1)']), /onload/);
});

function appShapedSeries() {
  const { STRATEGIES } = require('../engine.js');
  const { spendingProfile } = require('../stats.js');
  const { summarizeSweep } = require('../views.js');
  return ['fixedReal', 'fixedPercent', 'guytonKlinger'].map((strategyId, index) => {
    const strategy = STRATEGIES[strategyId];
    const spending = spendingProfile({ realSpending: [40000, 30000], baseline: 40000,
      horizon: 2, failed: false, partial: false, startYear: 2000 });
    const results = [{ startYear: 2000, metrics: { spending, success: true, partial: false, terminalWealthReal: 1000000, spendingVolatility: .1 } }];
    return { configuration: { id: index, strategyId,
      params: Object.fromEntries(strategy.paramSchema.map(field => [field.key, field.default])),
      color: `var(--series-${index + 1})`,
      options: { startingBalance: 1000000, allocation: { stock: .6, bond: .4, bill: 0 }, feeRate: 0, taxRate: 0 } },
    strategy, results, summary: summarizeSweep(results, strategy.supportsMaxSafeRate, 36000) };
  });
}

test('app-shaped comparisons preserve all configured colors and labels through model to SVG', () => {
  const { spendingRangeModel } = require('../lifestyle.js');
  const items = appShapedSeries();
  const model = spendingRangeModel(items, 36000);
  assert.deepEqual(model.series.map(item => item.color), ['var(--series-1)', 'var(--series-2)', 'var(--series-3)']);
  for (let index = 0; index < items.length; index += 1) {
    assert.ok(model.series[index].label.includes(items[index].strategy.name));
    assert.match(model.series[index].label, /Starting balance: \$1,000,000/);
  }
  const svg = api().spendingRangeSvg(model); check(svg);
  for (let index = 0; index < items.length; index += 1) {
    assert.match(svg, new RegExp(`fill="var\\(--series-${index + 1}\\)"`));
    assert.ok(svg.includes(require('../format.js').escapeHtml(items[index].strategy.name)));
  }
});

test('app-shaped single series carries its configured color and label without a color adapter', () => {
  const { spendingRangeModel } = require('../lifestyle.js');
  const item = appShapedSeries()[1];
  const model = spendingRangeModel([item], 36000);
  assert.equal(model.color, 'var(--series-2)');
  assert.ok(model.label.includes(item.strategy.name));
  const svg = api().spendingRangeSvg(model); check(svg);
  assert.match(svg, /fill="var\(--series-2\)"/);
  assert.ok(svg.includes(require('../format.js').escapeHtml(item.strategy.name)));
});

test('range reference labels stay separated when rules coincide or cluster near plot edges', () => {
  for (const values of [[100, 100, 99], [112, 112, 111], [0, 0, 1]]) {
    const labels = ['year 1 $100', 'worst surviving floor $100', 'need $99'];
    const rules = values.map((value, index) => ({ key: ['baseline', 'worst', 'need'][index], value, label: labels[index] }));
    const svg = api().spendingRangeSvg({ mode: 'bars', yMax: 112, bars: [], rules });
    check(svg);
    const positions = labels.map(label => {
      const match = [...svg.matchAll(/<text[^>]* y="([\d.-]+)"[^>]*>([^<]+)<\/text>/g)].find(hit => hit[2] === label);
      assert.ok(match, `${label} remains visible`);
      return Number(match[1]);
    }).sort((a, b) => a - b);
    assert.ok(positions.every(y => y >= 20 && y <= 270), 'labels stay inside drawing');
    assert.ok(positions[1] - positions[0] >= 16 && positions[2] - positions[1] >= 16, 'reference labels have readable spacing');
    const lines = [...svg.matchAll(/<line[^>]* y1="([\d.-]+)"[^>]*stroke-dasharray="5 4"/g)];
    assert.equal(lines.length, rules.length, 'all reference lines remain');
    for (let index = 0; index < rules.length; index += 1) assert.ok(Math.abs(Number(lines[index][1]) - (275 - values[index] / 112 * 245)) < .01, 'lines retain their data positions');
  }
});
