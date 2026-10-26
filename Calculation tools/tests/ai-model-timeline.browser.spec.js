const { expect, test } = require('@playwright/test');
const { pathToFileURL } = require('node:url');
const path = require('node:path');
const update = require('../docs/ai_model_timeline_update_sources_2026_10_14.json');
const october22 = require('../docs/ai_model_timeline_update_sources_2026_10_22.json');
const latestUpdate = require('../docs/ai_model_timeline_update_sources_2026_10_25.json');
const october26 = require('../docs/ai_model_timeline_update_sources_2026_10_26.json');

for (const width of [1440, 375]) {
  for (const target of ['http', 'file']) {
    test(`October update shows dated launches and access stages via ${target} at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
      await page.goto(target === 'http' ? '/ai-model-timeline.html' : pathToFileURL(path.join(__dirname, '..', 'ai-model-timeline.html')).href);
      await expect(page.locator('header')).toContainText('519 notable model releases from 96 labs');
      await page.getByRole('button', { name: 'Month', exact: true }).click();
      await page.getByLabel('Filter labs or models').fill('argon');
      await expect(page.locator('#chartwrap circle.dot:visible')).toHaveCount(2);
      await expect(page.locator('#range-summary')).toContainText('Oct 1 – Oct 26, 2026');
      await page.getByRole('button', { name: 'Report', exact: true }).click();
      await expect(page.locator('#report tr.release')).toHaveCount(2);
      await expect(page.locator('#report td.model')).toHaveText(update.additions.filter(row => row.lab === 'Google').map(row => row.model));
      await expect(page.locator('#report tr.release').first()).toContainText('Oct 13');
      await page.getByLabel('Filter labs or models').fill(update.additions.map(row => row.model).join(', '));
      await expect(page.locator('#report tr.release')).toHaveCount(update.additions.length);
      for (const row of update.additions) {
        const release = page.locator('#report tr.release').filter({ has: page.locator('td.model', { hasText: row.model }) });
        await expect(release).toHaveCount(1);
        await expect(release.locator('td.source a')).toHaveAttribute('href', row.source);
      }
      for (const manifest of [october22, latestUpdate]) {
        await page.getByLabel('Filter labs or models').fill(manifest.additions.map(row => row.model).join(', '));
        await expect(page.locator('#report tr.release')).toHaveCount(manifest.additions.length);
        for (const row of manifest.additions) {
          const release = page.locator('#report tr.release').filter({ has: page.getByRole('cell', { name: row.model, exact: true }) });
          await expect(release).toHaveCount(1);
          await expect(release.locator('td.source a')).toHaveAttribute('href', row.source);
          await expect(release).toContainText(`Oct ${Number(row.date.slice(-2))}`);
        }
      }
      await page.getByLabel('Filter labs or models').fill('GPT-6.1 Terra');
      await expect(page.locator('#report tr.release')).toHaveCount(1);
      await expect(page.locator('#report tr.release')).toContainText('Oct 26');
      await expect(page.locator('#report td.source a')).toHaveAttribute('href', october26.additions[0].source);
      await page.getByLabel('Filter labs or models').fill('kimi k3.1');
      await expect(page.locator('#report tr.release')).toHaveCount(2);
      await page.getByRole('button', { name: 'Timeline', exact: true }).click();
      await expect(page.locator('#chartwrap circle.dot:visible')).toHaveCount(2);
      await page.locator('#chartwrap circle.dot:visible').first().click();
      await expect(page.locator('#tooltip')).toContainText('Kimi K3.1 Pro');
      await expect(page.locator('#tooltip')).toContainText('weights are promised by November 4, 2026');
      await page.getByLabel('Filter labs or models').fill('maxwell');
      await page.getByRole('button', { name: 'Timeline', exact: true }).click();
      await page.locator('#chartwrap circle.dot:visible').click();
      await expect(page.locator('#tooltip')).toContainText('Access is by request');
      await page.getByLabel('Filter labs or models').fill('natura-1');
      await page.getByRole('button', { name: 'Timeline', exact: true }).click();
      await page.locator('#chartwrap circle.dot:visible').click();
      await expect(page.locator('#tooltip')).toContainText('external user access were not established');
      await page.getByRole('button', { name: 'Custom', exact: false }).click();
      await page.getByRole('button', { name: 'Latest release', exact: true }).click();
      await expect(page.locator('#custom-to')).toHaveValue(october26.latestRelease);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      expect(errors).toEqual([]);
    });
  }

  test(`timeline and report retain Meta releases and shared range state at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await page.goto('/ai-model-timeline.html');
    await expect(page.locator('header')).toContainText('October 26, 2026');
    await expect(page.locator('header')).toContainText('checked October 26, 2026');
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
    // A date tick can share a release's x-position; its grid line must not block the dot.
    await expect.poll(() => page.locator('#chartwrap circle.dot:visible').first().evaluate(dot => {
      const box = dot.getBoundingClientRect();
      return document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2) === dot;
    })).toBe(true);
    await page.locator('#chartwrap circle.dot:visible').first().click();
    await expect(page.locator('#tooltip')).toContainText('Muse Wonder');
    const bounds = await page.locator('#tooltip').boundingBox();
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
    await page.getByRole('button', { name: 'Report', exact: true }).click();
    await page.getByLabel('Filter labs or models').fill('no-such-model-synthetic');
    await expect(page.locator('#report-empty')).toContainText('No releases match these filters');
    await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
    await expect(page.locator('#report tr.release').first()).toContainText('Oct 26');
    await expect(page.locator('#period-label')).toHaveText('October 2026');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  });
}
