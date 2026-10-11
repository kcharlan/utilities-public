'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const api = import('../tools/data_contract.mjs');
const hash = value => createHash('sha256').update(value).digest('hex');
const { inventedPair } = require('./helpers/invented-pair.cjs');
test('recipe snapshots accept readable regular hard-linked files',async t=>{
 const fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os');
 const {RECIPE_FILES,readRecipe}=await api;
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'market-atlas-invented-recipe-'));t.after(()=>fs.rm(root,{recursive:true,force:true}));
 for(const name of RECIPE_FILES){const target=path.join(root,name);await fs.mkdir(path.dirname(target),{recursive:true});await fs.copyFile(path.resolve(__dirname,'..',name),target);}
 await fs.link(path.join(root,'engine.js'),path.join(root,'invented-source-alias'));
 assert.equal((await readRecipe(root)).files.length,RECIPE_FILES.length);
});
test('canonical file identity pins ordering, key insertion and newline', async () => {
  const { fileIdentity } = await api;
  assert.equal(fileIdentity([{path:'z',sha256:hash('z')},{path:'a',sha256:hash('a')}]),
    '7814448c740256efdcfc34b7f303a12e74c4e85d6dfdb42757d319569a3da7eb');
});
test('canonical bundle identity excludes private manual filenames', async () => {
  const { bundleIdentity } = await api;
  assert.equal(bundleIdentity({dataId:hash('data'),recipeId:hash('recipe'),generatedDate:'2026-10-01',
    sources:[{id:'z',url:'https://example.invalid/z',sha256:hash('z')},
      {id:'a',url:'https://example.invalid/a',sha256:hash('a')}]}),
    'de609a0d5b98b8884c403a5add5ba34ce04c1ee5c2b7df4f41c9b3d65d080cf1');
});
test('parsePair accepts algorithmically invented rows and never executes JS', async () => {
  const { parsePair } = await api; const {js,csv} = inventedPair();
  assert.equal(parsePair(js,csv).rows.length,154);
  assert.throws(() => parsePair(Buffer.concat([js,Buffer.from('process.exit(0);')]),csv), /envelope/);
});
test('both legacy and current schemas verify, mixed schemas and legacy candidates fail',async()=>{
 const {parsePair,retainedInputName}=await api;
 const current=inventedPair(),legacy=inventedPair({legacy:true});
 assert.ok(Object.hasOwn(parsePair(current.js,current.csv).rows[0],'tbill_dtb3_tr'));
 assert.ok(!Object.hasOwn(parsePair(legacy.js,legacy.csv).rows[0],'tbill_dtb3_tr'));
 assert.throws(()=>parsePair(legacy.js,legacy.csv,{requireCurrentSchema:true}),/tbill_dtb3_tr/);
 assert.throws(()=>parsePair(current.js,legacy.csv),/CSV/);
 assert.throws(()=>parsePair(legacy.js,current.csv),/CSV/);
 for(const [before,after]of [['"tbill_dtb3_tr":null','"tbill_dtb3_tr":0'],['"tbill_dtb3_tr":0.00456789','"tbill_dtb3_tr":null']])
  assert.throws(()=>parsePair(Buffer.from(current.js.toString().replace(before,after)),current.csv));
 assert.equal(retainedInputName('fred'),'source.csv');
 assert.equal(retainedInputName('shiller'),'source.xls');assert.equal(retainedInputName('damodaran'),'source.xls');
 assert.throws(()=>retainedInputName('invented'),/Unknown/);
});
test('parsePair rejects invalid dates, pair divergence, chronology and quality', async () => {
  const { parsePair } = await api; const {js,csv} = inventedPair();
  for (const [before,after] of [['2026-10-01','2026-02-30'],['"year":1872','"year":1873'],
    ['"quality":"ok"','"quality":"fabricated"'],['0.01234567','0.09999999']])
    assert.throws(() => parsePair(Buffer.from(js.toString().replace(before,after)),csv));
});
test('real historical checker rejects the invented fixture', async () => {
  const { checkHistorical } = await import('../tools/check_historical.mjs');
  const { parsePair } = await api;const {js,csv}=inventedPair();
  assert.throws(()=>checkHistorical(parsePair(js,csv).rows));
});
test('dataId and recipeId pin project-relative logical file names',async()=>{
 const { fileIdentity }=await api;
 assert.equal(fileIdentity([{path:'market-data.csv',sha256:hash('invented CSV')},{path:'market-data.js',sha256:hash('invented JS')}]),'82b331f6f4833cf8da5373ca4ff817779789eb048379ebac255f8ffffe26ad30');
 assert.equal(fileIdentity([{path:'data/compile_market_data.py',sha256:hash('invented compiler')},{path:'data/requirements.lock',sha256:hash('invented lock')},{path:'data/sources.json',sha256:hash('invented recipe')}]),'5ae57207ce94245b38c61cfe1ece873c10911f5c4d49ed989d590159a2b9bb72');
});
test('CSV decimal grammar rejects Number aliases and JS metadata preserves order',async()=>{
 const {parsePair}=await api;const {js,csv}=inventedPair();
 for(const replacement of ['0x750,','01872,',' 1872,','+1872,'])assert.throws(()=>parsePair(js,Buffer.from(csv.toString().replace('1872,',replacement))),/decimal/);
 const payload=JSON.parse(js.toString().slice('globalThis.MARKET_DATA = '.length,-2));
 payload.sources.stock_tr='';assert.throws(()=>parsePair(Buffer.from('globalThis.MARKET_DATA = '+JSON.stringify(payload)+';\n'),csv),/source metadata/);
 payload.sources.stock_tr='Invented synthetic source';payload.rows[0]={stock_tr:payload.rows[0].stock_tr,...payload.rows[0]};
 assert.throws(()=>parsePair(Buffer.from('globalThis.MARKET_DATA = '+JSON.stringify(payload)+';\n'),csv),/field order/);
});
test('generated calendar dates reject year zero while preserving early years and leap rules',async()=>{
 const {validDate,parsePair,bundleIdentity}=await api;
 for(const value of ['0001-01-01','0099-12-31','2000-02-29','9999-12-31'])assert.equal(validDate(value),value);
 for(const value of ['0000-01-01','0000-02-29','0099-02-29','1900-02-29','2026-02-30'])assert.throws(()=>validDate(value),/Invalid generated date/);
 const {js,csv}=inventedPair();assert.throws(()=>parsePair(Buffer.from(js.toString().replace('2026-10-01','0000-01-01')),csv),/Invalid generated date/);
 assert.throws(()=>bundleIdentity({dataId:hash('invented data'),recipeId:hash('invented recipe'),sources:[],generatedDate:'0000-01-01'}),/Invalid generated date/);
});
