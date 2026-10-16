const assert = require('node:assert/strict');
const { readFileSync, existsSync } = require('node:fs');
const { test } = require('node:test');
const vm = require('node:vm');

function loadAppearance(navigator = {}) {
  const path = require('node:path').join(__dirname, 'popup_appearance.js');
  assert.ok(existsSync(path), 'the synchronous appearance module must exist');
  const document = { documentElement: { dataset: {} } };
  const context = vm.createContext({ document, navigator, localStorage: { getItem() { return null; } } });
  vm.runInContext(readFileSync(path, 'utf8'), context);
  return { api: context.LLMPopupAppearance, document };
}

test('Automatic resolves platform while explicit skins remain unchanged', () => {
  const { api } = loadAppearance();
  for (const platform of ['macOS', 'MacIntel', 'Windows', '']) {
    assert.equal(api.resolveSkin('auto', platform), /Mac|macOS/.test(platform) ? 'native' : 'meter');
    for (const skin of ['meter', 'native']) assert.equal(api.resolveSkin(skin, platform), skin);
  }
});

test('preference reads and writes tolerate blocked storage', () => {
  const { api } = loadAppearance();
  assert.equal(api.PREF_KEY, 'llmUsageCounter.appearance');
  for (const value of [null, '', 'unknown', 'auto', 'meter', 'native']) {
    assert.equal(api.readPreference({ getItem: () => value }), ['auto', 'meter', 'native'].includes(value) ? value : 'auto');
  }
  const blocked = { getItem() { throw Error('synthetic read'); }, setItem() { throw Error('synthetic write'); } };
  assert.equal(api.readPreference(blocked), 'auto');
  assert.equal(api.writePreference(blocked, 'native'), false);
  let saved;
  assert.equal(api.writePreference({ setItem(key, value) { saved = [key, value]; } }, 'meter'), true);
  assert.deepEqual(saved, [api.PREF_KEY, 'meter']);
});

test('applySkin sets the document skin and startup uses preferred platform source', () => {
  const { api, document } = loadAppearance({ userAgentData: { platform: 'macOS' }, platform: 'Windows' });
  assert.equal(document.documentElement.dataset.skin, 'native');
  assert.equal(api.currentPlatform(), 'macOS');
  api.applySkin(document, { getItem: () => 'meter' }, 'MacIntel');
  assert.equal(document.documentElement.dataset.skin, 'meter');
  assert.equal(loadAppearance({ platform: 'MacIntel' }).api.currentPlatform(), 'MacIntel');
  assert.equal(loadAppearance().api.currentPlatform(), '');
});

test('appearance initializes before styles with a synchronous external script', () => {
  const html = readFileSync(require.resolve('./popup.html'), 'utf8');
  assert.equal(html.match(/<script\b[^>]*>/)[0], '<script src="popup_appearance.js">');
  assert.ok(html.indexOf('<script') < html.indexOf('<style'));
  assert.match(html, /<meta charset="utf-8">\s*<script src="popup_appearance.js">/);
  assert.doesNotMatch(html.match(/<html[^>]*>/)[0], /data-skin/);
});
