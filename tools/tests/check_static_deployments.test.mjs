// Invented history only; audit fixtures never use the live webroot.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {auditStaticDeployment,FAILURES} from '../check_static_deployments.mjs';
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
test('flat audit matches source and present data without writing',async t=>{
 const f=await fixture(t);const before=await fs.stat(f.site);
 const result=await auditStaticDeployment(f);assert.equal(result.ok,true);
 assert.equal((await fs.stat(f.site)).mtimeMs,before.mtimeMs);
});
for(const [label,mutate] of [
 ['changed source',f=>fs.appendFile(path.join(f.sourceRoot,'app.js'),'\n// invented drift\n')],
 ['leftover source/cache/backup',f=>fs.mkdir(path.join(f.site,'cache'))],
 ['symlinked runtime',async f=>{await fs.unlink(path.join(f.site,'app.js'));await fs.symlink(path.join(f.sourceRoot,'app.js'),path.join(f.site,'app.js'));}],
])test(`flat audit rejects ${label}`,async t=>{const f=await fixture(t);await mutate(f);assert.equal((await auditStaticDeployment(f)).ok,false);});
// Market history is not redistributable and is never acquired by the audit, so
// the installed pair is checked for presence only, never against a local dataset.
test('flat audit passes without any external data home',async t=>{
 const f=await fixture(t);await fs.rm(f.dataHome,{recursive:true});
 assert.deepEqual(await auditStaticDeployment(f),{ok:true,errors:[]});
});
test('flat audit accepts any non-empty installed data pair',async t=>{
 const f=await fixture(t);await fs.appendFile(path.join(f.site,'market-data.csv'),'invented refreshed row\n');
 assert.equal((await auditStaticDeployment(f)).ok,true);
});
for(const [label,mutate,reason] of [
 ['missing data file',f=>fs.unlink(path.join(f.site,'market-data.js')),'data'],
 ['empty data file',f=>fs.writeFile(path.join(f.site,'market-data.csv'),''),'data'],
 ['symlinked data file',async f=>{await fs.unlink(path.join(f.site,'market-data.csv'));await fs.symlink(path.join(f.dataRoot,'market-data.csv'),path.join(f.site,'market-data.csv'));},'data'],
 ['missing target',f=>fs.rm(f.site,{recursive:true}),'directory'],
 ['extra file',f=>fs.writeFile(path.join(f.site,'notes.txt'),'invented'),'files'],
 ['changed code',f=>fs.appendFile(path.join(f.site,'app.js'),'\n// invented drift\n'),'code'],
])test(`flat audit names the failure for ${label}`,async t=>{
 const f=await fixture(t);await mutate(f);
 assert.deepEqual(await auditStaticDeployment(f),{ok:false,errors:[FAILURES[reason]]});
});
test('flat audit names the failure for a path component that is a file',async t=>{
 const f=await fixture(t);await fs.rm(f.webroot,{recursive:true});
 await fs.mkdir(f.webroot);await fs.writeFile(path.join(f.webroot,'calculators'),'invented');
 assert.deepEqual(await auditStaticDeployment(f),{ok:false,errors:[FAILURES.directory]});
});
test('flat audit names the failure for an invalid source inventory',async t=>{
 const f=await fixture(t);
 const result=await auditStaticDeployment({webroot:f.webroot,sourceInventory:Buffer.from('invented\0')});
 assert.deepEqual(result,{ok:false,errors:[FAILURES.inventory]});
});
test('failure reasons are fixed lowercase text the fleet audit may print',()=>{
 for(const reason of Object.values(FAILURES))assert.match(reason,/^backtest [a-z ]+$/);
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
