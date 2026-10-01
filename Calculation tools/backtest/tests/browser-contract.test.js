'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs/promises'),path=require('node:path');
const {staticFixture}=require('./helpers/static-fixture.cjs');
const browser=require('./helpers/browser-target.cjs');
const {pathToFileURL}=require('node:url');

test('source and artifact browser contracts use independent bytes and exact resolved ordered scripts', async t=>{
 const f=await staticFixture(t),build=await import('../tools/build_static.mjs');
 const artifact={files:await build.readRuntime(f)},prefix='';
 assert.equal(typeof browser.makeExpected,'function');
 const expected=browser.makeExpected(artifact.files,{prefix});
 const target=browser.resolveTarget(path.join(f.base,'target'),undefined,{expected,purpose:'artifact',documentRoutes:'selected-entry'});
 assert.deepEqual(target.scriptUrls,build.SCRIPT_ASSETS.map(name=>new URL(prefix+name,target.baseUrl).href));
 assert.equal(target.noticeUrl,new URL(prefix+'DATA_SOURCES.md',target.baseUrl).href);
 assert.equal(expected.files.get('index.html').toString(),(await fs.readFile(path.join(f.sourceRoot,'index.html'))).toString());
 const packageRoot=path.join(f.base,'target');await build.buildStatic({...f,outputDir:packageRoot});
 await browser.verifyTarget(target);
 await fs.writeFile(path.join(packageRoot,prefix,'engine.js'),'// invented wrong asset');
 await assert.rejects(browser.verifyTarget(target),/bytes/);
 assert.equal(expected.files.get(prefix+'engine.js').toString().includes('invented wrong asset'),false);
});

test('installed explicit index contract never probes or permits the directory route',async t=>{
 const http=require('node:http');const f=await staticFixture(t);
 const files=new Map([['index.html',Buffer.from('<link rel="icon" href="data:,">')],...browser.STATIC_ASSETS.map(n=>[n,Buffer.from('invented '+n)])]);
 const seen=[];let corrupt=null,redirect=false;
 const server=http.createServer((req,res)=>{seen.push(req.url);if(redirect){res.writeHead(302,{Location:'/calculators/backtest/'});res.end();return;}const n=req.url.slice('/calculators/backtest/'.length);if(!files.has(n)){res.writeHead(404);res.end();return;}res.end(n===corrupt?Buffer.from('invented fallback'):files.get(n));});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>new Promise(r=>server.close(r)));
 const url=`http://127.0.0.1:${server.address().port}/calculators/backtest/index.html`;
 const target=browser.resolveTarget(f.base,url,{expected:browser.makeExpected(files),purpose:'installed',documentRoutes:'selected-entry'});
 await browser.verifyTarget(target);
 assert.equal(seen.includes('/calculators/backtest/'),false);
 assert.throws(()=>browser.resolveTarget(f.base,url.replace('index.html',''),{expected:browser.makeExpected(files),purpose:'installed'}),/explicit|index/);
 assert.throws(()=>browser.assertAllowedRequests(target,[target.baseUrl]),/unexpected/);
 for(const name of ['index.html','engine.js','DATA_SOURCES.md','market-data.csv']){corrupt=name;await assert.rejects(browser.verifyTarget(target),/bytes/);}
 corrupt=null;redirect=true;await assert.rejects(browser.verifyTarget(target));
});

test('browser resource policy admits blobs only for observed actual downloads and snapshots declared favicon',async t=>{
 const f=await staticFixture(t);const files=new Map([['index.html',Buffer.from('<link rel="icon" href="data:,">')],...browser.STATIC_ASSETS.map(n=>[n,Buffer.from('invented '+n)])]);
 const target=browser.resolveTarget(f.base,pathToFileURL(path.join(f.base,'index.html')).href,{expected:browser.makeExpected(files)});
 browser.assertAllowedRequests(target,[target.url,'data:,','blob:null/invented-download'],new Set(['blob:null/invented-download']));
 assert.throws(()=>browser.assertAllowedRequests(target,['blob:null/invented-unobserved']),/unexpected/);
 assert.throws(()=>browser.assertAllowedRequests(target,['data:text/html,invented']),/unexpected/);
 assert.throws(()=>browser.assertAllowedRequests(target,['http://127.0.0.1:1/engine.js']),/unexpected/);
});

test('browser target refuses encoded routes and normalization disguising another route',async t=>{
 const f=await staticFixture(t),files=new Map([['index.html',Buffer.from('invented document')],...browser.STATIC_ASSETS.map(n=>[n,Buffer.from('invented '+n)])]);
 for(const suffix of ['../backtest/index.html','%2e%2e/backtest/index.html','%69ndex.html','index.html?','index.html#']){
  assert.throws(()=>browser.resolveTarget(f.base,'http://127.0.0.1:1/calculators/backtest/'+suffix,{expected:browser.makeExpected(files),purpose:'installed'}),/target|route|query|fragment/);
 }
});

test('standalone file override preserves encoded spaces with independent package expectations',async t=>{
 const f=await staticFixture(t),api=await import('../tools/build_static.mjs'),artifact={files:await api.readRuntime(f)};
 const root=path.join(f.base,'invented package with spaces');await api.buildStatic({...f,outputDir:root});
 const expected=browser.makeExpected(artifact.files,{prefix:''});
 const url=pathToFileURL(path.join(root,'index.html')).href;assert.ok(url.includes('%20'));
 await browser.verifyTarget(browser.resolveTarget(root,url,{expected,purpose:'artifact',documentRoutes:'selected-entry'}));
});
