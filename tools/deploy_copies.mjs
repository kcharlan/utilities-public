#!/usr/bin/env node
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {regular,inspectAncestors,externalDirectory,sha,exists,atomicFile,parseStagedListing,normalizeEntries,hashInventory,finishCleanup,cleanupDirectories,pruneBackups} from './deployment_files.mjs';
const safe = s => typeof s==='string' && s.trim().length>0 && s!=='.' && s!=='..' && !/[\/\\|\x00-\x1f\x7f]/.test(s);
const relative = s => typeof s==='string' && s.length>0 && !path.posix.isAbsolute(s) && !s.includes('\\') && s.split('/').every(safe);
const exact = (o,required,optional=[]) => o && typeof o==='object' && !Array.isArray(o) && required.every(k=>Object.hasOwn(o,k)) && Object.keys(o).every(k=>required.includes(k)||optional.includes(k));
const git=(repo,...args)=>execFileSync('git',['-C',repo,'--literal-pathspecs',...args],{encoding:'utf8',maxBuffer:64*1024*1024});
function manifest(repo) {
 const obj=JSON.parse(fs.readFileSync(path.join(repo,'tools/deployment_copies.json'),'utf8'));
 if (!exact(obj,['scripts','projects']) || !Array.isArray(obj.scripts) || !Array.isArray(obj.projects) || !obj.scripts.length && !obj.projects.length) throw Error('Invalid manifest');
 if (!obj.scripts.every(e=>exact(e,['name','source'],['target','smoke'])) || !obj.projects.every(e=>exact(e,['name'],['entrypoint','smoke']))) throw Error('Invalid manifest entry');
 const names=new Set(), targets=new Set();
 return [...obj.scripts.map(e=>({...e,kind:'script'})),...obj.projects.map(e=>({...e,kind:'project'}))].map(e=>{
  const valid=e.kind==='script' ? exact(e,['name','source','kind'],['target','smoke']) && relative(e.source) && (!Object.hasOwn(e,'target')||safe(e.target)) : exact(e,['name','kind'],['entrypoint','smoke']) && (!Object.hasOwn(e,'entrypoint')||relative(e.entrypoint));
  if (!valid || !safe(e.name) || names.has(e.name) || (e.smoke!==undefined && (!Array.isArray(e.smoke)||!e.smoke.length||e.smoke.some(a=>typeof a!=='string'||!a||a.includes('\0')))) || (e.kind==='project' && e.smoke && !e.entrypoint)) throw Error('Invalid manifest entry');
  names.add(e.name); const key=e.kind+':'+(e.target||e.name); if(targets.has(key)) throw Error('Overlapping manifest destinations'); targets.add(key); return e;
 });
}
function admission(repo,paths) {
 if(git(repo,'branch','--show-current').trim()!=='main') throw Error('Deployments require main');
 if(git(repo,'status','--porcelain=v1','--untracked-files=all','--',...paths).trim()) throw Error('Uncommitted or untracked deployment inputs');
 const staged=git(repo,'ls-files','--stage','--sparse','-z','--',...paths);
 const head=git(repo,'ls-tree','-r','-z','HEAD','--',...paths).split('\0').filter(Boolean).map(x=>x.replace(/^(\d+) blob ([a-f0-9]+)\t/,'$1 $2 0\t')).join('\0')+'\0';
 if(staged!==head) throw Error('Index differs from HEAD');
 return normalizeEntries(parseStagedListing(staged));
}
function inventory(repo,e) {
 const source=e.kind==='script'?e.source:e.name;
 const entries=admission(repo,[source]); if(!entries.length || e.kind==='script' && (entries.length!==1||entries[0].name!==source)) throw Error('Blank or invalid source inventory');
 if(e.kind==='project' && e.entrypoint && !entries.some(item=>item.name===e.name+'/'+e.entrypoint)) throw Error('Project entrypoint is not tracked');
 for(const item of entries) inspectAncestors(path.dirname(path.join(repo,item.name)));
 hashInventory(repo,entries,true);
 return entries.map(item=>({...item,rel:e.kind==='script'?(e.target||e.name):item.name.slice(e.name.length+1)}));
}
function current(file) { if(!exists(file))return null; const mode=regular(file).mode&0o7777, bytes=fs.readFileSync(file); return {mode,hash:sha(bytes),bytes}; }
function destination(root,rel) { if(!relative(rel)) throw Error('Invalid destination path'); const file=path.join(root,rel); inspectAncestors(path.dirname(file)); if(exists(file)) regular(file); return file; }
function backup(repo,e,root,items,revision) {
 const backupRoot=externalDirectory(path.join(os.homedir(),'.utilities-deploy-backups'),repo);
 const namespace=externalDirectory(path.join(backupRoot,e.name),repo); fs.mkdirSync(namespace,{recursive:true,mode:0o700}); fs.chmodSync(backupRoot,0o700); fs.chmodSync(namespace,0o700);
 const dir=fs.mkdtempSync(path.join(namespace,'copy-')); fs.chmodSync(dir,0o700);
 console.log('Recovery backup: '+dir);
 const files=[];
 for(const {rel} of items){ const state=current(destination(root,rel)); files.push({path:rel,prior:state?{mode:state.mode,hash:state.hash}:null}); if(state){ const payload=path.join(dir,'payload',rel); fs.mkdirSync(path.dirname(payload),{recursive:true,mode:0o700}); fs.writeFileSync(payload,state.bytes,{mode:0o600}); } }
 fs.writeFileSync(path.join(dir,'state.json'),JSON.stringify({schema:1,name:e.name,kind:e.kind,revision,files})+'\n',{mode:0o600});
 for (const {path:rel,prior:before} of files) {
  const after=current(destination(root,rel));
  if ((before===null)!==(after===null) || before && (before.mode!==after.mode || before.hash!==after.hash)) throw Error('Destination changed while backing up: '+rel+'; Recovery backup: '+dir);
 }
 return dir;
}
function readBackup(repo,dir,entries) {
 inspectAncestors(dir); let s; try { const metadata=path.join(dir,'state.json'); if((regular(metadata).mode&0o7777)!==0o600) throw Error('invalid mode'); s=JSON.parse(fs.readFileSync(metadata,'utf8')); } catch(error) { throw Error('Invalid backup state: '+error.message,{cause:error}); }
 if(!exact(s,['schema','name','kind','revision','files'])||s.schema!==1||!safe(s.name)||!['script','project'].includes(s.kind)||typeof s.revision!=='string'||!/^([a-f0-9]{40}|[a-f0-9]{64})$/.test(s.revision)||!Array.isArray(s.files)||!s.files.length) throw Error('Invalid backup state');
 const e=entries.find(x=>x.name===s.name&&x.kind===s.kind); if(!e)throw Error('Backup entry is not in manifest');
 let paths; try {
  git(repo,'cat-file','-e',s.revision+'^{commit}');
  paths=git(repo,'ls-tree','-r','-z',s.revision,'--',e.kind==='script'?e.source:e.name).split('\0').filter(Boolean).flatMap(record=>{const match=/^(100644|100755) blob [a-f0-9]+\t(.+)$/.exec(record);return match?[match[2]]:[];});
 }catch{throw Error('Backup admission revision unavailable');}
 const allowed=new Set(e.kind==='script'?[e.target||e.name]:paths.map(p=>p.slice(e.name.length+1)));
 const seen=new Set();
 const items=s.files.map(record=>{
  if(!exact(record,['path','prior']))throw Error('Invalid backup inventory'); const rel=record.path,value=record.prior;
  if(!relative(rel)||!allowed.has(rel)||seen.has(rel))throw Error('Invalid backup inventory'); seen.add(rel);
  if(value===null)return {rel,value:null};
  if(!exact(value,['mode','hash'])||!Number.isInteger(value.mode)||value.mode<0||value.mode>0o7777||typeof value.hash!=='string'||!/^[a-f0-9]{64}$/.test(value.hash))throw Error('Invalid backup state');
  const file=path.join(dir,'payload',rel); inspectAncestors(path.dirname(file)); if((regular(file).mode&0o7777)!==0o600)throw Error('Invalid backup payload mode'); const bytes=fs.readFileSync(file); if(sha(bytes)!==value.hash)throw Error('Backup hash mismatch'); return {rel,value:{...value,bytes}};
 });
 return {e,items,revision:s.revision};
}
function publish(root,items,created) {
 for(const {rel,value} of items){ const file=destination(root,rel); if(value){ let d=path.dirname(file), missing=[]; while(!exists(d)){missing.push(d); d=path.dirname(d);} for(const dir of missing.reverse()){fs.mkdirSync(dir);created.push(dir);} atomicFile(file,value.bytes,value.mode,'.copy-stage-'); } else if(exists(file))fs.unlinkSync(file); }
}
function smoke(e,root) {
 if(!e.smoke)return; const executable=e.kind==='script'?path.join(root,e.target||e.name):path.join(root,e.entrypoint); regular(executable);
 const scratch=fs.mkdtempSync(path.join(os.tmpdir(),'copy-smoke-')); let primary;
 try{ const env={...process.env,UV_PYTHON_DOWNLOADS:'never'}; for(const key of ['VIRTUAL_ENV','VIRTUAL_ENV_PROMPT','CONDA_PREFIX','CONDA_DEFAULT_ENV','CONDA_SHLVL','CONDA_EXE','CONDA_PYTHON_EXE','PYENV_VERSION','PYTHONHOME','PYTHONPATH','PYTHONSTARTUP','PYTHONUSERBASE','__PYVENV_LAUNCHER__','UV_PYTHON','UV_SYSTEM_PYTHON','UV_BREAK_SYSTEM_PACKAGES']) delete env[key];
  const canonical=p=>{try{return fs.realpathSync(p);}catch{return path.resolve(p);}};
  const excluded=[process.env.VIRTUAL_ENV && path.join(process.env.VIRTUAL_ENV,'bin'),process.env.CONDA_PREFIX && path.join(process.env.CONDA_PREFIX,'bin'),process.env.PYENV_ROOT && path.join(process.env.PYENV_ROOT,'shims')].filter(Boolean).map(canonical);
  env.PATH=(env.PATH||'').split(path.delimiter).filter(p=>{if(!p)return false; const resolved=canonical(p); return !excluded.includes(resolved) && !(path.basename(resolved)==='bin' && exists(path.join(path.dirname(resolved),'pyvenv.cfg')));}).join(path.delimiter);
  execFileSync(executable,e.smoke,{cwd:scratch,env,timeout:120000,stdio:'pipe'}); }catch(error){primary=new Error('Smoke check failed: '+error.message,{cause:error});}
 finishCleanup(primary,cleanupDirectories([scratch]),'Smoke completed, but cleanup failed');
}
export function main(argv=process.argv.slice(2)) {
 let repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),scripts=path.resolve(process.env.UTILITIES_SCRIPTS_DIR||path.join(os.homedir(),'Library/Scripts')),local=path.resolve(process.env.UTILITIES_LOCAL_ROOT||os.homedir()),dry=false,rollback,only=[];
 for(let i=0;i<argv.length;i++){const a=argv[i]; if(a==='--help'){console.log('Usage: node tools/deploy_copies.mjs [--dry-run | --rollback BACKUP] [--only NAME]... [--repo DIR] [--scripts-dir DIR] [--local-root DIR]');return;} if(a==='--dry-run')dry=true; else if(['--repo','--scripts-dir','--local-root','--rollback','--only'].includes(a)&&argv[i+1]){const v=argv[++i]; if(a==='--repo')repo=path.resolve(v); else if(a==='--scripts-dir')scripts=path.resolve(v); else if(a==='--local-root')local=path.resolve(v); else if(a==='--rollback')rollback=path.resolve(v); else only.push(v);}else throw Error('Unknown or incomplete argument'); }
 if(rollback&&(dry||only.length))throw Error('Incompatible deployment options'); repo=fs.realpathSync(repo); scripts=externalDirectory(scripts,repo); local=externalDirectory(local,repo);
 const inputs=['tools/deployment_copies.json','tools/deploy_copies.mjs','tools/deployment_files.mjs'];
 const admitted=admission(repo,inputs); if(inputs.some(name=>!admitted.some(e=>e.name===name))) throw Error('Required deployment input is untracked');
 for(const entry of admitted) inspectAncestors(path.dirname(path.join(repo,entry.name)));
 hashInventory(repo,admitted,true);
 const entries=manifest(repo); if(only.some(n=>!entries.some(e=>e.name===n)))throw Error('Unknown entry');
 for (const e of entries) {
  const source=e.kind==='script'?e.source:e.name;
  const listed=parseStagedListing(git(repo,'ls-files','--stage','--sparse','-z','--',source));
  if (!listed.length || e.kind==='script' && (listed.length!==1 || listed[0].name!==source) || e.kind==='project' && e.entrypoint && !listed.some(item=>item.name===e.name+'/'+e.entrypoint)) throw Error('Manifest source or entrypoint is not tracked: '+source);
 }
 const selected=rollback?[readBackup(repo,rollback,entries).e]:entries.filter(e=>!only.length||only.includes(e.name));
 const roots=selected.map(e=>e.kind==='script'?path.join(scripts,e.target||e.name):externalDirectory(path.join(local,e.name),repo));
 for(const target of roots) if(target===repo||target.startsWith(repo+path.sep)||repo.startsWith(target+path.sep)) throw Error('Destination overlaps repository');
 for(let i=0;i<roots.length;i++) if(selected[i].kind==='script') { inspectAncestors(path.dirname(roots[i])); if(exists(roots[i])) regular(roots[i]); }
 for(let i=0;i<roots.length;i++)for(let j=0;j<i;j++)if(roots[i]===roots[j]||roots[i].startsWith(roots[j]+path.sep)||roots[j].startsWith(roots[i]+path.sep))throw Error('Overlapping destinations');
 let completed=[];
 try{ for(const e of selected){ const root=e.kind==='script'?scripts:path.join(local,e.name); externalDirectory(root,repo); let items,revision;
  if(rollback){ const saved=readBackup(repo,rollback,entries); items=saved.items; revision=saved.revision; }
  else { const source=inventory(repo,e); revision=git(repo,'rev-parse','HEAD').trim(); items=source.map(x=>({rel:x.rel,value:{bytes:x.bytes,mode:x.permissions}})).filter(x=>{const old=current(destination(root,x.rel));return !old||old.mode!==x.value.mode||old.hash!==sha(x.value.bytes);}); }
  if(!items.length){console.log(e.name+': already matches source');continue;} if(dry){console.log(e.name+': '+items.length+' files would change');continue;}
  const saved=backup(repo,e,root,items,revision); const recovery=readBackup(repo,saved,entries); const created=[]; let primary;
  try{publish(root,items,created); if(!rollback)smoke(e,root);}catch(error){ primary=error; try{publish(root,recovery.items,[]);}catch(restoreError){primary=new AggregateError([error,restoreError],error.message+'; restoration failed: '+restoreError.message);} }
  const cleanupErrors=[]; for(const d of created.reverse())try{fs.rmdirSync(d);}catch(error){if(error.code!=='ENOTEMPTY'&&error.code!=='ENOENT')cleanupErrors.push(new Error('Cleanup failed for '+d+': '+error.message,{cause:error}));}
  if (!primary && cleanupErrors.length) {
   try { publish(root,recovery.items,[]); } catch (error) { cleanupErrors.push(new Error('Restoration failed: '+error.message,{cause:error})); }
  }
  finishCleanup(primary,cleanupErrors,'Deployment completed, but cleanup failed',primary||cleanupErrors.length?saved:undefined);
  if(!rollback)pruneBackups(path.dirname(saved)); completed.push(e.name); console.log(e.name+': deployed');
 } }catch(error){if(completed.length)throw Error(error.message+'; completed before failure: '+completed.join(', '),{cause:error});throw error;}
}
if(process.argv[1]&&fs.realpathSync(process.argv[1])===fileURLToPath(import.meta.url)){try{main();}catch(error){console.error('Copy deployment failed: '+error.message);process.exitCode=1;}}
