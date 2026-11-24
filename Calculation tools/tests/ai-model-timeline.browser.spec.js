const { expect, test } = require('@playwright/test');
const { pathToFileURL } = require('node:url');
const path = require('node:path');
const fs = require('node:fs');
const {readData} = require('../scripts/timeline-analysis.cjs');
const raw = readData(fs.readFileSync(path.join(__dirname, '..', 'ai-model-timeline.html'), 'utf8'));
const latest = raw.reduce((max,row) => row.date > max ? row.date : max, '');
const octoberMatches = terms => raw.filter(row => row.date.startsWith('2026-10') && terms.some(term => row.model.toLowerCase().includes(term.toLowerCase()) || row.lab.toLowerCase().includes(term.toLowerCase())));
const releaseRow = (page,row) => page.locator('#report tr.release')
  .filter({has:page.getByRole('cell',{name:row.model,exact:true})})
  .filter({has:page.getByRole('cell',{name:row.lab,exact:true})})
  .filter({has:page.getByRole('cell',{name:new Date(row.date+'T00:00:00Z').toLocaleDateString('en-US',{month:'short',day:'numeric',timeZone:'UTC'}),exact:true})});

async function dotFor(page,row) {
  const dots = page.locator('#chartwrap circle.dot:visible');
  const index = await dots.evaluateAll((nodes, key) => nodes.findIndex(node => ['model','lab','date'].every(name => node.__data__[name] === key[name])), row);
  expect(index).toBeGreaterThanOrEqual(0);
  return dots.nth(index);
}
const update = require('../docs/ai_model_timeline_update_sources_2026_10_14.json');
const october22 = require('../docs/ai_model_timeline_update_sources_2026_10_22.json');
const latestUpdate = require('../docs/ai_model_timeline_update_sources_2026_10_25.json');
const october26 = require('../docs/ai_model_timeline_update_sources_2026_10_26.json');
const october28 = require('../docs/ai_model_timeline_update_sources_2026_10_28.json');
const november06 = require('../docs/ai_model_timeline_update_sources_2026_11_06.json');
const november10 = require('../docs/ai_model_timeline_update_sources_2026_11_10.json');
const november12 = require('../docs/ai_model_timeline_update_sources_2026_11_12.json');
const november13 = require('../docs/ai_model_timeline_update_sources_2026_11_13.json');
const november16 = require('../docs/ai_model_timeline_update_sources_2026_11_16.json');
const november17 = require('../docs/ai_model_timeline_update_sources_2026_11_17.json');
const november21 = require('../docs/ai_model_timeline_update_sources_2026_11_21.json');
const november24 = require('../docs/ai_model_timeline_update_sources_2026_11_24.json');

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
    test(`October and November show dated launches and access stages via ${target} at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
      await page.goto((target === 'http' ? '/ai-model-timeline.html' : pathToFileURL(path.join(__dirname, '..', 'ai-model-timeline.html')).href) + '#range=m:2026-11');
      await expect(page.locator('header')).toContainText(`${raw.length} model releases from ${new Set(raw.map(row => row.lab)).size} labs`);
      await page.getByRole('button', {name:'Everything', exact:true}).click();
      await expect(page.locator('#period-label')).toHaveText('November 2026');
      await page.getByRole('button', { name: 'Report', exact: true }).click();
      const novemberRows = [november06, november10, november12, november13, november16, november17, november21, november24]
        .flatMap(update => update.additions).filter(row => row.date.startsWith('2026-11'));
      await expect(page.locator('#report tr.release')).toHaveCount(raw.filter(row => row.date.startsWith('2026-11')).length);
      for (const row of novemberRows) {
        const release = releaseRow(page,row);
        await expect(release.locator('td.source a')).toHaveAttribute('href', row.source);
        await expect(release).toContainText(`Nov ${Number(row.date.slice(-2))}`);
        await expect(release.locator('td.lab')).toHaveText(row.lab);
        await expect(release.locator('td.tier')).toHaveText(row.tier);
      }
      await page.getByRole('button', { name: 'Previous period' }).click();
      await page.getByRole('button', { name: 'Timeline', exact: true }).click();
      await page.getByLabel('Filter labs or models').fill('argon');
      await expect(page.locator('#chartwrap circle.dot:visible')).toHaveCount(octoberMatches(['argon']).length);
      await expect(page.locator('#range-summary')).toContainText('Oct 1 – Oct 31, 2026');
      await page.getByRole('button', { name: 'Report', exact: true }).click();
      await expect(page.locator('#report tr.release')).toHaveCount(octoberMatches(['argon']).length);
      const argonFixtures = update.additions.filter(row => row.lab === 'Google');
      for (const row of argonFixtures) { await expect(releaseRow(page,row)).toHaveCount(1); await expect(releaseRow(page,row).locator('td.source a')).toHaveAttribute('href',row.source); }
      const argonOrder = await Promise.all(argonFixtures.map(row => releaseRow(page,row).evaluate(node => [...node.parentElement.querySelectorAll('tr.release')].indexOf(node))));
      expect(argonOrder[0]).toBeLessThan(argonOrder[1]);
      await page.getByLabel('Filter labs or models').fill(update.additions.map(row => row.model).join(', '));
      await expect(page.locator('#report tr.release')).toHaveCount(octoberMatches(update.additions.map(row => row.model)).length);
      for (const row of update.additions) {
        const release = releaseRow(page,row);
        await expect(release).toHaveCount(1);
        await expect(release.locator('td.source a')).toHaveAttribute('href', row.source);
      }
      for (const manifest of [october22, latestUpdate, october28]) {
        await page.getByLabel('Filter labs or models').fill(manifest.additions.map(row => row.model === 'Prism' ? row.lab : row.model).join(', '));
        await expect(page.locator('#report tr.release')).toHaveCount(octoberMatches(manifest.additions.map(row => row.model === 'Prism' ? row.lab : row.model)).length);
        for (const row of manifest.additions) {
          const release = releaseRow(page,row);
          await expect(release).toHaveCount(1);
          await expect(release.locator('td.source a')).toHaveAttribute('href', row.source);
          await expect(release).toContainText(`Oct ${Number(row.date.slice(-2))}`);
        }
      }
      await page.getByLabel('Filter labs or models').fill('GPT-6.1 Terra');
      await expect(page.locator('#report tr.release')).toHaveCount(octoberMatches(['GPT-6.1 Terra']).length);
      const terra = releaseRow(page,october26.additions[0]);
      await expect(terra).toHaveCount(1);
      await expect(terra.locator('td.source a')).toHaveAttribute('href', october26.additions[0].source);
      await page.getByLabel('Filter labs or models').fill('kimi k3.1');
      await expect(page.locator('#report tr.release')).toHaveCount(octoberMatches(['kimi k3.1']).length);
      await page.getByRole('button', { name: 'Timeline', exact: true }).click();
      await expect(page.locator('#chartwrap circle.dot:visible')).toHaveCount(octoberMatches(['kimi k3.1']).length);
      await (await dotFor(page,raw.find(row => row.model === 'Kimi K3.1 Pro' && row.lab === 'Moonshot' && row.date === '2026-10-23'))).click();
      await expect(page.locator('#tooltip')).toContainText('Kimi K3.1 Pro');
      await expect(page.locator('#tooltip')).toContainText(/weights.*November 4/);
      await page.getByLabel('Filter labs or models').fill('maxwell');
      await page.getByRole('button', { name: 'Timeline', exact: true }).click();
      await (await dotFor(page,raw.find(row => row.model === 'Maxwell (controlled early access)' && row.lab === 'doubleAI' && row.date === '2026-10-19'))).click();
      await expect(page.locator('#tooltip')).toContainText('Access is by request');
      await page.getByLabel('Filter labs or models').fill('natura-1');
      await page.getByRole('button', { name: 'Timeline', exact: true }).click();
      await (await dotFor(page,raw.find(row => row.model === 'Natura-1 (research announcement)' && row.lab === 'Nature Will' && row.date === '2026-10-13'))).click();
      await expect(page.locator('#tooltip')).toContainText('external user access were not established');
      await page.getByRole('button', { name: 'Custom', exact: false }).click();
      await page.getByRole('button', { name: 'Latest release', exact: true }).click();
      await expect(page.locator('#custom-to')).toHaveValue(latest);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      expect(errors).toEqual([]);
    });
  }

  test(`timeline and report retain Meta releases and shared range state at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await page.goto('/ai-model-timeline.html#range=m:2026-11');
    await page.getByRole('button', {name:'Everything', exact:true}).click();
    await expect(page.locator('header')).toContainText('November 24, 2026');
    await expect(page.locator('header')).toContainText('checked November 24, 2026');
    await page.getByRole('button', { name: 'Previous period' }).click();
    await page.getByLabel('Filter labs or models').fill('Muse Wonder');
    const metaMatches = octoberMatches(['Muse Wonder']);
    await expect(page.locator('#range-summary')).toContainText(`${metaMatches.length} releases · ${new Set(metaMatches.map(row => row.lab)).size} labs`);
    await expect(page.locator('#chartwrap circle.dot:visible')).toHaveCount(metaMatches.length);
    await page.getByRole('button', { name: 'Report', exact: true }).click();
    await expect(page.locator('#report tr.release')).toHaveCount(metaMatches.length);
    const metaFixtures = ['Muse Wonder','Muse Wonder Full'].map(model => raw.find(row => row.model === model && row.lab === 'Meta' && row.date === '2026-10-12'));
    for (const row of metaFixtures) { await expect(releaseRow(page,row)).toHaveCount(1); await expect(releaseRow(page,row).locator('td.source a')).toHaveAttribute('href','https://research.meta.ai/blog/muse-wonder'); }
    const metaOrder = await Promise.all(metaFixtures.map(row => releaseRow(page,row).evaluate(node => [...node.parentElement.querySelectorAll('tr.release')].indexOf(node))));
    expect(metaOrder[0]).toBeLessThan(metaOrder[1]);
    await page.reload();
    await expect(page.getByRole('button', { name: 'Report', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByLabel('Filter labs or models')).toHaveValue('muse wonder');
    await expect(page.locator('#report tr.release')).toHaveCount(metaMatches.length);
    await page.getByRole('button', { name: 'Timeline', exact: true }).click();
    // A date tick can share a release's x-position; its grid line must not block the dot.
    await expect.poll(() => page.locator('#chartwrap circle.dot:visible').first().evaluate(dot => {
      const box = dot.getBoundingClientRect();
      return document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2) === dot;
    })).toBe(true);
    await (await dotFor(page,raw.find(row => row.model === 'Muse Wonder' && row.lab === 'Meta' && row.date === '2026-10-12'))).click();
    await expect(page.locator('#tooltip')).toContainText('Muse Wonder');
    const bounds = await page.locator('#tooltip').boundingBox();
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
    await page.getByRole('button', { name: 'Report', exact: true }).click();
    await page.getByLabel('Filter labs or models').fill('no-such-model-synthetic');
    await expect(page.locator('#report-empty')).toContainText('No releases match these filters');
    await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
    await expect(page.locator('#report tr.release').first()).toContainText('Oct 30');
    await expect(page.locator('#period-label')).toHaveText('October 2026');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  });
}

for (const width of [1440, 375]) {
  test(`detail controls, report and panels at ${width}px`, async ({page}) => {
    const {joinedRows, loadCore} = require('./helpers/timeline-page');
    const rows = joinedRows(), core = loadCore();
    await page.setViewportSize({width,height:900});
    await page.goto('/ai-model-timeline.html');
    const count = show => rows.filter(row => core.rowShown(row,show)).length;
    await expect(page.getByRole('button',{name:'Notable',exact:true})).toHaveAttribute('aria-pressed','true');
    await expect(page.locator('#chartwrap circle.dot:visible')).toHaveCount(count('notable'));
    for (const [label,show] of [['Headline','headline'],['Everything','all'],['Notable','notable']]) {
      await page.getByRole('button',{name:label,exact:true}).click();
      await expect(page.locator('#chartwrap circle.dot:visible')).toHaveCount(count(show));
    }
    await page.getByRole('button',{name:'Month',exact:true}).click();
    await expect(page.locator('#period-label')).toHaveText(new Date(latest + 'T00:00:00Z').toLocaleDateString('en-US',{month:'long',year:'numeric',timeZone:'UTC'}));
    await page.getByRole('button',{name:'Everything',exact:true}).click();
    await page.reload();
    await expect(page.getByRole('button',{name:'Everything',exact:true})).toHaveAttribute('aria-pressed','true');
    await page.getByRole('button',{name:'Report',exact:true}).click();
    await expect(page.getByRole('columnheader',{name:'Level'})).toBeAttached();
    await page.getByRole('button',{name:'Reset',exact:true}).click();
    await expect(page.getByRole('button',{name:'Notable',exact:true})).toHaveAttribute('aria-pressed','true');
    const record = rows.find(row => !core.rowShown(row,'notable') && rows.filter(other => other.model.toLowerCase().includes(row.model.toLowerCase()) || other.lab.toLowerCase().includes(row.model.toLowerCase())).every(other => !core.rowShown(other,'notable')));
    await page.getByLabel('Filter labs or models').fill(record.model);
    await expect(page.getByRole('button',{name:'Show everything'})).toBeVisible();
    await page.getByRole('button',{name:'Show everything'}).click();
    await expect(page.locator('#report tr.release').first()).toBeVisible();
    await page.getByRole('button',{name:'Notable',exact:true}).click();
    await page.getByRole('button',{name:'Timeline',exact:true}).click();
    await page.getByRole('button',{name:'Show everything'}).click();
    await expect(page.locator('#chartwrap circle.dot:visible').first()).toBeVisible();
    await page.getByRole('button',{name:'Reset',exact:true}).click();
    for (const [button,panel] of [['Custom','#custom-popover'],['Controls and shortcuts','#help-popover'],...(width < 640 ? [['Filters','#filters-popover']] : [])]) {
      const toggle = page.getByRole('button',{name:button,exact:button !== 'Custom'});
      await toggle.click();
      const box = await page.locator(panel).boundingBox();
      expect(box.x).toBeGreaterThanOrEqual(8); expect(box.x + box.width).toBeLessThanOrEqual(width-8);
      expect(box.y).toBeGreaterThanOrEqual(0); expect(box.y+box.height).toBeLessThanOrEqual(900);
      await page.keyboard.press('Escape'); await expect(toggle).toBeFocused();
    }
    if (width < 640) {
      await page.getByRole('button',{name:'Filters',exact:true}).click();
      await page.locator('#filters-popover input[value="mid"]').uncheck();
      await expect(page.getByRole('button',{name:'Filters •'})).toBeVisible();
    }
  });
}

test('metadata in tooltip is displayed as text', async ({page}) => {
  const {html, levels, rawRows} = require('./helpers/timeline-page');
  const {embedLevels} = require('../scripts/timeline-levels.cjs');
  const doc = structuredClone(levels);
  const row = rawRows()[0];
  const entry = doc.entries.find(e => e.model === row.model && e.lab === row.lab && e.date === row.date);
  entry.reason = '<img src=x onerror=alert(1)> literal';
  await page.route('**/ai-model-timeline.html', route => route.fulfill({contentType:'text/html',body:embedLevels(html,doc)}));
  await page.goto('/ai-model-timeline.html');
  await page.getByRole('button',{name:'Everything',exact:true}).click();
  await page.getByLabel('Filter labs or models').fill(row.model);
  const dot = page.locator('#chartwrap circle.dot').filter({visible:true}).filter({hasNot:page.locator('nothing')});
  const target = dot.filter({}).first();
  await target.click();
  await expect(page.locator('#tooltip')).toContainText('<img src=x onerror=alert(1)> literal');
  await expect(page.locator('#tooltip img')).toHaveCount(0);
});

test('panels reposition, switch focus and dismiss without stealing focus', async ({page}) => {
  await page.setViewportSize({width:375,height:650});
  await page.goto('/ai-model-timeline.html');
  const custom = page.getByRole('button',{name:'Custom'}), help = page.getByRole('button',{name:'Controls and shortcuts'});
  await custom.click();
  await expect(page.locator('#custom-from')).toBeFocused();
  const before = await page.locator('#custom-popover').boundingBox();
  expect(before.x).toBeGreaterThanOrEqual(8); expect(before.x+before.width).toBeLessThanOrEqual(367);
  expect(before.y).toBeGreaterThanOrEqual(0); expect(before.y+before.height).toBeLessThanOrEqual(650);
  await page.locator('#custom-from').fill('');
  await page.getByRole('button',{name:'Apply',exact:true}).click();
  await expect(page.locator('#custom-error')).toBeVisible();
  const bounds = async selector => { const box = await page.locator(selector).boundingBox(); expect(box.x).toBeGreaterThanOrEqual(8); expect(box.x+box.width).toBeLessThanOrEqual(367); expect(box.y).toBeGreaterThanOrEqual(0); expect(box.y+box.height).toBeLessThanOrEqual(650); };
  await bounds('#custom-popover');
  await help.click(); await expect(help).toBeFocused(); await expect(page.locator('#custom-popover')).toBeHidden();
  await page.setViewportSize({width:340,height:650});
  await expect.poll(async () => { const box = await page.locator('#help-popover').boundingBox(); return box.x + box.width; }).toBeLessThanOrEqual(332);
  await page.getByLabel('Filter labs or models').click();
  await expect(page.getByLabel('Filter labs or models')).toBeFocused();
  await expect(page.locator('#help-popover')).toBeHidden();
  await help.click();
  const previous = await help.boundingBox();
  await page.evaluate(() => window.scrollBy({top:20,behavior:'instant'}));
  await expect(page.locator('#help-popover')).toBeVisible();
  await expect.poll(async () => (await help.boundingBox()).y).toBeLessThan(previous.y);
  await expect.poll(async () => { const toggle = await help.boundingBox(), panel = await page.locator('#help-popover').boundingBox(); return Math.min(Math.abs(panel.y - (toggle.y + toggle.height)), Math.abs(panel.y + panel.height - toggle.y)); }).toBeLessThanOrEqual(1);
  await page.evaluate(() => window.scrollTo({top:document.body.scrollHeight,behavior:'instant'}));
  await expect(page.locator('#help-popover')).toBeHidden();
});

test('shortcut focuses Help and open panel follows report toolbar reflow', async ({page}) => {
  await page.setViewportSize({width:1050,height:650});
  await page.goto('/ai-model-timeline.html');
  const help = page.getByRole('button',{name:'Controls and shortcuts'});
  await page.keyboard.press('?');
  await expect(help).toBeFocused();
  await page.keyboard.press('r');
  await expect(page.getByRole('button',{name:'Report',exact:true})).toHaveAttribute('aria-pressed','true');
  await expect.poll(async () => {
    const a = await help.boundingBox(), b = await page.locator('#help-popover').boundingBox();
    return Math.abs(a.x-b.x);
  }).toBeLessThanOrEqual(1);
});
for (const width of [1440,375]) {
  test(`report caption, copy, detail recovery and panel bounds at ${width}px`, async ({page}) => {
    const {joinedRows,loadCore} = require('./helpers/timeline-page');
    const rows = joinedRows(), core = loadCore();
    await page.setViewportSize({width,height:900});
    await page.addInitScript(() => Object.defineProperty(navigator,'clipboard',{value:{writeText: async value => { window.__copiedReport = value; }}}));
    await page.goto('/ai-model-timeline.html');
    await page.getByRole('button',{name:'Report',exact:true}).click();
    await expect(page.locator('table.report caption')).not.toContainText('Filters:');
    const hidden = rows.filter(row => !core.rowShown(row,'notable')).length;
    await expect(page.locator('table.report caption')).toContainText(`${hidden} more in Everything`);
    await page.getByRole('button',{name:'Copy',exact:true}).click();
    await expect.poll(() => page.evaluate(() => window.__copiedReport)).not.toContain('Filters:');
    const row = rows.find(item => item.of && !core.rowShown(item,'notable') && rows.filter(other => other.date.slice(0,7) === item.date.slice(0,7) && other.tier === item.tier && (other.model.toLowerCase().includes(item.model.toLowerCase()) || other.lab.toLowerCase().includes(item.model.toLowerCase()))).every(other => !core.rowShown(other,'notable')));
    const matching = rows.filter(other => other.date.slice(0,7) === row.date.slice(0,7) && other.tier === row.tier && (other.model.toLowerCase().includes(row.model.toLowerCase()) || other.lab.toLowerCase().includes(row.model.toLowerCase())));
    await page.goto(`/ai-model-timeline.html#view=report&range=m:${row.date.slice(0,7)}&tiers=${row.tier}&q=${encodeURIComponent(row.model)}`);
    await expect(page.locator('#report-empty')).toContainText(`${matching.length} more in Everything`);
    await page.getByRole('button',{name:'Show everything'}).click();
    await expect(page.locator('#report tr.release')).toHaveCount(matching.length);
    await expect(page.getByLabel('Filter labs or models')).toHaveValue(row.model.toLowerCase());
    await expect(page.locator('#period-label')).toHaveText(new Date(row.date+'T00:00:00Z').toLocaleDateString('en-US',{month:'long',year:'numeric',timeZone:'UTC'}));
    expect(await page.evaluate(() => new URLSearchParams(location.hash.slice(1)).get('tiers'))).toBe(row.tier);
    await expect(page.locator('table.report caption')).toContainText('Detail: Everything');
    await expect(page.locator('table.report caption')).toContainText('Tiers:');
    const target = releaseRow(page,row);
    if (width < 640) {
      const columns = await target.evaluate(node => Object.fromEntries(['lab','level','tier','source'].map(name => [name,getComputedStyle(node.querySelector('td.'+name)).gridColumn])));
      expect(columns).toEqual({lab:'1 / 3',level:'3',tier:'4',source:'5'});
    }
    await expect(target.locator('td.level')).toHaveAttribute('title',new RegExp(row.of.model.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')));
    await page.getByRole('button',{name:'Copy',exact:true}).click();
    await expect.poll(() => page.evaluate(() => window.__copiedReport)).toContain(row.of.model);
    await expect.poll(() => page.evaluate(() => window.__copiedReport)).toContain(row.label);
    await expect.poll(() => page.evaluate(() => window.__copiedReport)).toContain('Filters: Detail: Everything');
    await page.getByRole('button',{name:'Notable',exact:true}).click();
    await page.getByRole('button',{name:'Timeline',exact:true}).click();
    await expect(page.locator('#chart-empty')).toContainText(`${matching.length} more in Everything`);
    await page.getByRole('button',{name:'Show everything'}).click();
    await expect(page.locator('#chartwrap circle.dot:visible')).toHaveCount(matching.length);
    await expect(page.getByLabel('Filter labs or models')).toHaveValue(row.model.toLowerCase());
    expect(await page.evaluate(() => new URLSearchParams(location.hash.slice(1)).get('tiers'))).toBe(row.tier);
    await expect(page.locator('#period-label')).toHaveText(new Date(row.date+'T00:00:00Z').toLocaleDateString('en-US',{month:'long',year:'numeric',timeZone:'UTC'}));
    await page.getByRole('button',{name:'Report',exact:true}).click();
    for (const [name,selector] of [['Custom','#custom-popover'],['Controls and shortcuts','#help-popover'],...(width<640 ? [['Filters','#filters-popover']] : [])]) {
      const toggle = page.getByRole('button',{name:name === 'Filters' ? /^Filters/ : name,exact:name !== 'Custom'});
      await toggle.click();
      const box = await page.locator(selector).boundingBox();
      expect(box.x).toBeGreaterThanOrEqual(8); expect(box.x+box.width).toBeLessThanOrEqual(width-8);
      expect(box.y).toBeGreaterThanOrEqual(0); expect(box.y+box.height).toBeLessThanOrEqual(900);
      await page.keyboard.press('Escape');
    }
  });
}

test('custom validation repositions a panel above its toggle', async ({page}) => {
  await page.setViewportSize({width:280,height:370});
  await page.goto('/ai-model-timeline.html');
  const toggle = page.getByRole('button',{name:'Custom'}), panel = page.locator('#custom-popover');
  await toggle.click();
  const before = await panel.boundingBox(), anchor = await toggle.boundingBox();
  expect(before.y + before.height).toBeLessThanOrEqual(anchor.y + 1);
  await page.locator('#custom-from').fill('');
  await page.getByRole('button',{name:'Apply',exact:true}).click();
  await expect(page.locator('#custom-error')).toBeVisible();
  const after = await panel.boundingBox();

  expect(after.y).toBeLessThan(before.y);
  expect(after.y + after.height).toBeLessThanOrEqual(anchor.y + 1);
});

for (const target of ['http','file']) {
  test(`folds and shared lane geometry via ${target}`, async ({page}) => {
    const {joinedRows,loadCore} = require('./helpers/timeline-page');
    const rows = joinedRows(), core = loadCore();
    const laneLabs = new Set(rows.filter(r => !r.of && r.level <= 2).map(r => r.lab));
    const key = r => core.laneKey(r,laneLabs);
    const url = target === 'http' ? '/ai-model-timeline.html' : pathToFileURL(path.join(__dirname,'..','ai-model-timeline.html')).href;
    await page.setViewportSize({width:1440,height:900});
    await page.addInitScript(() => Object.defineProperty(navigator,'clipboard',{value:{writeText:async value => {window.__copiedReport=value;}}}));
    await page.goto(url);
    for (const range of ['all','month']) for (const show of ['notable','all']) {
      await page.locator(`[data-range="${range}"]`).click();
      await page.getByRole('button',{name:show === 'all' ? 'Everything' : 'Notable',exact:true}).click();
      const shown = rows.filter(r => core.rowShown(r,show) && (range === 'all' || r.date.slice(0,7) === latest.slice(0,7)));
      const expectedLinks = shown.filter(r => r.parent && shown.includes(r.parent));
      const actual = await page.locator('#chartwrap svg').evaluate(svg => {
        const visible = n => n.getAttribute('display') !== 'none';
        return {clip:svg.querySelector('line.fold-link').parentNode.getAttribute('clip-path'), lanes:[...svg.querySelectorAll('g.lane')].map(g => ({key:g.__data__,y:+g.querySelector('rect').getAttribute('y'),h:+g.querySelector('rect').getAttribute('height'),count:g.querySelector('.lane-count').textContent})),
          links:[...svg.querySelectorAll('line.fold-link')].filter(visible).map(n => ({row:n.__data__.model,x1:+n.getAttribute('x1'),y1:+n.getAttribute('y1'),x2:+n.getAttribute('x2'),y2:+n.getAttribute('y2'),pointer:getComputedStyle(n).pointerEvents})),
          marks:[...svg.querySelectorAll('circle.dot')].filter(visible).map(n=>({model:n.__data__.model,lab:n.__data__.lab,date:n.__data__.date,cy:+n.getAttribute('cy'),cx:+n.getAttribute('cx'),r:+n.getAttribute('r'),stroke:parseFloat(getComputedStyle(n).strokeWidth),fill:n.getAttribute('fill'),color:getComputedStyle(n).stroke}))};
      });
      expect(actual.marks).toHaveLength(shown.length);
      expect(actual.clip).toBe('url(#clip)');
      expect(new Set(actual.lanes.map(l => l.key))).toEqual(new Set(shown.map(key)));
      expect(actual.links).toHaveLength(expectedLinks.length);
      for (const lane of actual.lanes) {
        const n = shown.filter(r => key(r) === lane.key).length, total = rows.filter(r => key(r) === lane.key).length;
        expect(lane.count).toBe(n === total ? String(n) : `${n} / ${total}`);
      }
      for (const mark of actual.marks) {
        const row = shown.find(r => r.model === mark.model && r.lab === mark.lab && r.date === mark.date);
        const lane = actual.lanes.find(l => l.key === key(row));
        expect(mark.cy-mark.r-mark.stroke/2).toBeGreaterThanOrEqual(lane.y);
        expect(mark.cy+mark.r+mark.stroke/2).toBeLessThanOrEqual(lane.y+lane.h);
        if (row.of) {
          expect(mark.r).toBe(3); expect(mark.fill).toBe('none');
          expect(mark.color).toBe({flagship:'rgb(240, 136, 62)',mid:'rgb(88, 166, 255)',small:'rgb(63, 185, 80)','open-weights':'rgb(188, 140, 255)',specialty:'rgb(247, 120, 186)'}[row.tier]);
        }
      }
      for (const row of expectedLinks) {
        const link = actual.links.find(l => l.row === row.model), mark = actual.marks.find(m => m.model === row.model), parent = actual.marks.find(m => m.model === row.parent.model && m.lab === row.parent.lab && m.date === row.parent.date);
        expect([link.x1,link.y1,link.x2,link.y2]).toEqual([mark.cx,mark.cy,parent.cx,parent.cy]);
        expect(link.pointer).toBe('none');
      }
    }
    const stage = rows.find(r => r.kind === 'stage' && r.parent && r.tier !== r.parent.tier && core.rowShown(r,'notable'));
    await page.locator('[data-range="month"]').click();
    await page.getByRole('button',{name:'Notable',exact:true}).click();
    await page.getByLabel('Filter labs or models').fill(stage.model + ',' + stage.parent.model);
    await page.locator(`input.tierbox[value="${stage.parent.tier}"]`).first().uncheck();
    const dot = await dotFor(page,stage);
    await dot.scrollIntoViewIfNeeded(); await dot.click();
    await expect(page.locator('#tooltip')).toContainText(stage.parent.model);
    await expect(page.locator('#tooltip')).toContainText(stage.label);
    const stageLink = page.locator('line.fold-link');
    expect(await stageLink.evaluateAll((nodes,model) => nodes.find(n => n.__data__.model === model).getAttribute('display'),stage.model)).toBe('none');
    await page.locator(`input.tierbox[value="${stage.parent.tier}"]`).first().check();
    expect(await stageLink.evaluateAll((nodes,model) => nodes.find(n => n.__data__.model === model).getAttribute('display'),stage.model)).toBe(null);
    await page.getByRole('button',{name:'Report',exact:true}).click();
    await expect(releaseRow(page,stage).locator('td.level')).toHaveAttribute('title',core.reportLevel(stage));
    await page.getByRole('button',{name:'Copy',exact:true}).click();
    await expect.poll(() => page.evaluate(() => window.__copiedReport)).toContain(core.reportLevel(stage));
    await page.emulateMedia({media:'print'});
    await expect(releaseRow(page,stage).locator('td.level')).toBeVisible();
  });
}

test('overlapping folded marks receive natural clicks in the full timeline', async ({page}) => {
  const {joinedRows} = require('./helpers/timeline-page');
  const rows = joinedRows();
  await page.setViewportSize({width:1440,height:900});
  await page.goto(pathToFileURL(path.join(__dirname,'..','ai-model-timeline.html')).href);
  await page.getByRole('button',{name:'All',exact:true}).click();
  await page.getByRole('button',{name:'Everything',exact:true}).click();
  expect(await page.locator('#chartwrap text.mlabel').evaluateAll(nodes => nodes.filter(n => n.__data__.of && n.getAttribute('display') !== 'none').length)).toBe(0);
  for (const model of ['GPT-Live-1.1 (API release)', 'Gemini 3.8 Live with Live Avatar']) {
    const row = rows.find(item => item.model === model);
    const dot = await dotFor(page,row);
    await dot.scrollIntoViewIfNeeded();
    const box = await dot.boundingBox();
    await page.mouse.click(box.x + box.width/2, box.y + box.height/2);
    await expect.soft(page.locator('#tooltip .tt-model')).toContainText(model, {timeout:1000});
    await page.keyboard.press('Escape');
  }
  await page.getByRole('button',{name:'Month',exact:true}).click();
  expect(await page.locator('#chartwrap circle.dot').evaluateAll(nodes => nodes.filter(n => n.__data__.of && n.getAttribute('display') !== 'none').length)).toBeGreaterThan(0);
  expect(await page.locator('#chartwrap text.mlabel').evaluateAll(nodes => nodes.filter(n => n.__data__.of && n.getAttribute('display') !== 'none').length)).toBe(0);
});

test('dense phone timeline keeps main and folded dots naturally clickable', async ({page}) => {
  const {joinedRows} = require('./helpers/timeline-page');
  const rows = joinedRows();
  await page.setViewportSize({width:375,height:900});
  await page.goto(pathToFileURL(path.join(__dirname,'..','ai-model-timeline.html')).href);
  await page.getByRole('button',{name:'Everything',exact:true}).click();
  const nativeTargets = ['Phai-M1','Kanana-2-v-decide-3b-2611','Qwen3.8-Omni-Flash-Realtime'];
  for (const model of ['CSAM Image Classifier','Olala mini 7A1B','Edge0-145B / Edge0-120B','Sarvam-105B-1711 (hosted rollout)',...nativeTargets]) {
    const row = rows.find(r => r.model === model);
    await page.mouse.move(10,100);
    const dot = await dotFor(page,row);
    await dot.scrollIntoViewIfNeeded();
    const points = await dot.evaluate((node, nativeOnly) => {
      const rect = node.getBoundingClientRect(), x = rect.x + rect.width/2, y = rect.y + rect.height/2, r = +node.getAttribute('r') + (nativeOnly ? 0.75 : 0);
      const result = [];
      for (let py = Math.ceil(y-r); py <= Math.floor(y+r); py++) for (let px = Math.ceil(x-r); px <= Math.floor(x+r); px++) {
        const distance = Math.hypot(px-x,py-y);
        const hit = document.elementFromPoint(px,py);
        if (distance <= r && (nativeOnly ? hit === node : hit?.classList.contains('dot'))) result.push({x:px,y:py,distance});
      }
      return result.sort((a,b) => a.distance-b.distance);
    }, nativeTargets.includes(model));
    let found = false;
    for (const point of points) {
      await page.mouse.click(point.x,point.y);
      const text = await page.locator('#tooltip .tt-model').textContent();
      if (text.startsWith(model)) {
        found = true;
        await page.keyboard.press('Escape');
        await page.mouse.move(10,point.y);
        await page.mouse.move(point.x,point.y);
        await expect.soft(page.locator('#tooltip .tt-model')).toContainText(model);
        break;
      }
      await page.keyboard.press('Escape');
    }
    expect.soft(found, `${model} has a natural click point among ${points.length} visible points`).toBe(true);
  }
});
