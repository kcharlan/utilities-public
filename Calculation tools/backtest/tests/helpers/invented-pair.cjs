'use strict';
// Algorithmic invented fixture; never historical observations.
function inventedPair() {
  const rows = Array.from({ length: 154 }, (_, index) => ({ year: 1872 + index,
    stock_tr: (index % 7) / 1000, bond10_tr: 0.01234567, tbill_tr: index < 56 ? null : 0.00345678,
    cpi_change: 0.00123456, quality: index < 56 ? 'reconstructed' : 'ok' }));
  return { js: Buffer.from('globalThis.MARKET_DATA = ' + JSON.stringify({ generated: '2026-10-01',
    sources: { stock_tr: 'Invented synthetic source', bond10_tr: 'Invented synthetic source',
      tbill_tr: 'Invented synthetic source', cpi_change: 'Invented synthetic source' }, rows }) + ';\n'),
    csv: Buffer.from('year,stock_tr,bond10_tr,tbill_tr,cpi_change,quality\r\n' + rows.map(row =>
      Object.values(row).map(value => value === null ? '' : String(value)).join(',')).join('\r\n') + '\r\n') };
}
module.exports = { inventedPair };
