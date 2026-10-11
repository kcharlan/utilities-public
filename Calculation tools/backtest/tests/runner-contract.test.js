'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs/promises'),path=require('node:path'),http=require('node:http');
const {staticFixture}=require('./helpers/static-fixture.cjs');



test('runner captures inputs before assembly and writes private external source/package/expected layouts with spaces',async t=>{
 const runner=require('./helpers/runner.cjs'),f=await staticFixture(t);
 const reader=require('./helpers/dataset.cjs').createDatasetReader({sourceRoot:f.sourceRoot,dataRoot:f.dataRoot});
 const bundle=await reader.getDataset();const captured=await runner.captureInputs(f.sourceRoot,bundle);
 const outputs=await runner.prepareLayouts(captured,{tempParent:f.base});t.after(()=>outputs.cleanup());
 assert.ok(outputs.root.includes(' '));assert.equal((await fs.stat(outputs.root)).mode&0o777,0o700);
 assert.equal((await fs.stat(path.join(outputs.sourceRoot,'market-data.js'))).isSymbolicLink(),false);
 assert.deepEqual(await fs.readFile(path.join(outputs.sourceRoot,'market-data.js')),bundle.files.get('market-data.js'));
 assert.deepEqual(await fs.readFile(path.join(outputs.sourceRoot,'app.js')),captured.source.get('app.js'));
 const b=require('./helpers/browser-target.cjs');
 await b.verifyTarget(b.resolveTarget(outputs.sourceRoot,undefined,{expected:outputs.sourceExpected}));
 await b.verifyTarget(b.resolveTarget(outputs.artifactRoot,undefined,{expected:outputs.artifactExpected,purpose:'artifact'}));
 assert.equal((await fs.stat(path.join(outputs.artifactRoot,'index.html'))).mode&0o777,0o644);
 const loaded=await runner.loadExpected(outputs.artifactExpectedRoot);
 assert.deepEqual(loaded.files,outputs.artifactExpected.files);
 await outputs.cleanup();await assert.rejects(fs.stat(outputs.root),{code:'ENOENT'});
});

test('isolated HTTP server serves written disk bytes, exact inventory, two entries and traversal 404',async t=>{
 const runner=require('./helpers/runner.cjs'),f=await staticFixture(t),root=path.join(f.base,'invented disk with spaces');
 await fs.mkdir(root,{mode:0o700});await fs.writeFile(path.join(root,'index.html'),'invented entry');await fs.writeFile(path.join(root,'engine.js'),'invented original');
 const server=await runner.serveDirectory(root,['index.html','engine.js']);t.after(()=>server.close());
 assert.ok(server.port>0);assert.match(server.directoryUrl,/^http:\/\/127\.0\.0\.1:\d+\/calculators\/backtest\/$/);
 assert.equal(await(await fetch(server.directoryUrl)).text(),'invented entry');assert.equal(await(await fetch(server.indexUrl)).text(),'invented entry');
 await fs.writeFile(path.join(root,'engine.js'),'invented modified on disk');assert.equal(await(await fetch(server.directoryUrl+'engine.js')).text(),'invented modified on disk');
 for(const suffix of ['../index.html','%2e%2e/index.html','%252e%252e/index.html','assets/%2f../index.html','engine.js?x=1','unknown.js']){
  const code=await new Promise((resolve,reject)=>{const r=http.get({host:'127.0.0.1',port:server.port,path:'/calculators/backtest/'+suffix},res=>{res.resume();resolve(res.statusCode);});r.on('error',reject);});assert.equal(code,404,suffix);
 }
 await fs.unlink(path.join(root,'engine.js'));await fs.symlink(path.join(root,'index.html'),path.join(root,'engine.js'));assert.equal((await fetch(server.directoryUrl+'engine.js')).status,404);
 await server.close();await assert.rejects(fetch(server.indexUrl));
});

test('child nonzero exits fail and abort awaits child termination',async t=>{
 const {runChild}=require('./helpers/runner.cjs'),f=await staticFixture(t);
 await assert.rejects(runChild(process.execPath,['-e','process.exitCode=7'],{cwd:f.base,quiet:true}),/7/);
 const controller=new AbortController(),started=path.join(f.base,'invented child started');
 const child=runChild(process.execPath,['-e',`require('node:fs').writeFileSync(${JSON.stringify(started)},String(process.pid));process.on('SIGTERM',()=>{setTimeout(()=>process.exitCode=0,50);clearInterval(timer)});const timer=setInterval(()=>{},1000)`],{cwd:f.base,quiet:true,signal:controller.signal});
 while(!await fs.stat(started).catch(()=>false))await new Promise(r=>setTimeout(r,10));
 const pid=Number(await fs.readFile(started,'utf8'));controller.abort();await assert.rejects(child,/interrupt|abort/i);assert.throws(()=>process.kill(pid,0),{code:'ESRCH'});
});

test('synthetic suite is a whole-file explicit allowlist and requires both invented compiler modules',()=>{
 const {SYNTHETIC_TESTS,PYTHON_SYNTHETIC}=require('./helpers/runner.cjs');
 for(const mixed of ['dataset','engine','historical','lifestyle','export','sweep-render','browser-smoke'])assert.equal(SYNTHETIC_TESTS.includes(mixed+'.test.js'),false);
 for(const pure of ['admission','app-render','browser-target','charts','config-apply','data-contract','format','privacy','setup-data','stats','strategies','strategy-baseline','year-end','structure','theme','window-render','static-build','static-deploy','dataset-helper','runner-contract','browser-contract'])assert.ok(SYNTHETIC_TESTS.includes(pure+'.test.js'));
 assert.deepEqual(PYTHON_SYNTHETIC,['test_compile_market_data','test_external_compiler']);
});

test('Python validation refuses absent or system executables before execution and never bootstraps',async t=>{
 const {validatePython}=require('./helpers/runner.cjs'),f=await staticFixture(t);
 await assert.rejects(validatePython({env:{MARKET_ATLAS_TEST_PYTHON:process.execPath},sourceRoot:f.sourceRoot}),/venv|environment/i);
 await assert.rejects(validatePython({env:{MARKET_ATLAS_DATA_HOME:path.join(f.base,'absent')},sourceRoot:f.sourceRoot}),/MARKET_ATLAS_TEST_PYTHON|venv/);
 assert.equal(await fs.stat(path.join(f.base,'absent')).catch(()=>null),null);
});

// Exact binary/platform and metadata admission tests are withdrawn. Actual venv
// isolation, import and dependency lock probes remain required.

test('required unittest completion refuses ready-only, zero tests, missing cases, duplicate cases, and skips',async t=>{
 const {runChild}=require('./helpers/runner.cjs'),f=await staticFixture(t);
 const unittestCases=['invented_one.InventedTests.test_one','invented_two.InventedTests.test_two'];
 const one='test_one (invented_one.InventedTests.test_one) ... ok\n',two='test_two (invented_two.InventedTests.test_two) ... ok\n';
 for(const output of ['ready\n','Ran 0 tests in 0.0s\n\nOK\n',one+'Ran 2 tests in 0.0s\n\nOK\n',one+one+'Ran 2 tests in 0.0s\n\nOK\n',one+two.replace('ok','skipped \'invented\'')+'Ran 2 tests in 0.0s\n\nOK (skipped=1)\n']){
  await assert.rejects(runChild(process.execPath,['-e',`process.stderr.write(${JSON.stringify(output)})`],{quiet:true,cwd:f.base,unittestCases}),/unittest|compiler|skip/i);
 }
 const complete=one+two+'\n----------------------------------------------------------------------\nRan 2 tests in 0.001s\n\nOK\n';
 assert.equal(await runChild(process.execPath,['-e',`process.stderr.write(${JSON.stringify(complete)})`],{quiet:true,cwd:f.base,unittestCases}),complete);
});

test('public full runner is fatal/actionable with missing data and creates no test output',async t=>{
 const {runChild}=require('./helpers/runner.cjs'),f=await staticFixture(t),project=path.resolve(__dirname,'..');
 const {spawn}=require('node:child_process');
 const before=await fs.readdir(f.base);let output='';
 const child=spawn(process.execPath,[path.join(project,'tests/run_tests.cjs')],{cwd:project,env:{...process.env,MARKET_ATLAS_TEST_DATA_ROOT:'',MARKET_ATLAS_DATA_HOME:path.join(f.base,'missing data'),MARKET_ATLAS_TEST_TMPDIR:f.base}});
 child.stdout.on('data',c=>output+=c);child.stderr.on('data',c=>output+=c);
 const code=await new Promise(r=>child.once('close',r));assert.equal(code,1);assert.match(output,/npm run setup:data/);assert.deepEqual(await fs.readdir(f.base),before);
});

test('browser runner declares two sequential flat targets and installed override selects only explicit index',async t=>{
 const {browserTargets}=require('./run_artifact_browser.cjs'),f=await staticFixture(t);
 const layouts={sourceRoot:path.join(f.base,'source'),artifactRoot:path.join(f.base,'artifact'),sourceExpectedRoot:path.join(f.base,'source expected'),artifactExpectedRoot:path.join(f.base,'artifact expected')};
 const server={directoryUrl:'http://127.0.0.1:1/calculators/backtest/',indexUrl:'http://127.0.0.1:1/calculators/backtest/index.html'};
 const matrix=browserTargets(layouts,server);assert.deepEqual(matrix.map(m=>m.label),['flat file','isolated HTTP explicit index']);
 assert.equal(matrix[0].expectedRoot,layouts.artifactExpectedRoot);assert.ok(matrix.slice(1).every(m=>m.expectedRoot===layouts.artifactExpectedRoot));
 const override=browserTargets(layouts,null,server.indexUrl);assert.equal(override.length,1);assert.equal(override[0].purpose,'installed');assert.equal(override[0].documentRoutes,'selected-entry');
 assert.throws(()=>browserTargets(layouts,null,server.directoryUrl),/explicit|index/);
});

test('complete driver environment suppresses URL overrides and preserves its immutable data pin and caller environment',async t=>{
 const {fullTestEnvironment}=require('./run_tests.cjs'),{browserTargets}=require('./run_artifact_browser.cjs'),f=await staticFixture(t);
 assert.equal(typeof fullTestEnvironment,'function','Complete driver must enforce its browser matrix policy');
 const layouts={sourceRoot:path.join(f.base,'source'),artifactRoot:path.join(f.base,'artifact'),sourceExpectedRoot:path.join(f.base,'source expected'),artifactExpectedRoot:path.join(f.base,'artifact expected')};
 const server={directoryUrl:'http://127.0.0.1:1/calculators/backtest/',indexUrl:'http://127.0.0.1:1/calculators/backtest/index.html'};
 const bundle={root:f.dataRoot};
 for(const url of [require('node:url').pathToFileURL(path.join(f.base,'invented override/index.html')).href,server.indexUrl]){
  const caller=Object.freeze({MARKET_ATLAS_TEST_URL:url,MARKET_ATLAS_TEST_DATA_ROOT:'invented stale pin',MARKET_ATLAS_DATA_HOME:f.dataHome,MARKET_ATLAS_TEST_TMPDIR:f.base,PYTHONDONTWRITEBYTECODE:'1'});
  const pinned=fullTestEnvironment(caller,bundle);
  assert.notEqual(pinned,caller);assert.equal(pinned.MARKET_ATLAS_TEST_URL,'');assert.equal(pinned.MARKET_ATLAS_TEST_DATA_ROOT,bundle.root);
  assert.equal(pinned.MARKET_ATLAS_DATA_HOME,caller.MARKET_ATLAS_DATA_HOME);assert.equal(pinned.MARKET_ATLAS_TEST_TMPDIR,caller.MARKET_ATLAS_TEST_TMPDIR);assert.equal(pinned.PYTHONDONTWRITEBYTECODE,'1');
  assert.equal(caller.MARKET_ATLAS_TEST_URL,url);assert.equal(caller.MARKET_ATLAS_TEST_DATA_ROOT,'invented stale pin');
  assert.deepEqual(browserTargets(layouts,server,pinned.MARKET_ATLAS_TEST_URL).map(target=>target.label),['flat file','isolated HTTP explicit index']);
  const browserOnly=browserTargets(layouts,null,caller.MARKET_ATLAS_TEST_URL);assert.equal(browserOnly.length,1);assert.equal(browserOnly[0].url,url);
 }
});

test('venv path layout alone cannot admit an arbitrary linked executable',async t=>{
 const {validatePython}=require('./helpers/runner.cjs'),f=await staticFixture(t),root=path.join(f.base,'invented venv');
 await fs.mkdir(path.join(root,'bin'),{recursive:true,mode:0o700});
 await fs.writeFile(path.join(root,'pyvenv.cfg'),'home = /invented/not-an-interpreter\nversion = 3.14.7\ninclude-system-site-packages = false\nexecutable = /invented/not-an-interpreter/python\n',{mode:0o600});
 await fs.symlink(process.execPath,path.join(root,'bin/python'));
 await assert.rejects(validatePython({env:{MARKET_ATLAS_TEST_PYTHON:path.join(root,'bin/python')},sourceRoot:f.sourceRoot}),/ready external Python venv/);
});

test('runner refuses successful child output with skips and reaps descendants after leader exit',async t=>{
 const {runChild}=require('./helpers/runner.cjs'),f=await staticFixture(t);
 await assert.rejects(runChild(process.execPath,['-e','console.log("# skipped 1")'],{quiet:true,cwd:f.base,requireZeroSkips:true}),/skip/);
 const marker=path.join(f.base,'invented descendant pid');
 await runChild(process.execPath,['-e',`const fs=require('node:fs');const child=require('node:child_process').spawn(process.execPath,['-e','process.on("SIGTERM",()=>{});setInterval(()=>{},1000)'],{stdio:'ignore'});fs.writeFileSync(${JSON.stringify(marker)},String(child.pid));child.unref();`],{quiet:true,cwd:f.base});
 const pid=Number(await fs.readFile(marker,'utf8'));let alive=true;
 for(let attempt=0;attempt<100&&alive;attempt++){try{process.kill(pid,0);await new Promise(r=>setTimeout(r,10));}catch{alive=false;}}
 if(alive){process.kill(pid,'SIGKILL');assert.fail('Runner left a child descendant alive after leader exit');}
});


test('browser runner signal awaits managed Chromium termination and removes profiles/server/owned temporary trees', {timeout:20000},async t=>{
 const {spawn}=require('node:child_process'),f=await staticFixture(t),project=path.resolve(__dirname,'..');
 const child=spawn(process.execPath,[path.join(project,'tests/run_artifact_browser.cjs')],{cwd:project,env:{...process.env,
  MARKET_ATLAS_TEST_URL:'',MARKET_ATLAS_TEST_DATA_ROOT:f.dataRoot,MARKET_ATLAS_DATA_HOME:f.dataHome,MARKET_ATLAS_TEST_TMPDIR:f.base},stdio:['ignore','pipe','pipe']});
 let output='';child.stdout.on('data',c=>output+=c);child.stderr.on('data',c=>output+=c);
 const closed=new Promise(resolve=>child.once('close',(code,signal)=>resolve({code,signal})));
 t.after(async()=>{if(child.exitCode===null){child.kill('SIGTERM');await closed;}});
 let profile,port;const deadline=Date.now()+10000;
 while(Date.now()<deadline&&!port){
  const entries=(await fs.readdir(f.base)).filter(n=>n.startsWith('market-atlas test '));
  if(entries.length){const root=path.join(f.base,entries[0]);const profiles=(await fs.readdir(root)).filter(n=>n.startsWith('market-atlas chrome '));
   if(profiles.length){profile=path.join(root,profiles[0]);const bytes=await fs.readFile(path.join(profile,'DevToolsActivePort'),'utf8').catch(()=>null);if(bytes)port=Number(bytes.split('\n')[0]);}}
  if(child.exitCode!==null)assert.fail('Browser runner ended before managed Chromium readiness');
  if(!port)await new Promise(r=>setTimeout(r,20));
 }
 assert.ok(port,'Managed Chromium must become ready for this signal test');
 assert.equal((await fs.stat(profile)).mode&0o777,0o700);
 child.kill('SIGTERM');const result=await closed;
 assert.equal(result.signal,null);assert.notEqual(result.code,0);
 assert.equal((await fs.readdir(f.base)).some(n=>n.startsWith('market-atlas test ')),false);
 await assert.rejects(fetch(`http://127.0.0.1:${port}/json/version`));
 assert.equal(output.includes('Browser matrix: flat file'),true);
});

test('complete synthetic driver refuses a missing venv before any Node-only success',async t=>{
 const f=await staticFixture(t),project=path.resolve(__dirname,'..'),{spawn}=require('node:child_process');let output='';
 const child=spawn(process.execPath,[path.join(project,'tests/run_tests.cjs'),'--synthetic'],{cwd:project,env:{...process.env,MARKET_ATLAS_TEST_PYTHON:path.join(f.base,'missing venv/bin/python')}});
 child.stdout.on('data',c=>output+=c);child.stderr.on('data',c=>output+=c);
 const code=await new Promise(r=>child.once('close',r));assert.equal(code,1);assert.match(output,/MARKET_ATLAS_TEST_PYTHON/);assert.doesNotMatch(output,/(?:#|ℹ) (?:tests|pass) \d/);
});
