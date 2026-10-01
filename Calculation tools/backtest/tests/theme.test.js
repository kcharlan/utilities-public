'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

function readIndex() {
  return fs.readFileSync(require.resolve('../index.html'), 'utf8');
}

function controllerSource() {
  return fs.readFileSync(require.resolve('../app.js'), 'utf8');
}

test('pre-paint bootstrap and the theme controller agree on the storage key', () => {
  // The <head> bootstrap runs before the main script exists, so it cannot share
  // THEME_STORAGE_KEY. If the two literals drift apart, a stored dark preference
  // silently stops applying before first paint and the page flashes light.
  const bootstrap = readIndex().match(/localStorage\.getItem\('([^']+)'\)/);
  const declared = controllerSource().match(/const THEME_STORAGE_KEY = '([^']+)'/);
  assert.ok(bootstrap, 'head bootstrap must read a stored theme');
  assert.ok(declared, 'controller must declare THEME_STORAGE_KEY');
  assert.equal(bootstrap[1], declared[1]);
});

test('the bootstrap only honours explicit themes and never writes storage', () => {
  const html = readIndex();
  const head = html.slice(0, html.indexOf('<style>'));
  assert.match(head, /stored === 'dark' \|\| stored === 'light'/);
  assert.match(head, /setAttribute\('data-theme', stored\)/);
  // 'system' must leave the attribute off so prefers-color-scheme governs.
  assert.doesNotMatch(head, /setItem/);
  // Blocked storage (private browsing) must not break the page.
  assert.match(head, /catch \(error\)/);
});

test('dark tokens are defined for both the media query and the explicit attribute', () => {
  const html = readIndex();
  const styles = html.slice(html.indexOf('<style>'), html.indexOf('</style>'));

  const mediaBlock = styles.match(/@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme="light"\]\) \{([\s\S]*?)\n {4}\}/);
  const attrBlock = styles.match(/:root\[data-theme="dark"\] \{([\s\S]*?)\n {2}\}/);
  assert.ok(mediaBlock, 'system-dark block must be guarded against an explicit light choice');
  assert.ok(attrBlock, 'explicit dark block must exist so the toggle wins over the system setting');

  const names = (block) => new Set([...block.matchAll(/(--[a-z0-9-]+):/g)].map((m) => m[1]));
  const media = names(mediaBlock[1]);
  const attr = names(attrBlock[1]);
  assert.deepEqual([...media].sort(), [...attr].sort(), 'both dark blocks must define the same tokens');

  // Every dark token must correspond to one defined in the light base palette.
  const baseBlock = styles.match(/\n {2}:root \{([\s\S]*?)\n {2}\}/);
  assert.ok(baseBlock, 'light base palette must exist on bare :root');
  const base = names(baseBlock[1]);
  for (const token of media) {
    assert.ok(base.has(token), `${token} is themed dark but never defined on bare :root`);
  }
  assert.ok(base.size >= media.size, 'light palette must cover at least the themed tokens');
});

test('no colour outside the token blocks is hardcoded, except the interpolated heatmap palettes', () => {
  const html = readIndex();
  const styles = html.slice(html.indexOf('<style>'), html.indexOf('</style>'));
  const afterTokens = styles.slice(styles.indexOf('* { box-sizing: border-box;'));
  const strays = [...afterTokens.matchAll(/#[0-9A-Fa-f]{6}\b|rgba?\([^)]*\)/g)].map((m) => m[0]);
  assert.deepEqual(strays, [], `stylesheet colours must resolve through tokens, found: ${strays.join(', ')}`);

  // Inline SVG is generated in the script; its paint must also be tokenised.
  const script = html.slice(html.lastIndexOf('<script>'));
  const svgPaint = [...script.matchAll(/(?:stroke|fill|stop-color)="(#[0-9A-Fa-f]{6})"/g)].map((m) => m[1]);
  assert.deepEqual(svgPaint, [], `inline SVG paint must use var() tokens, found: ${svgPaint.join(', ')}`);
});

/* ---------------------------------------------------------------------------
   Text contrast. The light theme previously used one pale token (--ink-fade)
   for primary numbers, informative tertiary text, and disabled chrome at once,
   which left five surfaces below WCAG AA. The ramp is now split by role:
   --ink for primary values, --ink-soft for secondary, --ink-fade for tertiary
   (raised to pass AA), and --ink-disabled for disabled controls, which WCAG
   exempts. These tests pin that split.
   --------------------------------------------------------------------------- */

function relativeLuminance(hex) {
  const channels = [1, 3, 5]
    .map((offset) => parseInt(hex.slice(offset, offset + 2), 16) / 255)
    .map((channel) => (channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4));
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
}

function contrastRatio(left, right) {
  const [lighter, darker] = [relativeLuminance(left), relativeLuminance(right)].sort((a, b) => b - a);
  return (lighter + 0.05) / (darker + 0.05);
}

function tokensFrom(block) {
  return Object.fromEntries([...block.matchAll(/(--[a-z0-9-]+):\s*(#[0-9A-Fa-f]{6});/g)].map((m) => [m[1], m[2]]));
}

function themeTokens(themeName) {
  const html = readIndex();
  const styles = html.slice(html.indexOf('<style>'), html.indexOf('</style>'));
  const block = themeName === 'light'
    ? styles.match(/\n {2}:root \{([\s\S]*?)\n {2}\}/)
    : styles.match(/:root\[data-theme="dark"\] \{([\s\S]*?)\n {2}\}/);
  assert.ok(block, `${themeName} token block must exist`);
  return tokensFrom(block[1]);
}

test('every text token meets WCAG AA on every surface it can sit on, in both themes', () => {
  // --ink-disabled is deliberately excluded: WCAG exempts inactive controls, and
  // isolating it is the whole point of splitting it out of --ink-fade.
  const TEXT_TOKENS = ['--ink', '--ink-soft', '--ink-fade'];
  const SURFACES = ['--paper', '--paper-warm', '--paper-deep'];

  for (const theme of ['light', 'dark']) {
    const tokens = themeTokens(theme);
    for (const token of TEXT_TOKENS) {
      assert.ok(tokens[token], `${theme} must define ${token}`);
      for (const surface of SURFACES) {
        const ratio = contrastRatio(tokens[token], tokens[surface]);
        assert.ok(
          ratio >= 4.5,
          `${theme}: ${token} (${tokens[token]}) on ${surface} (${tokens[surface]}) is ${ratio.toFixed(2)}:1, below 4.5:1`,
        );
      }
    }
  }
});

test('the ink ramp stays ordered so the visual hierarchy survives the contrast fix', () => {
  for (const theme of ['light', 'dark']) {
    const tokens = themeTokens(theme);
    const [ink, soft, fade] = ['--ink', '--ink-soft', '--ink-fade'].map((t) => contrastRatio(tokens[t], tokens['--paper']));
    assert.ok(ink > soft, `${theme}: --ink must read stronger than --ink-soft`);
    assert.ok(soft > fade, `${theme}: --ink-soft must read stronger than --ink-fade`);
  }
});

test('primary numbers use full ink and only disabled chrome uses the exempt token', () => {
  const html = readIndex();
  const styles = html.slice(html.indexOf('<style>'), html.indexOf('</style>'));

  // The stats band is the page's primary number display.
  assert.match(styles, /\.stat-value \{ color: var\(--ink\);/);

  // --ink-disabled must not leak back into informative text.
  const disabledUses = [...styles.matchAll(/^\s*([^\n{]*)\{[^}]*var\(--ink-disabled\)/gm)].map((m) => m[1].trim());
  assert.deepEqual(disabledUses, ['.small-button:disabled'], `--ink-disabled may only style disabled controls, found: ${disabledUses.join(', ')}`);
});

test('controller and optional lifestyle charts use themed SVG paint', () => {
  const path = require('node:path');
  for (const file of ['app.js', 'lifestyle.js', 'charts.js']) {
    const filename = path.join(__dirname, '..', file);
    if (!fs.existsSync(filename)) continue;
    const source = fs.readFileSync(filename, 'utf8');
    const hardcoded = [...source.matchAll(/(?:stroke|fill|stop-color)\s*=\s*["']\s*(#[0-9a-f]{3,8}\b|rgba?\([^)]*\))/gi)].map(match => match[1]);
    assert.deepEqual(hardcoded, [], file + ' SVG paint must resolve through theme tokens');
  }
});
