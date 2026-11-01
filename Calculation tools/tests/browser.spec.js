const { expect, test } = require('@playwright/test');

test('early payoff preserves value when vendor and discount rates match', async ({ page }) => {
  await page.goto('/early_loan_termination_calculator.html');
  await page.locator('#price').fill('10000');
  await page.locator('#vendorRate').fill('12');
  await page.locator('#disc').fill('12');
  await page.locator('#timing').selectOption('end');
  await page.locator('#calcBtn').click();
  const savings = await page.evaluate(() => state.savingsRows.map(row => row[1]));
  for (const value of savings) expect(value).toBeLessThan(1e-8);
  const presentValues = await page.evaluate(() => {
    const P = paymentPMT(0.01, 24, 10000);
    return Array.from({length: 24}, (_, x) => scenarioPV({price: 10000, down: 0, term: 24, P, i_v: 0.01, i_d: 0.01, X: x + 1, timing: 'end'}));
  });
  for (const value of presentValues) expect(value).toBeCloseTo(10000, 8);
  // Unequal rates: month-one cash flows are one payment at t=1 and the
  // remaining balance with one month's interest at t=2.
  const actual = await page.evaluate(() => scenarioPV({price: 0, down: 0, term: 2, P: 104, i_v: 0.04, i_d: 0.02, X: 1, timing: 'end'}));
  expect(actual).toBeCloseTo(104 / 1.02 + 104 / (1.02 ** 2), 9);
});

test('immediate loan payments use annuity-due amounts and accrue after the first payment', async ({ page }) => {
  await page.goto('/early_loan_termination_calculator.html');
  await page.locator('#price').fill('110');
  await page.locator('#down').fill('10');
  await page.locator('#term').fill('2');
  await page.locator('#vendorRate').fill('120');
  await page.locator('#disc').fill('120');
  await page.locator('#timing').selectOption('immediate');
  await page.locator('#calcBtn').click();
  await expect(page.locator('#amortTbl tbody tr').first().locator('td')).toHaveText(['1', '52.38', '52.38', '0.00', '47.62']);
  await expect(page.locator('#amortTbl tbody tr').last().locator('td')).toHaveText(['2', '52.38', '47.62', '4.76', '0.00']);
  const values = await page.evaluate(() => {
    const cases = [{down: 10, term: 2, rate: 0.1}, {down: 10, term: 3, rate: 0}, {down: 10, term: 1, rate: 0.1}];
    return cases.flatMap(({down, term, rate}) => {
      const P = paymentPMT(rate, term, 110 - down);
      return ['immediate', 'end'].flatMap(timing => Array.from({length: term}, (_, x) => scenarioPV({price: 110, down, term, P, i_v: rate, i_d: rate, X: x + 1, timing})));
    });
  });
  for (const value of values) expect(value).toBeCloseTo(110, 8);
});

test('IRR refuses an unbracketed result and keeps beginning timing valid', async ({ page }) => {
  await page.goto('/lump_sum_calculator.html');
  expect(await page.evaluate(() => solveMonthlyIRR(1e12, 1, 1))).toBeNull();
  expect(await page.evaluate(() => solveMonthlyIRR(1, 1e12, 1))).toBeNull();
  await page.locator('#lump').fill('100');
  await page.locator('#pay').fill('20');
  await page.locator('#term').fill('5');
  await page.locator('#timing').selectOption('begin');
  await page.locator('#calcBtn').click();
  await expect(page.locator('#mirr')).toHaveValue('0.0000');
  await expect(page.locator('#amort1 tbody tr').last().locator('td').last()).toHaveText('0.00');
});

test('debt payoff at the safety limit succeeds, while an unpaid balance fails', async ({ page }) => {
  await page.goto('/money_sense_calculators.html');
  const maxMonths = await page.evaluate(async () => Number((await (await fetch(location.href)).text()).match(/const maxMonths = (\d+)/)[1]));
  await page.locator('#debtAPR').fill('0');
  await page.locator('#debtMode').selectOption('fixed');
  await page.locator('#debtFixedPayment').fill('1');
  await page.locator('#debtExtra').fill('0');
  await page.locator('#debtPrincipal').fill(String(maxMonths));
  const alerts = [];
  page.on('dialog', async dialog => { alerts.push(dialog.message()); await dialog.dismiss(); });
  await page.evaluate(() => calcDebt());
  await expect(page.locator('#debtMonths')).toHaveText(`${maxMonths} months`);
  expect(alerts).toEqual([]);
  await page.locator('#debtPrincipal').fill(String(maxMonths + 1));
  await page.evaluate(() => calcDebt());
  expect(alerts).toEqual(['Exceeded iteration limit; check inputs.']);
});

test('calculator default scenarios offer their downloads', async ({ page }) => {
  for (const [path, setup, selectors] of [
    ['/early_loan_termination_calculator.html', null, ['#dlChartBtn', '#dlAmortCsvBtn', '#dlSavingsCsvBtn']],
    ['/lump_sum_calculator.html', null, ['#export1', '#export2']],
    ['/money_sense_calculators.html', () => { calcDebt(); calcSavings(); }, ['#exportDebtBtn', '#exportSaveBtn']],
  ]) {
    await page.goto(path);
    if (setup) await page.evaluate(setup);
    for (const selector of selectors) {
      const download = page.waitForEvent('download');
      await page.locator(selector).click();
      expect((await download).suggestedFilename()).toMatch(/\.(csv|png)$/);
    }
  }
});

test('Chart.js initializes and renders the default financing calculation', async ({ page }) => {
  const browserErrors = [];
  page.on('pageerror', (error) => browserErrors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') browserErrors.push(message.text());
  });

  await page.goto('/early_loan_termination_calculator.html');

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
  await page.locator('#timing').selectOption('end');
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

test('drawdown closing principal edit changes this closing balance and next income', async ({ page }) => {
  const browserErrors = [];
  page.on('pageerror', error => browserErrors.push(error.message));
  await page.goto('/drawdown.html');
  const first = page.locator('#amort-body tr[data-month="1"]').first();
  await expect(first.locator('td[data-key="investments"]')).toHaveText('$600,000');
  await first.locator('td[data-key="investments"]').click();
  await first.locator('.cell-edit-input').fill('500000');
  await first.locator('.cell-edit-input').press('Enter');
  await expect(page.locator('#amort-body tr[data-month="1"] td[data-key="investments"]')).toHaveText('$500,000');
  await expect(page.locator('#amort-body tr[data-month="2"] td[data-key="investment_income"]')).toHaveText('$5,000');
  await expect(page.locator('#adjustments-list .adj-entry')).toHaveCount(1);
  expect(browserErrors).toEqual([]);
});

test('drawdown full editor composes start and end fields and keeps exact month identity', async ({ page }) => {
  const browserErrors = [];
  page.on('pageerror', error => browserErrors.push(error.message));
  await page.goto('/drawdown.html');
  await page.locator('#amort-body tr[data-month="2"] .pin-action').first().click();
  await page.locator('.pin-field-input[data-phase="start"][data-key="expense"]').fill('5100');
  await page.locator('.pin-field-input[data-phase="end"][data-key="investments"]').fill('550000');
  await page.locator('#pin-save').click();
  await expect(page.locator('#adjustments-list .adj-entry')).toHaveCount(1);
  await expect(page.locator('#adjustments-list .adj-entry')).toContainText('Month 2');
  await page.locator('#unit-years').click();
  await page.locator('#adjustments-list .adj-entry').click();
  await expect(page.locator('#pin-month')).toHaveValue('2');
  await expect(page.locator('.pin-field-input[data-phase="start"][data-key="expense"]')).toHaveValue('5100.00');
  await expect(page.locator('.pin-field-input[data-phase="end"][data-key="investments"]')).toHaveValue('550000.00');
  expect(browserErrors).toEqual([]);
});

test('drawdown end-income save compares against counterfactual after closing valuation', async ({ page }) => {
  const browserErrors = [];
  page.on('pageerror', error => browserErrors.push(error.message));
  await page.goto('/drawdown.html');
  await page.evaluate(() => {
    Object.assign(state.params, { buffer_initial: 100, floor: 100, investments_initial: 1000,
      investment_income: 100, expense: 200, external_income: 0, inflation: 0,
      tax_rate: 0, sale_tax_rate: 0, modifier: 1, unit: 'months', num_periods: 2 });
    acceptPins([{ id: 'both', at_month: 1, start: {}, end: { investments: 800, investment_income: 40 } }]);
    rerender();
  });
  await expect(page.locator('#amort-body tr[data-month="2"] td[data-key="investment_income"]')).toHaveText('$40');
  await page.locator('#adjustments-list .adj-entry').click();
  const endIncome = page.locator('.pin-field-input[data-phase="end"][data-key="investment_income"]');
  await expect(endIncome).toHaveValue('40.00');
  await endIncome.fill('90');
  await page.locator('#pin-save').click();
  await expect(page.locator('#amort-body tr[data-month="2"] td[data-key="investment_income"]')).toHaveText('$90');
  expect(await page.evaluate(() => state.pins[0].end.investment_income)).toBe(90);
  expect(browserErrors).toEqual([]);
});

test('unreachable drawdown adjustment can add a new ending field without a baseline', async ({ page }) => {
  const browserErrors = [];
  page.on('pageerror', error => browserErrors.push(error.message));
  await page.goto('/drawdown.html');
  await page.evaluate(() => {
    Object.assign(state.params, { buffer_initial: 100, floor: 100, investments_initial: 0,
      investment_income: 0, expense: 10, external_income: 0, inflation: 0,
      tax_rate: 0, sale_tax_rate: 0, modifier: 1, unit: 'months', num_periods: 12 });
    acceptPins([{ id: 'later', at_month: 8, start: { expense: 5 }, end: {} }]);
    rerender();
  });
  await expect(page.locator('#amort-body tr[data-month]')).toHaveCount(1);
  await page.locator('#adjustments-list .adj-entry').click();
  const endingCash = page.locator('#adjustments-list .pin-field-input[data-phase="end"][data-key="buffer"]');
  await expect(endingCash).toBeVisible();
  await expect(endingCash).toHaveValue('');
  await endingCash.fill('1000');
  const zeroIncome = page.locator('#adjustments-list .pin-field-input[data-phase="start"][data-key="external_income"]');
  await expect(zeroIncome).toHaveValue('');
  await zeroIncome.fill('0');
  await page.locator('#pin-save').click();
  expect(await page.evaluate(() => ({ pins: state.pins, reason: state.acceptedResult.terminatedReason }))).toEqual({
    pins: [{ id: 'later', at_month: 8, start: { expense: 5, external_income: 0 }, end: { buffer: 1000 } }],
    reason: 'reserve_failure',
  });
  await page.locator('#adjustments-list .adj-entry').click();
  await page.locator('#pin-month').fill('7');
  await page.locator('#pin-save').click();
  expect(await page.evaluate(() => state.pins[0])).toEqual({
    id: 'later', at_month: 7, start: { expense: 5, external_income: 0 }, end: { buffer: 1000 },
  });
  await page.locator('#adjustments-list .adj-remove').click();
  await expect(page.locator('#adjustments-list .adj-entry')).toHaveCount(0);
  expect(browserErrors).toEqual([]);
});

test('adjustments panel distinguishes applied and unapplied phases', async ({ page }) => {
  await page.goto('/drawdown.html');
  await page.evaluate(() => {
    Object.assign(state.params, { buffer_initial: 100, floor: 100, investments_initial: 0,
      investment_income: 0, expense: 10, external_income: 0, inflation: 0,
      tax_rate: 0, sale_tax_rate: 0, modifier: 1, unit: 'months', num_periods: 12 });
    acceptPins([
      { id: 'failure', at_month: 1, start: { expense: 10 }, end: { buffer: 1000 } },
      { id: 'later', at_month: 8, start: { expense: 5 }, end: { buffer: 1000 } },
    ]);
    rerender();
  });
  await expect(page.locator('#adjustments-list .adj-entry[data-id="failure"]')).toContainText('Beginning applied');
  await expect(page.locator('#adjustments-list .adj-entry[data-id="failure"]')).toContainText('End unapplied');
  await expect(page.locator('#adjustments-list .adj-entry[data-id="later"]')).toContainText('Beginning unapplied');
  await expect(page.locator('#adjustments-list .adj-entry[data-id="later"]')).toContainText('End unapplied');
  await page.evaluate(() => {
    Object.assign(state.params, { buffer_initial: 100, floor: 0, expense: 0, num_periods: 2 });
    rerender();
  });
  await expect(page.locator('#adjustments-list .adj-entry[data-id="later"]')).toContainText('outside horizon');
});

test('simultaneous closing principal and income edits retain both entered values', async ({ page }) => {
  const browserErrors = [];
  page.on('pageerror', error => browserErrors.push(error.message));
  await page.goto('/drawdown.html');
  await page.evaluate(() => {
    Object.assign(state.params, { buffer_initial: 100, floor: 100, investments_initial: 1000,
      investment_income: 100, expense: 200, external_income: 0, inflation: 0,
      tax_rate: 0, sale_tax_rate: 0, modifier: 1, unit: 'months', num_periods: 2 });
    acceptPins([{ id: 'both', at_month: 1, start: {}, end: { investments: 800, investment_income: 40 } }]);
    rerender();
  });
  await page.locator('#adjustments-list .adj-entry').click();
  await page.locator('.pin-field-input[data-phase="end"][data-key="investments"]').fill('900');
  await page.locator('.pin-field-input[data-phase="end"][data-key="investment_income"]').fill('80');
  await page.locator('#pin-save').click();
  expect(await page.evaluate(() => state.pins[0].end)).toEqual({ investments: 900, investment_income: 80 });
  await expect(page.locator('#amort-body tr[data-month="2"] td[data-key="investment_income"]')).toHaveText('$80');
  expect(browserErrors).toEqual([]);
});
