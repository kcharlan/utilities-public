const { expect, test } = require('@playwright/test');

test('pinned Chart.js initializes and renders the default financing calculation', async ({ page }) => {
  const browserErrors = [];
  page.on('pageerror', (error) => browserErrors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') browserErrors.push(message.text());
  });

  await page.goto('/early_loan_termination_calculator.html');

  await expect(page.locator('script[src*="chart.js"]')).toHaveAttribute(
    'src',
    'https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js',
  );
  await expect.poll(() => page.evaluate(() => window.Chart?.version)).toBe('4.5.1');
  await expect(page.locator('#amortTbl tbody tr')).toHaveCount(24);
  await expect(page.locator('#saveTbl tbody tr')).toHaveCount(24);
  await expect(page.locator('#amortTbl tbody tr').first().locator('td')).toHaveText([
    '1',
    '625.00',
    '625.00',
    '0.00',
    '14,375.00',
  ]);
  await expect(page.locator('#amortTbl tbody tr').last().locator('td').last()).toHaveText('0.00');
  await expect(page.locator('#saveTbl tbody tr').last().locator('td')).toHaveText([
    '24',
    '559.37',
    '100.00',
  ]);

  await page.locator('#vendorRate').fill('12');
  await page.locator('#calcBtn').click();
  await expect(page.locator('#amortTbl tbody tr').first().locator('td')).toHaveText([
    '1',
    '706.10',
    '556.10',
    '150.00',
    '14,443.90',
  ]);
  await expect.poll(() => page.evaluate(() => window._chart?.config?.type)).toBe('line');
  expect(browserErrors).toEqual([]);
});
