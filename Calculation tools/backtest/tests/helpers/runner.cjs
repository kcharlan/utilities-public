'use strict';
const fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os');
const http=require('node:http'),{spawn}=require('node:child_process');
const {makeExpected}=require('./browser-target.cjs');
const {SOURCE_ROOT,REPO_ROOT,dataOptions}=require('./dataset.cjs');
const SYNTHETIC_TESTS=Object.freeze(['admission','app-render','browser-target','charts','config-apply','data-contract','format','privacy','setup-data','stats','strategies','structure','theme','window-render','static-build','static-deploy','dataset-helper','runner-contract','browser-contract'].map(n=>n+'.test.js'));
const PYTHON_SYNTHETIC=Object.freeze(['test_compile_market_data','test_external_compiler']);
const own=(name)=>typeof name==='string'&&name&&!path.isAbsolute(name)&&!/[\\%?#\x00-\x20]/.test(name)&&name.split('/').every(s=>s&&s!=='.'&&s!=='..');
async function captureInputs(sourceRoot,bundle) {
 const {SOURCE_INPUTS}=await import('../../tools/build_static.mjs'),{readOwned}=await import('../../tools/data_contract.mjs');
 const source=new Map();for(const name of SOURCE_INPUTS)source.set(name,Buffer.from(await readOwned(path.join(sourceRoot,name))));
 const files=new Map([...source,...[...bundle.files].map(([name,bytes])=>[name,Buffer.from(bytes)])]);
 const expected=makeExpected(files);
 return {sourceRoot,dataRoot:bundle.root,source,files,sourceExpected:expected,artifactExpected:expected};
}
async function privateTemp({tempParent=process.env.MARKET_ATLAS_TEST_TMPDIR||os.tmpdir()}={}) {
 const {safeRoot}=await import('../../tools/data_contract.mjs');await safeRoot(tempParent,{sourceRoot:SOURCE_ROOT,repoRoot:REPO_ROOT,privateRoot:false});
 const root=await fs.mkdtemp(path.join(tempParent,'market-atlas test '));await fs.chmod(root,0o700);return root;
}
async function guardPrivateDirectory(root) {
 const {safeRoot,guardDirectory}=await import('../../tools/data_contract.mjs');await safeRoot(root,{sourceRoot:SOURCE_ROOT,repoRoot:REPO_ROOT});await guardDirectory(root);
}
async function writeFiles(root,files,{fileMode=0o600,directoryMode=0o700}={}) {
 await fs.mkdir(root,{mode:directoryMode});
 await guardPrivateDirectory(root);
 for(const [name,bytes]of files){
  if(!own(name))throw new Error('Unsafe expected filename');
  let directory=root;
  for(const part of path.dirname(name).split('/').filter(p=>p!=='.')){
   directory=path.join(directory,part);
   await fs.mkdir(directory,{mode:directoryMode}).catch(error=>{if(error.code!=='EEXIST')throw error;});
   await guardPrivateDirectory(directory);
  }
  await guardPrivateDirectory(directory);
  await fs.writeFile(path.join(root,name),bytes,{flag:'wx',mode:fileMode});
 }
}
async function saveExpected(root,expected) {
 await writeFiles(root,expected.files);
 const descriptor={entryPath:expected.entryPath,scripts:expected.scripts,noticePath:expected.noticePath,datasetCsvPath:expected.datasetCsvPath,paths:[...expected.files.keys()]};
 await guardPrivateDirectory(root);
 await fs.writeFile(path.join(root,'browser-contract.json'),JSON.stringify(descriptor)+'\n',{mode:0o600,flag:'wx'});
}
async function loadExpected(root) {
 const {safeRoot,guardDirectory,readOwned}=await import('../../tools/data_contract.mjs');
 await guardPrivateDirectory(root);
 const descriptor=JSON.parse(await readOwned(path.join(root,'browser-contract.json')));
 if(descriptor.entryPath!=='index.html'||!Array.isArray(descriptor.paths)||descriptor.paths.length>13||descriptor.paths.some(n=>!own(n))||new Set(descriptor.paths).size!==descriptor.paths.length)throw new Error('Invalid expected browser inventory');
 const files=new Map();
 for(const name of descriptor.paths){let directory=root;for(const part of path.dirname(name).split('/').filter(p=>p!=='.')){directory=path.join(directory,part);await guardDirectory(directory);}files.set(name,await readOwned(path.join(root,name)));}
 const prefix=descriptor.scripts?.[0]?.relativePath?.slice(0,-'market-data.js'.length);
 const expected=makeExpected(files,{prefix});
 if(JSON.stringify(descriptor.scripts)!==JSON.stringify(expected.scripts)||descriptor.noticePath!==expected.noticePath||descriptor.datasetCsvPath!==expected.datasetCsvPath)throw new Error('Invalid expected browser descriptor');
 return expected;
}
async function prepareLayouts(captured,options={}) {
 const root=await privateTemp(options);let cleaned=false;
 async function cleanup(){if(!cleaned){await fs.rm(root,{recursive:true,force:true});cleaned=true;}}
 try{
  const artifactRoot=path.join(root,'flat layout'),artifactExpectedRoot=path.join(root,'independent expectations');
  await saveExpected(artifactExpectedRoot,captured.artifactExpected);
  const {buildStatic}=await import('../../tools/build_static.mjs');
  await buildStatic({sourceRoot:captured.sourceRoot,dataRoot:captured.dataRoot,outputDir:artifactRoot});
  return {root,sourceRoot:artifactRoot,artifactRoot,sourceExpectedRoot:artifactExpectedRoot,artifactExpectedRoot,sourceExpected:captured.sourceExpected,artifactExpected:captured.artifactExpected,cleanup};
 }catch(error){await cleanup();throw error;}
}
async function diskFile(root,name) {
 if(!own(name))throw new Error('Unsafe served filename');
 let parent=root;if(!(await fs.lstat(parent)).isDirectory())throw new Error('Unsafe served root');
 for(const part of path.dirname(name).split('/').filter(p=>p!=='.')){parent=path.join(parent,part);if(!(await fs.lstat(parent)).isDirectory())throw new Error('Unsafe served directory');}
 const file=path.join(root,name),stat=await fs.lstat(file);if(!stat.isFile()||stat.nlink!==1)throw new Error('Unsafe served file');
 const handle=await fs.open(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);
 try{const actual=await handle.stat();if(actual.dev!==stat.dev||actual.ino!==stat.ino)throw new Error('Served file changed during read');return await handle.readFile();}finally{await handle.close();}
}
async function serveDirectory(root,inventory) {
 const names=new Set(inventory);if(!names.has('index.html')||[...names].some(n=>!own(n)))throw new Error('Invalid server inventory');
 const prefix='/calculators/backtest/';
 const server=http.createServer(async(req,res)=>{
  const raw=req.url;
  let name=raw===prefix?'index.html':raw.startsWith(prefix)?raw.slice(prefix.length):'';
  if(!['GET','HEAD'].includes(req.method)||!names.has(name)||!own(name)){res.writeHead(404);res.end();return;}
  try{const bytes=await diskFile(root,name);const type=name.endsWith('.js')?'text/javascript; charset=utf-8':name.endsWith('.html')?'text/html; charset=utf-8':name.endsWith('.csv')?'text/csv; charset=utf-8':'text/plain; charset=utf-8';
   res.writeHead(200,{'Content-Type':type,'Content-Length':bytes.length,'Cache-Control':'no-store'});res.end(req.method==='HEAD'?undefined:bytes);
  }catch{res.writeHead(404);res.end();}
 });
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
 const port=server.address().port;let closed=false;
 return {port,directoryUrl:`http://127.0.0.1:${port}${prefix}`,indexUrl:`http://127.0.0.1:${port}${prefix}index.html`,async close(){if(closed)return;closed=true;await new Promise((resolve,reject)=>{server.close(e=>e?reject(e):resolve());server.closeAllConnections();});}};
}
function runChild(executable,args,{cwd=SOURCE_ROOT,env=process.env,signal,quiet=false,timeout=0,requireZeroSkips=false,unittestCases}={}) {
 return new Promise((resolve,reject)=>{
  if(signal?.aborted){reject(new Error('Test run interrupted'));return;}
  const child=spawn(executable,args,{cwd,env,stdio:['ignore','pipe','pipe'],detached:process.platform!=='win32'});
  let output='',stderr='',interrupted=false,timedOut=false,escalation,deadline;
  const collect=(chunk,stream)=>{output+=chunk.toString();if(stream===process.stderr)stderr+=chunk.toString();if(!quiet)stream.write(chunk);};
  child.stdout.on('data',c=>collect(c,process.stdout));child.stderr.on('data',c=>collect(c,process.stderr));
  const stop=()=>{interrupted=true;child.kill('SIGTERM');escalation=setTimeout(()=>{try{if(process.platform==='win32')child.kill('SIGKILL');else process.kill(-child.pid,'SIGKILL');}catch{}},5000);};
  signal?.addEventListener('abort',stop,{once:true});
  if(timeout)deadline=setTimeout(()=>{timedOut=true;stop();},timeout);
  function reapGroup(){
   if(process.platform!=='win32'&&child.pid){try{process.kill(-child.pid,'SIGKILL');}catch(error){if(error.code!=='ESRCH')throw error;}}
  }
  // The leader may exit while descendants still hold pipes/resources.
  child.once('exit',reapGroup);
  function cleanup(){clearTimeout(escalation);clearTimeout(deadline);signal?.removeEventListener('abort',stop);}
  child.once('error',()=>{cleanup();reject(new Error('Test subprocess unavailable; prepare documented local prerequisites'));});
  child.once('close',(code,terminated)=>{
   cleanup();
   if(interrupted){reject(new Error(timedOut?'Test subprocess timed out':'Test run interrupted; child termination awaited'));return;}
   if(code!==0||terminated){reject(new Error(`Test subprocess failed (exit ${code}, signal ${terminated||'none'})`));return;}
   if(requireZeroSkips&&(/(?:#|ℹ) skipped [1-9]|\bskipped=[1-9]|\bskipped [1-9]/.test(output))){reject(new Error('Test subprocess reported prohibited skips'));return;}
   if(unittestCases){
    const results=[...stderr.matchAll(/^test_\w+ \(([\w.]+)\) \.\.\. (.+)$/gm)];
    const ids=results.map(match=>match[1]).sort(),expected=[...unittestCases].sort();
    const summary=stderr.match(/\nRan (\d+) tests in \d+(?:\.\d+)?s\n\nOK\s*$/);
    if(!expected.length||new Set(expected).size!==expected.length||results.some(match=>match[2]!=='ok')||JSON.stringify(ids)!==JSON.stringify(expected)||Number(summary?.[1])!==expected.length){reject(new Error('Required compiler unittest cases did not all execute successfully without skips'));return;}
   }
   resolve(output);
  });
 });
}
const VENV_GUIDANCE='A ready external Python venv is required. Prepare the documented test environment manually, then set MARKET_ATLAS_TEST_PYTHON to its bin/python (or use MARKET_ATLAS_DATA_HOME/.venv/bin/python). Tests never bootstrap or install dependencies.';
async function validatePython({env=process.env,sourceRoot=SOURCE_ROOT,signal}={}) {
 const executable=path.resolve(env.MARKET_ATLAS_TEST_PYTHON||path.join(dataOptions(env).dataHome,'.venv/bin/python'));
 const root=path.dirname(path.dirname(executable));
 try{
  const {safeRoot,readOwned}=await import('../../tools/data_contract.mjs');
  await safeRoot(root,{sourceRoot:SOURCE_ROOT,repoRoot:REPO_ROOT,privateRoot:false});
  if(path.basename(path.dirname(executable))!=='bin'||!/^python(?:3(?:\.\d+)?)?$/.test(path.basename(executable)))throw Error('Unknown interpreter layout');
  const cfg=(await readOwned(path.join(root,'pyvenv.cfg'))).toString();
  if(!/^include-system-site-packages = false$/m.test(cfg))throw Error('Venv must be isolated');
  const dependencies=(await fs.readFile(path.join(sourceRoot,'data/requirements.lock'),'utf8')).split(/\r?\n/).filter(l=>l&&!l.startsWith('#')).map(l=>l.split('=='));
  if(dependencies.some(p=>p.length!==2))throw Error('Unknown dependency lock');
  const probe="import sys,json,importlib.metadata as m\nassert sys.prefix != sys.base_prefix and sys.prefix == "+JSON.stringify(root)+"\nfor name,version in "+JSON.stringify(dependencies)+":\n assert m.version(name) == version\nimport pandas,xlrd\nprint('ready')";
  const result=await runChild(executable,['-I','-B','-c',probe],{cwd:sourceRoot,env:{...env,PYTHONDONTWRITEBYTECODE:'1'},signal,quiet:true,timeout:30000});
  if(result.trim()!=='ready')throw Error('Invalid venv probe');return executable;
 }catch(error){if(signal?.aborted)throw error;throw Error(VENV_GUIDANCE);}
}
async function runSyntheticCompiler(python,{env=process.env,sourceRoot=SOURCE_ROOT,signal}={}) {
 // Discover the actual case identities inside the already proven venv. The
 // mandatory command still runs both complete original modules, without filters.
 const probe=`import json,unittest\ndef cases(suite):\n for case in suite:\n  if isinstance(case,unittest.TestSuite):\n   yield from cases(case)\n  else:\n   yield case.id()\nprint(json.dumps(sorted(cases(unittest.defaultTestLoader.loadTestsFromNames(${JSON.stringify(PYTHON_SYNTHETIC)})))))`;
 const options={cwd:path.join(sourceRoot,'data'),env:{...env,PYTHONDONTWRITEBYTECODE:'1'},signal};
 const output=await runChild(python,['-B','-c',probe],{...options,quiet:true,timeout:30000});
 const unittestCases=JSON.parse(output);
 if(!Array.isArray(unittestCases)||!unittestCases.length||new Set(unittestCases).size!==unittestCases.length||unittestCases.some(id=>typeof id!=='string'||!PYTHON_SYNTHETIC.some(module=>id.startsWith(module+'.')))||PYTHON_SYNTHETIC.some(module=>!unittestCases.some(id=>id.startsWith(module+'.'))))throw new Error('Required compiler modules must discover unique cases from both complete modules');
 await runChild(python,['-B','-m','unittest','-v',...PYTHON_SYNTHETIC],{...options,requireZeroSkips:true,unittestCases});
}
function signalController() {
 const controller=new AbortController();
 const handlers=new Map(['SIGINT','SIGTERM'].map(name=>[name,()=>{process.exitCode=name==='SIGINT'?130:143;controller.abort();}]));
 for(const [name,fn]of handlers)process.on(name,fn);
 return {signal:controller.signal,dispose(){for(const [name,fn]of handlers)process.removeListener(name,fn);}};
}
module.exports={SYNTHETIC_TESTS,PYTHON_SYNTHETIC,captureInputs,prepareLayouts,privateTemp,guardPrivateDirectory,saveExpected,loadExpected,serveDirectory,runChild,validatePython,runSyntheticCompiler,signalController};
