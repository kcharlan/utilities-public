'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { calculatorHtml, loadDrawdownApi } = require('./helpers/load_drawdown');

function loadDateApi(year, monthIndex, day) {
  const todayStamp = { textContent: '' };
  const stopAfterHeader = new Error('stop after rendering the header');
  let onDomContentLoaded;

  const api = loadDrawdownApi({
    today: [year, monthIndex, day],
    document: {
      addEventListener(eventName, listener) {
        if (eventName === 'DOMContentLoaded') onDomContentLoaded = listener;
      },
      getElementById(id) {
        if (id === 'today-stamp') return todayStamp;
        throw stopAfterHeader;
      },
    },
  });

  return {
    ...api,
    renderHeader() {
      assert.equal(typeof onDomContentLoaded, 'function');
      assert.throws(onDomContentLoaded, (error) => error === stopAfterHeader);
      return todayStamp.textContent;
    },
  };
}

function localDateParts(date) {
  return [date.getFullYear(), date.getMonth(), date.getDate()];
}

test('anchors projections and the rendered header to the current month', () => {
  const { TODAY, dateForMonth, renderHeader } = loadDateApi(2026, 6, 30);

  assert.deepEqual(localDateParts(TODAY), [2026, 6, 1]);
  assert.deepEqual(localDateParts(dateForMonth(1)), [2026, 7, 1]);
  assert.deepEqual(localDateParts(dateForMonth(7)), [2027, 1, 1]);
  assert.equal(renderHeader(), 'July 2026');
  assert.match(
    calculatorHtml,
    /id="today-stamp"><\/strong>/,
    'the pre-initialization header must not contain a hard-coded model month',
  );
});

test('advances from a 31-day current date without skipping February', () => {
  const { TODAY, dateForMonth } = loadDateApi(2027, 0, 31);

  assert.deepEqual(localDateParts(TODAY), [2027, 0, 1]);
  assert.deepEqual(localDateParts(dateForMonth(1)), [2027, 1, 1]);
});
