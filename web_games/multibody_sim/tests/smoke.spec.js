const { test, expect } = require('@playwright/test');

async function openApp(page) {
  await page.goto('/index.html');
  await page.waitForFunction(() => !!window.__multibodyTestApi);
  await page.waitForTimeout(300);
}

async function switchToUserMode(page) {
  await page.selectOption('#modeSelect', 'user');
  await page.waitForFunction(() => {
    const snap = window.__multibodyTestApi.getSnapshot();
    return snap.mode === 'user' && snap.running === false;
  });
}

test('initial load starts in screensaver with active bodies', async ({ page }) => {
  await openApp(page);
  const result = await page.evaluate(() => window.__multibodyTestApi.getSnapshot());
  expect(result.mode).toBe('screensaver');
  expect(result.running).toBe(true);
  expect(result.bodies).toBeGreaterThanOrEqual(2);
});

test('switching to user mode pauses and clears setup', async ({ page }) => {
  await openApp(page);
  await switchToUserMode(page);
  const result = await page.evaluate(() => window.__multibodyTestApi.getSnapshot());
  expect(result.mode).toBe('user');
  expect(result.running).toBe(false);
  expect(result.bodies).toBe(0);
});

test('clicking canvas in user mode creates a body', async ({ page }) => {
  await openApp(page);
  await switchToUserMode(page);
  await page.locator('#canvas').click({ position: { x: 520, y: 380 } });
  await page.waitForFunction(() => window.__multibodyTestApi.getSnapshot().bodies === 1);
  const selectedId = await page.evaluate(() => window.__multibodyTestApi.getSnapshot().selectedBodyId);
  expect(selectedId).toBe(1);
});

test('user mode can start simulation after placing two bodies', async ({ page }) => {
  await openApp(page);
  await switchToUserMode(page);
  await page.locator('#canvas').click({ position: { x: 460, y: 340 } });
  await page.locator('#canvas').click({ position: { x: 640, y: 440 } });
  await page.click('#startPauseBtn');
  await page.waitForFunction(() => window.__multibodyTestApi.getSnapshot().running === true);
  const bodyCount = await page.evaluate(() => window.__multibodyTestApi.getSnapshot().bodies);
  expect(bodyCount).toBe(2);
});

test('start button toggles to pause while simulation is running', async ({ page }) => {
  await openApp(page);
  await switchToUserMode(page);
  await page.locator('#canvas').click({ position: { x: 450, y: 360 } });
  await page.locator('#canvas').click({ position: { x: 660, y: 420 } });
  await page.click('#startPauseBtn');
  await page.waitForFunction(() => window.__multibodyTestApi.getSnapshot().running === true);
  await page.click('#startPauseBtn');
  await page.waitForFunction(() => window.__multibodyTestApi.getSnapshot().running === false);
  const label = await page.locator('#startPauseBtn').textContent();
  expect(label).toBe('Start');
});

test('delete selected removes the chosen body in user mode', async ({ page }) => {
  await openApp(page);
  await switchToUserMode(page);
  await page.locator('#canvas').click({ position: { x: 460, y: 340 } });
  await page.locator('#canvas').click({ position: { x: 640, y: 440 } });
  await page.click('#deleteBodyBtn');
  await page.waitForFunction(() => window.__multibodyTestApi.getSnapshot().bodies === 1);
  const remainingIds = await page.evaluate(() => window.__multibodyTestApi.getSnapshot().bodyIds);
  expect(remainingIds).toEqual([1]);
});

test('deleting followed body resets camera to auto and warns', async ({ page }) => {
  await openApp(page);
  await switchToUserMode(page);
  await page.locator('#canvas').click({ position: { x: 520, y: 380 } });
  await page.selectOption('#cameraSubjectMode', 'object');
  await page.click('#deleteBodyBtn');
  await page.waitForFunction(() => window.__multibodyTestApi.getSnapshot().cameraSubjectMode === 'auto');
  const warning = await page.locator('#warningText').textContent();
  expect(warning).toContain('camera set to Auto');
});

test('epsilon slider accepts zero without crashing state', async ({ page }) => {
  await openApp(page);
  await page.locator('#epsilon').evaluate((el) => {
    el.value = '0';
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await page.waitForFunction(() => window.__multibodyTestApi.getSnapshot().epsilon === 0);
  const hasInvalid = await page.evaluate(() => window.__multibodyTestApi.hasInvalidBodyState());
  expect(hasInvalid).toBe(false);
});

test('screensaver body count control regenerates exact count', async ({ page }) => {
  await openApp(page);
  await page.fill('#screensaverNInput', '7');
  await page.dispatchEvent('#screensaverNInput', 'input');
  await page.waitForFunction(() => window.__multibodyTestApi.getSnapshot().bodies === 7);
  const count = await page.evaluate(() => window.__multibodyTestApi.getSnapshot().bodies);
  expect(count).toBe(7);
});

test('singularity max is respected for generated screensaver setup', async ({ page }) => {
  await openApp(page);
  await page.fill('#screensaverNInput', '8');
  await page.dispatchEvent('#screensaverNInput', 'input');
  await page.fill('#screensaverSingularityChanceInput', '100');
  await page.dispatchEvent('#screensaverSingularityChanceInput', 'input');
  await page.fill('#screensaverSingularityMaxInput', '1');
  await page.dispatchEvent('#screensaverSingularityMaxInput', 'input');
  await page.waitForFunction(() => window.__multibodyTestApi.getSnapshot().bodies === 8);
  const singularities = await page.evaluate(() => window.__multibodyTestApi.getSnapshot().singularities);
  expect(singularities).toBeLessThanOrEqual(1);
});
