const { expect, test } = require('@playwright/test');

test.beforeEach(async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto('/drawdown.html');
  page._drawdownErrors = errors;
});

test.afterEach(async ({ page }) => { expect(page._drawdownErrors).toEqual([]); });

test('subcent monetary detail is honest and visible on keyboard focus', async ({ page }) => {
  await page.evaluate(() => {
    Object.assign(state.params, { buffer_initial: 10, floor: 0, investments_initial: 0,
      investment_income: 0, external_income: 0, expense: 0.004, inflation: 0,
      tax_rate: 0, sale_tax_rate: 0, modifier: 1, unit: 'months', num_periods: 1 });
    acceptPins([]);
    rerender();
  });
  const row = page.locator('#amort-body tr[data-month="1"]');
  const expense = row.locator('td[data-key="expense"]');
  await expect(expense).toHaveText('$0');
  await expect(expense).toHaveAttribute('title', /Changes this value going forward.*Rounded to cents \$0\.00.*Model value \$0\.004/);
  await expect(expense).toHaveAttribute('tabindex', '0');
  await expense.focus();
  const detail = await expense.evaluate(cell => getComputedStyle(cell, '::after').content);
  expect(detail).toContain('Rounded to cents');
  expect(detail).toContain('Model value $0.004');
  await page.keyboard.press('Tab');
  await expect(row.locator('td[data-key="investment_income"]')).toBeFocused();
  const delta = row.locator('.delta-neg');
  await expect(delta).toHaveAttribute('title', /Rounded to cents −\$0\.00.*Model value −\$0\.004/);
});

test('annual table names both actual endpoint months and editor uses the planned span', async ({ page }) => {
  const dates = await page.evaluate(() => ({
    first: fmtDate(dateForMonth(1), 'months'),
    eighth: fmtDate(dateForMonth(8), 'months'),
    twelfth: fmtDate(dateForMonth(12), 'months'),
  }));
  await page.evaluate(() => {
    Object.assign(state.params, { buffer_initial: 70, floor: 0, investments_initial: 0,
      investment_income: 0, external_income: 0, expense: 10, inflation: 0,
      tax_rate: 0, sale_tax_rate: 0, modifier: 1, unit: 'years', num_periods: 1 });
    acceptPins([]);
    rerender();
  });
  const row = page.locator('#amort-body tr[data-month="1"]');
  await expect(row.locator('.col-period')).toHaveText('Y 1');
  await expect(row.locator('.col-date')).toHaveText(`${dates.first}–${dates.eighth}`);
  await row.locator('td[data-key="expense"]').click();
  await expect(page.locator('.cell-edit-details')).toContainText(`Annual total · ${dates.first}–${dates.twelfth}`);
  await page.locator('.cell-edit-input').press('Escape');

  await page.evaluate(() => {
    const params = { ...state.params, unit: 'months', num_periods: 8,
      buffer_initial: 100, expense: 0 };
    const result = simulate(params, []);
    state.params = { ...params, unit: 'years', num_periods: 1 };
    state.acceptedResult = result;
    renderTable(aggregateForView(result.rows, 'years', result.plannedLastMonth, []), result.rows, result);
  });
  await expect(row.locator('.col-date')).toHaveText(`${dates.first}–${dates.eighth}`);
  await row.locator('td[data-key="expense"]').click();
  await expect(page.locator('.cell-edit-details')).toContainText(`8-month total · ${dates.first}–${dates.eighth}`);
});

test('effective floor and precise cents remain visible after a fractional edit', async ({ page }) => {
  await page.evaluate(() => {
    acceptPins([{ id: 'synthetic-floor', at_month: 1, start: { floor: 120000 }, end: {} },
      { id: 'synthetic-cent', at_month: 2, start: { expense: 0.56 }, end: {} }]);
    rerender();
  });
  await expect(page.locator('#stats')).toContainText('floor at $120K');
  expect(await page.locator('#chart path[data-series="floor"]').count()).toBe(1);
  const cell = page.locator('#amort-body tr[data-month="2"] td[data-key="expense"]');
  await expect(cell).toHaveText('$1');
  await expect(cell).toHaveAttribute('title', /\$0\.56/);
  await cell.click();
  await page.locator('.cell-edit-input').press('Enter');
  expect(await page.evaluate(() => state.pins.find(p => p.id === 'synthetic-cent').start.expense)).toBe(0.56);
});

test('chart uses each effective floor and includes a raised floor in its bounds', async ({ page }) => {
  await page.evaluate(() => {
    acceptPins([{ id: 'synthetic-floor-one', at_month: 1, start: { floor: 120000 }, end: {} },
      { id: 'synthetic-floor-two', at_month: 2, start: { floor: 900000 }, end: {} }]);
    rerender();
  });
  const chart = page.locator('#chart');
  for (const series of ['cash', 'principal', 'floor']) {
    await expect(chart.locator(`path[data-series="${series}"]`)).toHaveCount(1);
  }
  const floorPath = await chart.locator('path[data-series="floor"]').getAttribute('d');
  const ys = [...floorPath.matchAll(/[ML] [\d.]+ ([\d.]+)/g)].map(match => Number(match[1]));
  expect(new Set(ys).size).toBeGreaterThan(1);
  expect(Math.min(...ys)).toBeGreaterThanOrEqual(8);
  await expect(page.locator('#chart-y-labels')).toContainText('floor $900K');
});

test('reserve failure names funded expense and retains principal with full sale tax', async ({ page }) => {
  await page.evaluate(() => {
    Object.assign(state.params, { buffer_initial: 10, floor: 10, investments_initial: 100,
      investment_income: 0, external_income: 0, expense: 1, sale_tax_rate: 1,
      tax_rate: 0, num_periods: 12, unit: 'months' });
    acceptPins([]);
    rerender();
  });
  await expect(page.locator('#stats')).toContainText('Reserve cannot be maintained at month 1');
  await expect(page.locator('#amort-body tr[data-month="1"]')).not.toContainText('sold from principal');
  await expect(page.locator('#table-footer')).toContainText('Last fully funded month 0');
  await expect(page.locator('#table-footer')).toContainText('Required expense $1, funded expense $0, unmet expense $1, unmet reserve $0');
  await expect(page.locator('#stats .stat').filter({ hasText: 'Ending principal' })).toContainText('$100');
  await expect(page.locator('#chart')).toContainText('reserve failure');
});

test('empty projection renders a controlled status and clears chart labels', async ({ page }) => {
  await page.evaluate(() => {
    renderStats([], { terminatedReason: 'invalid' });
    renderChart([]);
  });
  await expect(page.locator('#stats')).toContainText('Projection unavailable');
  await expect(page.locator('#chart path')).toHaveCount(0);
  await expect(page.locator('#chart-y-labels')).toBeEmpty();
  await expect(page.locator('#chart-x-labels')).toBeEmpty();
});

test('download includes exact raw values from the accepted visible scenario', async ({ page }) => {
  await page.locator('#expense').fill('0.56');
  const downloadPromise = page.waitForEvent('download');
  await page.locator('#export-csv').click();
  const download = await downloadPromise;
  const stream = await download.createReadStream();
  let csv = '';
  for await (const chunk of stream) csv += chunk.toString();
  const headers = csv.split('\n')[0].split(',');
  const first = csv.split('\n')[1].split(',');
  expect(headers.includes('expense_raw')).toBe(true);
  expect(first[headers.indexOf('expense_raw')]).toBe('0.56');
  expect(first[headers.indexOf('expense')]).toBe('0.56');
  expect(await page.evaluate(() => state.acceptedResult.rows[0].expense)).toBe(0.56);
});

test('annual expense cell sets an exact yearly target and shows its monthly assumption', async ({ page }) => {
  await page.locator('#unit-years').click();
  await page.locator('#amort-body tr[data-month="1"] td[data-key="expense"]').click();
  await expect(page.locator('.cell-edit-input')).toBeVisible();
  await page.locator('.cell-edit-input').fill('72000');
  await page.locator('.cell-edit-input').press('Enter');
  await expect(page.locator('#amort-body tr[data-month="1"] td[data-key="expense"]')).toHaveText('$72,000');
  expect(await page.evaluate(() => state.pins[0].annual_edits.expense.target_total)).toBe(72000);
  const actualTotal = await page.evaluate(() => state.acceptedResult.rows.slice(0, 12)
    .reduce((sum, row) => sum + row.expense, 0));
  expect(Math.abs(actualTotal - 72000)).toBeLessThanOrEqual(1e-6);
});

test('yearly closing edit targets the last funded month and row lists exact adjustment identities', async ({ page }) => {
  await page.locator('#amort-body tr[data-month="8"] .pin-action').first().click();
  await page.locator('.pin-field-input[data-phase="start"][data-key="expense"]').fill('5100');
  await page.locator('#pin-save').click();
  await page.locator('#unit-years').click();
  await page.locator('#amort-body tr[data-month="1"] td[data-key="buffer"]').click();
  await page.locator('.cell-edit-input').fill('222000');
  await page.locator('.cell-edit-input').press('Enter');
  expect(await page.evaluate(() => state.pins.map(p => p.at_month))).toEqual([8,12]);
  await page.locator('#amort-body tr[data-month="1"] .pin-action[data-month="8"]').click();
  await expect(page.locator('#pin-month')).toHaveValue('8');
});

test('untouched fractional override survives no-op save and an unrelated full-editor change', async ({ page }) => {
  await page.locator('#amort-body tr[data-month="1"] td[data-key="expense"]').click();
  await page.locator('.cell-edit-input').fill('5000.1234');
  await page.locator('.cell-edit-input').press('Enter');
  expect(await page.evaluate(() => state.pins[0].start.expense)).toBe(5000.1234);
  await page.locator('#amort-body tr[data-month="1"] td[data-key="expense"]').click();
  await page.locator('.cell-edit-input').press('Enter');
  expect(await page.evaluate(() => state.pins[0].start.expense)).toBe(5000.1234);
  await page.locator('#adjustments-list .adj-entry').click();
  await page.locator('.pin-field-input[data-phase="start"][data-key="external_income"]').fill('2100');
  await page.locator('#pin-save').click();
  expect(await page.evaluate(() => state.pins[0].start.expense)).toBe(5000.1234);
});

test('occupied adjustment move stays open with an error and preserves both records', async ({ page }) => {
  for (const month of [1,2]) {
    await page.locator(`#amort-body tr[data-month="${month}"] .pin-action`).first().click();
    await page.locator('.pin-field-input[data-phase="start"][data-key="expense"]').fill(String(5000+month));
    await page.locator('#pin-save').click();
  }
  await page.locator('#adjustments-list .adj-entry[data-month="1"]').click();
  await page.locator('#pin-month').fill('2');
  await page.locator('#pin-save').click();
  await expect(page.locator('#pin-month')).toHaveValue('2');
  await expect(page.locator('#pin-editor-error')).toContainText('Another adjustment already occupies that month.');
  expect(await page.evaluate(() => state.pins.map(p => p.at_month))).toEqual([1,2]);
});

test('subcent solved assumption stays exact through no-op, reverted draft, and Escape', async ({ page }) => {
  await page.evaluate(() => {
    acceptPins([{ id: 'synthetic', at_month: 1, start: { investment_income: 6000.001234 }, end: {} }]);
    rerender();
  });
  const cell = page.locator('#amort-body tr[data-month="1"] td[data-key="investment_income"]');
  await cell.click();
  await expect(page.locator('.cell-edit-input')).toHaveValue('6000.00');
  await page.locator('.cell-edit-input').fill('6001');
  await page.locator('.cell-edit-input').fill('6000.00');
  await page.locator('.cell-edit-input').press('Enter');
  expect(await page.evaluate(() => state.pins[0].start.investment_income)).toBe(6000.001234);
  await cell.click();
  await page.locator('.cell-edit-input').fill('7000');
  await page.locator('.cell-edit-input').press('Escape');
  expect(await page.evaluate(() => state.pins[0].start.investment_income)).toBe(6000.001234);
  await page.locator('#adjustments-list .adj-entry').click();
  await page.locator('#pin-save').click();
  expect(await page.evaluate(() => state.pins[0].start.investment_income)).toBe(6000.001234);
});

test('reset removes a precise override without parsing its rounded baseline', async ({ page }) => {
  await page.evaluate(() => {
    acceptPins([{ id: 'synthetic', at_month: 1, start: { expense: 5000.001234 }, end: {} }]);
    rerender();
  });
  await page.locator('#adjustments-list .adj-entry').click();
  await page.locator('.pin-reset-field[data-phase="start"][data-key="expense"]').click();
  await page.locator('#pin-save').click();
  expect(await page.evaluate(() => state.pins)).toEqual([]);
});

test('pending sidebar change is used when saving a cell and exporting', async ({ page }) => {
  await page.locator('#expense').fill('6000');
  await page.locator('#amort-body tr[data-month="1"] td[data-key="buffer"]').click();
  await page.locator('.cell-edit-input').fill('200000');
  await page.locator('.cell-edit-input').press('Enter');
  expect(await page.evaluate(() => state.params.expense)).toBe(6000);
  await page.locator('#expense').fill('7000');
  const download = page.waitForEvent('download');
  await page.locator('#export-csv').click();
  await download;
  expect(await page.evaluate(() => state.params.expense)).toBe(7000);
});

test('annual income solver ignores completion after view switch', async ({ page }) => {
  await page.evaluate(() => {
    const original = solveAnnualTarget;
    let release;
    window.releaseAnnualTrial = () => release?.();
    solveAnnualTarget = async (...args) => {
      await new Promise(resolve => { release = resolve; });
      return original(...args);
    };
  });
  await page.locator('#unit-years').click();
  await page.locator('#amort-body tr[data-month="1"] td[data-key="investment_income"]').click();
  await page.locator('.cell-edit-input').fill('80000');
  await page.locator('.cell-edit-input').press('Enter');
  await expect(page.locator('.cell-edit-feedback')).toContainText('Solving');
  await page.locator('#unit-months').click();
  await page.evaluate(() => window.releaseAnnualTrial());
  await expect(page.locator('#unit-months')).toHaveClass(/active/);
  expect(await page.evaluate(() => state.params.unit)).toBe('months');
  expect(await page.evaluate(() => state.pins.some(pin => pin.annual_edits?.investment_income))).toBe(false);
});

test('annual investment income cell solves exact yearly sum and exposes derivation', async ({ page }) => {
  await page.locator('#unit-years').click();
  await page.locator('#amort-body tr[data-month="1"] td[data-key="investment_income"]').click();
  await page.locator('.cell-edit-input').fill('78000');
  await page.locator('.cell-edit-input').press('Enter');
  await expect.poll(() => page.evaluate(() => state.pins[0]?.annual_edits?.investment_income?.target_total)).toBe(78000);
  const total = await page.evaluate(() => state.acceptedResult.rows.slice(0,12).reduce((sum,row) => sum + row.investment_income, 0));
  expect(Math.abs(total-78000)).toBeLessThanOrEqual(1e-6);
  await expect(page.locator('#adjustments-list')).toContainText('derived monthly assumption');
  await expect(page.locator('#adjustments-list')).toContainText('effective');
});

test('sidebar change invalidates pending annual solve and duplicate Enter cannot save twice', async ({ page }) => {
  await page.evaluate(() => {
    const original = solveAnnualTarget;
    let release;
    window.releaseAnnualTrial = () => release?.();
    solveAnnualTarget = async (...args) => {
      await new Promise(resolve => { release = resolve; });
      return original(...args);
    };
  });
  await page.locator('#unit-years').click();
  await page.locator('#amort-body tr[data-month="1"] td[data-key="investment_income"]').click();
  await page.locator('.cell-edit-input').fill('80000');
  await page.locator('.cell-edit-input').press('Enter');
  await expect(page.locator('.cell-edit-input')).toBeDisabled();
  const revisionDuringTrial = await page.evaluate(() => state.revision);
  await page.locator('.cell-edit-input').dispatchEvent('keydown', { key: 'Enter' });
  expect(await page.evaluate(() => state.revision)).toBe(revisionDuringTrial);
  await page.locator('#expense').fill('5100');
  await page.locator('#calc-button').click();
  await page.evaluate(() => window.releaseAnnualTrial());
  expect(await page.evaluate(() => state.params.expense)).toBe(5100);
  expect(await page.evaluate(() => state.pins.length)).toBe(0);
});

test('two Enter presses during annual solve produce one accepted transaction', async ({ page }) => {
  await page.evaluate(() => {
    const original = solveAnnualTarget;
    let release;
    window.releaseAnnualTrial = () => release?.();
    window.solveCalls = 0;
    solveAnnualTarget = async (...args) => {
      window.solveCalls++;
      await new Promise(resolve => { release = resolve; });
      return original(...args);
    };
  });
  await page.locator('#unit-years').click();
  await page.locator('#amort-body tr[data-month="1"] td[data-key="investment_income"]').click();
  await page.locator('.cell-edit-input').fill('80000');
  const revisionBefore = await page.evaluate(() => state.revision);
  await page.locator('.cell-edit-input').press('Enter');
  await expect(page.locator('.cell-edit-input')).toBeDisabled();
  await page.keyboard.press('Enter');
  expect(await page.evaluate(() => window.solveCalls)).toBe(1);
  await page.evaluate(() => window.releaseAnnualTrial());
  await expect.poll(() => page.evaluate(() => state.pins.length)).toBe(1);
  expect(await page.evaluate(() => state.revision)).toBe(revisionBefore + 1);
});

test('full editor preserves an unsaved field through sidebar debounce', async ({ page }) => {
  await page.locator('#amort-body tr[data-month="1"] .pin-action').first().click();
  const expense = page.locator('.pin-field-input[data-phase="start"][data-key="expense"]');
  await expense.fill('5500');
  await page.locator('#external-income').fill('2200');
  await expect.poll(() => page.evaluate(() => state.params.external_income)).toBe(2200);
  await expect(expense).toHaveValue('5500');
  await expect(expense.locator('xpath=..').locator('xpath=..')).toHaveClass(/changed/);
  await page.locator('#pin-save').click();
  expect(await page.evaluate(() => state.pins[0]?.start.expense)).toBe(5500);
});

test('unsaved adjustment remains editable when sidebar shortens the horizon', async ({ page }) => {
  await page.locator('#amort-body tr[data-month="8"] .pin-action').first().click();
  await page.locator('.pin-field-input[data-phase="start"][data-key="expense"]').fill('5500');
  await page.locator('#periods').fill('3');
  await expect.poll(() => page.evaluate(() => state.params.num_periods)).toBe(3);
  await expect(page.locator('#adjustments-list .pin-field-input[data-phase="start"][data-key="expense"]')).toHaveValue('5500');
  await page.locator('#pin-save').click();
  expect(await page.evaluate(() => state.pins[0]?.at_month)).toBe(8);
  expect(await page.evaluate(() => state.pins[0]?.start.expense)).toBe(5500);
});

test('full editor marks monthly flows without labeling balances monthly', async ({ page }) => {
  await page.locator('#amort-body tr[data-month="1"] .pin-action').first().click();
  await expect(page.locator('.pin-editor-field[data-phase="start"][data-key="expense"] label')).toContainText('(monthly)');
  await expect(page.locator('.pin-editor-field[data-phase="start"][data-key="investment_income"] label')).toContainText('(monthly)');
  for (const [phase, key] of [['start','floor'], ['end','buffer'], ['end','investments']]) {
    await expect(page.locator(`.pin-editor-field[data-phase="${phase}"][data-key="${key}"] label`)).not.toContainText('(monthly)');
  }
});

test('full editor can set a baseline explicitly at the same displayed amount', async ({ page }) => {
  await page.locator('#amort-body tr[data-month="1"] .pin-action').first().click();
  await page.locator('#pin-reset-income').click();
  await page.locator('#pin-save').click();
  expect(await page.evaluate(() => state.pins[0].start.investment_income)).toBe(6000);
});

test('blurring an untouched cents display preserves fractional projection', async ({ page }) => {
  await page.evaluate(() => {
    acceptPins([{ id: 'synthetic', at_month: 1, start: { expense: 5000.001234 }, end: {} }]);
    rerender();
  });
  const before = await page.evaluate(() => JSON.stringify(state.acceptedResult.rows));
  await page.locator('#amort-body tr[data-month="1"] td[data-key="expense"]').click();
  await page.locator('#today-stamp').click();
  expect(await page.evaluate(() => JSON.stringify(state.acceptedResult.rows))).toBe(before);
  expect(await page.evaluate(() => state.pins[0].start.expense)).toBe(5000.001234);
});

test('numeric equivalent of displayed cents preserves exact override until explicit reset', async ({ page }) => {
  await page.evaluate(() => {
    acceptPins([{ id: 'synthetic', at_month: 1, start: { expense: 5000.001234 }, end: {} }]);
    rerender();
  });
  const cell = page.locator('#amort-body tr[data-month="1"] td[data-key="expense"]');
  await cell.click();
  await expect(page.locator('.cell-edit-input')).toHaveValue('5000.00');
  await page.locator('.cell-edit-input').fill('5000');
  await page.locator('.cell-edit-input').press('Enter');
  expect(await page.evaluate(() => state.pins[0].start.expense)).toBe(5000.001234);
  await cell.click();
  await page.locator('.cell-reset-field').click();
  expect(await page.evaluate(() => state.pins)).toEqual([]);
});

test('failed-month end-only adjustment is marked unapplied in yearly table', async ({ page }) => {
  for (const [selector, value] of [
    ['#buffer-initial', '100'], ['#floor', '100'], ['#investments-initial', '0'],
    ['#investment-income', '0'], ['#external-income', '0'], ['#expense', '10'],
  ]) await page.locator(selector).fill(value);
  await page.locator('#calc-button').click();
  await page.evaluate(() => {
    acceptPins([{ id: 'synthetic', at_month: 1, start: {}, end: { buffer: 100 } }]);
    rerender();
  });
  await expect(page.locator('#adjustments-list')).toContainText('End unapplied');
  await page.locator('#unit-years').click();
  await expect(page.locator('#amort-body tr[data-month="1"] .col-notes')).toContainText('unapplied month 1');
  await expect(page.locator('#amort-body tr[data-month="1"] .col-notes')).not.toContainText('adjusted month 1');
});
