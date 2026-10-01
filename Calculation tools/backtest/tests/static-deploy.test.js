'use strict';
// Receipts, metadata restoration and immutable runtime rollback are withdrawn.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs/promises'),path=require('node:path');
const {staticFixture}=require('./helpers/static-fixture.cjs');
async function fixture(t){const f=await staticFixture(t);f.buildDir=path.join(f.base,'build');f.webroot=path.join(f.base,'webroot');f.backupRoot=path.join(f.base,'backups');await fs.mkdir(f.webroot);await(await import('../tools/build_static.mjs')).buildStatic({...f,outputDir:f.buildDir});f.site=path.join(f.webroot,'calculators/backtest');return f;}
const load=()=>import('../tools/deploy_static.mjs');
test('deploy copies flat runtime and moves whole legacy app privately preserving links and siblings',async t=>{
 const f=await fixture(t),api=await load();await fs.mkdir(f.site,{recursive:true});await fs.writeFile(path.join(f.site,'legacy.txt'),'invented old');await fs.symlink('legacy.txt',path.join(f.site,'legacy-link'));await fs.writeFile(path.join(f.webroot,'calculators/other.html'),'invented sibling');
 const result=await api.deployStatic(f);assert.equal(result.canonicalURL,'/calculators/backtest/index.html');assert.equal(await fs.readFile(path.join(result.backupDirectory,'legacy.txt'),'utf8'),'invented old');assert.equal(await fs.readlink(path.join(result.backupDirectory,'legacy-link')),'legacy.txt');assert.equal((await fs.stat(path.dirname(result.backupDirectory))).mode&0o777,0o700);
 assert.equal(await fs.readFile(path.join(f.webroot,'calculators/other.html'),'utf8'),'invented sibling');assert.deepEqual((await fs.readdir(f.site)).sort(),(await fs.readdir(f.buildDir)).sort());
});
test('dry run writes nothing including backup or calculator directories',async t=>{const f=await fixture(t),api=await load(),before=await fs.readdir(f.base);const result=await api.deployStatic({...f,dryRun:true});assert.equal(result.dryRun,true);assert.equal(result.fileCount,12);assert.deepEqual(await fs.readdir(f.base),before);assert.deepEqual(await fs.readdir(f.webroot),[]);});
for(const absent of [false,true])test('copy/postcopy failure restores '+(absent?'absence':'whole prior tree'),async t=>{
 const f=await fixture(t),api=await load();if(!absent){await fs.mkdir(f.site,{recursive:true});await fs.writeFile(path.join(f.site,'legacy'),'invented prior');}
 for(const hooks of [{copyFile:async()=>{throw Error('invented copy failure');}},{verify:async()=>{throw Error('invented postcopy failure');}}]){await assert.rejects(api.deployStatic({...f,hooks}),/invented/);if(absent)await assert.rejects(fs.stat(f.site),{code:'ENOENT'});else assert.equal(await fs.readFile(path.join(f.site,'legacy'),'utf8'),'invented prior');}
});
test('stale build extra files symlinks and backup/webroot overlap fail before mutation',async t=>{
 const f=await fixture(t),api=await load();await fs.appendFile(path.join(f.sourceRoot,'app.js'),'\n// invented drift\n');await assert.rejects(api.deployStatic(f),/stale|bytes/);assert.deepEqual(await fs.readdir(f.webroot),[]);
 await(await import('../tools/build_static.mjs')).buildStatic({...f,outputDir:f.buildDir});await fs.writeFile(path.join(f.buildDir,'foreign'),'invented');await assert.rejects(api.deployStatic(f),/inventory/);await fs.unlink(path.join(f.buildDir,'foreign'));
 await assert.rejects(api.deployStatic({...f,backupRoot:path.join(f.webroot,'backups')}),/overlap/);
});
test('restoration failure reports both errors and retained backup path',async t=>{
 const f=await fixture(t),api=await load();await fs.mkdir(f.site,{recursive:true});await fs.writeFile(path.join(f.site,'legacy'),'invented prior');let error;
 try{await api.deployStatic({...f,hooks:{copyFile:async()=>{throw Error('invented original');},rename:async(a,b)=>{if(path.dirname(a)!==path.dirname(f.site)&&path.basename(a)==='backtest')throw Error('invented restoration');await fs.rename(a,b);}}});}catch(e){error=e;}
 assert.match(error.message,/invented original/);assert.match(error.restorationError.message,/invented restoration/);assert.equal(await fs.readFile(path.join(error.backupDirectory,'legacy'),'utf8'),'invented prior');assert.match(api.formatDeploymentFailure(error).join('\n'),/restoration/);
});
test('deploy CLI accepts only build webroot and dry-run options',async()=>{const api=await load();assert.deepEqual(api.parseDeployArgs(['--build-dir','invented build','--webroot','invented root','--dry-run']),{buildDir:'invented build',webroot:'invented root',dryRun:true});assert.throws(()=>api.parseDeployArgs(['--rollback','invented']),/Usage/);});
test('deploy refuses a webroot in source or repository before touching it',async t=>{const f=await fixture(t),api=await load();for(const webroot of [f.sourceRoot,path.resolve(__dirname,'..')])await assert.rejects(api.deployStatic({...f,webroot}),/overlap/);});
test('deploy canonicalizes a missing webroot below an alias before overlap checks',async t=>{const f=await fixture(t),api=await load(),alias=path.join(f.base,'source alias');await fs.symlink(f.sourceRoot,alias);await assert.rejects(api.deployStatic({...f,webroot:path.join(alias,'missing webroot')}),/overlap|symlink/i);await assert.rejects(fs.stat(path.join(f.sourceRoot,'missing webroot')),{code:'ENOENT'});});
test('deploy refuses a custom selected data root as the webroot',async t=>{
 const f=await fixture(t),api=await load(),dataHome=path.join(f.base,'different data home');
 await assert.rejects(api.deployStatic({...f,dataHome,webroot:f.dataRoot}),/overlap/);
 await assert.rejects(fs.stat(path.join(f.dataRoot,'calculators')),{code:'ENOENT'});
});
