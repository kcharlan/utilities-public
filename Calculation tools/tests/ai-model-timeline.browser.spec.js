const { expect, test } = require('@playwright/test');

for (const width of [1440, 375]) {
  test(`timeline and report retain Meta releases and shared range state at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await page.goto('/ai-model-timeline.html');
    await expect(page.locator('header')).toContainText('October 12, 2026');
    await page.getByRole('button', { name: 'Month', exact: true }).click();
    await page.getByLabel('Filter labs or models').fill('Muse Wonder');
    await expect(page.locator('#range-summary')).toContainText('2 releases · 1 labs');
    await expect(page.locator('#chartwrap circle.dot:visible')).toHaveCount(2);
    await page.getByRole('button', { name: 'Report', exact: true }).click();
    await expect(page.locator('#report tr.release')).toHaveCount(2);
    await expect(page.locator('#report td.model')).toHaveText(['Muse Wonder', 'Muse Wonder Full']);
    await expect(page.locator('#report tr.release').first()).toContainText('Oct 12');
    await expect(page.locator('#report td.source a').first()).toHaveAttribute('href', 'https://research.meta.ai/blog/muse-wonder');
    await page.reload();
    await expect(page.getByRole('button', { name: 'Report', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByLabel('Filter labs or models')).toHaveValue('muse wonder');
    await expect(page.locator('#report tr.release')).toHaveCount(2);
    await page.getByRole('button', { name: 'Timeline', exact: true }).click();
    await page.locator('#chartwrap circle.dot:visible').first().click();
    await expect(page.locator('#tooltip')).toContainText('Muse Wonder');
    const bounds = await page.locator('#tooltip').boundingBox();
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
    await page.getByRole('button', { name: 'Report', exact: true }).click();
    await page.getByLabel('Filter labs or models').fill('no-such-model-synthetic');
    await expect(page.locator('#report-empty')).toContainText('No releases match these filters');
    await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
    await expect(page.locator('#report tr.release').first()).toContainText('Oct 12');
    await expect(page.locator('#period-label')).toHaveText('October 2026');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  });
}
