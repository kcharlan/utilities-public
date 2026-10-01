'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { fileURLToPath, pathToFileURL } = require('node:url');
const SCRIPT_ASSETS=Object.freeze(['market-data.js','format.js','stats.js','views.js','lifestyle.js','charts.js','csv.js','engine.js','app.js']);
const STATIC_ASSETS=Object.freeze([...SCRIPT_ASSETS,'DATA_SOURCES.md','market-data.csv']);
const HTTP_DIRECTORY='/calculators/backtest/';
function relativeName(name) {
  if(typeof name!=='string'||!name||name.startsWith('/')||name.split('/').some(part=>!part||part==='.'||part==='..')||/[\\%?#\x00-\x20]/.test(name))throw new Error('Invalid browser contract relative path');
  return name;
}
function makeExpected(files,{prefix=''}={}) {
  if(prefix)relativeName(prefix.slice(0,-1));
  const captured=new Map([...files].map(([name,bytes])=>[relativeName(name),Buffer.from(bytes)]));
  const scripts=SCRIPT_ASSETS.map(logicalName=>({logicalName,relativePath:prefix+logicalName}));
  const expected={files:captured,entryPath:'index.html',scripts,noticePath:prefix+'DATA_SOURCES.md',datasetCsvPath:prefix+'market-data.csv'};
  for(const name of [expected.entryPath,...scripts.map(s=>s.relativePath),expected.noticePath,expected.datasetCsvPath]){
    relativeName(name);if(!captured.get(name)?.length)throw new Error('Browser expected bytes missing: '+name);
  }
  return expected;
}
function captureSource(sourceRoot) {
  return makeExpected(new Map(['index.html',...STATIC_ASSETS].map(name=>[name,fs.readFileSync(path.join(sourceRoot,name))])));
}
function validateRawTarget(override) {
  // Reject characters WHATWG parsing trims/removes before checking raw schemes.
  if(/^[\x00-\x20]|[\x00-\x20]$|[\t\n\r]/.test(override))throw new Error('Browser target cannot contain boundary whitespace/control characters or embedded tab, LF, or CR.');
}
function resolveTarget(runtimeRoot,override,{expected,purpose='source',documentRoutes='both-http-entries'}={}) {
  const root=path.resolve(runtimeRoot);
  let url;
  if(override)validateRawTarget(override);
  if(override&&(/[?#]/.test(override)||(/^https?:/i.test(override)&&/[\\%]|(?:^|\/)\.{1,2}(?:\/|$)/.test(override))))throw new Error('Browser target cannot contain backslashes, encoded/traversal routes, query, or fragment.');
  try{url=new URL(override||pathToFileURL(path.join(root,'index.html')).href);}catch{throw new Error('Browser target must be an absolute file or loopback HTTP URL.');}
  if(url.username||url.password||url.search||url.hash)throw new Error('Browser target cannot contain credentials, query, or fragment.');
  if(url.protocol==='file:'){
    if(url.hostname||path.basename(fileURLToPath(url))!=='index.html')throw new Error('File target must be a local index.html.');
  }else if(url.protocol==='http:'){
    if(!['127.0.0.1','localhost','[::1]'].includes(url.hostname))throw new Error('HTTP browser target must use a loopback origin.');
    if(![HTTP_DIRECTORY,HTTP_DIRECTORY+'index.html'].includes(url.pathname))throw new Error('HTTP browser target must use the /calculators/backtest/ route or its index.html.');
    if(purpose==='installed'&&url.pathname!==HTTP_DIRECTORY+'index.html')throw new Error('Installed browser target requires the explicit index.html route.');
  }else throw new Error('Browser target must be a local file or loopback HTTP URL.');
  if(!['source','artifact','installed'].includes(purpose)||!['selected-entry','both-http-entries'].includes(documentRoutes))throw new Error('Unknown browser route policy');
  if(purpose==='installed')documentRoutes='selected-entry';
  // Snapshot the independent contract once; no later target mutation changes expectations.
  const contract=expected?{...expected,files:new Map([...expected.files].map(([n,b])=>[relativeName(n),Buffer.from(b)])),scripts:expected.scripts.map(s=>({...s}))}:captureSource(root);
  const base=new URL('.',url),scriptUrls=contract.scripts.map(s=>new URL(s.relativePath,base).href);
  const documents=url.protocol==='http:'&&documentRoutes==='both-http-entries'?[base.href,new URL('index.html',base).href]:[url.href];
  const resourceNames=[...contract.scripts.map(s=>s.relativePath),contract.noticePath,contract.datasetCsvPath];
  return Object.freeze({runtimeRoot:root,sourceRoot:root,url:url.href,baseUrl:base.href,protocol:url.protocol,purpose,documentRoutes,
    expected:contract,documents,resourceNames,scriptUrls,noticeUrl:new URL(contract.noticePath,base).href});
}
function requirePrerequisites(chromium,targetOrRoot) {
  const executable=chromium.executablePath();
  if(!fs.existsSync(executable)||!fs.statSync(executable).isFile())throw new Error('Managed Chromium is unavailable. Run npm ci and npx playwright install chromium.');
  const target=typeof targetOrRoot==='string'?{runtimeRoot:targetOrRoot,resourceNames:STATIC_ASSETS}:targetOrRoot;
  for(const name of ['index.html',...target.resourceNames]){
    const file=path.join(target.runtimeRoot,name);let stat;
    try{stat=fs.lstatSync(file);}catch{}
    if(!stat?.isFile()||!stat.size)throw new Error('Browser prerequisite missing or empty: '+name+'. Run npm run setup:data and npm run test:browser.');
  }
  return executable;
}
async function verifyTarget(target) {
  const resources=[...target.documents.map(url=>({url,name:target.expected.entryPath})),...target.resourceNames.map(name=>({url:new URL(name,target.baseUrl).href,name}))];
  for(const resource of resources){
    const expected=target.expected.files.get(resource.name);let actual;
    if(target.protocol==='file:'){
      const file=fileURLToPath(resource.url);const stat=fs.lstatSync(file);
      assert.ok(stat.isFile()&&!stat.isSymbolicLink(),'Target must contain regular files');actual=fs.readFileSync(file);
    }else{
      const response=await fetch(resource.url,{redirect:'error',signal:AbortSignal.timeout(5000)});
      assert.equal(response.status,200,'Expected successful static response for '+resource.name);actual=Buffer.from(await response.arrayBuffer());
    }
    assert.ok(expected?.length>0&&actual.equals(expected),'Target bytes differ for '+resource.name);
  }
}
function assertAllowedRequests(target,requests,downloads=new Set()) {
  const allowed=new Set([...target.documents,...target.resourceNames.map(name=>new URL(name,target.baseUrl).href)]);
  if(/<link\s+rel="icon"\s+href="data:,"\s*\/?\>/.test(target.expected.files.get(target.expected.entryPath).toString('utf8')))allowed.add('data:,');
  const unexpected=requests.filter(url=>!allowed.has(url)&&!(url.startsWith('blob:')&&downloads.has(url)));
  const categories=new Map();
  for(const raw of unexpected){
    let category='unparseable resource';
    try{const url=new URL(raw);const protocol=['http:','https:','file:','data:','blob:'].includes(url.protocol)?url.protocol:'other protocol';
      const location=['127.0.0.1','localhost','[::1]'].includes(url.hostname)?'loopback origin':url.hostname?'remote origin':'local/inline resource';
      category=protocol+' '+location+' '+(url.pathname==='/favicon.ico'?'undeclared favicon':'undeclared path/payload');
    }catch{}
    categories.set(category,(categories.get(category)||0)+1);
  }
  assert.equal(unexpected.length,0,'Browser made unexpected resource requests: '+[...categories].map(([name,count])=>name+' x'+count).join('; '));
  if(target.protocol==='file:')assert.equal(requests.filter(url=>/^https?:/i.test(url)).length,0,'File target must make zero HTTP requests');
}

function parseCsv(text) {
  const rows = [];
  let row = [], cell = '', quoted = false;
  for (let index = 0; index < text.length; index++) {
    const char = text[index];
    if (char === '"') {
      if (quoted && text[index + 1] === '"') { cell += '"'; index++; }
      else quoted = !quoted;
    } else if (!quoted && char === ',') { row.push(cell); cell = ''; }
    else if (!quoted && (char === '\r' || char === '\n')) {
      row.push(cell); rows.push(row); row = []; cell = '';
      if (char === '\r' && text[index + 1] === '\n') index++;
    } else cell += char;
  }
  assert.equal(quoted, false, 'CSV bytes have an unterminated quoted cell');
  row.push(cell); rows.push(row);
  return rows;
}

function assertCsvDownload(file, model) {
  assert.ok(fs.existsSync(file), 'CSV download must exist on disk');
  const actual = fs.readFileSync(file, 'utf8');
  assert.ok(actual.length, 'CSV download must not be empty');
  assert.ok(model.rows.length, 'Accepted export model must have rows');
  const parsed = parseCsv(actual);
  const headers = Object.keys(model.rows[0]);
  assert.deepEqual(parsed[0], headers, 'CSV schema differs from accepted model');
  assert.equal(parsed.length - 1, model.rows.length, 'CSV rows differ from accepted model');
  for (const [index, expected] of model.rows.entries()) {
    const cells = headers.map(header => {
      const value = expected[header];
      if (value == null) return '';
      const text = String(value);
      return typeof value === 'string' && /^[\x00-\x20]*[=+\-@]/.test(text) ? "'" + text : text;
    });
    assert.deepEqual(parsed[index + 1], cells, 'CSV bytes differ at row ' + (index + 1));
  }
}

module.exports = { STATIC_ASSETS, SCRIPT_ASSETS, makeExpected, validateRawTarget, resolveTarget, requirePrerequisites, verifyTarget, assertAllowedRequests, assertCsvDownload };
