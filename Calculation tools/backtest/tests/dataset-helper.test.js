'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs/promises'), path = require('node:path');
const { staticFixture } = require('./helpers/static-fixture.cjs');

// Every dataset here is algorithmically invented; no historical observations.
test('verified test reader pins a bundle and returns fresh payload, pair and row copies', async t => {
  const { createDatasetReader } = require('./helpers/dataset.cjs');
  const f = await staticFixture(t);
  const reader = createDatasetReader({dataRoot:f.dataRoot,sourceRoot:f.sourceRoot});
  const first = await reader.getDataset();
  assert.equal(first.bundleId,f.provenance.bundleId);
  assert.deepEqual(first.provenance,f.provenance);
  assert.deepEqual(first.files.get('market-data.csv'),f.pair.csv);
  first.payload.rows[0].year = -123;
  first.files.get('market-data.js').fill(0);
  const rows = await reader.getMarketRows(); rows[0].year = -456;
  assert.equal((await reader.getMarketRows())[0].year,1872);
  assert.equal((await reader.getDataset()).payload.rows[0].year,1872);
  assert.deepEqual((await reader.getDataset()).files.get('market-data.js'),f.pair.js);
});

test('missing, corrupt and stale test data fails actionably without setup or writes', async t => {
  const { createDatasetReader } = require('./helpers/dataset.cjs');
  const f = await staticFixture(t);
  const options = {dataRoot:f.dataRoot,sourceRoot:f.sourceRoot};
  await assert.rejects(createDatasetReader({dataHome:path.join(f.base,'absent'),sourceRoot:f.sourceRoot}).getDataset(),/npm run setup:data/);
  const before = await fs.readdir(f.base);
  await fs.writeFile(path.join(f.dataRoot,'market-data.js'),'globalThis.SYNTHETIC_EXECUTED = true;\n',{mode:0o600});
  await assert.rejects(createDatasetReader(options).getDataset(),/npm run setup:data/);
  assert.equal(globalThis.SYNTHETIC_EXECUTED,undefined);
  assert.deepEqual(await fs.readdir(f.base),before);
  await fs.writeFile(path.join(f.dataRoot,'market-data.js'),f.pair.js);
  await fs.appendFile(path.join(f.sourceRoot,'engine.js'),'\n// invented stale recipe\n');
  await assert.rejects(createDatasetReader(options).getDataset(),/stale.*npm run setup:data/);
});

test('one-process selection cache cannot be changed by later selector edits', async t => {
  const { createDatasetReader } = require('./helpers/dataset.cjs');
  const f = await staticFixture(t);
  await fs.mkdir(path.join(f.dataHome,'datasets'),{mode:0o700});
  const root=path.join(f.dataHome,'datasets',f.provenance.bundleId);
  await fs.rename(f.dataRoot,root);
  const selector=path.join(f.dataHome,'current.json');
  await fs.writeFile(selector,JSON.stringify({schemaVersion:1,bundleId:f.provenance.bundleId,dataId:f.provenance.dataId,recipeId:f.provenance.recipeId}),{mode:0o600});
  const reader=createDatasetReader({dataHome:f.dataHome,sourceRoot:f.sourceRoot});
  await reader.getDataset();
  await fs.writeFile(selector,'{"invented":"invalid later selection"}');
  assert.equal((await reader.getDataset()).bundleId,f.provenance.bundleId);
  await assert.rejects(createDatasetReader({dataHome:f.dataHome,sourceRoot:f.sourceRoot}).getDataset(),/npm run setup:data/);
});

test('a hash-consistent malicious JavaScript pair is rejected as data and cannot execute',async t=>{
 const {createDatasetReader}=require('./helpers/dataset.cjs'),f=await staticFixture(t),contract=await import('../tools/data_contract.mjs');
 const malicious=Buffer.from(f.pair.js.toString().replace(/"stock_tr":-?\d+(?:\.\d+)?/,'"stock_tr":(globalThis.SYNTHETIC_EXECUTED = true, 0)'));
 assert.notDeepEqual(malicious,f.pair.js);
 const provenance=structuredClone(f.provenance);
 provenance.files=provenance.files.map(r=>r.path==='market-data.js'?{...r,sha256:contract.sha256(malicious)}:r);
 provenance.dataId=contract.fileIdentity(provenance.files);provenance.bundleId=contract.bundleIdentity(provenance);
 const dataRoot=path.join(f.dataHome,provenance.bundleId);await fs.cp(f.dataRoot,dataRoot,{recursive:true});
 await fs.writeFile(path.join(dataRoot,'market-data.js'),malicious);await fs.writeFile(path.join(dataRoot,'provenance.json'),JSON.stringify(provenance)+'\n');
 await assert.rejects(createDatasetReader({dataRoot,sourceRoot:f.sourceRoot}).getDataset(),/npm run setup:data/);
 assert.equal(globalThis.SYNTHETIC_EXECUTED,undefined);
});
