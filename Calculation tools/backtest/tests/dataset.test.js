'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { getDataset } = require('./helpers/dataset.cjs');

// Current history exposes both bill bases in stable field order.
const FIELDS = ['year', 'stock_tr', 'bond10_tr', 'tbill_tr', 'tbill_dtb3_tr', 'cpi_change', 'quality'];

function validateRows(rows) {
  assert.ok(Array.isArray(rows), 'rows must be an array');
  assert.equal(rows.length, 154, 'snapshot must contain 154 annual rows');
  for (const [index, row] of rows.entries()) {
    assert.deepEqual(Object.keys(row), FIELDS, 'exact field order is required');
    assert.equal(row.year, 1872 + index, 'years must be contiguous from 1872 to 2025');
    for (const field of ['stock_tr', 'bond10_tr', 'cpi_change']) {
      assert.ok(typeof row[field] === 'number' && Number.isFinite(row[field]) && row[field] > -1,
        `${field} must be a finite decimal greater than -1`);
    }
    if (row.year < 1928) {
      assert.equal(row.tbill_tr, null, 'pre-1928 bills are unavailable');
      assert.equal(row.tbill_dtb3_tr, null, 'pre-1928 DTB3 is unavailable');
      assert.equal(row.quality, 'reconstructed', 'pre-1928 quality is reconstructed');
    } else {
      assert.ok(typeof row.tbill_tr === 'number' && Number.isFinite(row.tbill_tr) && row.tbill_tr > -1,
        'modern bills must be a finite decimal greater than -1');
      assert.ok(typeof row.tbill_dtb3_tr === 'number' && Number.isFinite(row.tbill_dtb3_tr) && row.tbill_dtb3_tr > -1,
        'modern DTB3 must be a finite decimal greater than -1');
      assert.equal(row.quality, 'ok', 'modern quality is ok');
    }
  }
}

function parseCsv(csv) {
  const lines = csv.split(/\r?\n/);
  if (lines.at(-1) === '') lines.pop();
  assert.equal(lines.shift(), FIELDS.join(','), 'CSV field order must match JS');
  return lines.map((line) => {
    const cells = line.split(',');
    assert.equal(cells.length, FIELDS.length, 'CSV row must contain exactly seven fields');
    return Object.fromEntries(FIELDS.map((field, index) => {
      const value = cells[index];
      if (field === 'quality') return [field, value];
      if (field.startsWith('tbill_') && value === '') return [field, null];
      assert.match(value, /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:e[+-]?\d+)?$/i, `${field} must be a decimal`);
      return [field, Number(value)];
    }));
  });
}

test('authentic JS and CSV snapshot has exact annual schema and value parity', async () => {
  // Both files are mandatory; provenance and pair are verified without evaluation.
  const bundle = await getDataset();
  const { payload } = bundle;
  const csv = bundle.files.get('market-data.csv').toString('utf8');
  const { validDate } = await import('../tools/data_contract.mjs');
  validDate(payload.generated);
  assert.equal(payload.generated, bundle.provenance.generatedDate, 'generation date matches verified provenance');
  assert.deepEqual(Object.keys(payload.sources), FIELDS.slice(1,-1));
  for (const source of Object.values(payload.sources)) assert.ok(typeof source === 'string' && source.length > 0);
  validateRows(payload.rows);
  const csvRows = parseCsv(csv);
  validateRows(csvRows);
  assert.deepEqual(csvRows, payload.rows, 'all JS and CSV values must agree');
});

// Conspicuously synthetic rows exercise rejection only; these do not establish
// historical acceptance and are never substituted for the authentic snapshot.
function syntheticRows() {
  return Array.from({ length: 154 }, (_, index) => ({
    year: 1872 + index, stock_tr: 0.11111111, bond10_tr: 0.02222222,
    tbill_tr: index < 56 ? null : 0.00333333, tbill_dtb3_tr:index < 56 ? null : 0.00333333, cpi_change: 0.00444444,
    quality: index < 56 ? 'reconstructed' : 'ok',
  }));
}

test('synthetic dataset defects cannot satisfy the snapshot validator', () => {
  const defects = [
    (rows) => rows.pop(),
    (rows) => { rows[1].year = rows[0].year; },
    (rows) => { rows[0] = { stock_tr: rows[0].stock_tr, ...rows[0] }; },
    (rows) => { rows[0].extra = 'synthetic'; },
    (rows) => { rows[0].stock_tr = NaN; },
    (rows) => { rows[0].bond10_tr = Infinity; },
    (rows) => { rows[0].cpi_change = -1; },
    (rows) => { rows[0].stock_tr = '0.11111111'; },
    (rows) => { rows[0].tbill_tr = 0; },
    (rows) => { rows[0].quality = 'ok'; },
    (rows) => { rows[56].tbill_tr = null; },
    (rows) => { rows[56].tbill_tr = -1; },
    (rows) => { rows[0].tbill_dtb3_tr = 0; },
    (rows) => { rows[56].tbill_dtb3_tr = null; },
    (rows) => { rows[56].quality = 'reconstructed'; },
  ];
  validateRows(syntheticRows());
  for (const defect of defects) {
    const rows = syntheticRows();
    defect(rows);
    assert.throws(() => validateRows(rows), assert.AssertionError);
  }
});

test('synthetic CSV defects reject headers, field counts and invalid numeric cells', () => {
  for (const csv of [
    'stock_tr,year,bond10_tr,tbill_tr,cpi_change,quality\n',
    `${FIELDS.join(',')}\n1872,0.1,0.2,,0.3,reconstructed,synthetic\n`,
    `${FIELDS.join(',')}\n1872,NaN,0.2,,0.3,reconstructed\n`,
    `${FIELDS.join(',')}\n1872,,0.2,,0.3,reconstructed\n`,
    `${FIELDS.join(',')}\n1872,0.1,0.2,null,0.3,reconstructed\n`,
  ]) assert.throws(() => parseCsv(csv), assert.AssertionError);
});
