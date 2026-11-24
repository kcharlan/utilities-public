const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const levels = require('../scripts/timeline-levels.cjs');
const {readData} = require('../scripts/timeline-analysis.cjs');
const html = fs.readFileSync(path.join(__dirname, '..', 'ai-model-timeline.html'), 'utf8');

test('supplied levels validate and embedding is safe and idempotent', () => {
  const doc = levels.readLevelsFile();
  assert.deepEqual(levels.validateLevels(readData(html), doc), []);
  assert.deepEqual(levels.readEmbeddedLevels(html), doc);
  const embedded = levels.embedLevels(html, doc);
  assert.deepEqual(levels.readEmbeddedLevels(embedded), doc);
  assert.equal(levels.embedLevels(embedded, doc), embedded);
  const dangerous = {...doc, extra: "</script> const DATA = $& $$ $' $`"};
  assert.deepEqual(levels.readEmbeddedLevels(levels.embedLevels(html, dangerous)), dangerous);
  assert.deepEqual(readData(levels.embedLevels(html, dangerous)), readData(html));
  const {extractInlineScript} = require('./helpers/timeline-page');
  assert.match(extractInlineScript(levels.embedLevels(html, dangerous)), /(?:^|\n)const DATA = \[/);
  const tight = embedded.replace('</script>\n<script id="timeline-core">', '</script><script id="timeline-core">');
  assert.deepEqual(levels.readEmbeddedLevels(levels.embedLevels(tight,dangerous)), dangerous);
});

test('validator rejects malformed fields, dates, entries, and fold relationships', () => {
  const rows = [{model:'A',lab:'Lab',date:'2024-01-01'}, {model:'B',lab:'Lab',date:'2024-01-02'}];
  const base = {checked:'2024-02-29', fields:['general'], fieldLabels:{general:'General'}, roster:['Lab'], entries:[
    {...rows[0],level:1,field:'general',reason:'Main'},
    {...rows[1],level:3,field:'general',reason:'Stage',kind:'stage',label:'API',of:{model:'A',date:'2024-01-01'}}
  ]};
  assert.deepEqual(levels.validateLevels(rows,base), []);
  const invalid = [
    d=>d.checked='2023-02-29', d=>d.fields=[], d=>d.fields=['a,b'], d=>d.fields=[['general']], d=>d.fields=['g\ud800'],
    d=>d.fieldLabels.extra='Extra', d=>d.fieldLabels.general=' ', d=>d.roster.push('Lab'), d=>d.roster=['Unknown'],
    d=>d.entries.pop(), d=>d.entries.push({...d.entries[0]}), d=>d.entries[0].model='Missing',
    d=>d.entries[0].level=0, d=>d.entries[0].field='missing', d=>d.entries[0].reason=' ', d=>d.entries[0].evidence='',
    d=>d.roster=[], d=>d.entries[1].of=null, d=>d.entries[1].kind='bad', d=>d.entries[1].label='',
    d=>d.entries[1].of.model='Missing', d=>d.entries[1].field='other', d=>d.entries[0].kind='stage',
    d=>d.entries[1].date='2023-12-31'
  ];
  for (const mutate of invalid) {
    const doc = structuredClone(base); mutate(doc);
    assert.ok(levels.validateLevels(rows,doc).length, `accepted ${mutate}`);
  }
  const variant = structuredClone(base);
  variant.entries[1].kind = 'variant';
  variant.entries[1].date = '2023-12-31';
  const earlierRows = [rows[0], {...rows[1],date:'2023-12-31'}];
  assert.deepEqual(levels.validateLevels(earlierRows,variant), []);
});

test('embedded levels reader diagnoses missing, duplicate and malformed blocks', () => {
  assert.throws(() => levels.readEmbeddedLevels(''), /found 0/);
  const block = '<script id="timeline-levels" type="application/json">{}</script>';
  assert.throws(() => levels.readEmbeddedLevels(block + block), /found 2/);
  assert.throws(() => levels.readEmbeddedLevels(block.replace('{}', '{')), /Malformed/);
});

test('validator rejects incomplete structures and enforces fold ordering', () => {
  const rows = [{model:'A',lab:'Lab',date:'2024-01-02'}, {model:'B',lab:'Lab',date:'2024-01-01'}];
  const doc = {checked:'2024-01-01',fields:['general'],fieldLabels:{general:'General'},roster:['Lab'],entries:[
    {...rows[0],level:1,field:'general',reason:'Main'},
    {...rows[1],level:3,field:'general',reason:'Fold',kind:'variant',label:'Fast',of:{model:'A',date:'2024-01-02'}}
  ]};
  assert.deepEqual(levels.validateLevels(rows,doc), []);
  for (const mutate of [d=>d.entries=null, d=>d.fields=null, d=>d.roster=null, d=>d.fieldLabels=null,
    d=>d.fields.push('general'), d=>d.entries[0]=null, d=>d.entries[0].level=1.5,
    d=>d.entries[1].level=2, d=>d.entries[1].kind='stage', d=>delete d.entries[1].of.date,
    d=>d.entries[0].of={model:'B',date:'2024-01-01'}]) {
    const candidate = structuredClone(doc); mutate(candidate);
    assert.ok(levels.validateLevels(rows,candidate).length, `accepted ${mutate}`);
  }
  assert.ok(levels.validateLevels(rows,null).length);
});

test('malformed identities produce indexed diagnostics without coercion', () => {
  const doc = {checked:'2024-01-01',fields:['general'],fieldLabels:{general:'General'},roster:[],entries:[{model:{toString:null},lab:'Lab',date:'2024-01-01',level:3,field:'general',reason:'test'}]};
  assert.match(levels.validateLevels([],doc).join('\n'), /entry 0.*model/i);
});

test('embedded reader recognizes attribute order and rejects duplicate or wrong-type IDs', () => {
  const block = '<script type="application/json" id="timeline-levels">{}</script>';
  assert.deepEqual(levels.readEmbeddedLevels(block), {});
  assert.deepEqual(levels.readEmbeddedLevels('<script type=application/json id=timeline-levels>{}</script>'), {});
  assert.throws(() => levels.embedLevels('<script id=timeline-levels>',{}), /missing closing/);
  assert.throws(() => levels.readEmbeddedLevels(block + '<script id="timeline-levels" type="application/json">{}</script>'), /2|duplicate/i);
  assert.throws(() => levels.readEmbeddedLevels('<script id="timeline-levels" type="text/javascript">{}</script>'), /type/i);
  const embedded = levels.embedLevels(block + '<script id="timeline-core"></script>', {value:'test'});
  assert.deepEqual(levels.readEmbeddedLevels(embedded), {value:'test'});
  assert.equal((embedded.match(/id="timeline-levels"/g) || []).length, 1);
});

test('embedding rejects ambiguous unclosed levels and ignores IDs inside quoted attributes', () => {
  const broken = '<script id="timeline-levels" type="application/json">{}\n<script id="timeline-core">core()</script>';
  assert.throws(() => levels.embedLevels(broken,{}), /malformed|closing/i);
  const innocent = `<script data-example=' id="timeline-levels" ' type="application/json">{}</script><script id="timeline-core">core()</script>`;
  const result = levels.embedLevels(innocent,{valid:true});
  assert.ok(result.includes(innocent.slice(0,innocent.indexOf('<script id="timeline-core">'))));
  assert.deepEqual(levels.readEmbeddedLevels(result), {valid:true});
});

test('script opening tags respect greater-than signs inside quoted attributes', () => {
  const reordered = '<script data-caption="A > B" id="timeline-levels" type="application/json">{}</script><script id="timeline-core">core()</script>';
  assert.deepEqual(levels.readEmbeddedLevels(reordered), {});
  const replaced = levels.embedLevels(reordered,{valid:true});
  assert.equal((replaced.match(/id="timeline-levels"/g) || []).length,1);
  assert.deepEqual(levels.readEmbeddedLevels(replaced), {valid:true});
  const decoy = `<script data-caption=' id="timeline-levels" > text ' type="application/json">{}</script><script id="timeline-core">core()</script>`;
  const embedded = levels.embedLevels(decoy,{valid:true});
  assert.ok(embedded.startsWith(decoy.slice(0,decoy.indexOf('<script id="timeline-core">'))));
  assert.deepEqual(levels.readEmbeddedLevels(embedded), {valid:true});
});
