const { expect, test } = require('@playwright/test');

test.beforeEach(async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto('/drawdown.html');
  page._drawdownErrors = errors;
});

test.afterEach(async ({ page }) => { expect(page._drawdownErrors).toEqual([]); });

test('pending status is quiet and does not move sidebar inputs', async ({ page }) => {
  const pending = await page.evaluate(() => {
    const input = document.getElementById('expense');
    const beforeTop = document.getElementById('buffer-initial').getBoundingClientRect().top;
    input.value = '5100';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    const status = document.getElementById('scenario-status');
    return { tone: status.getAttribute('data-tone'), text: status.textContent,
      hidden: status.hidden, beforeTop,
      duringTop: document.getElementById('buffer-initial').getBoundingClientRect().top };
  });
  expect(pending.tone).toBe('pending');
  expect(pending.text).toContain('Showing the last valid projection');
  expect(pending.text).toContain('Updating after your change…');
  expect(pending.text).not.toContain('draft');
  expect(pending.hidden).toBe(false);
  expect(pending.duringTop).toBe(pending.beforeTop);
});

test('invalid sidebar status stays visible and identifies the input', async ({ page }) => {
  await page.locator('#buffer-initial').fill('');
  await expect.poll(() => page.evaluate(() => sidebarTimers.size)).toBe(0);
  const status = page.locator('#scenario-status');
  await expect(status).toHaveAttribute('data-tone', 'error');
  await expect(status).toContainText('Starting cash:');
  await expect(status).not.toContainText('buffer_initial');
  await expect(page.locator('#buffer-initial')).toHaveAttribute('aria-errormessage', 'scenario-status');
  const edges = await page.evaluate(() => {
    const sidebar = document.querySelector('.sidebar');
    sidebar.scrollTop = sidebar.scrollHeight;
    return { status: document.getElementById('scenario-status').getBoundingClientRect().top,
      sidebar: sidebar.getBoundingClientRect().top };
  });
  expect(Math.abs(edges.status - edges.sidebar)).toBeLessThanOrEqual(4);
});

test('keyboard pin and cell editors return focus to their openers', async ({ page }) => {
  const add = page.getByRole('button', { name: 'Add adjustment at month 2', exact: true });
  await add.focus();
  await add.press('Enter');
  await expect(page.locator('.pin-field-input').first()).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(add).toBeFocused();

  const expense = page.locator('#amort-body td.editable-cell[data-month="2"][data-key="expense"]');
  await expense.focus();
  await expense.press('Enter');
  await expect(page.locator('.cell-edit-input')).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(expense).toBeFocused();
  await expense.press('Space');
  await expect(page.locator('.cell-edit-input')).toBeFocused();
});

test('adjustment list opens by keyboard and Cancel returns focus', async ({ page }) => {
  await page.evaluate(() => {
    acceptPins([{ id: 'synthetic-pin', at_month: 2, start: { expense: 12345.67 }, end: {} }]);
    rerender();
  });
  const opener = page.locator('.adj-entry[data-id="synthetic-pin"] .adj-open');
  await opener.focus();
  await opener.press('Enter');
  await expect(page.locator('.pin-field-input').first()).toBeFocused();
  await page.locator('#pin-cancel').click();
  await expect(opener).toBeFocused();
});

test('saving and removing a pin return focus to a month action', async ({ page }) => {
  const add = page.getByRole('button', { name: 'Add adjustment at month 2', exact: true });
  await add.press('Enter');
  await page.locator('.pin-field-input[data-phase="start"][data-key="expense"]').fill('12345.67');
  await page.locator('#pin-save').click();
  await expect(add).toBeFocused();
  const edit = page.getByRole('button', { name: 'Edit adjustment at month 2', exact: true });
  await edit.press('Enter');
  await expect(page.locator('.pin-field-input').first()).toBeFocused();
  await page.locator('#pin-remove').click();
  await expect(edit).toHaveCount(0);
  await expect(add).toBeFocused();
});

test('Enter commits an inline cell and returns focus to the cell', async ({ page }) => {
  const cell = page.locator('#amort-body td.editable-cell[data-month="2"][data-key="expense"]');
  await cell.press('Enter');
  await page.locator('.cell-edit-input').fill('12345.67');
  await page.locator('.cell-edit-input').press('Enter');
  await expect(cell).toBeFocused();
  await expect(cell).toContainText('$12,346');
});

test('moving a table-opened pin beyond the horizon focuses its sidebar action', async ({ page }) => {
  const add = page.getByRole('button', { name: 'Add adjustment at month 2', exact: true });
  await add.click();
  await page.locator('.pin-field-input[data-phase="start"][data-key="expense"]').fill('12345.67');
  await page.locator('#pin-save').click();
  await page.getByRole('button', { name: 'Edit adjustment at month 2', exact: true }).click();
  await page.locator('#pin-month').fill('121');
  await page.locator('#pin-save').click();

  const moved = page.locator('#adjustments-list .adj-entry[data-month="121"] .adj-open');
  await expect(moved).toBeFocused();
  await expect(page.locator('#amort-body .pin-action[data-id]')).toHaveCount(0);
});

test('Clear pins while editing returns focus to Recalculate', async ({ page }) => {
  await page.evaluate(() => {
    acceptPins([{ id: 'synthetic-pin', at_month: 2, start: { expense: 12345.67 }, end: {} }]);
    rerender();
  });
  await page.getByRole('button', { name: 'Edit adjustment at month 2', exact: true }).click();
  await page.locator('#clear-pins').click();
  await expect(page.locator('#calc-button')).toBeFocused();
  await expect(page.locator('#clear-pins')).toBeDisabled();
});

test('Clear pins does not restore focus to a surviving unsaved Add action', async ({ page }) => {
  await page.evaluate(() => {
    acceptPins([{ id: 'synthetic-pin', at_month: 2, start: { expense: 12345.67 }, end: {} }]);
    rerender();
  });
  await page.getByRole('button', { name: 'Add adjustment at month 2', exact: true }).click();
  await page.locator('#clear-pins').click();
  await expect(page.locator('#calc-button')).toBeFocused();
});

test('removing an unreachable pin from its editor focuses Recalculate', async ({ page }) => {
  await page.evaluate(() => {
    acceptPins([{ id: 'synthetic-unreachable-pin', at_month: 121,
      start: { expense: 12345.67 }, end: {} }]);
    rerender();
  });
  await page.locator('.adj-entry[data-id="synthetic-unreachable-pin"] .adj-open').click();
  await page.locator('#pin-remove').click();
  await expect(page.locator('#calc-button')).toBeFocused();
  await expect(page.locator('#adjustments-list .adj-entry')).toHaveCount(0);
});

test('direct keyboard removal from adjustments focuses Recalculate', async ({ page }) => {
  await page.evaluate(() => {
    acceptPins([{ id: 'synthetic-direct-pin', at_month: 2,
      start: { expense: 12345.67 }, end: {} }]);
    rerender();
  });
  const remove = page.locator('.adj-entry[data-id="synthetic-direct-pin"] .adj-remove');
  await remove.focus();
  await remove.press('Enter');
  await expect(page.locator('#calc-button')).toBeFocused();
  await expect(remove).toHaveCount(0);
});

test('sidebar controls have associated names and described hints', async ({ page }) => {
  await expect(page.getByLabel('Starting cash', { exact: true })).toHaveId('buffer-initial');
  await expect(page.getByLabel('Expenses, monthly', { exact: true })).toHaveId('expense');
  await expect(page.getByLabel('Periods', { exact: true })).toHaveId('periods');
  await expect(page.getByLabel('External income, monthly', { exact: true })).toHaveId('external-income');
  await expect(page.getByLabel('Investments, monthly income', { exact: true })).toHaveId('investment-income');
  await expect(page.locator('#periods')).toHaveAttribute('aria-describedby', 'periods-hint');
  await expect(page.locator('#periods-hint')).toContainText('0 = run until reserve failure or cap');
});

test('editing an assumption does not replay table row animations', async ({ page }) => {
  await page.evaluate(() => {
    window.tableRowAnimations = 0;
    document.addEventListener('animationstart', event => {
      if (event.target.matches('#amort-body tr[data-month]')) window.tableRowAnimations++;
    }, true);
  });
  await page.locator('#expense').fill('5100');
  await expect.poll(() => page.evaluate(() => sidebarTimers.size)).toBe(0);
  await page.waitForTimeout(250);
  expect(await page.evaluate(() => window.tableRowAnimations)).toBe(0);
});

test('pin editor fades when opened but not when rerendered', async ({ page }) => {
  await page.locator('#amort-body tr[data-month="2"] .pin-action').click();
  await expect(page.locator('.pin-editor-row')).toHaveClass(/is-entering/);
  const count = await page.evaluate(async () => {
    let animations = 0;
    document.addEventListener('animationstart', event => {
      if (event.target.matches('.pin-editor-row')) animations++;
    }, true);
    rerender();
    await new Promise(resolve => setTimeout(resolve, 250));
    return animations;
  });
  expect(count).toBe(0);
  await expect(page.locator('.pin-editor-row')).not.toHaveClass(/is-entering/);
});

test('reduced motion shortens the pin editor fade', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.locator('#amort-body tr[data-month="2"] .pin-action').click();
  const duration = await page.locator('.pin-editor-row').evaluate(node =>
    parseFloat(getComputedStyle(node).animationDuration));
  expect(duration).toBeLessThan(0.001);
});

test('phone layout stacks the sidebar and keeps content inside the viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => {
    const rect = selector => document.querySelector(selector).getBoundingClientRect();
    const stamp = rect('.today-stamp');
    const heading = rect('.header h2');
    const titles = rect('.table-head-titles');
    const actions = rect('.table-actions');
    return document.documentElement.scrollWidth <= innerWidth
      && ['#chart', '.stats', '.table-scroll'].every(selector => rect(selector).width >= 300)
      && rect('.sidebar').bottom <= rect('.main').top
      && (stamp.right <= heading.left || heading.right <= stamp.left
        || stamp.bottom <= heading.top || heading.bottom <= stamp.top)
      && actions.top >= titles.bottom;
  })).toBe(true);
  await page.locator('#amort-body tr[data-month="1"] td[data-key="expense"]').click();
  await page.locator('#today-stamp').click();
  await expect(page.locator('.cell-edit-input')).toHaveCount(0);
});

test('tablet layout keeps stat labels compact without page overflow', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 800 });
  await expect.poll(() => page.evaluate(() =>
    document.documentElement.scrollWidth <= innerWidth
      && [...document.querySelectorAll('.stat-label')].every(label => label.getBoundingClientRect().height < 30)
  )).toBe(true);
});

test('table pin editor keeps Save visible while the table scrolls horizontally', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.locator('#expense').fill('12000');
  await expect.poll(() => page.evaluate(() => sidebarTimers.size)).toBe(0);
  await page.locator('#amort-body tr[data-month="3"] .pin-action').click();

  const geometry = () => page.evaluate(() => {
    const scroller = document.querySelector('.table-scroll');
    const editor = document.querySelector('.pin-editor');
    const cell = document.querySelector('.pin-editor-row > td');
    const save = document.getElementById('pin-save');
    return {
      scrollerLeft: scroller.getBoundingClientRect().left,
      scrollerRight: scroller.getBoundingClientRect().right,
      editorLeft: editor.getBoundingClientRect().left,
      saveRight: save.getBoundingClientRect().right,
      textAlign: getComputedStyle(cell).textAlign,
    };
  });
  let position = await geometry();
  expect(position.saveRight).toBeLessThanOrEqual(position.scrollerRight + 1);
  expect(position.textAlign).toBe('left');

  await page.locator('.table-scroll').evaluate(node => { node.scrollLeft = node.scrollWidth; });
  position = await geometry();
  expect(Math.abs(position.editorLeft - position.scrollerLeft)).toBeLessThanOrEqual(1);
  expect(position.saveRight).toBeLessThanOrEqual(position.scrollerRight + 1);
});

test('narrow table pin editor wraps its explanation and keeps Save visible', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('#amort-body tr[data-month="2"] .pin-action').click();
  const geometry = await page.evaluate(() => ({
    subHeight: document.querySelector('.pin-editor-sub').getBoundingClientRect().height,
    saveRight: document.getElementById('pin-save').getBoundingClientRect().right,
    scrollerRight: document.querySelector('.table-scroll').getBoundingClientRect().right,
  }));
  expect(geometry.subHeight).toBeGreaterThan(20);
  expect(geometry.saveRight).toBeLessThanOrEqual(geometry.scrollerRight + 1);
});

test('sidebar recovery pin editor fits and Save is directly clickable', async ({ page }) => {
  await page.evaluate(() => {
    acceptPins([{ id: 'synthetic-late', at_month: 100, start: { expense: 6000 }, end: {} }]);
    rerender();
  });
  await page.locator('#periods').fill('50');
  await expect.poll(() => page.evaluate(() => sidebarTimers.size)).toBe(0);
  await page.locator('.adj-entry[data-id="synthetic-late"]').click();
  const geometry = await page.evaluate(() => {
    const sidebar = document.querySelector('.sidebar');
    return {
      scrollWidth: sidebar.scrollWidth,
      clientWidth: sidebar.clientWidth,
      saveRight: document.getElementById('pin-save').getBoundingClientRect().right,
      sidebarRight: sidebar.getBoundingClientRect().right,
    };
  });
  expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth);
  expect(geometry.saveRight).toBeLessThanOrEqual(geometry.sidebarRight + 1);
  await page.locator('#pin-save').click();
  expect(await page.evaluate(() => state.pins[0].at_month)).toBe(100);
});

test.describe('theme token rendering', () => {
  test('system scheme changes body, chart, halo, and texture without reload', async ({ page }) => {
    const cash = page.locator('#chart path[data-series="cash"]');
    const label = page.locator('.chart-y-label').first();
    await page.emulateMedia({ colorScheme: 'dark' });
    await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(22, 19, 14)');
    await expect(cash).toHaveCSS('stroke', 'rgb(140, 194, 168)');
    await expect(label).toHaveCSS('background-color', 'rgba(29, 25, 19, 0.85)');
    await expect.poll(() => page.locator('body').evaluate(node => getComputedStyle(node).backgroundImage))
      .toContain('rgba(236, 228, 212, 0.035)');

    await page.emulateMedia({ colorScheme: 'light' });
    await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(242, 236, 224)');
    await expect(cash).toHaveCSS('stroke', 'rgb(44, 74, 62)');
    await expect.poll(() => page.locator('body').evaluate(node => getComputedStyle(node).backgroundImage))
      .toContain('rgba(26, 24, 20, 0.035)');
  });

  test('print uses light colours under a dark system scheme', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(22, 19, 14)');
    await page.emulateMedia({ media: 'print', colorScheme: 'dark' });
    await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(242, 236, 224)');
  });
});

test.describe('theme control', () => {
  const pressed = async page => Promise.all(['auto', 'light', 'dark'].map(choice =>
    page.locator(`#theme-${choice}`).getAttribute('aria-pressed')));

  test('Auto follows live system changes without an override', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(22, 19, 14)');
    await expect(page.locator('html')).not.toHaveAttribute('data-theme');
    await expect(page.locator('#theme-auto')).toHaveAttribute('aria-pressed', 'true');
    await page.emulateMedia({ colorScheme: 'light' });
    await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(242, 236, 224)');
  });

  test('Dark overrides a light system for body and chart without recalculating', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    const before = await page.evaluate(() => state.acceptedResult);
    await page.locator('#theme-dark').click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(22, 19, 14)');
    await expect(page.locator('#chart path[data-series="cash"]')).toHaveCSS('stroke', 'rgb(140, 194, 168)');
    expect(await pressed(page)).toEqual(['false', 'false', 'true']);
    expect(await page.evaluate(() => state.acceptedResult)).toEqual(before);
  });

  test('Light overrides a dark system and Auto restores following', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.locator('#theme-light').click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(242, 236, 224)');
    expect(await pressed(page)).toEqual(['false', 'true', 'false']);
    await page.locator('#theme-auto').click();
    await expect(page.locator('html')).not.toHaveAttribute('data-theme');
    await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(22, 19, 14)');
    expect(await pressed(page)).toEqual(['true', 'false', 'false']);
    await page.emulateMedia({ colorScheme: 'light' });
    await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(242, 236, 224)');
  });

  test('theme choice resets to Auto on reload without browser storage', async ({ page }) => {
    await page.locator('#theme-dark').click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await page.reload();
    await expect(page.locator('html')).not.toHaveAttribute('data-theme');
    expect(await pressed(page)).toEqual(['true', 'false', 'false']);
    expect(await page.evaluate(() => [localStorage.length, sessionStorage.length, document.cookie])).toEqual([0, 0, '']);
  });

  test('Space activates the focused Dark button', async ({ page }) => {
    await page.locator('#theme-dark').focus();
    await page.keyboard.press('Space');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(page.locator('#theme-dark')).toHaveAttribute('aria-pressed', 'true');
  });

  test('unit buttons update their pressed states', async ({ page }) => {
    await page.locator('#unit-years').click();
    await expect(page.locator('#unit-years')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('#unit-months')).toHaveAttribute('aria-pressed', 'false');
  });
});

test('keyboard navigation shows a visible theme-button focus ring', async ({ page }) => {
  for (let press = 0; press < 40; press++) {
    await page.keyboard.press('Tab');
    if (await page.evaluate(() => document.activeElement.id === 'theme-light')) break;
  }
  await expect(page.locator('#theme-light')).toBeFocused();
  await expect(page.locator('#theme-light')).toHaveCSS('outline-style', 'solid');
});

test('Clear pins is disabled until an adjustment exists', async ({ page }) => {
  await expect(page.locator('#clear-pins')).toBeDisabled();
  await page.evaluate(() => {
    acceptPins([{ id: 'synthetic', at_month: 1, start: { expense: 5001 }, end: {} }]);
    rerender();
  });
  await expect(page.locator('#clear-pins')).toBeEnabled();
});

test('disabled CSV export stays muted while hovered', async ({ page }) => {
  await page.locator('#expense').fill('');
  await expect.poll(() => page.evaluate(() => sidebarTimers.size)).toBe(0);
  const exportButton = page.locator('#export-csv');
  await expect(exportButton).toBeDisabled();
  await expect(exportButton).toHaveCSS('opacity', '0.45');
  const restingFill = await exportButton.evaluate(button => getComputedStyle(button).backgroundColor);
  await exportButton.hover({ force: true });
  await page.waitForTimeout(200); // Let the button's 150 ms hover transition finish.
  await expect.poll(() => exportButton.evaluate(button => getComputedStyle(button).backgroundColor))
    .toBe(restingFill);
});

test('fresh projection keeps its last valid rows during invalid input and restores CSV export', async ({ page }) => {
  const firstRow = page.locator('#amort-body tr').first();
  await expect(firstRow).toBeVisible();
  const before = await firstRow.innerText();
  const expense = page.locator('#expense');
  await expense.fill('');
  await expect(page.locator('#scenario-status')).toContainText('Showing the last valid projection');
  await expect(page.locator('#export-csv')).toBeDisabled();
  await expect(firstRow).toHaveText(before);

  await expense.fill('5100');
  await expect(page.locator('#scenario-status')).toBeHidden();
  await expect(page.locator('#export-csv')).toBeEnabled();
  await expect(firstRow.locator('td[data-key="expense"]')).toHaveText('$5,100');
  const downloadPromise = page.waitForEvent('download');
  await page.locator('#export-csv').click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^drawdown-months-\d{4}-\d{2}-\d{2}\.csv$/);
  const stream = await download.createReadStream();
  let csv = '';
  for await (const chunk of stream) csv += chunk.toString();
  const firstDataRow = csv.split('\n')[1].split(',');
  expect(firstDataRow[2]).toBe('5100.00');
});

test('opening and closing a pin editor keeps an invalid sidebar draft stale', async ({ page }) => {
  await page.locator('#expense').fill('');
  await expect.poll(() => page.evaluate(() => sidebarTimers.size)).toBe(0);
  await expect(page.locator('#export-csv')).toBeDisabled();
  await page.locator('#amort-body tr[data-month="1"] .pin-action').first().click();
  await expect(page.locator('#pin-save')).toBeVisible();
  await expect(page.locator('#scenario-status')).toContainText('Showing the last valid projection');
  await expect(page.locator('#export-csv')).toBeDisabled();
  await page.locator('#pin-cancel').click();
  await expect(page.locator('#scenario-status')).toContainText('Showing the last valid projection');
  await expect(page.locator('#export-csv')).toBeDisabled();
});

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

test('chart axis labels align with plotted pixel coordinates', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const positions = await page.evaluate(() => {
    const svg = document.getElementById('chart');
    const svgBox = svg.getBoundingClientRect();
    const labels = [...document.querySelectorAll('.chart-y-label')];
    const centres = labels.map(label => {
      const box = label.getBoundingClientRect();
      return { y: box.top + box.height / 2, left: box.left, height: box.height };
    });
    return {
      svgTop: svgBox.top, svgLeft: svgBox.left,
      maxY: chartGeometry.padT,
      floorY: chartGeometry.yOf(chartGeometry.floorOf(lastChartRows.at(-1))),
      zeroY: chartGeometry.H - chartGeometry.padB,
      centres,
    };
  });
  expect(positions.centres).toHaveLength(3);
  for (const [index, y] of [positions.maxY, positions.floorY, positions.zeroY].entries()) {
    expect(Math.abs(positions.centres[index].y - positions.svgTop - y)).toBeLessThanOrEqual(2);
  }
  for (const label of positions.centres) {
    expect(label.left).toBeGreaterThanOrEqual(positions.svgLeft);
    expect(label.height).toBeLessThan(18);
  }
});

test('spreadLabels separates and clamps positions without changing input', async ({ page }) => {
  const result = await page.evaluate(() => {
    const first = [{ key: 'a', y: 50 }, { key: 'b', y: 52 }];
    const second = [{ key: 'a', y: 195 }, { key: 'b', y: 198 }];
    const low = [{ key: 'a', y: -5 }];
    return {
      first: spreadLabels(first, 14, 0, 200),
      second: spreadLabels(second, 14, 0, 200),
      low: spreadLabels(low, 14, 0, 200),
      originals: [first, second, low],
    };
  });
  expect(result.first).toEqual([{ key: 'a', y: 50 }, { key: 'b', y: 64 }]);
  expect(result.second).toEqual([{ key: 'a', y: 186 }, { key: 'b', y: 200 }]);
  expect(result.low).toEqual([{ key: 'a', y: 0 }]);
  expect(result.originals).toEqual([
    [{ key: 'a', y: 50 }, { key: 'b', y: 52 }],
    [{ key: 'a', y: 195 }, { key: 'b', y: 198 }],
    [{ key: 'a', y: -5 }],
  ]);
});

test('chart viewBox follows its resized SVG width', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.setViewportSize({ width: 1024, height: 800 });
  await expect.poll(() => page.locator('#chart').evaluate(svg =>
    svg.viewBox.baseVal.width === Math.round(svg.getBoundingClientRect().width))).toBe(true);
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

test('rejected move after a pending sidebar change keeps export stale until the visible projection catches up', async ({ page }) => {
  await page.evaluate(() => {
    acceptPins([
      { id: 'synthetic-one', at_month: 1, start: { expense: 5001 }, end: {} },
      { id: 'synthetic-two', at_month: 2, start: { expense: 5002 }, end: {} },
    ]);
    rerender();
  });
  await page.locator('#adjustments-list .adj-entry[data-month="1"]').click();
  await page.locator('#pin-month').fill('2');
  await page.evaluate(() => {
    const input = document.getElementById('investments-initial');
    input.value = '700000';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    document.getElementById('pin-save').click();
  });
  await expect(page.locator('#pin-editor-error')).toContainText('Another adjustment already occupies that month.');
  await expect(page.locator('#scenario-status')).toContainText('Showing the last valid projection');
  await expect(page.locator('#export-csv')).toBeDisabled();
  expect(await page.evaluate(() => state.acceptedResult.rows[0].investments)).not.toBe(700000);
  expect(await page.evaluate(() => state.pins.map(p => p.at_month))).toEqual([1, 2]);

  await page.locator('#calc-button').click();
  await expect(page.locator('#export-csv')).toBeEnabled();
  expect(await page.evaluate(() => state.acceptedResult.rows[0].pre_start_state.investments)).toBe(700000);
  const downloadPromise = page.waitForEvent('download');
  await page.locator('#export-csv').click();
  const stream = await (await downloadPromise).createReadStream();
  let csv = '';
  for await (const chunk of stream) csv += chunk.toString();
  const first = csv.split('\n')[1].split(',');
  expect(Number(first[9])).toBe(await page.evaluate(() => state.acceptedResult.rows[0].investments));
});

test('rejected cell edit after a pending sidebar change retains the editor and disables stale export', async ({ page }) => {
  await page.evaluate(() => {
    acceptPins([
      { id: 'synthetic-principal', at_month: 1, start: {}, end: { investments: 100 } },
      { id: 'synthetic-income', at_month: 2, start: { investment_income: 10 }, end: {} },
    ]);
    rerender();
  });
  await page.locator('#amort-body tr[data-month="1"] td[data-key="investments"]').click();
  await page.locator('.cell-edit-input').fill('0');
  await page.evaluate(() => {
    const input = document.getElementById('investments-initial');
    input.value = '700000';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    document.querySelector('.cell-edit-input').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  });
  await expect(page.locator('.cell-edit-feedback')).toContainText('Investment income must be zero when principal is zero.');
  await expect(page.locator('.cell-edit-input')).toBeVisible();
  await expect(page.locator('#scenario-status')).toContainText('Showing the last valid projection');
  await expect(page.locator('#export-csv')).toBeDisabled();
  expect(await page.evaluate(() => state.pins[0].end.investments)).toBe(100);
  await page.locator('#calc-button').click();
  await expect(page.locator('#export-csv')).toBeEnabled();
});

test('removing a prerequisite adjustment is rejected in the sidebar and full editor', async ({ page }) => {
  await page.evaluate(() => {
    Object.assign(state.params, { buffer_initial: 100, floor: 0, investments_initial: 0,
      investment_income: 0, external_income: 0, expense: 0, inflation: 0,
      tax_rate: 0, sale_tax_rate: 0, modifier: 1, unit: 'months', num_periods: 3 });
    acceptPins([
      { id: 'synthetic-prerequisite', at_month: 1, start: {}, end: { investments: 100 } },
      { id: 'synthetic-dependent', at_month: 2, start: { investment_income: 10 }, end: {} },
    ]);
    rerender();
  });
  const accepted = await page.evaluate(() => JSON.stringify(state.acceptedResult.rows));
  await page.locator('.adj-remove[data-id="synthetic-prerequisite"]').click();
  await expect(page.locator('#scenario-status')).toContainText('month 2');
  expect(await page.evaluate(() => state.pins.map(p => p.id))).toEqual(['synthetic-prerequisite', 'synthetic-dependent']);
  expect(await page.evaluate(() => JSON.stringify(state.acceptedResult.rows))).toBe(accepted);

  await page.locator('.adj-entry[data-id="synthetic-prerequisite"]').click();
  await page.locator('#pin-remove').click();
  await expect(page.locator('#pin-editor-error')).toContainText('Investment income must be zero when principal is zero.');
  await expect(page.locator('#pin-remove')).toBeVisible();
  expect(await page.evaluate(() => state.pins.map(p => p.id))).toEqual(['synthetic-prerequisite', 'synthetic-dependent']);
  expect(await page.evaluate(() => JSON.stringify(state.acceptedResult.rows))).toBe(accepted);
});

test('removing an adjustment can resolve a pending sidebar change that invalidates only that adjustment', async ({ page }) => {
  await page.locator('#investments-initial').fill('100');
  await page.locator('#investment-income').fill('0');
  await page.locator('#expense').fill('0');
  await page.locator('#calc-button').click();
  await page.evaluate(() => {
    acceptPins([{ id: 'synthetic-income', at_month: 1, start: { investment_income: 10 }, end: {} }]);
    rerender();
    const input = document.getElementById('investments-initial');
    input.value = '0';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    document.querySelector('.adj-remove[data-id="synthetic-income"]').click();
  });
  expect(await page.evaluate(() => state.pins)).toEqual([]);
  expect(await page.evaluate(() => state.params.investments_initial)).toBe(0);
  await expect(page.locator('#scenario-status')).toBeHidden();
  await expect(page.locator('#export-csv')).toBeEnabled();
});

test('annual provenance names the original target and current changed total', async ({ page }) => {
  await page.locator('#unit-years').click();
  await page.locator('#amort-body tr[data-month="1"] td[data-key="expense"]').click();
  await page.locator('.cell-edit-input').fill('72000');
  await page.locator('.cell-edit-input').press('Enter');
  await expect(page.locator('#adjustments-list')).toContainText('Annual expense target');
  await page.locator('#unit-months').click();
  await page.locator('#amort-body tr[data-month="2"] td[data-key="expense"]').click();
  await page.locator('.cell-edit-input').fill('6000');
  await page.locator('.cell-edit-input').press('Enter');
  const current = await page.evaluate(() => state.acceptedResult.rows.slice(0, 12).reduce((sum, row) => sum + row.expense, 0));
  await expect(page.locator('.adj-entry[data-month="1"]')).toContainText('originally targeted');
  await expect(page.locator('.adj-entry[data-month="1"]')).toContainText(`current total ${fmtForTest(current)}`);
});

test('annual provenance marks an incomplete span even when its partial sum matches the old target', async ({ page }) => {
  await page.evaluate(() => {
    Object.assign(state.params, { buffer_initial: 20, floor: 0, investments_initial: 0,
      investment_income: 0, external_income: 0, expense: 10, inflation: 0,
      tax_rate: 0, sale_tax_rate: 0, modifier: 1, unit: 'years', num_periods: 1 });
    acceptPins([{ id: 'synthetic-annual', at_month: 1, start: { expense: 10 }, end: {},
      annual_edits: { expense: { target_total: 30, first_month: 1, last_month: 12,
        resolved_monthly_value: 10 } } }]);
    rerender();
  });
  await expect(page.locator('.adj-entry[data-id="synthetic-annual"]')).toContainText('originally targeted $30');
  await expect(page.locator('.adj-entry[data-id="synthetic-annual"]')).toContainText('current total $30 through month 3');
});

test('annual provenance includes terminal-month income in a failed span total', async ({ page }) => {
  await page.evaluate(() => {
    Object.assign(state.params, { buffer_initial: 0, floor: 0, investments_initial: 100,
      investment_income: 10, external_income: 0, expense: 20, inflation: 0,
      tax_rate: 0, sale_tax_rate: 1, modifier: 1, unit: 'years', num_periods: 1 });
    acceptPins([{ id: 'synthetic-annual-income', at_month: 1,
      start: { investment_income: 10 }, end: {},
      annual_edits: { investment_income: { target_total: 10, first_month: 1,
        last_month: 12, resolved_monthly_value: 10 } } }]);
    rerender();
  });
  expect(await page.evaluate(() => state.acceptedResult.rows[0].investment_income)).toBe(10);
  expect(await page.evaluate(() => state.acceptedResult.rows[0].insolvency)).toBe(true);
  await expect(page.locator('.adj-entry[data-id="synthetic-annual-income"]')).toContainText('originally targeted $10');
  await expect(page.locator('.adj-entry[data-id="synthetic-annual-income"]')).toContainText('current total $10 through month 1');
});

test('export preserves an open annual cell draft when the displayed scenario is current', async ({ page }) => {
  await page.locator('#unit-years').click();
  await page.locator('#amort-body tr[data-month="1"] td[data-key="expense"]').click();
  await page.locator('.cell-edit-input').fill('73000');
  const download = page.waitForEvent('download');
  await page.locator('#export-csv').click();
  await download;
  await expect(page.locator('.cell-edit-input')).toHaveValue('73000');
  await page.locator('.cell-edit-input').press('Enter');
  await expect.poll(() => page.evaluate(() => state.pins[0]?.annual_edits?.expense?.target_total)).toBe(73000);
});

test('clearing pins with a pending sidebar draft synchronizes the visible projection and export', async ({ page }) => {
  await page.evaluate(() => {
    acceptPins([{ id: 'synthetic', at_month: 1, start: { expense: 5001 }, end: {} }]);
    rerender();
    const input = document.getElementById('investments-initial');
    input.value = '700000';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    document.getElementById('clear-pins').click();
  });
  expect(await page.evaluate(() => state.pins.length)).toBe(0);
  expect(await page.evaluate(() => state.params.investments_initial)).toBe(700000);
  await expect(page.locator('#export-csv')).toBeEnabled();
  expect(await page.evaluate(() => state.acceptedResult.rows[0].pre_start_state.investments)).toBe(700000);
});

function fmtForTest(value) {
  return `$${Math.round(value).toLocaleString('en-US')}`;
}

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
