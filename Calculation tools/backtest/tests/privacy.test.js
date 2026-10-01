'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.resolve(__dirname, '..');
const RUNTIME = ['index.html', 'app.js', 'engine.js', 'views.js', 'stats.js', 'lifestyle.js', 'charts.js', 'csv.js', 'format.js'];
const THEME_KEY = 'market-atlas-theme';
const NON_THEME_RUNTIME = RUNTIME.filter((file) => !['index.html', 'app.js'].includes(file));

// Conspicuously synthetic forbidden markers exercise the guard without real data.
function privacyFindings(source, file) {
  const patterns = {
    personalPath: /(?:\/Users\/|\/home\/|[A-Za-z]:\\Users\\)[^\s'"<>]+/,
    forbiddenFixture: /SYNTHETIC_FORBIDDEN_(?:ACCOUNT|SECRET|LOCATION)/,
    credential: /(?:api[_-]?key|password|access[_-]?token)\s*[:=]\s*['"][^'"]+['"]/i,
    locationSuggestion: /navigator\.geolocation|autocomplete\s*=\s*['"](?:street-address|postal-code|address-level[1-4])['"]/i,
  };
  if (NON_THEME_RUNTIME.includes(file)) patterns.scenarioStorage = /\blocalStorage\b/;
  return Object.entries(patterns).filter(([, pattern]) => pattern.test(source)).map(([name]) => name);
}

function readRuntime(file) {
  const filename = path.join(ROOT, file);
  assert.ok(fs.existsSync(filename), `Approved runtime file must be admitted: ${file}`);
  assert.ok(fs.lstatSync(filename).isFile(), `Runtime files must be regular files: ${file}`);
  return fs.readFileSync(filename, 'utf8');
}

function storage() {
  const calls = [];
  return {
    calls,
    getItem(key) { calls.push(['get', key]); assert.equal(key, THEME_KEY); return 'dark'; },
    setItem(key, value) { calls.push(['set', key, value]); assert.equal(key, THEME_KEY); assert.ok(['light', 'dark'].includes(value)); },
    removeItem(key) { calls.push(['remove', key]); assert.equal(key, THEME_KEY); },
  };
}

test('privacy guard rejects synthetic forbidden markers and personal paths', () => {
  for (const marker of ['SYNTHETIC_FORBIDDEN_ACCOUNT', 'SYNTHETIC_FORBIDDEN_SECRET', 'SYNTHETIC_FORBIDDEN_LOCATION']) {
    assert.deepEqual(privacyFindings(marker), ['forbiddenFixture']);
  }
  assert.deepEqual(privacyFindings('/Users/SYNTHETIC_USER/private-export.csv'), ['personalPath']);
  assert.deepEqual(privacyFindings('password = "SYNTHETIC_CREDENTIAL"'), ['credential']);
  assert.deepEqual(privacyFindings('navigator.geolocation.getCurrentPosition()'), ['locationSuggestion']);
  assert.deepEqual(privacyFindings('startingBalance: 1000000, feeRate: 0'), []);
});

test('privacy guard detects synthetic scenario storage added to every non-theme module', () => {
  for (const file of NON_THEME_RUNTIME) {
    const mutatedSource = readRuntime(file) + "\nlocalStorage.setItem('SYNTHETIC_SCENARIO', '{}');\n";
    assert.deepEqual(privacyFindings(mutatedSource, file), ['scenarioStorage'], `Scenario storage must be rejected in ${file}`);
  }
});

test('admitted runtime has no personal literals, location suggestions, or remote assets', () => {
  for (const file of RUNTIME) {
    const source = readRuntime(file);
    assert.deepEqual(privacyFindings(source, file), [], `Forbidden privacy category in ${file}`);
    assert.doesNotMatch(source, /(?:src|href)\s*=\s*['"](?:https?:)?\/\/|@import\b|url\(\s*['"]?(?:https?:)?\/\//i, `Remote runtime asset in ${file}`);
    assert.doesNotMatch(source, /\b(?:fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon)\b/, `Network runtime API in ${file}`);
    assert.doesNotMatch(source, /\bsessionStorage\b|\bindexedDB\b|document\.cookie/, `Scenario persistence in ${file}`);
  }
});

test('ordinary defaults are visibly synthetic and data provenance is linked', () => {
  const source = readRuntime('index.html');
  assert.match(source, /Synthetic example defaults/i);
  assert.match(source, /href="DATA_SOURCES\.md"/);
  assert.match(source, /id="starting-balance"[^>]*value="1000000"/);
});

test('theme bootstrap reads only its appearance preference at runtime', () => {
  const source = readRuntime('index.html');
  const scripts = [...source.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)].filter((match) => !/\bsrc\s*=/.test(match[1]));
  assert.equal(scripts.length, 1);
  const localStorage = storage();
  const attributes = new Map();
  vm.runInNewContext(scripts[0][2], { window: { localStorage }, document: { documentElement: { setAttribute: (key, value) => attributes.set(key, value) } } });
  assert.deepEqual(localStorage.calls, [['get', THEME_KEY]]);
  assert.equal(attributes.get('data-theme'), 'dark');
});

function assertControllerThemePrivacy(source) {
  const start = source.indexOf("const THEME_STORAGE_KEY =");
  const end = source.indexOf('\nfunction recalculate()', start);
  assert.ok(start >= 0 && end > start, 'Theme component must be identifiable');
  const theme = source.slice(start, end);
  assert.doesNotMatch(source.slice(0, start) + source.slice(end), /\blocalStorage\b|\bStorage\b/);
  const localStorage = storage();
  const listeners = new Map();
  const buttons = ['system', 'light', 'dark'].map((choice) => ({
    getAttribute: () => choice, setAttribute() {}, classList: { toggle() {} },
    addEventListener: (name, callback) => listeners.set(choice, callback),
  }));
  const context = {
    window: { localStorage, matchMedia: () => ({ matches: false, addEventListener() {} }) },
    document: { documentElement: { setAttribute() {}, removeAttribute() {} }, querySelectorAll: () => buttons },
    heatmapPalette: (choice) => choice, setStatus() {},
  };
  vm.runInNewContext(theme + '\nTheme.initialize(() => {});', context);
  listeners.get('light')();
  listeners.get('system')();
  assert.deepEqual(localStorage.calls, [['get', THEME_KEY], ['set', THEME_KEY, 'light'], ['remove', THEME_KEY]]);
}

test('controller theme interactions persist only appearance and no scenario', () => {
  assertControllerThemePrivacy(readRuntime('app.js'));
});

test('controller privacy detects unauthorized persistence swallowed by theme recovery', () => {
  const source = readRuntime('app.js');
  const legitimateWrite = 'window.localStorage.setItem(THEME_STORAGE_KEY, next);';
  assert.ok(source.includes(legitimateWrite), 'Synthetic mutation must target the actual theme write');
  const mutatedSource = source.replace(legitimateWrite,
    "{ window.localStorage.setItem(THEME_STORAGE_KEY, next); window.localStorage.setItem('SYNTHETIC_SCENARIO', '{}'); }");
  assert.throws(() => assertControllerThemePrivacy(mutatedSource), (error) =>
    error.name === 'AssertionError' && Array.isArray(error.actual)
    && error.actual.some(([operation, key]) => operation === 'set' && key === 'SYNTHETIC_SCENARIO'));
});
