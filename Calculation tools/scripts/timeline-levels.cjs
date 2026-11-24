const fs = require('node:fs');
const path = require('node:path');
const file = path.join(__dirname, '..', 'docs', 'ai_model_timeline_levels.json');
const page = path.join(__dirname, '..', 'ai-model-timeline.html');
const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
const text = x => typeof x === 'string' && x.trim().length > 0;
const key = row => JSON.stringify([row.model, row.lab, row.date]);
function readLevelsFile() { return JSON.parse(fs.readFileSync(file, 'utf8')); }
function attribute(attrs, name, value) {
  const tokens = /([^\s"'<>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'\x60=<>]+)))?/g;
  for (const match of attrs.matchAll(tokens)) {
    if (match[1].toLowerCase() === name && (match[2] ?? match[3] ?? match[4] ?? '').toLowerCase() === value) return true;
  }
  return false;
}
function blocks(html) {
  const opening = /<script(?=[\s>])((?:[^'">]|"[^"]*"|'[^']*')*)>/gi, closing = /<\/script\s*>/gi, found = [];
  let match;
  while ((match = opening.exec(html))) {
    closing.lastIndex = opening.lastIndex;
    const end = closing.exec(html);
    const target = attribute(match[1], 'id', 'timeline-levels');
    if (!end) { if (target) throw new Error('Malformed timeline-levels block: missing closing script'); break; }
    if (target && /<script\b/i.test(html.slice(opening.lastIndex, end.index))) throw new Error('Malformed timeline-levels block: missing closing script before another script');
    if (target) {
      const block = [html.slice(match.index, closing.lastIndex), match[1], html.slice(opening.lastIndex,end.index)];
      block.index = match.index;
      found.push(block);
    }
    opening.lastIndex = closing.lastIndex;
  }
  return found;
}
function checkType(block) {
  if (!attribute(block[1], 'type', 'application/json')) throw new Error('timeline-levels block must have type application/json');
}
function readEmbeddedLevels(html) {
  const found = blocks(html);
  if (found.length !== 1) throw new Error(`Expected one timeline-levels block, found ${found.length}`);
  checkType(found[0]);
  try { return JSON.parse(found[0][2]); } catch (e) { throw new Error(`Malformed timeline-levels JSON: ${e.message}`); }
}
function embedLevels(html, doc) {
  const found = blocks(html);
  if (found.length > 1) throw new Error('Duplicate timeline-levels blocks');
  if (found.length) checkType(found[0]);
  const block = `<script id="timeline-levels" type="application/json">\n${JSON.stringify(doc, null, 2).replace(/</g, '\\u003c')}\n</script>\n`;
  if (found.length) return html.slice(0, found[0].index) + block.trimEnd() + html.slice(found[0].index + found[0][0].length);
  if (!html.includes('<script id="timeline-core">')) throw new Error('Missing timeline-core block');
  return html.replace('<script id="timeline-core">', () => block + '<script id="timeline-core">');
}
function validateLevels(data, doc) {
  const errors = [];
  const fail = s => errors.push(s);
  if (!object(doc)) return ['Levels document must be an object'];
  const date = doc.checked;
  if (typeof date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(date) || !Number.isFinite(Date.parse(date)) || new Date(date).toISOString().slice(0, 10) !== date) fail('checked must be a real ISO date');
  for (const name of ['entries', 'fields', 'roster']) if (!Array.isArray(doc[name])) fail(`${name} must be an array`);
  if (!Array.isArray(doc.entries) || !Array.isArray(doc.fields) || !Array.isArray(doc.roster)) return errors;
  const fieldsValid = doc.fields.length > 0 && doc.fields.every(f => typeof f === 'string' && /^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/.test(f)) && new Set(doc.fields).size === doc.fields.length;
  if (!fieldsValid) fail('fields must be distinct valid field IDs');
  if (fieldsValid && (!object(doc.fieldLabels) || Object.keys(doc.fieldLabels).length !== doc.fields.length || doc.fields.some(f => !Object.hasOwn(doc.fieldLabels, f) || !text(doc.fieldLabels[f])))) fail('fieldLabels must contain exactly one non-blank label per field');
  const labs = new Set(data.map(row => row.lab));
  if (new Set(doc.roster).size !== doc.roster.length || doc.roster.some(lab => typeof lab !== 'string' || !labs.has(lab))) fail('roster must contain distinct DATA labs');
  const rows = new Map(data.map(row => [key(row), row]));
  const entries = new Map();
  for (const [index, entry] of doc.entries.entries()) {
    if (!object(entry)) { fail(`entry ${index} must be an object`); continue; }
    const invalid = ['model','lab','date'].filter(name => typeof entry[name] !== 'string' || !entry[name].trim());
    if (invalid.length) { fail(`entry ${index}: invalid identity ${invalid.join(', ')}`); continue; }
    const k = key(entry), name = `${entry.lab} / ${entry.model} / ${entry.date}`;
    if (!rows.has(k)) fail(`${name}: no DATA row`);
    if (entries.has(k)) fail(`${name}: duplicate entry`);
    entries.set(k, entry);
    if (!Number.isInteger(entry.level) || entry.level < 1 || entry.level > 3) fail(`${name}: invalid level`);
    if (typeof entry.field !== 'string' || !doc.fields.includes(entry.field)) fail(`${name}: unknown field`);
    if (!text(entry.reason)) fail(`${name}: missing reason`);
    if (Object.hasOwn(entry, 'evidence') && !text(entry.evidence)) fail(`${name}: invalid evidence`);
    if (entry.level === 1 && !doc.roster.includes(entry.lab)) fail(`${name}: level 1 lab not in roster`);
    if (Object.hasOwn(entry, 'of')) {
      if (entry.level !== 3 || !object(entry.of) || !text(entry.of.model) || !text(entry.of.date) || !['stage', 'snapshot', 'variant'].includes(entry.kind) || !text(entry.label)) fail(`${name}: invalid fold`);
    } else if (Object.hasOwn(entry, 'kind') || Object.hasOwn(entry, 'label')) fail(`${name}: main entry has fold properties`);
  }
  for (const row of data) if (!entries.has(key(row))) fail(`${row.lab} / ${row.model} / ${row.date}: missing entry`);
  for (const entry of doc.entries) {
    if (!object(entry) || !object(entry.of) || !['model','lab','date'].every(name => typeof entry[name] === 'string' && entry[name].trim()) || !text(entry.of.model) || !text(entry.of.date)) continue;
    const parent = entries.get(key({model:entry.of.model, lab:entry.lab, date:entry.of.date}));
    if (!parent || Object.hasOwn(parent, 'of') || parent.field !== entry.field) fail(`${entry.model}: invalid fold parent`);
    else if (entry.kind !== 'variant' && entry.date < parent.date) fail(`${entry.model}: fold precedes parent`);
  }
  return errors;
}
if (require.main === module) {
  try {
    const {readData} = require('./timeline-analysis.cjs');
    const html = fs.readFileSync(page, 'utf8'), doc = readLevelsFile();
    const errors = validateLevels(readData(html), doc);
    if (errors.length) throw new Error(errors.join('\n'));
    if (process.argv.includes('--write')) fs.writeFileSync(page, embedLevels(html, doc));
    const totals = [1,2,3].map(n => `${n}: ${doc.entries.filter(e => e.level === n).length}`).join(', ');
    console.log(`${doc.entries.length} entries; levels ${totals}; ${doc.entries.filter(e => e.of).length} folds`);
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
module.exports = {readLevelsFile, readEmbeddedLevels, validateLevels, embedLevels};
