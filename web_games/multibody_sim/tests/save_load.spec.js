const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');

async function openApp(page) {
  await page.goto('/index.html');
  await page.waitForFunction(() => !!window.__multibodyTestApi);
  await page.selectOption('#modeSelect', 'user');
  await page.waitForFunction(() => {
    const snapshot = window.__multibodyTestApi.getSnapshot();
    return snapshot.mode === 'user' && !snapshot.running;
  });
}

async function upload(page, file, name) {
  await page.locator('#loadFileInput').setInputFiles(file);
  await expect.poll(() => page.evaluate(() => window.__multibodyTestApi.getSnapshot().warningText))
    .toBe(`Loaded setup from ${name}.`);
}

for (const name of ['multibody-test-1.json', 'multibody-test-2.json', 'multibody-test-3.json']) {
  test(`loads bundled sample ${name}`, async ({ page }) => {
    const file = path.join(__dirname, '..', name);
    const payload = JSON.parse(fs.readFileSync(file, 'utf8'));
    await openApp(page);
    await upload(page, file, name);
    const snapshot = await page.evaluate(() => window.__multibodyTestApi.getSnapshot());
    expect(snapshot.mode).toBe('user');
    expect(snapshot.running).toBe(false);
    expect(snapshot.bodyIds).toEqual((payload.userSetupBaseline?.bodies?.length
      ? payload.userSetupBaseline.bodies : payload.bodies).map(body => body.id));
    if (payload.settings?.epsilon !== undefined) expect(snapshot.epsilon).toBe(payload.settings.epsilon);
  });
}

test('save then reload restores the scene', async ({ page }) => {
  await page.addInitScript(() => { delete window.showSaveFilePicker; });
  await openApp(page);
  await upload(page, path.join(__dirname, '..', 'multibody-test-3.json'), 'multibody-test-3.json');
  const before = await page.evaluate(() => ({
    bodies: window.__multibodyTestApi.getBodies().map(({ id, mass }) => ({ id, mass })),
    epsilon: window.__multibodyTestApi.getSnapshot().epsilon
  }));
  const [download] = await Promise.all([page.waitForEvent('download'), page.click('#saveBtn')]);
  const savedFile = await download.path();
  await openApp(page);
  await upload(page, savedFile, path.basename(savedFile));
  const after = await page.evaluate(() => ({
    bodies: window.__multibodyTestApi.getBodies().map(({ id, mass }) => ({ id, mass })),
    epsilon: window.__multibodyTestApi.getSnapshot().epsilon
  }));
  expect(after).toEqual(before);
});

test('rejects malformed setups without replacing bodies', async ({ page }) => {
  await openApp(page);
  await upload(page, path.join(__dirname, '..', 'multibody-test-3.json'), 'multibody-test-3.json');
  const before = await page.evaluate(() => window.__multibodyTestApi.getSnapshot().bodyIds);
  for (const [payload, message] of [[{}, 'JSON must include a bodies array.'],
    [{ bodies: [] }, 'No valid bodies found in JSON.']]) {
    await page.locator('#loadFileInput').setInputFiles({
      name: 'invalid.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(payload))
    });
    await expect.poll(() => page.evaluate(() => window.__multibodyTestApi.getSnapshot().warningText))
      .toBe(`Load failed: ${message}`);
    expect(await page.evaluate(() => window.__multibodyTestApi.getSnapshot().bodyIds)).toEqual(before);
  }
});

test('body snapshots cannot mutate the scene', async ({ page }) => {
  await openApp(page);
  await upload(page, path.join(__dirname, '..', 'multibody-test-3.json'), 'multibody-test-3.json');
  const result = await page.evaluate(() => {
    const original = window.__multibodyTestApi.getBodies();
    const snapshot = window.__multibodyTestApi.getBodies();
    snapshot[0].mass = -1;
    snapshot[0].vel.x = -1;
    snapshot.pop();
    return { original, current: window.__multibodyTestApi.getBodies() };
  });
  expect(result.current).toEqual(result.original);
  expect(Object.keys(result.current[0]).sort()).toEqual(['id', 'isSingularity', 'mass', 'vel']);
});

test('merge conserves mass and momentum', async ({ page }) => {
  await openApp(page);
  const payload = {
    type: 'multibody-user-setup', version: 3,
    settings: { autoAssignOnStart: false, G: 1, epsilon: 5 },
    bodies: [
      { id: 1, pos: { x: 0, y: 0 }, mass: 10, vel: { x: 1, y: 0 } },
      { id: 2, pos: { x: 0, y: 0 }, mass: 30, vel: { x: 0, y: 2 } }
    ]
  };
  await upload(page, { name: 'synthetic-merge.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(payload)) }, 'synthetic-merge.json');
  await page.click('#startPauseBtn');
  await page.waitForFunction(() => window.__multibodyTestApi.getBodies().length === 1);
  const [body] = await page.evaluate(() => window.__multibodyTestApi.getBodies());
  for (const [actual, expected] of [[body.mass, 40], [body.vel.x, 0.25], [body.vel.y, 1.5],
    [body.mass * body.vel.x, 10], [body.mass * body.vel.y, 60]]) {
    expect(Math.abs(actual - expected)).toBeLessThanOrEqual(Math.abs(expected) * 1e-6);
  }
});
