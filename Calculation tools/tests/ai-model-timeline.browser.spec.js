const { expect, test } = require('@playwright/test');
const { pathToFileURL } = require('node:url');
const path = require('node:path');
const update = require('../docs/ai_model_timeline_update_sources_2026_10_14.json');
const october22 = require('../docs/ai_model_timeline_update_sources_2026_10_22.json');
const latestUpdate = require('../docs/ai_model_timeline_update_sources_2026_10_25.json');
const october26 = require('../docs/ai_model_timeline_update_sources_2026_10_26.json');
const october28 = require('../docs/ai_model_timeline_update_sources_2026_10_28.json');
const october30 = require('../docs/ai_model_timeline_update_sources_2026_10_30.json');

for (const width of [1440, 375]) {
  for (const target of ['http', 'file']) {
    test(`wheel scrolls the lab gutter and zooms the plot via ${target} at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 700 });
      await page.goto(target === 'http' ? '/ai-model-timeline.html' : pathToFileURL(path.join(__dirname, '..', 'ai-model-timeline.html')).href);
      const svg = page.locator('#chartwrap svg');
      const transform = () => svg.evaluate(node => ({k: window.d3.zoomTransform(node).k, x: window.d3.zoomTransform(node).x}));
      const position = async offset => {
        const box = await svg.boundingBox();
        return {x: box.x + offset, y: Math.max(200, box.y + 150)};
      };
      const left = width < 640 ? 96 : 150;
      await page.mouse.move(...Object.values(await position(left + 30)));
      const initial = await transform();
      const initialScroll = await page.evaluate(() => window.scrollY);
      await page.mouse.wheel(0, -250);
      await expect.poll(async () => (await transform()).k).toBeGreaterThan(initial.k);
      expect(await page.evaluate(() => window.scrollY)).toBe(initialScroll);
      const zoomed = await transform();
      await page.mouse.move(...Object.values(await position(left - 10)));
      await page.mouse.wheel(0, 300);
      await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(initialScroll);
      expect(await transform()).toEqual(zoomed);
      const scrolled = await page.evaluate(() => window.scrollY);
      await page.mouse.wheel(0, -180);
      await expect.poll(() => page.evaluate(() => window.scrollY)).toBeLessThan(scrolled);
      expect(await transform()).toEqual(zoomed);
      await page.mouse.move(...Object.values(await position(left + 30)));
      await page.keyboard.down('Control');
      await page.mouse.wheel(0, -30);
      await page.keyboard.up('Control');
      await expect.poll(async () => (await transform()).k).toBeGreaterThan(zoomed.k);
      const beforePan = await transform();
      await page.mouse.move(...Object.values(await position(left + 120)));
      await page.mouse.down();
      await page.mouse.move(...Object.values(await position(left + 80)), {steps: 5});
      await page.mouse.up();
      await expect.poll(async () => (await transform()).x).not.toBe(beforePan.x);
      await page.getByRole('button', {name: 'Reset', exact: true}).click();
      await expect.poll(async () => (await transform()).k).toBe(1);
    });
  }
}

for (const width of [1440, 375]) {
  for (const target of ['http', 'file']) {
    test(`October update shows dated launches and access stages via ${target} at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
      await page.goto(target === 'http' ? '/ai-model-timeline.html' : pathToFileURL(path.join(__dirname, '..', 'ai-model-timeline.html')).href);
      await expect(page.locator('header')).toContainText('531 notable model releases from 98 labs');
      await page.getByRole('button', { name: 'Month', exact: true }).click();
      await page.getByLabel('Filter labs or models').fill('argon');
      await expect(page.locator('#chartwrap circle.dot:visible')).toHaveCount(2);
      await expect(page.locator('#range-summary')).toContainText('Oct 1 – Oct 29, 2026');
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
      for (const manifest of [october22, latestUpdate, october28]) {
        await page.getByLabel('Filter labs or models').fill(manifest.additions.map(row => row.model === 'Prism' ? row.lab : row.model).join(', '));
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
      await expect(page.locator('#custom-to')).toHaveValue(october30.latestRelease);
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
    await expect(page.locator('header')).toContainText('October 29, 2026');
    await expect(page.locator('header')).toContainText('checked October 30, 2026');
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
    await expect(page.locator('#report tr.release').first()).toContainText('Oct 29');
    await expect(page.locator('#period-label')).toHaveText('October 2026');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  });
}
