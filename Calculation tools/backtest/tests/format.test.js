'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const format = require('../format.js');

test('compact money has exactly one canonical rendering', () => {
  // Regression: the sweep view carried a second compact formatter that disagreed
  // with this one in both case and precision. The summary stat and the heatmap
  // legend are on screen together, so the same figure rendered two ways.
  assert.equal(format.fmtMoneyCompact(1_234_567), '$1.2M');
  assert.equal(format.fmtMoneyCompact(950_000), '$950K');
  assert.equal(format.fmtMoneyCompact(1_200), '$1.2K');   // the old duplicate said "$1k"
  assert.equal(format.fmtMoneyCompact(0), '$0');
  assert.equal(format.fmtMoneyCompact(-2_500_000), '-$2.5M');
});

test('every formatter degrades to an em dash on non-finite input', () => {
  for (const [name, fn] of Object.entries(format).filter(([name]) => name.startsWith('fmt'))) {
    for (const bad of [NaN, Infinity, -Infinity, undefined, null, 'x']) {
      assert.equal(fn(bad), '—', `${name}(${String(bad)}) must render an em dash`);
    }
  }
});

test('percent formatters differ only in trailing-zero policy', () => {
  assert.equal(format.fmtPct(0.0367), '3.7%');
  assert.equal(format.fmtPct(0.04, 2), '4.00%');
  assert.equal(format.fmtPctConcise(0.04), '4%');
  assert.equal(format.fmtPctConcise(0.0367), '3.67%');
  assert.equal(format.fmtPctConcise(0.0367, 1), '3.7%');
});

test('money and count render full precision with grouping', () => {
  assert.equal(format.fmtMoney(1_000_000), '$1,000,000');
  assert.equal(format.fmtMoney(1234.56, 2), '$1,234.56');
  assert.equal(format.fmtCount(1_000_000), '1,000,000');
});

test('the module is dual-loadable and exposes a frozen surface', () => {
  assert.equal(typeof globalThis.MarketAtlasFormat, 'object');
  assert.equal(globalThis.MarketAtlasFormat.fmtMoneyCompact, format.fmtMoneyCompact);
  assert.ok(Object.isFrozen(format));
  const source = fs.readFileSync(require.resolve('../format.js'), 'utf8');
  assert.doesNotMatch(source, /document|window\.|localStorage/, 'format.js must stay DOM-free');
});

test('no view carries its own money or percent formatter any more', () => {
  const script = fs.readFileSync(require.resolve('../app.js'), 'utf8')
    + fs.readFileSync(require.resolve('../views.js'), 'utf8');

  // The two former duplicates are gone by name...
  assert.doesNotMatch(script, /function heatmapMoney\b/);
  assert.doesNotMatch(script, /function concisePercent\b/);
  // ...and no view re-derives a currency or percent string inline.
  assert.doesNotMatch(script, /style: 'currency'/, 'currency formatting belongs to format.js');
  assert.doesNotMatch(script, /\$\$\{Number\([^)]*\)\.toLocaleString/, 'no inline currency assembly');

  // format.js must load before the code that consumes it.
  const html = fs.readFileSync(require.resolve('../index.html'), 'utf8');
  assert.ok(html.indexOf('src="format.js"') < html.indexOf('src="views.js"'));
  assert.ok(html.indexOf('src="views.js"') < html.indexOf('src="app.js"'));
});

test('escapeHtml converts values to safe text markup without changing plain text', () => {
  assert.equal(format.escapeHtml(`&<>'"`), '&amp;&lt;&gt;&#39;&quot;');
  assert.equal(format.escapeHtml(42), '42');
  assert.equal(format.escapeHtml(null), 'null');
  assert.equal(format.escapeHtml('ordinary text'), 'ordinary text');
});
