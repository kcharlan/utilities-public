'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { calculatorHtml } = require('./helpers/load_drawdown');

const rootMatch = calculatorHtml.match(/:root\s*\{[^}]*\}/);
assert.ok(rootMatch, 'drawdown must have a root token block');
const root = rootMatch[0];
const tokenPairs = new Map([...root.matchAll(/--([a-z0-9-]+):\s*light-dark\(\s*(#[0-9A-Fa-f]{6})\s*,\s*(#[0-9A-Fa-f]{6})\s*\)/g)]
  .map(([, name, light, dark]) => [name, [light, dark]]));

function luminance(hex) {
  const channels = [1, 3, 5].map(index => parseInt(hex.slice(index, index + 2), 16) / 255);
  const linear = channels.map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrast(first, second) {
  const a = luminance(first), b = luminance(second);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

test('theme colour tokens meet their contrast contracts in both schemes', () => {
  const surfaces = ['surface', 'surface-raised', 'surface-sunken'];
  const textTokens = ['text', 'text-muted', 'text-subtle', 'accent-strong', 'negative', 'positive', 'series-principal'];
  const affordances = ['accent', 'negative-soft', 'control-border'];
  for (const [mode, index] of [['light', 0], ['dark', 1]]) {
    for (const surface of surfaces) {
      for (const [names, minimum] of [[textTokens, 4.5], [affordances, 3]]) {
        for (const name of names) {
          assert.ok(tokenPairs.has(name), `missing ${name}`);
          assert.ok(tokenPairs.has(surface), `missing ${surface}`);
          const ratio = contrast(tokenPairs.get(name)[index], tokenPairs.get(surface)[index]);
          assert.ok(ratio >= minimum, `${name} on ${surface} in ${mode}: ${ratio.toFixed(2)} < ${minimum}`);
        }
      }
    }
    for (const fill of ['accent-strong', 'negative', 'text']) {
      assert.ok(tokenPairs.has(fill), `missing ${fill}`);
      const ratio = contrast(tokenPairs.get('surface')[index], tokenPairs.get(fill)[index]);
      assert.ok(ratio >= 4.5, `surface on ${fill} in ${mode}: ${ratio.toFixed(2)} < 4.5`);
    }
  }
});

test('all colour literals live in the root token block', () => {
  const outside = calculatorHtml.replace(root, '');
  assert.deepEqual(outside.match(/(?<!&)#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b/g), null);
  assert.deepEqual(outside.match(/rgba?\(|color-mix\(/g), null);
});

test('system, explicit, and print schemes have the required structure', () => {
  assert.match(root, /color-scheme:\s*light dark/);
  assert.match(calculatorHtml, /:root\[data-theme="light"\]\s*\{\s*color-scheme:\s*light;/);
  const dark = calculatorHtml.match(/:root\[data-theme="dark"\]\s*\{\s*color-scheme:\s*dark;/);
  assert.ok(dark);
  const print = calculatorHtml.match(/@media print\s*\{\s*:root,\s*:root\[data-theme\]\s*\{\s*color-scheme:\s*light;/);
  assert.ok(print);
  assert.ok(calculatorHtml.indexOf(print[0]) > calculatorHtml.indexOf(dark[0]));
});

test('old colour names, browser storage, and extra scripts are absent', () => {
  assert.doesNotMatch(calculatorHtml, /var\(--(paper|ink|oxblood|forest|ochre|umber|rule-soft)\b/);
  assert.doesNotMatch(calculatorHtml, /localStorage|sessionStorage|indexedDB|document\.cookie/);
  assert.equal((calculatorHtml.match(/<script\b/g) || []).length, 1);
});

test('retired drawdown presentation hooks stay removed', () => {
  assert.doesNotMatch(calculatorHtml, /pull-quote|pq-mark|marker-dot\.surplus/);
  assert.doesNotMatch(calculatorHtml, /\.amort tr\.is-pinned \+ tr td\s*\{\s*(?:\/\*[^*]*\*\/\s*)?\}/);
});

test('renderTable contains no empty surplus branch', () => {
  assert.doesNotMatch(calculatorHtml, /if \(r\.surplus[^)]*\)\s*\{\s*(\/\/[^\n]*\n\s*)?\}/);
});

test('named font declarations include a fallback', () => {
  assert.doesNotMatch(calculatorHtml, /font-family:\s*'[^']+'\s*;/);
});
