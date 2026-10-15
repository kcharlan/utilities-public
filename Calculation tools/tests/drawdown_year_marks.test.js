'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { loadDrawdownApi } = require('./helpers/load_drawdown');

// Loaded in October 2026, so month 1 is November 2026.
const october = () => loadDrawdownApi({ today: [2026, 9, 15] });

test('relative years count twelve months from month 1', () => {
  const { yearOfMonth, isYearStart, yearMarkTag } = october();
  assert.deepEqual([1, 12, 13, 24, 25].map(month => yearOfMonth(month, 'relative')), [1, 1, 2, 2, 3]);
  assert.deepEqual([1, 2, 12, 13, 14, 25].map(month => isYearStart(month, 'relative')),
    [true, false, false, true, false, true]);
  assert.equal(yearMarkTag(13, 'relative'), 'Y2');
});

test('calendar years break between December and January', () => {
  const { yearOfMonth, isYearStart, yearMarkTag, dateForMonth } = october();
  assert.equal(dateForMonth(2).getMonth(), 11);
  assert.equal(dateForMonth(3).getMonth(), 0);
  assert.deepEqual([1, 2, 3, 14, 15].map(month => yearOfMonth(month, 'calendar')), [2026, 2026, 2027, 2027, 2028]);
  assert.deepEqual([1, 2, 3, 4, 13, 15].map(month => isYearStart(month, 'calendar')),
    [true, false, true, false, false, true]);
  assert.equal(yearMarkTag(3, 'calendar'), '2027');
});

test('relative and calendar years coincide when month 1 is January', () => {
  const { isYearStart } = loadDrawdownApi({ today: [2026, 11, 3] });
  for (let month = 1; month <= 1200; month++) {
    assert.equal(isYearStart(month, 'calendar'), isYearStart(month, 'relative'), `month ${month}`);
  }
});

test('year boundaries sit between the last month of one year and the first of the next', () => {
  const { yearBoundaries } = october();
  const rows = Array.from({ length: 120 }, (_, index) => ({ month: index + 1 }));
  assert.deepEqual(yearBoundaries(rows, 'relative').map(b => [b.index, b.year]),
    [[12, 2], [24, 3], [36, 4], [48, 5], [60, 6], [72, 7], [84, 8], [96, 9], [108, 10]]);
  const calendar = yearBoundaries(rows, 'calendar');
  assert.deepEqual(calendar.slice(0, 2).map(b => [b.index, b.year]), [[2, 2027], [14, 2028]]);
  assert.equal(calendar.length, 10);
  assert.deepEqual(yearBoundaries(rows.slice(0, 12), 'relative'), []);
});

test('chart year lines thin out to avoid crowding', () => {
  const { chartYearSteps } = october();
  assert.deepEqual({ ...chartYearSteps(80) }, { lineEvery: 1, labelEvery: 1 });
  assert.deepEqual({ ...chartYearSteps(30) }, { lineEvery: 1, labelEvery: 5 });
  assert.deepEqual({ ...chartYearSteps(8) }, { lineEvery: 5, labelEvery: 10 });
  assert.deepEqual({ ...chartYearSteps(3) }, { lineEvery: 10, labelEvery: 20 });
});
