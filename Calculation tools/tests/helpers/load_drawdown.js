'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const calculatorHtml = fs.readFileSync(path.join(__dirname, '..', '..', 'drawdown.html'), 'utf8');
const script = calculatorHtml.match(/<script>\s*([\s\S]*?)<\/script>/)?.[1];
assert.ok(script, 'drawdown.html must contain an inline script');

function loadDrawdownApi({ document = {}, today = [2026, 6, 30] } = {}) {
  const RealDate = Date;
  class LocalDate extends RealDate {
    constructor(...args) {
      super(...(args.length ? args : [today[0], today[1], today[2], 12]));
    }
    static now() { return new RealDate(today[0], today[1], today[2], 12).getTime(); }
  }
  const context = { Date: LocalDate, document: { addEventListener() {}, ...document } };
  vm.createContext(context);
  vm.runInContext(`${script}\nglobalThis.__api = {
    state, TODAY, PARAM_DEFS, dateForMonth, simulate, validateParams, validatePinDraft,
    prepareCellEdit, applyEditTransaction, commitCellEdit,
    readParams, recalc, rerender, exportCsv, acceptPins, tryAcceptPins, aggregateForView, renderStats,
    calculateAssetSale, createIncomeLedger, applyPrincipalEvent, resetIncomeLedger, effectiveIncome,
    normalizeTaxPercent, readNormalizedTaxRate,
    readPinFieldValue, collectPinFields, renderPinEditor,
    toRoundedCents, formatCents, buildCsvText,
  };`, context);
  return context.__api;
}

module.exports = { calculatorHtml, loadDrawdownApi };
