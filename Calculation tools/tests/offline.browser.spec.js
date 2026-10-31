const { test, expect } = require('@playwright/test');
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const area = path.resolve(__dirname, '..');
const repo = path.resolve(area, '..');
const names = ['ai-model-timeline.html', 'drawdown.html', 'early_loan_termination_calculator.html'];

for (const name of names) {
  test(`${name} works offline from file://`, async ({ page }) => {
    const blocked = [], errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await page.route('**/*', route => {
      const url = route.request().url();
      if (/^(file|data|blob):/.test(url)) return route.continue();
      blocked.push(url);
      return route.abort();
    });
    await page.goto(pathToFileURL(path.join(area, name)).href);
    if (name === names[0]) {
      await expect(page.locator('#chartwrap svg')).toBeVisible();
      await expect.poll(() => page.locator('#chartwrap svg circle').count()).toBeGreaterThan(0);
    } else if (name === names[1]) {
      await expect(page.locator('#amort-body')).toBeVisible();
      await expect(page.locator('input').first()).toBeVisible();
      await expect(page.locator('#amort-body tr').first()).toBeVisible();
      expect(await page.evaluate(async () => {
        await document.fonts.ready;
        return [...document.fonts].some(face => face.family === 'Fraunces' && face.status === 'loaded');
      })).toBe(true);
    } else {
      await expect.poll(() => page.evaluate(() => window.Chart?.version)).toBe('4.5.1');
      await expect(page.locator('#amortTbl tbody tr')).toHaveCount(24);
      await expect(page.locator('#saveTbl tbody tr')).toHaveCount(24);
      await expect(page.locator('#amortTbl tbody tr').first().locator('td')).toHaveText(['1', '625.00', '625.00', '0.00', '14,375.00']);
      await expect(page.locator('#amortTbl tbody tr').last().locator('td').last()).toHaveText('0.00');
      await expect(page.locator('#saveTbl tbody tr').last().locator('td')).toHaveText(['24', '559.37', '100.00']);
      await page.locator('#vendorRate').fill('12');
      await page.locator('#calcBtn').click();
      await expect(page.locator('#amortTbl tbody tr').first().locator('td')).toHaveText(['1', '706.10', '556.10', '150.00', '14,443.90']);
      await expect.poll(() => page.evaluate(() => window._chart?.config?.type)).toBe('line');
    }
    expect(blocked).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test('embedded vendor assets are current', () => {
  execFileSync(process.execPath, [path.join(repo, 'tools/sync_frontend_vendor.mjs'), '--check', ...names.map(name => path.join(area, name))], { cwd: repo });
});
