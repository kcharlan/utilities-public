const fs = require('node:fs');
const path = require('node:path');
const {readData} = require('../../scripts/timeline-analysis.cjs');
const {readEmbeddedLevels} = require('../../scripts/timeline-levels.cjs');
const html = fs.readFileSync(path.join(__dirname, '..', '..', 'ai-model-timeline.html'), 'utf8');
function extractInlineScript(page = html) {
  const scripts = [...page.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)];
  const app = scripts.find(match => /(?:^|\n)const DATA = \[/.test(match[1]));
  if (!app) throw new Error('Application script missing');
  return app[1];
}
function extractCoreScript(page = html) {
  const match = page.match(/<script\s+id="timeline-core"\s*>([\s\S]*?)<\/script>/i);
  if (!match) throw new Error('TimelineCore script missing');
  return match[1];
}
function loadCore() { const win = {}; new Function('window',extractCoreScript())(win); return win.TimelineCore; }
function rawRows() { return readData(html); }
function joinedRows() { return loadCore().attachLevels(rawRows(), readEmbeddedLevels(html).entries); }
module.exports = {html, extractInlineScript, extractCoreScript, loadCore, rawRows, joinedRows, levels:readEmbeddedLevels(html)};
