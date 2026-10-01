'use strict';
// Immutable generations, rewritten HTML and metadata admission were withdrawn.
// These tests retain the ordinary copy, input, modes and recovery contracts.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs/promises'),path=require('node:path');
const {staticFixture}=require('./helpers/static-fixture.cjs');
const load=()=>import('../tools/build_static.mjs');
test('flat build copies exactly twelve unchanged source and selected data files',async t=>{
 const f=await staticFixture(t),api=await load(),out=path.join(f.base,'site');
 assert.equal(typeof api.buildStatic,'function');await api.buildStatic({...f,outputDir:out});
 assert.deepEqual((await fs.readdir(out)).sort(),[...api.RUNTIME_FILES].sort());assert.equal(api.RUNTIME_FILES.length,12);
 for(const name of api.RUNTIME_FILES){assert.deepEqual(await fs.readFile(path.join(out,name)),await fs.readFile(path.join(name.startsWith('market-data.')?f.dataRoot:f.sourceRoot,name)));assert.equal((await fs.stat(path.join(out,name))).mode&0o777,0o644);}
 assert.equal((await fs.stat(out)).mode&0o777,0o755);
 await fs.appendFile(path.join(f.sourceRoot,'app.js'),'\n// invented revision\n');await api.buildStatic({...f,outputDir:out});
 assert.deepEqual(await fs.readFile(path.join(out,'app.js')),await fs.readFile(path.join(f.sourceRoot,'app.js')));
});
test('flat build rejects unrelated output material and input/output overlap without writes',async t=>{
 const f=await staticFixture(t),api=await load(),out=path.join(f.base,'site');await fs.mkdir(out);await fs.writeFile(path.join(out,'foreign.txt'),'invented');
 await assert.rejects(api.buildStatic({...f,outputDir:out}),/inventory|unrelated/);assert.equal(await fs.readFile(path.join(out,'foreign.txt'),'utf8'),'invented');
 for(const outputDir of [f.sourceRoot,f.dataRoot,f.base,path.resolve(__dirname,'..')])await assert.rejects(api.buildStatic({...f,outputDir}),/overlap/);
});
test('flat build rejects symlinked managed files and missing data',async t=>{
 const f=await staticFixture(t),api=await load(),out=path.join(f.base,'site');await fs.unlink(path.join(f.sourceRoot,'format.js'));await fs.symlink(path.join(f.sourceRoot,'app.js'),path.join(f.sourceRoot,'format.js'));
 await assert.rejects(api.buildStatic({...f,outputDir:out}),/regular/);await assert.rejects(fs.stat(out),{code:'ENOENT'});
});
test('build copy and promotion errors preserve prior build and clean temporary siblings',async t=>{
 const f=await staticFixture(t),api=await load(),out=path.join(f.base,'site');await api.buildStatic({...f,outputDir:out});const prior=await fs.readFile(path.join(out,'app.js'));
 await fs.appendFile(path.join(f.sourceRoot,'app.js'),'\n// invented next\n');
 for(const hooks of [{copyFile:async()=>{throw Error('invented copy failure');}},{rename:async(a,b)=>{if(path.basename(a).startsWith('.atlas-stage-'))throw Error('invented promotion failure');await fs.rename(a,b);}}]){
 await assert.rejects(api.buildStatic({...f,outputDir:out,hooks}),/invented/);assert.deepEqual(await fs.readFile(path.join(out,'app.js')),prior);assert.equal((await fs.readdir(f.base)).some(n=>n.startsWith('.atlas-')),false);}
});
test('local build forwards offline setup and defaults to external site',async t=>{
 const f=await staticFixture(t),api=await load(),calls=[];const result=await api.buildLocal({...f,offline:true,hooks:{setup:async o=>{calls.push(o);return {root:f.dataRoot};}}});
 assert.equal(result.outputDirectory,path.join(f.dataHome,'site'));assert.equal(calls[0].offline,true);
 assert.deepEqual(api.parseBuildArgs(['--offline','--out','invented path']),{offline:true,out:'invented path'});assert.throws(()=>api.parseBuildArgs(['--unknown']),/Usage/);
});
test('flat build refuses a symlinked source root without producing output',async t=>{const f=await staticFixture(t),api=await load(),alias=path.join(f.base,'source alias'),out=path.join(f.base,'site');await fs.symlink(f.sourceRoot,alias);await assert.rejects(api.buildStatic({...f,sourceRoot:alias,outputDir:out}),/regular|symlink/i);await assert.rejects(fs.stat(out),{code:'ENOENT'});});
test('previous build cleanup failure preserves the verified new build and reports retained recovery',async t=>{
 const f=await staticFixture(t),api=await load(),out=path.join(f.base,'site');await api.buildStatic({...f,outputDir:out});
 await fs.appendFile(path.join(f.sourceRoot,'app.js'),'\n// invented committed build\n');const expected=await fs.readFile(path.join(f.sourceRoot,'app.js'));let error;
 try{await api.buildStatic({...f,outputDir:out,hooks:{remove:async target=>{if(path.basename(target).startsWith('.atlas-recovery-')){await fs.unlink(path.join(target,'app.js'));throw Error('invented previous cleanup failure');}await fs.rm(target,{recursive:true,force:true});}}});}catch(e){error=e;}
 assert.match(error?.message||'',/invented previous cleanup failure/);assert.equal(error.committedOutputDirectory,out);assert.ok(error.recoveryDirectory);
 assert.deepEqual(await fs.readFile(path.join(out,'app.js')),expected);assert.equal((await fs.stat(error.recoveryDirectory)).isDirectory(),true);
});
test('rollback removal failure retains original and reports occupied output and previous build',async t=>{
 const f=await staticFixture(t),api=await load(),out=path.join(f.base,'site');await api.buildStatic({...f,outputDir:out});const prior=await fs.readFile(path.join(out,'app.js'));let error;
 try{await api.buildStatic({...f,outputDir:out,hooks:{rename:async(a,b)=>{await fs.rename(a,b);if(path.basename(a).startsWith('.atlas-stage-'))await fs.appendFile(path.join(b,'app.js'),'invented postcopy damage');},remove:async target=>{if(target===out)throw Error('invented removal failure');await fs.rm(target,{recursive:true,force:true});}}});}catch(e){error=e;}
 assert.match(error?.message||'',/bytes|stale/);assert.match(error.removalError?.message||'',/invented removal failure/);assert.ok(error.recoveryDirectory);
 assert.deepEqual(await fs.readFile(path.join(error.recoveryDirectory,'app.js')),prior);assert.equal((await fs.stat(out)).isDirectory(),true);
});
test('stage cleanup failure never hides original copy error',async t=>{
 const f=await staticFixture(t),api=await load(),out=path.join(f.base,'site');let error;
 try{await api.buildStatic({...f,outputDir:out,hooks:{copyFile:async()=>{throw Error('invented copy original');},remove:async()=>{throw Error('invented stage cleanup');}}});}catch(e){error=e;}
 assert.match(error?.message||'',/invented copy original/);assert.match(error.cleanupError?.message||'',/invented stage cleanup/);assert.ok(error.stageDirectory);assert.equal((await fs.stat(error.stageDirectory)).isDirectory(),true);
});
