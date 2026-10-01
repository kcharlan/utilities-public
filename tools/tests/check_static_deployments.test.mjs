// Invented history only; audit fixtures never use the live webroot.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {auditStaticDeployment} from '../check_static_deployments.mjs';
const require=createRequire(import.meta.url);
const {staticFixture}=require('../../Calculation tools/backtest/tests/helpers/static-fixture.cjs');
const sourceNames=['index.html','format.js','stats.js','views.js','lifestyle.js','charts.js','csv.js','engine.js','app.js','DATA_SOURCES.md'];
async function fixture(t){
 const f=await staticFixture(t),webroot=path.join(f.base,'webroot'),site=path.join(webroot,'calculators/backtest');
 await fs.mkdir(site,{recursive:true});
 await fs.mkdir(path.join(f.dataHome,'datasets'));
 const dataRoot=path.join(f.dataHome,'datasets',f.provenance.bundleId);
 await fs.rename(f.dataRoot,dataRoot);
 const {bundleId,dataId,recipeId}=f.provenance;
 await fs.writeFile(path.join(f.dataHome,'current.json'),JSON.stringify({schemaVersion:1,bundleId,dataId,recipeId}));
 for(const name of sourceNames)await fs.copyFile(path.join(f.sourceRoot,name),path.join(site,name));
 for(const name of ['market-data.js','market-data.csv'])await fs.copyFile(path.join(dataRoot,name),path.join(site,name));
 return {...f,dataRoot,webroot,site,sourceContext:{sourceRoot:f.sourceRoot,repoRoot:path.join(f.base,'unused repo')}};
}
test('flat audit matches source and selected pair without writing',async t=>{
 const f=await fixture(t);const before=await fs.stat(f.site);
 const result=await auditStaticDeployment(f);assert.equal(result.ok,true);
 assert.equal((await fs.stat(f.site)).mtimeMs,before.mtimeMs);
});
for(const [label,mutate] of [
 ['changed source',f=>fs.appendFile(path.join(f.sourceRoot,'app.js'),'\n// invented drift\n')],
 ['changed deployed data',f=>fs.appendFile(path.join(f.site,'market-data.csv'),'invented drift')],
 ['missing pair',f=>fs.unlink(path.join(f.dataRoot,'market-data.csv'))],
 ['missing target',f=>fs.rm(f.site,{recursive:true})],
 ['leftover source/cache/backup',f=>fs.mkdir(path.join(f.site,'cache'))],
 ['symlinked runtime',async f=>{await fs.unlink(path.join(f.site,'app.js'));await fs.symlink(path.join(f.sourceRoot,'app.js'),path.join(f.site,'app.js'));}],
])test(`flat audit rejects ${label}`,async t=>{const f=await fixture(t);await mutate(f);assert.equal((await auditStaticDeployment(f)).ok,false);});
test('flat audit reports selected data refresh as drift until redeployed',async t=>{
 const f=await fixture(t);
 const pair={js:Buffer.from(f.pair.js.toString().replaceAll('0.01234567','0.02234567')),csv:Buffer.from(f.pair.csv.toString().replaceAll('0.01234567','0.02234567'))};
 const next=await f.generation({pair,sourceSalt:'another invented input'});
 const target=path.join(f.dataHome,'datasets',next.provenance.bundleId);await fs.rename(next.dataRoot,target);
 const {bundleId,dataId,recipeId}=next.provenance;
 await fs.writeFile(path.join(f.dataHome,'current.json'),JSON.stringify({schemaVersion:1,bundleId,dataId,recipeId}));
 const before=await fs.readFile(path.join(f.dataHome,'current.json'));
 assert.equal((await auditStaticDeployment(f)).ok,false);
 assert.deepEqual(await fs.readFile(path.join(f.dataHome,'current.json')),before);
});
test('source inventory requires every declared source member exactly once',async()=>{
 const {AUDIT_SOURCE_INPUTS,validateSourceInventory}=await import('../check_static_deployments.mjs');
 const bytes=names=>Buffer.from(names.map(n=>'100644\t'+n+'\0').join(''));
 assert.equal(validateSourceInventory(bytes(AUDIT_SOURCE_INPUTS)).size,AUDIT_SOURCE_INPUTS.length);
 assert.throws(()=>validateSourceInventory(bytes(AUDIT_SOURCE_INPUTS.slice(1))));
 assert.throws(()=>validateSourceInventory(bytes([...AUDIT_SOURCE_INPUTS,AUDIT_SOURCE_INPUTS[0]])));
 assert.throws(()=>validateSourceInventory(bytes([...AUDIT_SOURCE_INPUTS,'invented-untracked.js'])));
});
test('recipe-only source edits do not create runtime byte drift',async t=>{
 const f=await fixture(t);
 await fs.appendFile(path.join(f.sourceRoot,'tools/setup_data.mjs'),'\n// Invented compiler-maintenance-only edit\n');
 assert.equal((await auditStaticDeployment(f)).ok,true);
});
