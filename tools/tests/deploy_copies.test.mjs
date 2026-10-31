import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync,execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {hashInventory} from '../deployment_files.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
function fixture(t) {
 const base=fs.mkdtempSync(path.join(os.tmpdir(),'copy-deploy-test-')); t.after(()=>fs.rmSync(base,{recursive:true,force:true}));
 const repo=path.join(base,'repo'), home=path.join(base,'home'), scripts=path.join(home,'scripts'), local=path.join(home,'local');
 fs.mkdirSync(path.join(repo,'tools'),{recursive:true}); fs.mkdirSync(home);
 for (const n of ['deploy_copies.mjs','deployment_files.mjs']) fs.copyFileSync(path.join(root,'tools',n),path.join(repo,'tools',n));
 fs.mkdirSync(path.join(repo,'project')); fs.writeFileSync(path.join(repo,'project','file'),'new');
 fs.writeFileSync(path.join(repo,'tools','deployment_copies.json'),JSON.stringify({scripts:[],projects:[{name:'project'}]}));
 const git=(...a)=>execFileSync('git',['-C',repo,...a],{stdio:'pipe'});
 git('init','-b','main'); git('config','user.email','synthetic@example.invalid'); git('config','user.name','Synthetic'); git('add','.'); git('commit','-m','synthetic');
 const runEnv=(env,...a)=>spawnSync('node',[path.join(repo,'tools/deploy_copies.mjs'),'--repo',repo,'--scripts-dir',scripts,'--local-root',local,...a],{env:{...process.env,HOME:home,...env},encoding:'utf8'});
 const run=(...a)=>runEnv({},...a);
 return {base,repo,home,scripts,local,git,run,runEnv};
}
test('default deployment admits large tracked blobs and still rejects index mismatches',t=>{
 const f=fixture(t), file=path.join(f.repo,'project/large-synthetic.bin');
 const original=Buffer.alloc(2*1024*1024+200000,0x53);
 fs.writeFileSync(file,original); f.git('add','.'); f.git('commit','-m','add synthetic large blob');
 let r=f.run('--dry-run'); assert.equal(r.status,0,r.stderr); assert.equal(fs.existsSync(f.local),false);
 r=f.run(); assert.equal(r.status,0,r.stderr); assert.deepEqual(fs.readFileSync(path.join(f.local,'project/large-synthetic.bin')),original);
 const entry=()=>[{name:'project/large-synthetic.bin',mode:'100644'}];
 const changed=Buffer.alloc(original.length,0x54); fs.writeFileSync(file,changed);
 assert.throws(()=>hashInventory(f.repo,entry(),true),/working bytes differ from Git index/);
 f.git('add','project/large-synthetic.bin'); fs.writeFileSync(file,original);
 assert.throws(()=>hashInventory(f.repo,entry(),true),/working bytes differ from Git index/);
});
test('installs a tracked project and restores it through rollback',t=>{
 const f=fixture(t), target=path.join(f.local,'project/file');
 let r=f.run('--dry-run'); assert.equal(r.status,0,r.stderr); assert.equal(fs.existsSync(target),false);
 r=f.run(); assert.equal(r.status,0,r.stderr); assert.equal(fs.readFileSync(target,'utf8'),'new');
 r=f.run(); assert.equal(r.status,0,r.stderr); assert.match(r.stdout,/already matches source/);
 fs.writeFileSync(path.join(f.repo,'project/file'),'updated'); f.git('add','.'); f.git('commit','-m','update');
 r=f.run(); assert.equal(r.status,0,r.stderr); const backup=r.stdout.match(/Recovery backup: (.+)/)?.[1]; assert.ok(backup,r.stdout);
 r=f.run('--rollback',backup); assert.equal(r.status,0,r.stderr); assert.equal(fs.readFileSync(target,'utf8'),'new');
});
test('failed smoke restores old files and removes newly added files',t=>{
 const f=fixture(t); assert.equal(f.run().status,0);
 fs.writeFileSync(path.join(f.repo,'project/file'),'updated');
 fs.writeFileSync(path.join(f.repo,'project/run'),'#!/bin/sh\nexit 1\n',{mode:0o755});
 fs.writeFileSync(path.join(f.repo,'tools/deployment_copies.json'),JSON.stringify({scripts:[],projects:[{name:'project',entrypoint:'run',smoke:['--help']}]}));
 f.git('add','.'); f.git('commit','-m','failing smoke');
 fs.writeFileSync(path.join(f.local,'project','neighbor'),'local');
 const r=f.run(); assert.notEqual(r.status,0); assert.match(r.stderr,/Smoke check failed.*Recovery backup:/);
 assert.equal(fs.readFileSync(path.join(f.local,'project/file'),'utf8'),'new'); assert.equal(fs.existsSync(path.join(f.local,'project/run')),false); assert.equal(fs.readFileSync(path.join(f.local,'project/neighbor'),'utf8'),'local');
});
test('rejects altered backup payload and uncommitted source before writes',t=>{
 const f=fixture(t); let r=f.run(); assert.equal(r.status,0,r.stderr);
 fs.writeFileSync(path.join(f.repo,'project/file'),'update'); f.git('add','.'); f.git('commit','-m','update');
 r=f.run(); assert.equal(r.status,0,r.stderr); const backup=r.stdout.match(/Recovery backup: (.+)/)[1];
 fs.writeFileSync(path.join(backup,'payload/file'),'tampered'); r=f.run('--rollback',backup); assert.notEqual(r.status,0); assert.match(r.stderr,/hash mismatch/); assert.equal(fs.readFileSync(path.join(f.local,'project/file'),'utf8'),'update');
 fs.writeFileSync(path.join(f.repo,'project/file'),'dirty'); r=f.run(); assert.notEqual(r.status,0); assert.match(r.stderr,/Uncommitted/); assert.equal(fs.readFileSync(path.join(f.local,'project/file'),'utf8'),'update');
});
test('historical rollback and rollback of rollback admit files deleted from current revision',t=>{
 const f=fixture(t); assert.equal(f.run().status,0);
 fs.writeFileSync(path.join(f.repo,'project/file'),'second'); f.git('add','.'); f.git('commit','-m','second');
 let r=f.run(); assert.equal(r.status,0,r.stderr); const old=r.stdout.match(/Recovery backup: (.+)/)[1];
 f.git('rm','project/file'); fs.mkdirSync(path.join(f.repo,'project'),{recursive:true}); fs.writeFileSync(path.join(f.repo,'project/other'),'other'); f.git('add','.'); f.git('commit','-m','remove file');
 r=f.run('--rollback',old); assert.equal(r.status,0,r.stderr); assert.equal(fs.readFileSync(path.join(f.local,'project/file'),'utf8'),'new');
 const redo=r.stdout.match(/Recovery backup: (.+)/)[1]; r=f.run('--rollback',redo); assert.equal(r.status,0,r.stderr); assert.equal(fs.readFileSync(path.join(f.local,'project/file'),'utf8'),'second');
});
test('first installation records absence and preserves source mode; rollback removes it',t=>{
 const f=fixture(t); fs.chmodSync(path.join(f.repo,'project/file'),0o755); f.git('add','.'); f.git('commit','-m','mode');
 let r=f.run(); assert.equal(r.status,0,r.stderr); const backup=r.stdout.match(/Recovery backup: (.+)/)[1];
 const state=JSON.parse(fs.readFileSync(path.join(backup,'state.json'))); assert.equal(state.files[0].prior,null); assert.equal(fs.statSync(path.join(f.local,'project/file')).mode&0o777,0o755); assert.equal(fs.statSync(path.join(backup,'state.json')).mode&0o777,0o600);
 r=f.run('--rollback',backup); assert.equal(r.status,0,r.stderr); assert.equal(fs.existsSync(path.join(f.local,'project/file')),false);
});
test('retains two backups after forward update, and does not prune on rollback or unchanged run',t=>{
 const f=fixture(t); assert.equal(f.run().status,0); const ns=path.join(f.home,'.utilities-deploy-backups/project');
 for(const name of ['copy-old-a','copy-old-b']){const dir=path.join(ns,name);fs.mkdirSync(dir);fs.writeFileSync(path.join(dir,'marker'),'synthetic');fs.utimesSync(dir,new Date(0),new Date(0));}
 const before=fs.readdirSync(ns); assert.equal(f.run().status,0); assert.deepEqual(fs.readdirSync(ns),before);
 fs.writeFileSync(path.join(f.repo,'project/file'),'next');f.git('add','.');f.git('commit','-m','next'); const r=f.run();assert.equal(r.status,0,r.stderr);assert.equal(fs.readdirSync(ns).length,2); const backup=r.stdout.match(/Recovery backup: (.+)/)[1]; assert.equal(f.run('--rollback',backup).status,0);assert.equal(fs.readdirSync(ns).length,3);
});
test('rejects malformed backup, incompatible options, dirty inputs and linked destinations',t=>{
 const f=fixture(t); const bad=path.join(f.base,'bad');fs.mkdirSync(bad); fs.writeFileSync(path.join(bad,'state.json'),'{}');
 let r=f.run('--rollback',bad); assert.notEqual(r.status,0);assert.match(r.stderr,/Invalid backup state/);
 fs.unlinkSync(path.join(bad,'state.json')); r=f.run('--rollback',bad); assert.notEqual(r.status,0);assert.match(r.stderr,/Invalid backup state/);
 r=f.run('--only','missing');assert.notEqual(r.status,0);assert.match(r.stderr,/Unknown entry/);
 r=f.run('--only','project','--rollback',bad);assert.notEqual(r.status,0);assert.match(r.stderr,/Incompatible/);
 fs.mkdirSync(f.local);const outside=path.join(f.base,'outside');fs.mkdirSync(outside);fs.symlinkSync(outside,path.join(f.local,'project'));r=f.run();assert.notEqual(r.status,0);assert.match(r.stderr,/symlink/);assert.deepEqual(fs.readdirSync(outside),[]);
 fs.unlinkSync(path.join(f.local,'project'));fs.writeFileSync(path.join(f.repo,'tools/deployment_copies.json'),'{}');r=f.run();assert.notEqual(r.status,0);assert.match(r.stderr,/Uncommitted/);
});
test('script target is installed and backed up under its entry name',t=>{
 const f=fixture(t);fs.writeFileSync(path.join(f.repo,'tools/deployment_copies.json'),JSON.stringify({scripts:[{name:'wrapper',source:'project/file',target:'command'}],projects:[]}));f.git('add','.');f.git('commit','-m','script');
 let r=f.run();assert.equal(r.status,0,r.stderr);assert.equal(fs.readFileSync(path.join(f.scripts,'command'),'utf8'),'new');assert.match(r.stdout,/backups\/wrapper\/copy-/);
});
test('preactivation backup corruption is refused before changing installed files',t=>{
 const f=fixture(t);assert.equal(f.run().status,0);fs.writeFileSync(path.join(f.repo,'project/file'),'changed');f.git('add','.');f.git('commit','-m','changed');
 const hook=path.join(f.base,'hook.cjs');fs.writeFileSync(hook,`const fs=require('fs');const orig=fs.writeFileSync;fs.writeFileSync=function(p,data,...a){const r=orig.call(this,p,data,...a);if(String(p).includes('/payload/'))orig.call(this,p,'corrupted');return r;};`);
 const r=f.runEnv({NODE_OPTIONS:`--require=${hook}`});assert.notEqual(r.status,0);assert.match(r.stderr,/hash mismatch/);assert.equal(fs.readFileSync(path.join(f.local,'project/file'),'utf8'),'new');
});
test('publication and restoration failures report both errors and recovery path',t=>{
 const f=fixture(t);assert.equal(f.run().status,0);fs.writeFileSync(path.join(f.repo,'project/file'),'changed');f.git('add','.');f.git('commit','-m','changed');
 const hook=path.join(f.base,'hook.cjs');fs.writeFileSync(hook,`const fs=require('fs');const orig=fs.renameSync;fs.renameSync=function(a,b){if(String(b).endsWith('/project/file'))throw Error('synthetic publication failure');return orig.call(this,a,b);};`);
 const r=f.runEnv({NODE_OPTIONS:`--require=${hook}`});assert.notEqual(r.status,0);assert.match(r.stderr,/synthetic publication failure.*restoration failed: synthetic publication failure.*Recovery backup:/);assert.equal(fs.readFileSync(path.join(f.local,'project/file'),'utf8'),'new');
});
test('smoke removes inherited Python activation and prevents downloads',t=>{
 const f=fixture(t), fake=path.join(f.base,'fake-env');fs.mkdirSync(path.join(fake,'bin'),{recursive:true});fs.writeFileSync(path.join(fake,'pyvenv.cfg'),'synthetic');
 fs.writeFileSync(path.join(f.repo,'project/run'),`#!/bin/sh\n[ "$UV_PYTHON_DOWNLOADS" = never ] && [ -z "\${VIRTUAL_ENV:-}" ] && [ -z "\${PYTHONPATH:-}" ] && [ -z "\${UV_SYSTEM_PYTHON:-}" ] && [ -z "\${UV_PYTHON:-}" ] && [ -z "\${CONDA_PREFIX:-}" ] && [ -z "\${PYENV_VERSION:-}" ] && case ":$PATH:" in *"${fake}/bin"*) exit 1;; esac\n`,{mode:0o755});
 fs.writeFileSync(path.join(f.repo,'tools/deployment_copies.json'),JSON.stringify({scripts:[],projects:[{name:'project',entrypoint:'run',smoke:['--help']}]}));f.git('add','.');f.git('commit','-m','smoke');
 const r=f.runEnv({VIRTUAL_ENV:fake,CONDA_PREFIX:fake,PYENV_VERSION:'synthetic',UV_PYTHON:'/synthetic',PYTHONPATH:'/synthetic',UV_SYSTEM_PYTHON:'1',PATH:path.join(fake,'bin')+path.delimiter+process.env.PATH});assert.equal(r.status,0,r.stderr);
});
test('manifest retains the prior direct and project mappings',()=>{
 const m=JSON.parse(fs.readFileSync(path.join(root,'tools/deployment_copies.json')));
 assert.deepEqual(m.scripts.map(e=>`${e.source}|${e.target||e.name}`).sort(),[
 'abacus usage/de-abacus.py|de-abacus.py','div_conv/div_conv|div_conv','dloc/dloc|dloc','docker/docker-disk-compact/docker-disk-compact.zsh|docker-disk-compact.zsh','editdb/editdb|editdb','etf_montecarlo/etf_montecarlo|etf_montecarlo','expense_dock/expense_dock|expense_dock','harscope/harscope|harscope','jtree/jtree|jtree','launchmaster/launchmaster|launchmaster','media-dater/media-dater|media-dater','moneydance backup rotation/moneydance_rotate_backups.sh|moneydance_rotate_backups.sh','router-log-analyzer/router_log_analyze.py|router_log_analyze.py','routerview/routerview|routerview','trim_last/trim_last|trim_last','usage-monthly-csv/usage-monthly-csv|usage-monthly-csv','worktree-helper/worktree|worktree','apple-health-extract/run.sh|apple-health-extract'].sort());
 assert.deepEqual(m.projects.map(e=>e.name).sort(),['apple-health-extract','mem_snapshots','mls-tracker','tax2','transcription','vid-compiler','video-scenes'].sort());
});
test('refuses off-main, source symlink, malicious manifests and source checkout destinations',t=>{
 const f=fixture(t); f.git('checkout','-b','other');let r=f.run();assert.notEqual(r.status,0);assert.match(r.stderr,/require main/);f.git('checkout','main');
 fs.unlinkSync(path.join(f.repo,'project/file'));fs.symlinkSync('/synthetic-target',path.join(f.repo,'project/file'));f.git('add','.');f.git('commit','-m','link');r=f.run();assert.notEqual(r.status,0);assert.equal(fs.existsSync(f.local),false);
 f.git('rm','project/file');fs.writeFileSync(path.join(f.repo,'tools/deployment_copies.json'),JSON.stringify({scripts:[{name:'evil',source:'../escape'}],projects:[]}));f.git('add','.');f.git('commit','-m','invalid');r=f.run();assert.notEqual(r.status,0);assert.match(r.stderr,/Invalid manifest/);assert.equal(fs.existsSync(f.local),false);
 r=f.run('--local-root',f.repo);assert.notEqual(r.status,0);assert.match(r.stderr,/outside the repository/);
});
test('rejects duplicate and unadmitted backup paths and unavailable revisions',t=>{
 const f=fixture(t);let r=f.run();assert.equal(r.status,0);const backup=r.stdout.match(/Recovery backup: (.+)/)[1], meta=path.join(backup,'state.json'), original=JSON.parse(fs.readFileSync(meta));
 for(const edit of [s=>s.files.push({...s.files[0]}),s=>s.files[0].path='../escape',s=>s.revision='0'.repeat(40)]){
  const s=structuredClone(original);edit(s);fs.writeFileSync(meta,JSON.stringify(s));r=f.run('--rollback',backup);assert.notEqual(r.status,0);assert.match(r.stderr,/Invalid backup inventory|revision unavailable/);assert.equal(fs.readFileSync(path.join(f.local,'project/file'),'utf8'),'new');
 }
});
test('failed first-install smoke removes new files',t=>{
 const f=fixture(t);fs.writeFileSync(path.join(f.repo,'project/run'),'#!/bin/sh\nexit 1\n',{mode:0o755});fs.writeFileSync(path.join(f.repo,'tools/deployment_copies.json'),JSON.stringify({scripts:[],projects:[{name:'project',entrypoint:'run',smoke:['--help']}]}));f.git('add','.');f.git('commit','-m','smoke fails');const r=f.run();assert.notEqual(r.status,0);assert.match(r.stderr,/Recovery backup/);assert.equal(fs.existsSync(path.join(f.local,'project/file')),false);assert.equal(fs.existsSync(path.join(f.local,'project/run')),false);
});
test('linked backup ancestors are refused without changing their targets',t=>{
 const f=fixture(t), outside=path.join(f.base,'outside');fs.mkdirSync(outside);fs.symlinkSync(outside,path.join(f.home,'.utilities-deploy-backups'));
 const r=f.run();assert.notEqual(r.status,0);assert.match(r.stderr,/symlink/);assert.deepEqual(fs.readdirSync(outside),[]);assert.equal(fs.existsSync(f.local),false);
});
test('only selects a named entry and reports partial completion on later failure',t=>{
 const f=fixture(t);fs.mkdirSync(path.join(f.repo,'second'));fs.writeFileSync(path.join(f.repo,'second/run'),'#!/bin/sh\nexit 1\n',{mode:0o755});fs.writeFileSync(path.join(f.repo,'tools/deployment_copies.json'),JSON.stringify({scripts:[],projects:[{name:'project'},{name:'second',entrypoint:'run',smoke:['--help']}]}));f.git('add','.');f.git('commit','-m','second');
 let r=f.run('--only','project');assert.equal(r.status,0,r.stderr);assert.equal(fs.existsSync(path.join(f.local,'second')),false);
 fs.writeFileSync(path.join(f.repo,'project/file'),'newer');f.git('add','.');f.git('commit','-m','update');r=f.run();assert.notEqual(r.status,0);assert.match(r.stderr,/completed before failure: project/);assert.equal(fs.readFileSync(path.join(f.local,'project/file'),'utf8'),'newer');assert.equal(fs.existsSync(path.join(f.local,'second/run')),false);
});
test('rollback publication failure preserves current state and reports recovery',t=>{
 const f=fixture(t);assert.equal(f.run().status,0);fs.writeFileSync(path.join(f.repo,'project/file'),'next');f.git('add','.');f.git('commit','-m','next');let r=f.run();const backup=r.stdout.match(/Recovery backup: (.+)/)[1];
 const hook=path.join(f.base,'once.cjs');fs.writeFileSync(hook,`const fs=require('fs');const orig=fs.renameSync;let n=0;fs.renameSync=function(a,b){if(String(b).endsWith('/project/file') && n++===0)throw Error('synthetic rollback failure');return orig.call(this,a,b);};`);
 r=f.runEnv({NODE_OPTIONS:`--require=${hook}`},'--rollback',backup);assert.notEqual(r.status,0);assert.match(r.stderr,/synthetic rollback failure.*Recovery backup:/);assert.equal(fs.readFileSync(path.join(f.local,'project/file'),'utf8'),'next');
});
test('refuses untracked sources, modified deployer and staged input before writes',t=>{
 const f=fixture(t);fs.writeFileSync(path.join(f.repo,'tools/deployment_copies.json'),JSON.stringify({scripts:[{name:'new',source:'untracked'}],projects:[]}));f.git('add','.');f.git('commit','-m','untracked source');fs.writeFileSync(path.join(f.repo,'untracked'),'synthetic');let r=f.run();assert.notEqual(r.status,0);assert.match(r.stderr,/not tracked/);assert.equal(fs.existsSync(f.scripts),false);
 f.git('add','untracked');f.git('commit','-m','track source');fs.appendFileSync(path.join(f.repo,'tools/deploy_copies.mjs'),'\n// synthetic edit\n');r=f.run();assert.notEqual(r.status,0);assert.match(r.stderr,/Uncommitted/);f.git('checkout','--','tools/deploy_copies.mjs');
 fs.writeFileSync(path.join(f.repo,'untracked'),'staged change');f.git('add','untracked');r=f.run();assert.notEqual(r.status,0);assert.match(r.stderr,/Uncommitted/);assert.equal(fs.existsSync(f.scripts),false);
});
test('refuses deployment input mode drift even when Git ignores mode changes',t=>{
 const f=fixture(t);f.git('config','core.filemode','false');fs.chmodSync(path.join(f.repo,'tools/deploy_copies.mjs'),0o755);const r=f.run();assert.notEqual(r.status,0);assert.match(r.stderr,/mode differs/);assert.equal(fs.existsSync(f.local),false);
});
test('rejects invalid manifest fields, unsafe paths and invalid smoke arguments before writes',t=>{
 const f=fixture(t);const manifests=[
 {scripts:[{name:'../bad',source:'project/file'}],projects:[]},
 {scripts:[{name:' ',source:'project/file'}],projects:[]},
 {scripts:[{name:'ok',source:'/absolute'}],projects:[]},
 {scripts:[{name:'ok',source:'project/file',target:null}],projects:[]},
 {scripts:[{name:'ok',source:'project/file',smoke:['']}],projects:[]},
 {scripts:[{name:'ok',source:'project/file',extra:true}],projects:[]},
 {scripts:[{name:'ok',source:'project/file',kind:'project'}],projects:[]},
 {scripts:[],projects:[{name:'project',entrypoint:'../run'}]},
 {scripts:[{name:'duplicate',source:'project/file'},{name:'duplicate',source:'project/file'}],projects:[]}
 ];
 for(const m of manifests){fs.writeFileSync(path.join(f.repo,'tools/deployment_copies.json'),JSON.stringify(m));f.git('add','.');f.git('commit','-m','invalid');const r=f.run();assert.notEqual(r.status,0);assert.match(r.stderr,/Invalid manifest/);assert.equal(fs.existsSync(f.local),false);assert.equal(fs.existsSync(f.scripts),false);}
});
test('refuses submodule inventory and staged deployment helper changes',t=>{
 const f=fixture(t);const oid=execFileSync('git',['-C',f.repo,'rev-parse','HEAD'],{encoding:'utf8'}).trim();f.git('update-index','--add','--cacheinfo',`160000,${oid},project/nested`);f.git('commit','-m','synthetic gitlink');let r=f.run();assert.notEqual(r.status,0);assert.match(r.stderr,/regular stage-zero/);assert.equal(fs.existsSync(f.local),false);
 f.git('rm','--cached','project/nested');f.git('commit','-m','remove gitlink');fs.appendFileSync(path.join(f.repo,'tools/deployment_files.mjs'),'\n// synthetic edit\n');f.git('add','tools/deployment_files.mjs');r=f.run();assert.notEqual(r.status,0);assert.match(r.stderr,/Uncommitted/);assert.equal(fs.existsSync(f.local),false);
});
test('admits the Darwin /tmp system alias for a destination',t=>{
 if(process.platform!=='darwin'){t.skip('Darwin system alias');return;} const f=fixture(t);const directory=fs.mkdtempSync('/tmp/copy-alias-test-');t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));const r=f.run('--local-root',directory);assert.equal(r.status,0,r.stderr);assert.equal(fs.readFileSync(path.join(directory,'project/file'),'utf8'),'new');
});
test('validates all selected destination roots before the first publication',t=>{
 const f=fixture(t);fs.writeFileSync(path.join(f.repo,'tools/deployment_copies.json'),JSON.stringify({scripts:[{name:'first',source:'project/file'},{name:'second',source:'project/file'}],projects:[]}));f.git('add','.');f.git('commit','-m','two scripts');fs.mkdirSync(f.scripts);const outside=path.join(f.base,'outside');fs.writeFileSync(outside,'untouched');fs.symlinkSync(outside,path.join(f.scripts,'second'));
 const r=f.run();assert.notEqual(r.status,0);assert.equal(fs.existsSync(path.join(f.scripts,'first')),false);assert.equal(fs.readFileSync(outside,'utf8'),'untouched');
});
test('dry run creates no backup and update saves only changed files',t=>{
 const f=fixture(t);fs.writeFileSync(path.join(f.repo,'project/unchanged'),'same');f.git('add','.');f.git('commit','-m','second source');
 let r=f.run('--dry-run');assert.equal(r.status,0,r.stderr);assert.equal(fs.existsSync(path.join(f.home,'.utilities-deploy-backups')),false);assert.equal(f.run().status,0);
 fs.writeFileSync(path.join(f.local,'project/local-only'),'local');fs.writeFileSync(path.join(f.repo,'project/file'),'changed');f.git('add','.');f.git('commit','-m','changed file');r=f.run();assert.equal(r.status,0,r.stderr);
 const backup=r.stdout.match(/Recovery backup: (.+)/)[1],state=JSON.parse(fs.readFileSync(path.join(backup,'state.json')));assert.deepEqual(state.files.map(x=>x.path),['file']);assert.equal(fs.readFileSync(path.join(backup,'payload/file'),'utf8'),'new');assert.equal(fs.statSync(path.join(backup,'payload/file')).mode&0o777,0o600);assert.equal(fs.readFileSync(path.join(f.local,'project/local-only'),'utf8'),'local');
});
test('script rollback remains bound to target after manifest source moves',t=>{
 const f=fixture(t);const manifest=path.join(f.repo,'tools/deployment_copies.json');fs.writeFileSync(manifest,JSON.stringify({scripts:[{name:'wrapper',source:'project/file',target:'command'}],projects:[]}));f.git('add','.');f.git('commit','-m','script');assert.equal(f.run().status,0);
 fs.writeFileSync(path.join(f.repo,'project/file'),'second');f.git('add','.');f.git('commit','-m','second');const r=f.run(), backup=r.stdout.match(/Recovery backup: (.+)/)[1];assert.equal(r.status,0,r.stderr);
 f.git('mv','project/file','project/renamed');fs.writeFileSync(manifest,JSON.stringify({scripts:[{name:'wrapper',source:'project/renamed',target:'command'}],projects:[]}));f.git('add','.');f.git('commit','-m','move source');const rollback=f.run('--rollback',backup);assert.equal(rollback.status,0,rollback.stderr);assert.equal(fs.readFileSync(path.join(f.scripts,'command'),'utf8'),'new');
});
test('cleanup failure restores activation and reports retained backup',t=>{
 const f=fixture(t),hook=path.join(f.base,'cleanup.cjs');fs.writeFileSync(hook,`const fs=require('fs');const orig=fs.rmdirSync;fs.rmdirSync=function(p,...args){if(String(p).endsWith('/local/project')){const e=Error('synthetic cleanup failure');e.code='EACCES';throw e;}return orig.call(this,p,...args);};`);
 const r=f.runEnv({NODE_OPTIONS:`--require=${hook}`});assert.notEqual(r.status,0);assert.match(r.stderr,/Cleanup failed.*synthetic cleanup failure.*Recovery backup:/);assert.equal(fs.existsSync(path.join(f.local,'project/file')),false);
});
