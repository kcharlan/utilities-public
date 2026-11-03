'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '..');
const read = (file) => fs.readFileSync(path.join(ROOT, file), 'utf8');
test('index.html stays a document, not an application', () => {
  // No inline application script: behaviour belongs in app.js.
  const html = read('index.html');
  const inlineScripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
  assert.equal(inlineScripts.length, 1, 'only the pre-paint theme bootstrap may be inline');
  assert.ok(inlineScripts[0].includes('data-theme'), 'the one inline script must be the theme bootstrap');
  assert.ok(inlineScripts[0].split('\n').length < 25, 'the inline bootstrap must stay tiny');
});

test('each module keeps to one responsibility', () => {
  // views.js and format.js are pure: no DOM, no app state, no storage.
  for (const file of ['views.js', 'format.js', 'stats.js', 'lifestyle.js', 'charts.js', 'engine.js']) {
    const source = read(file);
    for (const forbidden of ['document.', 'window.', 'localStorage', 'AppState']) {
      assert.ok(!source.includes(forbidden), `${file} must not reference ${forbidden}`);
    }
  }

  // The engine stays deterministic.
  const engine = read('engine.js');
  assert.ok(!/Math\.random|Date\.now|new Date\(/.test(engine), 'engine.js must stay deterministic');
});

test('the load order in the markup satisfies every dependency', () => {
  const html = read('index.html');
  const order = [...html.matchAll(/<script src="([^"]+)"><\/script>/g)].map((m) => m[1]);
  assert.deepEqual(order, ['market-data.js', 'format.js', 'stats.js', 'views.js', 'lifestyle.js', 'charts.js', 'csv.js', 'engine.js', 'app.js']);

  assert.ok(order.indexOf('stats.js') < order.indexOf('views.js'));
  assert.ok(order.indexOf('views.js') < order.indexOf('lifestyle.js'));
  assert.ok(order.indexOf('lifestyle.js') < order.indexOf('charts.js'));
  assert.ok(order.indexOf('stats.js') < order.indexOf('engine.js'));

  // views.js consumes format.js; app.js consumes everything before it.
  assert.ok(order.indexOf('format.js') < order.indexOf('views.js'));
  assert.ok(order.indexOf('views.js') < order.indexOf('app.js'));
  assert.ok(order.indexOf('engine.js') < order.indexOf('app.js'));
  assert.ok(order.indexOf('csv.js') < order.indexOf('app.js'));
});

test('every module is dual-loadable and exports a frozen surface', () => {
  for (const file of ['format.js', 'stats.js', 'views.js', 'lifestyle.js', 'charts.js', 'csv.js']) {
    const api = require(path.join(ROOT, file));
    assert.ok(Object.isFrozen(api), `${file} must export a frozen object`);
    assert.ok(Object.keys(api).length > 0, `${file} must export something`);
  }
  assert.equal(typeof require(path.join(ROOT, 'engine.js')).simulate, 'function');
});

test('modules publish only their namespace, never a spread of bare globals', () => {
  // Spreading every export onto globalThis made each new export an implicit
  // global, where a name collision would shadow silently instead of failing.
  for (const file of ['format.js', 'stats.js', 'views.js', 'lifestyle.js', 'charts.js', 'csv.js']) {
    const source = read(file);
    assert.ok(
      !/Object\.entries\(api\)\)\s*root\[name\]/.test(source),
      `${file} must not spread its exports onto the global object`,
    );
    assert.match(source, /root\.MarketAtlas\w+ = api;/, `${file} must publish a namespace`);
  }

  // The controller imports by name from those namespaces.
  const app = read('app.js');
  for (const ns of ['MarketAtlasFormat', 'MarketAtlasStats', 'MarketAtlasViews', 'MarketAtlasLifestyle', 'MarketAtlasCharts', 'MarketAtlasCsv']) {
    assert.match(app, new RegExp(`= globalThis\\.${ns};`), `app.js must import from ${ns}`);
  }
});
