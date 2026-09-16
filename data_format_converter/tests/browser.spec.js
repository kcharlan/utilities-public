const { expect, test } = require('@playwright/test');

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
    'https://cdn.jsdelivr.net/npm/js-yaml@4.1.1/dist/js-yaml.min.js',
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
