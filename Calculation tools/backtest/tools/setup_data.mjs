/** Node maintainer orchestration; all history and environments stay external. */
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { RECIPE_FILES,PAIR_FILES,DataContractError,sha256,fileIdentity,bundleIdentity,
  safeRoot,guardDirectory,readOwned,readRecipe,parsePair,verifySelected,verifyBundle,verifyRetainedInputs,validDate,retainedInputName } from './data_contract.mjs';
const DEFAULT_SOURCE=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const fail=message=>{throw new DataContractError(message);};
export async function runCommand(command,args,{env=process.env,signal,timeout=120000}={}) {
  if(signal?.aborted)fail('Setup interrupted');
  return await new Promise((resolve,reject)=>{
    const grouped=process.platform!=='win32';
    const child=spawn(command,args,{env,shell:false,detached:grouped,stdio:['ignore','pipe','pipe']});
    const stdout=[],stderr=[];let size=0,timedOut=false,grace;
    const kill=how=>{try{if(grouped&&child.pid)process.kill(-child.pid,how);else child.kill(how);}catch(error){if(error.code!=='ESRCH')throw error;}};
    const terminate=()=>{kill('SIGTERM');if(!grace)grace=setTimeout(()=>kill('SIGKILL'),5000);};
    const abort=()=>terminate();signal?.addEventListener('abort',abort,{once:true});
    const timer=setTimeout(()=>{timedOut=true;terminate();},timeout);
    const collect=chunks=>bytes=>{size+=bytes.length;if(size<=1024*1024)chunks.push(bytes);else terminate();};
    child.stdout.on('data',collect(stdout));child.stderr.on('data',collect(stderr));
    const cleanup=()=>{
      // Any leader may close before its descendants, even after success.
      // Kill only this spawn's remaining group before releasing resources.
      if(grouped||grace)kill('SIGKILL');
      clearTimeout(timer);clearTimeout(grace);signal?.removeEventListener('abort',abort);
    };
    child.on('error',()=>{cleanup();reject(new DataContractError('Subprocess unavailable; prepare the documented Python venv'));});
    child.on('close',code=>{cleanup();if(code!==0||timedOut||size>1024*1024||signal?.aborted){
      const error=new DataContractError(signal?.aborted?'Setup interrupted':'Compiler/dependency subprocess failed; check official endpoints or use --shiller/--damodaran/--fred with a compatible venv');
      // Private callers may retain bounded diagnostics; the CLI never prints them.
      error.diagnostics={code,timedOut,stdout:Buffer.concat(stdout).toString('utf8'),stderr:Buffer.concat(stderr).toString('utf8')};reject(error);
    }else resolve(Buffer.concat(stdout).toString('utf8'));});
  });
}
async function privateDir(target) {
  const missing=[];let parent=target;
  while(true) {try {await fs.lstat(parent);break;}catch(error){if(error.code!=='ENOENT')throw error;missing.push(parent);parent=path.dirname(parent);}}
  for(const directory of missing.reverse())await fs.mkdir(directory,{mode:0o700});
  await guardDirectory(target);
}
async function privateWrite(target,bytes) {await fs.writeFile(target,bytes,{mode:0o600,flag:'wx'});}
async function environment({dataHome,sourceRoot,offline,python,run,signal}) {
  const root=path.join(dataHome,'.venv'),executable=path.join(root,'bin','python');let fresh=false;
  try {await guardDirectory(root);} catch(error) {
    if(error.code!=='ENOENT')throw error;
    if(offline)fail('Offline setup requires a ready compatible venv; prepare it online with npm run setup:data');
    await run(python,['-m','venv','--copies',root],{signal,timeout:120000});fresh=true;
    // Only this newly created root is protected. Interpreter targets are never chmodded.
    await fs.chmod(root,0o700);await guardDirectory(root);
  }
  const config=await readOwned(path.join(root,'pyvenv.cfg'),{manual:true});if(!/^home = .+$/m.test(config.toString())||!/^version = 3\.\d+\.\d+$/m.test(config.toString())||!/^include-system-site-packages = false$/m.test(config.toString()))fail('Unknown venv layout; prepare a dedicated compiler venv');
  const bin=await fs.lstat(path.join(root,'bin'));if(!bin.isDirectory())fail('Unsafe venv layout');
  const interpreter=await fs.stat(executable);if(!interpreter.isFile())fail('Unsafe venv interpreter');
  const probe=`import json,sys,platform,importlib.metadata as m\nready=True\nfor line in open(${JSON.stringify(path.join(sourceRoot,'data/requirements.lock'))}):\n if '==' in line:\n  name,version=line.strip().split('==')\n  try: ready=ready and m.version(name)==version\n  except m.PackageNotFoundError: ready=False\nif ready:\n import pandas,xlrd\nprint(json.dumps({'version':platform.python_version(),'platform':sys.platform,'machine':platform.machine(),'ready':ready,'isolated':sys.prefix != sys.base_prefix and sys.prefix == ${JSON.stringify(root)}}))`;
  let status=JSON.parse(await run(executable,['-c',probe],{signal}));
  if(status.isolated!==true)fail('Compiler venv must be isolated; prepare a dedicated compiler venv');
  if(!/^3\.(?:1[0-9]|[2-9][0-9])\.\d+$/.test(status.version))fail('Compiler requires Python 3.10 or newer');
  if(fresh||!status.ready) {
    if(offline)fail('Offline setup requires installed locked dependencies; run npm run setup:data online');
    await run(executable,['-m','pip','--isolated','install','--index-url','https://pypi.org/simple','-r',path.join(sourceRoot,'data/requirements.lock')],{signal,timeout:900000});
    await run(executable,['-m','pip','check'],{signal});
    status=JSON.parse(await run(executable,['-c',probe],{signal}));if(!status.ready)fail('Locked compiler dependencies are not ready');
  }
  return executable;
}
async function sourceInput(source,target,{manual=false}={}) {
  const bytes=await readOwned(target,{manual});
  if(bytes.length>32*1024*1024)fail('Source input exceeds the byte maximum');
  if(source.format==='OLE/XLS'){
    if(bytes.length<512||!bytes.subarray(0,8).equals(Buffer.from([0xd0,0xcf,0x11,0xe0,0xa1,0xb1,0x1a,0xe1])))fail('Invalid XLS input; supply --shiller/--damodaran workbooks');
  }else if(source.format==='CSV'){
    let text;try{text=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(bytes);}catch{fail('Invalid UTF-8 CSV input; supply --fred');}
    const lines=text.replaceAll('\r\n','\n').split('\n');if(lines.at(-1)==='')lines.pop();
    if(lines.shift()!==source.layout.header.join(',')||!lines.length)fail('Invalid FRED CSV header or empty input');
    let previous='';
    for(const line of lines){
      // Numeric/date cells cannot contain embedded commas, quotes or newlines.
      // Accept ordinary quoted CSV cells as the compiler's stdlib reader does.
      const cells=line.match(/^("?)([^",]*)\1,("?)([^",]*)\3$/);
      if(!cells)fail('Invalid FRED date-value row');
      const day=cells[2],value=cells[4];validDate(day);
      if(day<=previous)fail('FRED dates must be strictly increasing');previous=day;
      if(value!==''&&(!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(value)||!Number.isFinite(Number(value))))fail('FRED values must be finite signed decimals or empty');
    }
  }else fail('Unsupported source input format');
  return bytes;
}
export async function setupData(options={}) {
  const {offline=false,refresh=false,shiller,damodaran,fred,generatedDate,python='python3.14',hooks={}}=options;
  if(options.signal?.aborted)fail('Setup interrupted');
  if(offline&&refresh)fail('Offline and refresh cannot be combined');if(generatedDate!==undefined)validDate(generatedDate);
  const sourceRoot=path.resolve(options.sourceRoot||DEFAULT_SOURCE);
  const repoRoot=options.repoRoot||path.resolve(sourceRoot,'../..');
  const dataHome=await safeRoot(options.dataHome||process.env.MARKET_ATLAS_DATA_HOME||path.join(os.homedir(),'.cache/market-atlas'),{sourceRoot,repoRoot,webroots:options.webroots});
  let selected=await verifySelected({dataHome,sourceRoot,repoRoot});
  const recipe=await readRecipe(sourceRoot);
  if(selected&&selected.recipeId===recipe.recipeId&&!refresh&&!shiller&&!damodaran&&!fred&&generatedDate===undefined)return {...selected,reused:true};
  if(selected)await verifyRetainedInputs({dataHome,sourceRoot,repoRoot,provenance:selected.provenance});
  // Validate external manual inputs before creating any mutation state.
  const sources=[...recipe.recipe.sources].sort((a,b)=>a.id<b.id?-1:1),sourceById=new Map(sources.map(source=>[source.id,source]));
  const supplied={shiller,damodaran,fred},manualBytes=new Map(),manualRecords=new Map();
  for(const [id,target]of Object.entries(supplied))if(target) {
    const requested=path.resolve(target),parent=await safeRoot(path.dirname(requested),{sourceRoot,repoRoot,webroots:options.webroots,privateRoot:false}),safe=path.join(parent,path.basename(requested));
    const relative=path.relative(dataHome,safe),managed=relative===''||(!relative.startsWith('..'+path.sep)&&relative!=='..'&&!path.isAbsolute(relative));
    const source=sourceById.get(id);
    if(managed){const logical=relative.split(path.sep).join('/'),match=logical.match(/^inputs\/([a-f0-9]{64})\/([^/]+)$/);
      if(match&&match[2]!==retainedInputName(id))fail('Unrecognized managed manual input path');
      if(!match&&!sources.some(item=>item.id===id&&item.cacheFilename===logical))fail('Unrecognized managed manual input path');
      if(match){await guardDirectory(path.join(dataHome,'inputs'));await guardDirectory(path.dirname(safe));}
      const bytes=await sourceInput(source,safe);if(match&&sha256(bytes)!==match[1])fail('Managed input hash mismatch');manualBytes.set(id,bytes);
    }else manualBytes.set(id,await sourceInput(source,safe,{manual:true}));
    manualRecords.set(id,{id,path:safe,sha256:sha256(manualBytes.get(id)),manual:!managed});
  }
  await privateDir(dataHome);const lock=path.join(dataHome,'.setup.lock');let handle;
  try {handle=await fs.open(lock,'wx',0o600);}catch(error){if(error.code==='EEXIST')fail('Setup mutation lock exists; investigate the other operation before retrying');throw error;}
  const controller=new AbortController();const abort=()=>controller.abort();process.once('SIGINT',abort);process.once('SIGTERM',abort);
  const signal=options.signal?AbortSignal.any([options.signal,controller.signal]):controller.signal; const run=hooks.run||runCommand;
  const lockStat=await handle.stat();
  const ownsLock=async()=>{try{const actual=await fs.lstat(lock);return actual.isFile()&&actual.ino===lockStat.ino&&actual.dev===lockStat.dev;}catch(error){if(error.code==='ENOENT')return false;throw error;}};
  let stage,selectorTemp;
  try {
    // Recheck after taking the mutation lock to avoid promoting against a raced selector.
    selected=await verifySelected({dataHome,sourceRoot,repoRoot});
    const retainedBytes=selected?await verifyRetainedInputs({dataHome,sourceRoot,repoRoot,provenance:selected.provenance}):new Map();
    const prior=selected?await readOwned(path.join(dataHome,'current.json')):null;
    stage=path.join(dataHome,'.candidate-'+randomUUID());await privateDir(stage);
    const cache=path.join(stage,'cache'),output=path.join(stage,'generation');await privateDir(cache);await privateDir(output);
    const inputSnapshots=new Map(),originals=[];
    const snapshot=async(id,bytes,original)=>{
      const parent=path.join(stage,'compile-inputs',id);await privateDir(parent);
      const target=path.join(parent,retainedInputName(id)),digest=sha256(bytes);await privateWrite(target,bytes);
      if(sha256(await sourceInput(sourceById.get(id),target))!==digest)fail('Candidate input integrity failure');
      inputSnapshots.set(id,{id,path:target,sha256:digest,bytes});originals.push({...original,id});
    };
    for(const source of sources) {
      if(manualBytes.has(source.id)){await snapshot(source.id,manualBytes.get(source.id),manualRecords.get(source.id));continue;}
      if(!refresh&&selected){const retained=selected.provenance.sources.find(item=>item.id===source.id);if(!retained)fail('Missing retained input');
        await snapshot(source.id,retainedBytes.get(source.id),{path:path.join(dataHome,retained.path),sha256:retained.sha256});continue;}
      const legacy=path.join(dataHome,source.cacheFilename);let bytes;
      if(!refresh)try{bytes=await sourceInput(source,legacy);}catch(error){if(error.code!=='ENOENT')throw error;}
      if(!refresh&&bytes)await snapshot(source.id,bytes,{path:legacy,sha256:sha256(bytes)});
      else if(offline)fail('Offline setup is missing an input; supply --shiller, --damodaran and --fred or run setup online');
    }
    const recipeRoot=path.join(output,'recipe');
    for(const name of RECIPE_FILES){await privateDir(path.dirname(path.join(recipeRoot,name)));await privateWrite(path.join(recipeRoot,name),recipe.bytes.get(name));}
    if((await readRecipe(sourceRoot)).recipeId!==recipe.recipeId)fail('Source recipe changed during setup; retry with a stable checkout');
    const executable=await environment({dataHome,sourceRoot:recipeRoot,offline,python,run,signal});
    const command=[path.join(recipeRoot,'data/compile_market_data.py'),'--output-dir',output,'--end-year','2025'];
    const execution={signal,env:{...process.env,MARKET_ATLAS_DATA_HOME:cache},timeout:180000};
    if(inputSnapshots.size!==sources.length){
      const acquisition=[...command,'--acquire-only'];
      for(const [id,input]of inputSnapshots)acquisition.push('--'+id,input.path);
      await run(executable,acquisition,execution);
      for(const source of sources)if(!inputSnapshots.has(source.id)){
        const target=path.join(cache,source.cacheFilename),bytes=await sourceInput(source,target);
        await snapshot(source.id,bytes,{path:target,sha256:sha256(bytes)});
      }
    }
    const assertInputsStable=async()=>{
      for(const input of inputSnapshots.values())if(sha256(await sourceInput(sourceById.get(input.id),input.path))!==input.sha256)fail('Candidate input changed during setup');
      for(const original of originals)if(sha256(await sourceInput(sourceById.get(original.id),original.path,{manual:original.manual}))!==original.sha256)fail('Source input changed during setup');
      if(selected)await verifyRetainedInputs({dataHome,sourceRoot,repoRoot,provenance:selected.provenance});
    };
    await assertInputsStable();
    const args=[...command];for(const [id,input]of inputSnapshots)args.push('--'+id,input.path);
    if(generatedDate!==undefined)args.push('--generated-date',generatedDate);
    await run(executable,args,execution);await assertInputsStable();
    const pair=new Map(),files=[];for(const name of PAIR_FILES){const content=await readOwned(path.join(output,name));pair.set(name,content);files.push({path:name,sha256:sha256(content)});}
    const payload=parsePair(pair.get('market-data.js'),pair.get('market-data.csv'),{requireCurrentSchema:true});
    if(signal.aborted)fail('Setup interrupted');
    if(hooks.historical)await hooks.historical(payload.rows);
    else await run(process.execPath,[path.join(recipeRoot,'tools/check_historical.mjs'),'--pair-dir',output],{signal,timeout:120000});
    await assertInputsStable();
    const retainedSources=[];await privateDir(path.join(dataHome,'inputs'));
    for(const source of sources) {
      const {bytes,sha256:digest}=inputSnapshots.get(source.id);
      const name=retainedInputName(source.id),parent=path.join(dataHome,'inputs',digest),object=path.join(parent,name);
      let exists=true;try {await guardDirectory(parent);}catch(error){if(error.code!=='ENOENT')throw error;exists=false;}
      if(exists){let retained;try{retained=await sourceInput(source,object);}catch(error){if(error.code==='ENOENT')fail('Existing immutable input is corrupt: missing source object');throw error;}if(sha256(retained)!==digest)fail('Existing immutable input corruption');}
      else {
        const pending=path.join(stage,'input-'+digest);await privateDir(pending);
        const candidate=path.join(pending,name);await privateWrite(candidate,bytes);
        if(sha256(await sourceInput(source,candidate))!==digest)fail('Candidate input hash mismatch');
        await fs.rename(pending,parent);
      }
      retainedSources.push({id:source.id,url:source.url,sha256:digest,path:`inputs/${digest}/${name}`});
    }
    const dataId=fileIdentity(files),bundleId=bundleIdentity({dataId,recipeId:recipe.recipeId,sources:retainedSources,generatedDate:payload.generated});
    const provenance={schemaVersion:1,bundleId,dataId,recipeId:recipe.recipeId,generatedDate:payload.generated,sources:retainedSources,files,recipeFiles:recipe.files,range:{firstYear:1872,lastYear:2025,count:154}};
    await privateWrite(path.join(output,'provenance.json'),JSON.stringify(provenance)+'\n');await privateDir(path.join(dataHome,'datasets'));
    const destination=path.join(dataHome,'datasets',bundleId);
    try {await guardDirectory(destination);await verifyBundle({dataHome,sourceRoot,repoRoot,bundleId});}
    catch(error){if(error.code!=='ENOENT')throw error;await fs.rename(output,destination);}
    const verified=await verifyBundle({dataHome,sourceRoot,repoRoot,bundleId,requireCurrentRecipe:true});
    await assertInputsStable();await verifyRetainedInputs({dataHome,sourceRoot,repoRoot,provenance});
    if(signal.aborted)fail('Setup interrupted');
    let actual=null;try{actual=await readOwned(path.join(dataHome,'current.json'));}catch(error){if(error.code!=='ENOENT')throw error;}
    if((actual===null)!==(prior===null)||(actual&& !actual.equals(prior)))fail('Selection changed during setup');
    if(!await ownsLock())fail('Setup lock changed during operation');
    selectorTemp=path.join(dataHome,'.current-'+randomUUID());await privateWrite(selectorTemp,JSON.stringify({schemaVersion:1,bundleId,dataId,recipeId:recipe.recipeId})+'\n');
    await assertInputsStable();await verifyRetainedInputs({dataHome,sourceRoot,repoRoot,provenance});
    if((await readRecipe(sourceRoot)).recipeId!==recipe.recipeId)fail('Source recipe changed during setup; retry with a stable checkout');
    actual=null;try{actual=await readOwned(path.join(dataHome,'current.json'));}catch(error){if(error.code!=='ENOENT')throw error;}
    if((actual===null)!==(prior===null)||(actual&& !actual.equals(prior)))fail('Selection changed during setup');
    if(!await ownsLock())fail('Setup lock changed during operation');
    if(signal.aborted)fail('Setup interrupted');
    if(hooks.promote)await hooks.promote(selectorTemp,path.join(dataHome,'current.json'));
    else await fs.rename(selectorTemp,path.join(dataHome,'current.json'));
    selectorTemp=undefined;return {...verified,reused:false};
  } finally {
    process.removeListener('SIGINT',abort);process.removeListener('SIGTERM',abort);
    if(selectorTemp)await fs.unlink(selectorTemp).catch(()=>{});
    if(stage)await fs.rm(stage,{recursive:true,force:true});
    const owned=await ownsLock();await handle.close();if(owned)await fs.unlink(lock);
  }
}
export function parseArgs(args) {
  const options={};for(let index=0;index<args.length;index++) {
    const arg=args[index];if(['--offline','--refresh'].includes(arg)){options[arg.slice(2)]=true;continue;}
    const key={'--shiller':'shiller','--damodaran':'damodaran','--fred':'fred','--generated-date':'generatedDate','--python':'python'}[arg];
    if(!key||!args[index+1]||args[index+1].startsWith('--'))fail('Usage: setup:data [--offline] [--refresh] [--shiller PATH] [--damodaran PATH] [--fred PATH] [--generated-date YYYY-MM-DD] [--python EXECUTABLE]');
    options[key]=args[++index];
  }return options;
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  try {const result=await setupData(parseArgs(process.argv.slice(2)));console.log(JSON.stringify({status:result.reused?'reused':'selected',bundleId:result.bundleId,dataId:result.dataId,recipeId:result.recipeId,count:result.payload.rows.length}));}
  catch(error){console.error(error instanceof DataContractError?error.message:'Setup validation failed; selected data was preserved. Check local prerequisites and supplied workbooks.');process.exitCode=1;}
}
