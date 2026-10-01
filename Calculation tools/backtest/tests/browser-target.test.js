'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const { pathToFileURL } = require('node:url');
const helpers = require('./helpers/browser-target.cjs');

const ASSETS = ['market-data.js', 'format.js', 'stats.js', 'views.js', 'lifestyle.js', 'charts.js', 'csv.js', 'engine.js', 'app.js', 'DATA_SOURCES.md', 'market-data.csv'];

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'market-atlas-synthetic-target-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.writeFileSync(path.join(root, 'index.html'), '<!doctype html><title>Synthetic target fixture</title>');
  for (const name of [...ASSETS, 'market-data.csv']) fs.writeFileSync(path.join(root, name), 'synthetic fixture: ' + name);
  return root;
}

test('browser target defaults to the source file and accepts only explicit local routes', t => {
  const root = fixture(t);
  assert.equal(helpers.resolveTarget(root).url, pathToFileURL(path.join(root, 'index.html')).href);
  for (const override of ['http://127.0.0.1:1234/calculators/backtest/', 'http://localhost:1234/calculators/backtest/index.html', 'http://[::1]:1234/calculators/backtest/']) {
    assert.equal(helpers.resolveTarget(root, override).url, override);
  }
  for (const override of ['https://example.invalid/calculators/backtest/', 'http://127.0.0.1:1234/', 'http://127.0.0.1:1234/calculators/backtest', 'http://127.0.0.1:1234/calculators/backtest/?x=1', 'http://user:password@localhost:1234/calculators/backtest/', 'file:///synthetic/other.html']) {
    assert.throws(() => helpers.resolveTarget(root, override), /target|route|loopback/i);
  }
});

test('raw HTTP backslashes are refused before normalization in both target production boundaries',t=>{
 const root=fixture(t),{browserTargets}=require('./run_artifact_browser.cjs');
 const layouts={sourceRoot:root,artifactRoot:root,sourceExpectedRoot:root,artifactExpectedRoot:root};
 for(const override of ['http://127.0.0.1:1/calculators/other\\..\\backtest/index.html','http://127.0.0.1:1/calculators\\backtest\\index.html','http:\\\\127.0.0.1:1\\calculators\\backtest\\index.html']){
  assert.throws(()=>helpers.resolveTarget(root,override,{purpose:'installed'}),/target|route|backslash/i);
  assert.throws(()=>browserTargets(layouts,null,override),/target|route|backslash/i);
 }
 const spaced=pathToFileURL(path.join(root,'invented directory with spaces','index.html')).href;
 assert.ok(spaced.includes('%20'));assert.equal(helpers.resolveTarget(root,spaced).url,spaced);
 assert.equal(browserTargets(layouts,null,spaced)[0].url,spaced);
});

test('all trimmed ASCII C0 and space edges are refused at both raw target boundaries',t=>{
 const root=fixture(t),{browserTargets}=require('./run_artifact_browser.cjs');
 const layouts={sourceRoot:root,artifactRoot:root,sourceExpectedRoot:root,artifactExpectedRoot:root};
 const index='http://127.0.0.1:1/calculators/backtest/index.html',folder='http://127.0.0.1:1/calculators/backtest/';
 const traversal='http://127.0.0.1:1/calculators/other\\..\\backtest/index.html';
 const file=pathToFileURL(path.join(root,'invented directory with spaces','index.html')).href;
 for(let code=0;code<=0x20;code++){
  const edge=String.fromCharCode(code);
  for(const override of [edge+index,index+edge,edge+traversal,edge+folder,edge+file,file+edge]){
   assert.throws(()=>helpers.resolveTarget(root,override,{purpose:'installed'}),/target|route|control|whitespace/i,`resolveTarget must reject edge ${code}`);
   assert.throws(()=>browserTargets(layouts,null,override),/target|route|control|whitespace/i,`browserTargets must reject edge ${code}`);
  }
 }
});

test('embedded tab LF and CR scheme disguises fail while ordinary file spaces and direct HTTP index remain supported',t=>{
 const root=fixture(t),{browserTargets}=require('./run_artifact_browser.cjs');
 const layouts={sourceRoot:root,artifactRoot:root,sourceExpectedRoot:root,artifactExpectedRoot:root};
 for(const control of ['\t','\n','\r'])for(const override of [`h${control}ttp://127.0.0.1:1/calculators/backtest/index.html`,`http${control}://127.0.0.1:1/calculators/backtest/`,`http:${control}//127.0.0.1:1/calculators/backtest/index.html`,`http://127.0.0.1:1/calculators/${control}backtest/index.html`,`f${control}ile:///invented/index.html`]){
  assert.throws(()=>helpers.resolveTarget(root,override,{purpose:'installed'}),/target|route|control|whitespace/i);
  assert.throws(()=>browserTargets(layouts,null,override),/target|route|control|whitespace/i);
 }
 const index='http://127.0.0.1:1/calculators/backtest/index.html';
 assert.equal(helpers.resolveTarget(root,index,{purpose:'installed'}).url,index);
 const installed=browserTargets(layouts,null,index)[0];assert.equal(installed.url,index);assert.equal(installed.purpose,'installed');assert.equal(installed.documentRoutes,'selected-entry');
 const file=pathToFileURL(path.join(root,'invented directory with spaces','index.html')).href;
 for(const override of [file,file.replaceAll('%20',' ')]){
  assert.equal(helpers.resolveTarget(root,override).url,file);
  const target=browserTargets(layouts,null,override)[0];assert.equal(target.url,override);assert.equal(target.purpose,'artifact');
 }
});

test('missing managed Chromium and data are fatal prerequisites', t => {
  const root = fixture(t);
  assert.throws(() => helpers.requirePrerequisites({ executablePath: () => path.join(root, 'missing-browser') }, root), /playwright install chromium/);
  const executable = path.join(root, 'synthetic-browser');
  fs.writeFileSync(executable, 'synthetic executable fixture');
  assert.equal(helpers.requirePrerequisites({ executablePath: () => executable }, root), executable);
  fs.unlinkSync(path.join(root, 'market-data.js'));
  assert.throws(() => helpers.requirePrerequisites({ executablePath: () => executable }, root), /market-data.js/);
});

test('target guards compare document and asset bytes including both HTTP routes', async t => {
  const root = fixture(t);
  const seen = [];
  let corrupted = null;
  let missing = null;
  const server = http.createServer((req, res) => {
    seen.push(req.url);
    const name = req.url.endsWith('/') ? 'index.html' : req.url.split('/').pop();
    if (name === missing) { res.writeHead(404); res.end('synthetic missing'); return; }
    res.end(name === corrupted ? '<html>synthetic fallback</html>' : fs.readFileSync(path.join(root, name)));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const target = helpers.resolveTarget(root, `http://127.0.0.1:${server.address().port}/calculators/backtest/`);
  await helpers.verifyTarget(target);
  assert.ok(seen.includes('/calculators/backtest/') && seen.includes('/calculators/backtest/index.html'));
  for (const asset of ASSETS) assert.ok(seen.includes('/calculators/backtest/' + asset));
  for (const name of ['index.html', 'engine.js', 'DATA_SOURCES.md', 'market-data.csv']) {
    corrupted = name;
    await assert.rejects(helpers.verifyTarget(target), /bytes/);
  }
  corrupted = null;
  missing = 'app.js';
  await assert.rejects(helpers.verifyTarget(target), /404/);
});

test('file targets compare alternate target bytes and reject fallback content', async t => {
  const root = fixture(t);
  await helpers.verifyTarget(helpers.resolveTarget(root));
  const other = fs.mkdtempSync(path.join(os.tmpdir(), 'market-atlas-synthetic-other-'));
  t.after(() => fs.rmSync(other, { recursive: true, force: true }));
  for (const name of ['index.html', ...ASSETS]) fs.copyFileSync(path.join(root, name), path.join(other, name));
  const target = helpers.resolveTarget(root, pathToFileURL(path.join(other, 'index.html')).href);
  await helpers.verifyTarget(target);
  fs.writeFileSync(path.join(other, 'engine.js'), '<html>synthetic fallback</html>');
  await assert.rejects(helpers.verifyTarget(target), /bytes/);
});

test('network guards reject any remote or unexpected static resource', t => {
  const root = fixture(t);
  const local = helpers.resolveTarget(root);
  helpers.assertAllowedRequests(local, [local.url, new URL('engine.js', local.url).href, 'blob:null/synthetic'], new Set(['blob:null/synthetic']));
  assert.throws(() => helpers.assertAllowedRequests(local, ['http://127.0.0.1:1234/calculators/backtest/engine.js']), /unexpected/);
  const hosted = helpers.resolveTarget(root, 'http://127.0.0.1:1234/calculators/backtest/');
  helpers.assertAllowedRequests(hosted, [hosted.url, hosted.url + 'engine.js']);
  for (const unexpected of ['http://example.invalid/engine.js', hosted.url + 'other.js', hosted.url + 'engine.js?stale=1']) {
    assert.throws(() => helpers.assertAllowedRequests(hosted, [unexpected]), /unexpected/);
  }
});

test('download inspection requires complete actual bytes, schema, rows, and values', t => {
  const root = fixture(t);
  const model = { filename: 'synthetic.csv', rows: [{year: 2000, value: 12.5, status: 'synthetic, quoted', empty: null, flag: false}] };
  const destination = path.join(root, model.filename);
  assert.throws(() => helpers.assertCsvDownload(destination, model), /exist/);
  fs.writeFileSync(destination, 'year,value,status,empty,flag\r\n2000,12.5,"synthetic, quoted",,false');
  helpers.assertCsvDownload(destination, model);
  for (const bytes of ['', 'year,value,status,empty,flag\r\n2000,99,"synthetic, quoted",,false', 'value,year\r\n12.5,2000', 'year,value,status,empty,flag\r\n2000,12.5,"synthetic, quoted",,false\r\n2001,0,x,,true']) {
    fs.writeFileSync(destination, bytes);
    assert.throws(() => helpers.assertCsvDownload(destination, model), /bytes|schema|rows|empty/);
  }
});

test('only a declared empty inline favicon is an allowed data resource', t => {
  const root = fixture(t);
  const target = helpers.resolveTarget(root);
  assert.throws(() => helpers.assertAllowedRequests(target, ['data:,']), /unexpected/);
  fs.appendFileSync(path.join(root, 'index.html'), '<link rel="icon" href="data:,">');
  helpers.assertAllowedRequests(helpers.resolveTarget(root), ['data:,']);
  assert.throws(() => helpers.assertAllowedRequests(target, ['data:image/png;base64,SYNTHETIC']), /unexpected/);
});

test('unexpected request diagnostics are bounded and never print raw payloads', t => {
  const target = helpers.resolveTarget(fixture(t));
  const payload = 'data:image/png;base64,SYNTHETIC_PRIVATE_PAYLOAD_' + 'x'.repeat(10_000);
  assert.throws(() => helpers.assertAllowedRequests(target, [payload]), error => {
    assert.ok(error.message.length < 500);
    assert.match(error.message, /unexpected.*data:/i);
    assert.doesNotMatch(error.message, /SYNTHETIC_PRIVATE_PAYLOAD/);
    return true;
  });
});
