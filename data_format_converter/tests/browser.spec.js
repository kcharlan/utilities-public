const { expect, test } = require('@playwright/test');

const implicitNumberCase = {
  source: 'bin: 0b101\nsep: 1_000\nplain: 1000\n',
  expected: { bin: '0b101', sep: '1_000', plain: 1000 },
};
const explicitNumberCases = [
  { source: 'n: !!int 1_000\n', expected: { n: 1000 } },
  { source: 'n: !!float 1_000.5\n', expected: { n: 1000.5 } },
];
const malformedExplicitNumber = 'n: !!int synthetic\n';
const multilineDumpCases = ['a\n\n', { text: 'a\n\n' }, 'a\n', 'a\n\n\n'];
const whitespaceQuoteCase = '   ';

test.describe('YAML compatibility', () => {
  test.beforeEach(async ({ page }) => {
    const errors = [];
    const uploads = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => {
      if (message.type() === 'error') errors.push(message.text());
    });
    page.on('request', request => {
      if (request.method() !== 'GET') uploads.push(request.url());
    });
    await page.goto('/web/index.html');
    await expect.poll(() => page.evaluate(() => typeof window.jsyaml?.load)).toBe('function');
    // Assert the guards after each test's converter calls, too.
    page.yamlGuards = { errors, uploads };
  });

  test.afterEach(async ({ page }) => {
    expect(page.yamlGuards.errors).toEqual([]);
    expect(page.yamlGuards.uploads).toEqual([]);
  });

  test('yaml_load_preserves_legacy_collections_and_timestamps', async ({ page }) => {
    const cases = [
      { source: 'base: &base { synthetic: 1 }\nmerged: { <<: *base, extra: 2 }\n', expected: { base: { synthetic: 1 }, merged: { synthetic: 1, extra: 2 } } },
      { source: '? [a, b]\n: synthetic\n? { x: y }\n: mapping\n', expected: { 'a,b': 'synthetic', '[object Object]': 'mapping' } },
      { source: 'n: !!set { a: null, b: null }\n', expected: { n: { a: null, b: null } } },
      { source: 'n: !!omap [ {a: 1}, {b: 2} ]\n', expected: { n: [{ a: 1 }, { b: 2 }] } },
      { source: 'n: !!pairs [ {a: 1}, {a: 2} ]\n', expected: { n: [['a', 1], ['a', 2]] } },
      { source: 'a: yes\nb: no\nc: on\nd: off\n', expected: { a: 'yes', b: 'no', c: 'on', d: 'off' } },
      { source: '# synthetic\n', expected: null },
    ];
    for (const { source, expected } of cases) {
      expect(await page.evaluate(source => jsonFromYaml(source), source)).toEqual(expected);
    }
    expect(await page.evaluate(() => {
      const value = jsonFromYaml('date: 2001-02-03\ntime: 2001-02-03T04:05:06Z\n');
      return { dates: [value.date, value.time].map(v => v instanceof Date), iso: [value.date.toISOString(), value.time.toISOString()] };
    })).toEqual({ dates: [true, true], iso: ['2001-02-03T00:00:00.000Z', '2001-02-03T04:05:06.000Z'] });
    expect(await page.evaluate(() => {
      const value = jsonFromYaml('n: !!binary U1lOVEhFVElD\n').n;
      return { binary: value instanceof Uint8Array, bytes: Array.from(value) };
    })).toEqual({ binary: true, bytes: [83, 89, 78, 84, 72, 69, 84, 73, 67] });
  });

  test('yaml_implicit_legacy_numbers_use_core_strings', async ({ page }) => {
    expect(await page.evaluate(source => jsonFromYaml(source), implicitNumberCase.source)).toEqual(implicitNumberCase.expected);
  });

  test('yaml_explicit_numeric_tags_keep_baseline_values', async ({ page }) => {
    for (const { source, expected } of explicitNumberCases) {
      expect(await page.evaluate(source => jsonFromYaml(source), source)).toEqual(expected);
    }
    expect(await page.evaluate(source => {
      try { jsonFromYaml(source); return false; } catch { return true; }
    }, malformedExplicitNumber)).toBe(true);
  });

  test('yaml_dump_keeps_baseline_multiline_output', async ({ page }) => {
    // Approved v5 exception: only terminal keep-chomping scalars add `...`.
    const expected = ['|+\n  a\n\n...\n', 'text: |+\n  a\n\n...\n', '|\n  a\n', '|+\n  a\n\n\n...\n'];
    for (const [index, value] of multilineDumpCases.entries()) {
      const output = await page.evaluate(value => yamlFromJson(value), value);
      expect(output).toBe(expected[index]);
      expect(await page.evaluate(output => jsonFromYaml(output), output)).toEqual(value);
    }
  });

  test('yaml_dump_accepts_whitespace_quote_change', async ({ page }) => {
    const output = await page.evaluate(value => yamlFromJson(value), whitespaceQuoteCase);
    expect(["'   '\n", '"   "\n']).toContain(output);
    expect(await page.evaluate(output => jsonFromYaml(output), output)).toBe(whitespaceQuoteCase);
  });
});

test('pinned browser converters initialize and convert synthetic JSON', async ({ page }) => {
  const browserErrors = [];
  const openAIRequests = [];
  page.on('pageerror', (error) => browserErrors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') browserErrors.push(message.text());
  });
  await page.addInitScript(() => {
    window.OPENAI_API_KEY = 'synthetic-test-key-not-real';
  });
  await page.route('https://api.openai.com/**', async (route) => {
    openAIRequests.push(route.request().url());
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ usage: { prompt_tokens: 999 } }),
    });
  });

  await page.goto('/web/index.html');

  await expect(page.locator('script[src*="js-yaml"]')).toHaveAttribute(
    'src',
    'https://cdn.jsdelivr.net/npm/js-yaml@5.4.3/dist/browser/js-yaml.umd.min.js',
  );
  await expect
    .poll(() => page.locator('script[type="module"]').textContent())
    .toContain('https://cdn.jsdelivr.net/npm/@iarna/toml@3.0.0/+esm');
  await expect.poll(() => page.evaluate(() => typeof window.jsyaml?.load)).toBe('function');
  await expect.poll(() => page.evaluate(() => typeof window.TOML?.parse)).toBe('function');

  await page.locator('#text-json-pretty').fill('{"synthetic_name":"Example","enabled":true}');
  await page.locator('#btn-json-pretty').click();

  await expect(page.locator('#text-yaml')).toHaveValue(/synthetic_name: Example/);
  await expect(page.locator('#text-toml')).toHaveValue(/synthetic_name = "Example"/);
  await expect(page.locator('#comparison-table tbody tr')).toHaveCount(6);
  await expect(page.locator('.status-chip')).toHaveText([
    '',
    '⚙️ Local',
    '⚙️ Local',
    '⚙️ Local',
    '⚙️ Local',
    '⚙️ Local',
    '⚙️ Local',
  ]);
  expect(openAIRequests).toEqual([]);
  expect(browserErrors).toEqual([]);
});
