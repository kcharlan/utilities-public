'use strict';
const test=require('node:test'), assert=require('node:assert/strict');
const fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os');
const { inventedPair }=require('./helpers/invented-pair.cjs');
const api=import('../tools/setup_data.mjs'); const contract=import('../tools/data_contract.mjs');
const sourceRoot=path.resolve(__dirname,'..');
async function fixture(t) {
 const base=await fs.mkdtemp(path.join(os.tmpdir(),'market-atlas-invented-'));t.after(()=>fs.rm(base,{recursive:true,force:true}));
 const dataHome=path.join(base,'data home');await fs.mkdir(dataHome,{mode:0o700});
 const calls=[],compiledInputs=[];let revision=0;
 const manual={};for(const id of ['shiller','damodaran']) {manual[id]=path.join(base,id+' invented.xls');await fs.writeFile(manual[id],Buffer.concat([Buffer.from([0xd0,0xcf,0x11,0xe0,0xa1,0xb1,0x1a,0xe1]),Buffer.alloc(504,id==='shiller'?17:23)]),{mode:0o644});}
 for(const target of Object.values(manual))await fs.chmod(target,0o644);
 const hooks={ async run(command,args,options) {
  calls.push({command,args,options});
  if(args[0]==='-m'&&args[1]==='venv') {const dir=args.at(-1);await fs.mkdir(path.join(dir,'bin'),{recursive:true,mode:0o700});await fs.writeFile(path.join(dir,'pyvenv.cfg'),'home = /invented/python\nversion = 3.14.7\ninclude-system-site-packages = false\n',{mode:0o600});await fs.writeFile(path.join(dir,'bin','python'),'invented executable\n',{mode:0o700});return '';}
  if(args[0]==='-c') return JSON.stringify({version:'3.14.7',platform:'darwin',machine:'arm64',ready:true,isolated:true});
  if(args[0]?.endsWith('compile_market_data.py')) {
   for(const id of ['shiller','damodaran'])if(!args.includes('--'+id))await fs.writeFile(path.join(options.env.MARKET_ATLAS_DATA_HOME,id==='shiller'?'ie_data.xls':'histretSP.xls'),Buffer.concat([Buffer.from([0xd0,0xcf,0x11,0xe0,0xa1,0xb1,0x1a,0xe1]),Buffer.alloc(504,31+revision++)]),{mode:0o600});
   if(args.includes('--acquire-only'))return '';
   const inputs=new Map();for(const id of ['shiller','damodaran'])if(args.includes('--'+id))inputs.set(id,await fs.readFile(args[args.indexOf('--'+id)+1]));compiledInputs.push({args,inputs});
   const output=args[args.indexOf('--output-dir')+1],pair=inventedPair();for(const [name,bytes]of [['market-data.js',pair.js],['market-data.csv',pair.csv]])await fs.writeFile(path.join(output,name),bytes,{mode:0o600});return '';
  }
  return '';
 }, async historical() { calls.push({historical:true}); }};
 return {base,dataHome,manual,calls,compiledInputs,hooks,options:{sourceRoot,repoRoot:path.resolve(sourceRoot,'../..'),dataHome,hooks}};
}
test('cold setup prepares venv, compiler and immutable selected generation',async t=>{
 const f=await fixture(t),{setupData}=await api,{verifySelected}=await contract;
 const result=await setupData(f.options);assert.equal(result.reused,false);
 assert.equal(f.calls[0].command,'python3.14');assert.deepEqual(f.calls[0].args.slice(0,3),['-m','venv','--copies']);
 assert.ok(f.calls.some(call=>call.args?.includes('data/requirements.lock')||call.args?.some(arg=>arg.endsWith('/data/requirements.lock'))));
 const selected=await verifySelected(f.options);assert.equal(selected.bundleId,result.bundleId);
 assert.equal((await fs.stat(path.join(f.dataHome,'current.json'))).mode&0o777,0o600);
});
test('warm and offline reuse are read-only with zero Python/acquisition/dependency calls or lock creation',async t=>{
 const f=await fixture(t),{setupData}=await api;await setupData(f.options);f.calls.length=0;
 const before=await fs.readFile(path.join(f.dataHome,'current.json'));
 const warm=await setupData({...f.options,offline:true});assert.equal(warm.reused,true);assert.deepEqual(f.calls,[]);
 assert.deepEqual(await fs.readFile(path.join(f.dataHome,'current.json')),before);await assert.rejects(fs.stat(path.join(f.dataHome,'.setup.lock')),{code:'ENOENT'});
});
test('setup preserves unrelated site, temporary and legacy entries through warm offline reuse',async t=>{
 const f=await fixture(t),{setupData}=await api;
 for(const name of ['site','.temporary','legacy.txt'])await fs.writeFile(path.join(f.dataHome,name),'invented unrelated entry');
 await fs.chmod(f.dataHome,0o755);
 await setupData(f.options);f.calls.length=0;
 const before=await fs.readFile(path.join(f.dataHome,'current.json'));
 assert.equal((await setupData({...f.options,offline:true})).reused,true);
 assert.deepEqual(f.calls,[]);assert.deepEqual(await fs.readFile(path.join(f.dataHome,'current.json')),before);
 for(const name of ['site','.temporary','legacy.txt'])assert.equal(await fs.readFile(path.join(f.dataHome,name),'utf8'),'invented unrelated entry');
 assert.equal((await fs.stat(f.dataHome)).mode&0o777,0o755);
});
test('compatible isolated compiler venv accepts different patch and CPU identities',async t=>{
 const f=await fixture(t),{setupData}=await api;await setupData(f.options);
 await fs.writeFile(path.join(f.dataHome,'.venv','pyvenv.cfg'),'home = /invented/python\nversion = 3.14.8\ninclude-system-site-packages = false\n');
 const hooks={...f.hooks,run:async(command,args,options)=>args[0]==='-c'?JSON.stringify({version:'3.14.8',platform:'darwin',machine:'x86_64',ready:true,isolated:true}):f.hooks.run(command,args,options)};
 assert.equal((await setupData({...f.options,refresh:true,hooks})).reused,false);
});
test('explicit input compilation leaves unconsumed legacy caches and build entries alone',async t=>{
 const f=await fixture(t),{setupData}=await api;
 await fs.writeFile(path.join(f.dataHome,'ie_data.xls'),'invented unrelated old cache');
 await fs.writeFile(path.join(f.dataHome,'builds'),'invented unrelated build entry');
 assert.equal((await setupData({...f.options,...f.manual})).reused,false);
 assert.equal(await fs.readFile(path.join(f.dataHome,'ie_data.xls'),'utf8'),'invented unrelated old cache');
});
test('refresh ignores unconsumed legacy cache bytes and preserves them',async t=>{
 const f=await fixture(t),{setupData}=await api;
 const legacy=path.join(f.dataHome,'ie_data.xls');await fs.writeFile(legacy,'invented unrelated old cache');
 assert.equal((await setupData({...f.options,refresh:true})).reused,false);
 assert.equal(await fs.readFile(legacy,'utf8'),'invented unrelated old cache');
});
test('offline refresh fails before creating the data root',async t=>{
 const f=await fixture(t),{setupData}=await api;const missing=path.join(f.base,'absent');
 await assert.rejects(setupData({...f.options,dataHome:missing,offline:true,refresh:true}),/offline.*refresh/i);await assert.rejects(fs.stat(missing),{code:'ENOENT'});
});
test('offline missing inputs or venv reports actionable preparation failure',async t=>{
 const f=await fixture(t),{setupData}=await api;
 await assert.rejects(setupData({...f.options,offline:true,...f.manual}),/offline.*venv/i);assert.equal(f.calls.length,0);
 await setupData(f.options);await fs.unlink(path.join(f.dataHome,'current.json'));
 await assert.rejects(setupData({...f.options,offline:true}),/offline.*input/i);
});
test('manual inputs remain unchanged and force candidate despite current selection',async t=>{
 const f=await fixture(t),{setupData}=await api;const first=await setupData(f.options);f.calls.length=0;
 const before=await fs.readFile(f.manual.shiller);const next=await setupData({...f.options,...f.manual,offline:true});assert.equal(next.reused,false);assert.notEqual(next.bundleId,first.bundleId);
 assert.deepEqual(await fs.readFile(f.manual.shiller),before);assert.equal((await fs.stat(f.manual.shiller)).mode&0o777,0o644);
 const compile=f.calls.find(call=>call.args?.[0]?.endsWith('compile_market_data.py'));assert.ok(compile.args.includes('--shiller')&&compile.args.includes('--damodaran'));
});
test('refresh retains old selected bundle and source objects',async t=>{
 const f=await fixture(t),{setupData}=await api,{verifyBundle}=await contract;const first=await setupData(f.options);
 const old=await verifyBundle({...f.options,bundleId:first.bundleId});const next=await setupData({...f.options,refresh:true});assert.notEqual(next.bundleId,first.bundleId);
 assert.equal((await verifyBundle({...f.options,bundleId:first.bundleId})).bundleId,old.bundleId);
});
test('compile and historical gate failures preserve selected bytes and clear own lock',async t=>{
 const f=await fixture(t),{setupData}=await api;await setupData(f.options);const before=await fs.readFile(path.join(f.dataHome,'current.json'));
 for(const hooks of [{...f.hooks,run:async()=>{throw new Error('invented compiler failure');}},
  {...f.hooks,historical:async()=>{throw new Error('invented historical rejection');}}]) {
  await assert.rejects(setupData({...f.options,refresh:true,hooks}),/invented/);assert.deepEqual(await fs.readFile(path.join(f.dataHome,'current.json')),before);
  await assert.rejects(fs.stat(path.join(f.dataHome,'.setup.lock')),{code:'ENOENT'});
 }
});
test('corrupt selector and input bytes fail closed without redownload',async t=>{
 const f=await fixture(t),{setupData}=await api,{verifySelected}=await contract;await setupData(f.options);const selected=await verifySelected(f.options);
 await fs.appendFile(path.join(f.dataHome,selected.provenance.sources[0].path),'invented corruption');f.calls.length=0;
 await assert.rejects(setupData({...f.options,refresh:true}),/input hash/);assert.deepEqual(f.calls,[]);
});
test('conflicting lock is retained and repository aliases are refused',async t=>{
 const f=await fixture(t),{setupData}=await api;
 await fs.writeFile(path.join(f.dataHome,'.setup.lock'),'other process',{mode:0o600});await assert.rejects(setupData(f.options),/lock/);
 assert.equal(await fs.readFile(path.join(f.dataHome,'.setup.lock'),'utf8'),'other process');
 const alias=path.join(f.base,'alias');await fs.symlink(sourceRoot,alias);await assert.rejects(setupData({...f.options,dataHome:alias}),/overlap|Symlink/);
});
test('stale recipe uses exact retained inputs while old bundles remain independently verifiable',async t=>{
 const f=await fixture(t),{setupData}=await api,{RECIPE_FILES,verifyBundle}=await contract;
 const copy=path.join(f.base,'invented recipe source');await fs.mkdir(copy,{mode:0o700});
 for(const name of RECIPE_FILES){await fs.mkdir(path.dirname(path.join(copy,name)),{recursive:true});await fs.copyFile(path.join(sourceRoot,name),path.join(copy,name));}
 const first=await setupData({...f.options,sourceRoot:copy});const old=await verifyBundle({...f.options,bundleId:first.bundleId});
 await fs.appendFile(path.join(copy,'data/compile_market_data.py'),'\n# Invented recipe revision\n');f.calls.length=0;
 const next=await setupData({...f.options,sourceRoot:copy,offline:true});assert.equal(next.dataId,first.dataId);assert.notEqual(next.bundleId,first.bundleId);
 const compile=f.calls.find(call=>call.args?.[0]?.endsWith('compile_market_data.py'));
 for(const item of old.provenance.sources){const input=compile.args[compile.args.indexOf('--'+item.id)+1];assert.ok(input.includes('/compile-inputs/'));assert.equal((await contract).sha256(f.compiledInputs.at(-1).inputs.get(item.id)),item.sha256);}
 await verifyBundle({...f.options,sourceRoot:copy,bundleId:first.bundleId});
 await assert.rejects(verifyBundle({...f.options,sourceRoot:copy,bundleId:first.bundleId,requireCurrentRecipe:true}),/stale/);
});
test('selector promotion failure and cancellation preserve old bytes',async t=>{
 const f=await fixture(t),{setupData}=await api;await setupData(f.options);const before=await fs.readFile(path.join(f.dataHome,'current.json'));
 await assert.rejects(setupData({...f.options,refresh:true,hooks:{...f.hooks,promote:async()=>{throw new Error('invented rename failure');}}}),/rename failure/);
 const controller=new AbortController();controller.abort();await assert.rejects(setupData({...f.options,refresh:true,signal:controller.signal}),/interrupted/);
 assert.deepEqual(await fs.readFile(path.join(f.dataHome,'current.json')),before);
 assert.equal((await fs.readdir(f.dataHome)).filter(name=>name.startsWith('.candidate')||name.startsWith('.current')||name==='.setup.lock').length,0);
});
test('corrupt selected identities, dates, recipe snapshots and pair fail closed',async t=>{
 const f=await fixture(t),{setupData}=await api,{verifySelected}=await contract;await setupData(f.options);const selected=await verifySelected(f.options);
 for(const [filename,mutate]of [
  [path.join(f.dataHome,'current.json'),bytes=>bytes.toString().replace(selected.dataId,'a'.repeat(64))],
  [path.join(selected.root,'provenance.json'),bytes=>bytes.toString().replace('2026-10-01','2026-02-30')],
  [path.join(selected.root,'market-data.csv'),bytes=>bytes.toString()+'invented damage'],
  [path.join(selected.root,'recipe/data/requirements.lock'),bytes=>bytes.toString()+'# altered'],
 ]) {const before=await fs.readFile(filename);await fs.writeFile(filename,mutate(before));f.calls.length=0;
   await assert.rejects(setupData(f.options));assert.deepEqual(f.calls,[]);await fs.writeFile(filename,before);}
});
test('managed symlinks and cache corruption are refused',async t=>{
 const f=await fixture(t),{setupData}=await api;
 await fs.writeFile(path.join(f.dataHome,'ie_data.xls'),'invented corrupt cache',{mode:0o600});await assert.rejects(setupData(f.options),/XLS/);assert.deepEqual(f.calls,[]);
 await fs.unlink(path.join(f.dataHome,'ie_data.xls'));
 const alias=path.join(f.base,'manual alias.xls');await fs.symlink(f.manual.shiller,alias);await assert.rejects(setupData({...f.options,...f.manual,shiller:alias}),/regular file/);
});
test('legacy644 manual sources in a755 parent are read without mode changes',async t=>{
 const f=await fixture(t),{setupData}=await api;const dir=path.join(f.base,'legacy');await fs.mkdir(dir,{mode:0o755});await fs.chmod(dir,0o755);
 const manual={};for(const id of ['shiller','damodaran']){manual[id]=path.join(dir,id+'.xls');await fs.copyFile(f.manual[id],manual[id]);await fs.chmod(manual[id],0o644);}
 const result=await setupData({...f.options,...manual});assert.equal(result.reused,false);assert.equal((await fs.stat(dir)).mode&0o777,0o755);
});
test('missing retained objects are corruption rather than repairable cache misses',async t=>{
 const f=await fixture(t),{setupData}=await api,{sha256}=await contract;
 const bytes=await fs.readFile(f.manual.shiller),parent=path.join(f.dataHome,'inputs',sha256(bytes));await fs.mkdir(parent,{recursive:true,mode:0o700});
 await assert.rejects(setupData({...f.options,...f.manual}),/immutable input|corrupt/i);
});
test('unsupported venv isolation config fails before compiler',async t=>{
 const f=await fixture(t),{setupData}=await api;

 await setupData(f.options);await fs.writeFile(path.join(f.dataHome,'.venv','pyvenv.cfg'),'include-system-site-packages = true\n');f.calls.length=0;
 await assert.rejects(setupData({...f.options,refresh:true}),/venv layout|dedicated compiler venv/);assert.deepEqual(f.calls,[]);
});
test('endpoint failures do not publish inputs or a selector',async t=>{
 const f=await fixture(t),{setupData}=await api;
 const hooks={...f.hooks,run:async(command,args,options)=>{if(args[0]?.endsWith('compile_market_data.py'))throw new Error('invented endpoint failure');return f.hooks.run(command,args,options);}};
 await assert.rejects(setupData({...f.options,hooks}),/endpoint failure/);
 await assert.rejects(fs.stat(path.join(f.dataHome,'current.json')),{code:'ENOENT'});
 await assert.rejects(fs.stat(path.join(f.dataHome,'inputs')),{code:'ENOENT'});
});
test('extra retained recipe files are unrecognized provenance inventory',async t=>{
 const f=await fixture(t),{setupData}=await api,{verifySelected}=await contract;await setupData(f.options);const selected=await verifySelected(f.options);
 await fs.writeFile(path.join(selected.root,'recipe','extra.txt'),'invented foreign snapshot',{mode:0o600});f.calls.length=0;
 await assert.rejects(setupData(f.options),/recipe.*inventory/);assert.deepEqual(f.calls,[]);
});
test('subprocess runner handles failing exit and bounded timeout without a shell',async()=>{
 const {runCommand}=await api;
 await assert.rejects(runCommand(process.execPath,['-e','process.exit(7)']),/failed/);
 await assert.rejects(runCommand(process.execPath,['-e','setInterval(()=>{},1000)'],{timeout:20}),/failed/);
 assert.equal(await runCommand(process.execPath,['-e','process.stdout.write("invented output")']),'invented output');
});
test('replacement lock belongs to another operation and is never removed',async t=>{
 const f=await fixture(t),{setupData}=await api;await setupData(f.options);const before=await fs.readFile(path.join(f.dataHome,'current.json'));
 const foreign=path.join(f.dataHome,'.setup.lock');const hooks={...f.hooks,historical:async()=>{await fs.unlink(foreign);await fs.writeFile(foreign,'invented foreign lock',{mode:0o600});}};
 await assert.rejects(setupData({...f.options,refresh:true,hooks}),/lock.*changed/);
 assert.equal(await fs.readFile(foreign,'utf8'),'invented foreign lock');assert.deepEqual(await fs.readFile(path.join(f.dataHome,'current.json')),before);
});
test('ready venv must actually be isolated and refuses ABI/import failures',async t=>{
 const f=await fixture(t),{setupData}=await api;await setupData(f.options);
 const hooks={...f.hooks,run:async(command,args,options)=>args[0]==='-c'?JSON.stringify({version:'3.14.7',platform:'darwin',machine:'arm64',ready:true,isolated:false}):f.hooks.run(command,args,options)};
 await assert.rejects(setupData({...f.options,refresh:true,hooks}),/isolated/);
});
test('source mutation during compilation cannot select or mislabel output recipe bytes',async t=>{
 const f=await fixture(t),{setupData}=await api,{RECIPE_FILES}=await contract;
 const copy=path.join(f.base,'mutable recipe');await fs.mkdir(copy,{mode:0o700});
 for(const name of RECIPE_FILES){await fs.mkdir(path.dirname(path.join(copy,name)),{recursive:true});await fs.copyFile(path.join(sourceRoot,name),path.join(copy,name));}
 const initial=await setupData({...f.options,sourceRoot:copy});const before=await fs.readFile(path.join(f.dataHome,'current.json'));let captured;
 const hooks={...f.hooks,run:async(command,args,options)=>{if(args[0]?.endsWith('compile_market_data.py')){
   captured=await fs.readFile(args[0]);assert.ok(args[0].startsWith(await fs.realpath(f.dataHome)));
   await fs.appendFile(path.join(copy,'data/compile_market_data.py'),'\n# invented concurrent source change\n');
  }return f.hooks.run(command,args,options);}};
 await assert.rejects(setupData({...f.options,sourceRoot:copy,refresh:true,hooks}),/stale|source.*changed/);
 assert.deepEqual(await fs.readFile(path.join(f.dataHome,'current.json')),before);assert.ok(captured);
 const old=require('node:crypto').createHash('sha256').update(captured).digest('hex');assert.equal(old,initial.provenance.recipeFiles.find(item=>item.path==='data/compile_market_data.py').sha256);
});
test('explicit retained input objects reproduce an old bundle after refresh',async t=>{
 const f=await fixture(t),{setupData}=await api;const first=await setupData(f.options);await setupData({...f.options,refresh:true});f.calls.length=0;
 const manual=Object.fromEntries(first.provenance.sources.map(item=>[item.id,path.join(f.dataHome,item.path)]));
 const result=await setupData({...f.options,...manual,offline:true,generatedDate:first.provenance.generatedDate});
 assert.equal(result.bundleId,first.bundleId);assert.equal(result.reused,false);
 const compile=f.calls.find(call=>call.args?.[0]?.endsWith('compile_market_data.py'));assert.ok(compile.args.includes('--shiller')&&compile.args.includes('--damodaran'));
});
test('explicit fixed-name compatibility inputs are valid read-only managed sources',async t=>{
 const f=await fixture(t),{setupData}=await api;await setupData(f.options);const manual={};
 for(const [id,name]of [['shiller','ie_data.xls'],['damodaran','histretSP.xls']]){manual[id]=path.join(f.dataHome,name);await fs.copyFile(f.manual[id],manual[id]);await fs.chmod(manual[id],0o600);}
 const before=await fs.readFile(manual.shiller);const result=await setupData({...f.options,...manual,offline:true});assert.equal(result.reused,false);assert.deepEqual(await fs.readFile(manual.shiller),before);
});
test('unknown managed manual input and mismatched hash-addressed paths are refused',async t=>{
 const f=await fixture(t),{setupData}=await api;await setupData(f.options);
 const target=path.join(f.dataHome,'unrecognized.xls');await fs.copyFile(f.manual.shiller,target);await fs.chmod(target,0o600);
 await assert.rejects(setupData({...f.options,...f.manual,shiller:target}),/layout|managed.*input/);await fs.unlink(target);
 const wrong=path.join(f.dataHome,'inputs','a'.repeat(64),'source.xls');await fs.mkdir(path.dirname(wrong),{mode:0o700});await fs.copyFile(f.manual.shiller,wrong);await fs.chmod(wrong,0o600);
 await assert.rejects(setupData({...f.options,...f.manual,shiller:wrong}),/input.*hash|hash.*input/);
});
test('offline missing locked dependencies never invokes pip',async t=>{
 const f=await fixture(t),{setupData}=await api;await setupData(f.options);f.calls.length=0;
 const hooks={...f.hooks,run:async(command,args,options)=>{f.calls.push({command,args});if(args[0]==='-c')return JSON.stringify({version:'3.14.7',platform:'darwin',machine:'arm64',ready:false,isolated:true});throw new Error('unexpected subprocess');}};
 await assert.rejects(setupData({...f.options,...f.manual,offline:true,hooks}),/Offline.*locked dependencies/);
 assert.equal(f.calls.length,1);assert.equal(f.calls[0].args[0],'-c');
});
test('configured serving-root aliases and repository destinations fail before writes',async t=>{
 const f=await fixture(t),{setupData}=await api;
 const served=path.join(f.base,'served');await fs.mkdir(served,{mode:0o700});const alias=path.join(f.base,'served alias');await fs.symlink(served,alias);
 for(const dataHome of [path.join(sourceRoot,'never-create-data'),path.join(served,'never-create-data'),path.join(alias,'never-create-data')])
  await assert.rejects(setupData({...f.options,dataHome,webroots:[served]}),/overlap|Symlink/);
 assert.deepEqual(f.calls,[]);await assert.rejects(fs.stat(path.join(served,'never-create-data')),{code:'ENOENT'});
});
test('owned lock is released when a command receives a termination signal',async t=>{
 const f=await fixture(t),{setupData}=await api;await setupData(f.options);const before=await fs.readFile(path.join(f.dataHome,'current.json'));let interrupted=false;
 const hooks={...f.hooks,run:async(command,args,options)=>{if(args[0]?.endsWith('compile_market_data.py')){process.emit('SIGTERM');interrupted=options.signal.aborted;}return f.hooks.run(command,args,options);}};
 await assert.rejects(setupData({...f.options,refresh:true,hooks}),/interrupted/);assert.equal(interrupted,true);assert.deepEqual(await fs.readFile(path.join(f.dataHome,'current.json')),before);
 await assert.rejects(fs.stat(path.join(f.dataHome,'.setup.lock')),{code:'ENOENT'});
});
test('warm reuse and generation-local verification need no raw workbook access',async t=>{
 const f=await fixture(t),{setupData}=await api,{verifyBundle}=await contract;const first=await setupData(f.options);
 await fs.rename(path.join(f.dataHome,'inputs'),path.join(f.base,'unavailable originals'));f.calls.length=0;
 const warm=await setupData({...f.options,offline:true});assert.equal(warm.reused,true);assert.deepEqual(f.calls,[]);
 const verified=await verifyBundle({dataRoot:first.root,sourceRoot,repoRoot:f.options.repoRoot});assert.equal(verified.bundleId,first.bundleId);
 await assert.rejects(setupData({...f.options,refresh:true}),/retained.*input|ENOENT/);assert.deepEqual(f.calls,[]);
});
test('unexpected empty snapshot directories fail closed',async t=>{
 const f=await fixture(t),{setupData}=await api,{verifySelected}=await contract;await setupData(f.options);const selected=await verifySelected(f.options);
 const extra=path.join(selected.root,'recipe','unrecognized');await fs.mkdir(extra,{mode:0o700});await assert.rejects(setupData(f.options),/recipe.*inventory/);await fs.rmdir(extra);

});
test('partial immutable input writes never publish a corrupt object',async t=>{
 const f=await fixture(t),{setupData}=await api;await setupData(f.options);
 const before=await fs.readFile(path.join(f.dataHome,'current.json')),inventory=(await fs.readdir(path.join(f.dataHome,'inputs'))).sort();
 const original=fs.writeFile;fs.writeFile=async(target,bytes,options)=>{
  if(path.basename(String(target))==='source.xls'){await original(target,Buffer.from('invented partial input'),options);throw new Error('invented input write failure');}
  return original(target,bytes,options);
 };
 try{await assert.rejects(setupData({...f.options,...f.manual,offline:true}),/input write failure/);}finally{fs.writeFile=original;}
 assert.deepEqual((await fs.readdir(path.join(f.dataHome,'inputs'))).sort(),inventory);
 assert.deepEqual(await fs.readFile(path.join(f.dataHome,'current.json')),before);
});
test('existing standard interpreter symlinks never chmod or rewrite their external target',async t=>{
 const f=await fixture(t),{setupData}=await api;await setupData(f.options);
 const external=path.join(f.base,'invented external interpreter');await fs.writeFile(external,'invented interpreter bytes',{mode:0o755});await fs.chmod(external,0o755);
 const interpreter=path.join(f.dataHome,'.venv','bin','python');await fs.unlink(interpreter);await fs.symlink(external,interpreter);
 const bytes=await fs.readFile(external);await setupData({...f.options,...f.manual,offline:true});
 assert.deepEqual(await fs.readFile(external),bytes);assert.equal((await fs.stat(external)).mode&0o777,0o755);assert.equal((await fs.lstat(interpreter)).isSymbolicLink(),true);
});
for(const target of ['retained','manual','candidate-during-compile','candidate-during-checker','acquired-cache'])test('input integrity through selection: '+target,async t=>{
 const {setupData}=await api,{sha256}=await contract;
  const f=await fixture(t);const initial=await setupData(f.options);const before=await fs.readFile(path.join(f.dataHome,'current.json'));let observed;
  const hooks={...f.hooks,run:async(command,args,options)=>{
   if(args[0]?.endsWith('compile_market_data.py')&&!args.includes('--acquire-only')){
    const file=args[args.indexOf('--shiller')+1];if(args.includes('--shiller'))observed={file,sha256:sha256(await fs.readFile(file)),cache:options.env.MARKET_ATLAS_DATA_HOME};
    if(target==='manual')await fs.appendFile(f.manual.shiller,'invented manual mutation');
    if(target==='candidate-during-compile')await fs.appendFile(file,'invented candidate mutation');
   }return f.hooks.run(command,args,options);
  },historical:async()=>{
   if(target==='retained')await fs.appendFile(path.join(f.dataHome,initial.provenance.sources.find(source=>source.id==='shiller').path),'invented retained mutation');
   if(target==='candidate-during-checker')await fs.appendFile(observed.file,'invented candidate mutation');
   if(target==='acquired-cache')await fs.appendFile(path.join(observed?.cache || f.calls.find(call=>call.args?.[0]?.endsWith('compile_market_data.py')).options.env.MARKET_ATLAS_DATA_HOME,'ie_data.xls'),'invented acquired mutation');
  }};
  const options={...f.options,hooks,...(target==='manual'?f.manual:{refresh:target==='acquired-cache',generatedDate:'2026-10-01'})};
  await assert.rejects(setupData(options),/input.*changed|input.*hash|input.*integrity/i,target);
  assert.deepEqual(await fs.readFile(path.join(f.dataHome,'current.json')),before);
  assert.equal((await fs.readdir(f.dataHome)).filter(name=>name.startsWith('.candidate')||name.startsWith('.current')||name==='.setup.lock').length,0);
});
test('abort immediately after selector temporary write preserves selection and releases owned state',async t=>{
 const f=await fixture(t),{setupData}=await api;await setupData(f.options);const before=await fs.readFile(path.join(f.dataHome,'current.json'));
 const controller=new AbortController(),original=fs.writeFile;let dispatched=false;
 fs.writeFile=async(target,bytes,options)=>{await original(target,bytes,options);if(path.basename(String(target)).startsWith('.current-'))controller.abort();};
 try{await assert.rejects(setupData({...f.options,...f.manual,offline:true,signal:controller.signal,hooks:{...f.hooks,promote:async()=>{dispatched=true;}}}),/interrupted/);}finally{fs.writeFile=original;}
 assert.equal(dispatched,false);assert.deepEqual(await fs.readFile(path.join(f.dataHome,'current.json')),before);
 assert.equal((await fs.readdir(f.dataHome)).filter(name=>name.startsWith('.candidate')||name.startsWith('.current')||name==='.setup.lock').length,0);
});
test('cold acquisition precedes explicit copied-source compilation and provenance matches observed bytes',async t=>{
 const f=await fixture(t),{setupData}=await api,{sha256}=await contract;const result=await setupData(f.options);
 const phases=f.calls.filter(call=>call.args?.[0]?.endsWith('compile_market_data.py'));
 assert.equal(phases.length,2);assert.ok(phases[0].args.includes('--acquire-only'));assert.ok(!phases[1].args.includes('--acquire-only'));
 assert.equal(f.compiledInputs.length,1);
 for(const source of result.provenance.sources){const flag='--'+source.id,filename=phases[1].args[phases[1].args.indexOf(flag)+1];assert.ok(filename.includes('/compile-inputs/'));assert.equal(sha256(f.compiledInputs[0].inputs.get(source.id)),source.sha256);}
});
test('source recipe change immediately after selector temporary write preserves selection and retained objects',async t=>{
 const f=await fixture(t),{setupData}=await api,{RECIPE_FILES}=await contract;
 const copy=path.join(f.base,'late mutable recipe');await fs.mkdir(copy,{mode:0o700});
 for(const name of RECIPE_FILES){await fs.mkdir(path.dirname(path.join(copy,name)),{recursive:true});await fs.copyFile(path.join(sourceRoot,name),path.join(copy,name));}
 const initial=await setupData({...f.options,sourceRoot:copy});
 const manual=Object.fromEntries(initial.provenance.sources.map(source=>[source.id,path.join(f.dataHome,source.path)]));
 const retained=[path.join(f.dataHome,'current.json'),...initial.provenance.sources.map(source=>path.join(f.dataHome,source.path)),
  ...['market-data.js','market-data.csv','provenance.json',...RECIPE_FILES.map(name=>'recipe/'+name)].map(name=>path.join(initial.root,name))];
 const before=new Map(await Promise.all(retained.map(async target=>[target,await fs.readFile(target)])));
 const original=fs.writeFile;let changed=false,dispatched=false;
 fs.writeFile=async(target,bytes,options)=>{await original(target,bytes,options);if(path.basename(String(target)).startsWith('.current-')){
  changed=true;await fs.appendFile(path.join(copy,'data/compile_market_data.py'),'\n# invented final-boundary recipe change\n');
 }};
 try{await assert.rejects(setupData({...f.options,sourceRoot:copy,...manual,offline:true,hooks:{...f.hooks,promote:async(from,to)=>{dispatched=true;await fs.rename(from,to);}}}),/stale|source.*changed|recipe.*changed/i);}
 finally{fs.writeFile=original;}
 assert.equal(changed,true);assert.equal(dispatched,false);
 for(const [target,bytes]of before)assert.deepEqual(await fs.readFile(target),bytes);
 assert.equal((await fs.readdir(f.dataHome)).filter(name=>name.startsWith('.candidate')||name.startsWith('.current')||name==='.setup.lock').length,0);
});
for(const reason of ['timeout','abort'])test('production runner kills TERM-resistant closed-stdio descendants before '+reason+' rejection',async t=>{
 const {runCommand}=await api,base=await fs.mkdtemp(path.join(os.tmpdir(),'market-atlas-invented-process-')),ready=path.join(base,'descendant ready');let pid;
 const alive=()=>{try{process.kill(pid,0);return true;}catch(error){if(error.code==='ESRCH')return false;throw error;}};
 t.after(async()=>{if(pid&&alive())process.kill(pid,'SIGKILL');await fs.rm(base,{recursive:true,force:true});});
 const descendant="process.on('SIGTERM',()=>{});require('node:fs').writeFileSync("+JSON.stringify(ready)+",String(process.pid));setInterval(()=>{},1000);";
 const leader="require('node:child_process').spawn(process.execPath,['-e',"+JSON.stringify(descendant)+"],{stdio:'ignore'});setInterval(()=>{},1000);";
 const controller=new AbortController(),running=runCommand(process.execPath,['-e',leader],{timeout:2000,signal:controller.signal});
 // Attach the rejection assertion before waiting for the descendant's readiness.
 const rejected=assert.rejects(running,reason==='abort'?/interrupted/:/failed/);
 const deadline=Date.now()+5000;while(!pid&&Date.now()<deadline){try{pid=Number(await fs.readFile(ready,'utf8'));}catch(error){if(error.code!=='ENOENT')throw error;}if(!pid)await new Promise(resolve=>setTimeout(resolve,10));}
 assert.ok(pid,'invented descendant must start');if(reason==='abort')controller.abort();await rejected;
 const stopped=Date.now()+1000;while(alive()&&Date.now()<stopped)await new Promise(resolve=>setTimeout(resolve,10));
 assert.equal(alive(),false,'TERM-resistant descendant survived operation rejection');
});
for(const code of [7,0])test('production runner cleans closed-stdio descendants after leader exit '+code,async t=>{
 const {runCommand}=await api,base=await fs.mkdtemp(path.join(os.tmpdir(),'market-atlas-invented-exit-')),ready=path.join(base,'descendant ready');let pid;
 const alive=()=>{try{process.kill(pid,0);return true;}catch(error){if(error.code==='ESRCH')return false;throw error;}};
 t.after(async()=>{if(pid&&alive())process.kill(pid,'SIGKILL');await fs.rm(base,{recursive:true,force:true});});
 const descendant="process.on('SIGTERM',()=>{});require('node:fs').writeFileSync("+JSON.stringify(ready)+",String(process.pid));setInterval(()=>{},1000);";
 const leader="const fs=require('node:fs');require('node:child_process').spawn(process.execPath,['-e',"+JSON.stringify(descendant)+"],{stdio:'ignore'});setInterval(()=>{if(fs.existsSync("+JSON.stringify(ready)+")){process.stdout.write('invented normal output');process.exit("+code+");}},10);";
 const running=runCommand(process.execPath,['-e',leader],{timeout:5000});
 const settled=code===7?assert.rejects(running,/failed/):running.then(output=>assert.equal(output,'invented normal output'));
 const deadline=Date.now()+5000;while(!pid&&Date.now()<deadline){try{pid=Number(await fs.readFile(ready,'utf8'));}catch(error){if(error.code!=='ENOENT')throw error;}if(!pid)await new Promise(resolve=>setTimeout(resolve,10));}
 assert.ok(pid,'invented descendant must start');await settled;
 const stopped=Date.now()+1000;while(alive()&&Date.now()<stopped)await new Promise(resolve=>setTimeout(resolve,10));
 assert.equal(alive(),false,'Owned descendant survived leader settlement');
});
