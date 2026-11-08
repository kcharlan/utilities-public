import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const installer=await import('../scripts/deploy.mjs').catch(()=>({}));
function fixture(t){
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'office-picnic-deploy-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const repo=path.join(root,'repo'),webroot=path.join(root,'webroot'),backups=path.join(root,'backups');
  const source=path.join(repo,'web_games/office_picnic/dist');fs.mkdirSync(source,{recursive:true});
  fs.writeFileSync(path.join(source,'index.html'),'synthetic game');fs.writeFileSync(path.join(source,'main.js'),'synthetic module');
  execFileSync('git',['init','-q',repo]);execFileSync('git',['-C',repo,'add','.']);
  fs.writeFileSync(path.join(source,'private.txt'),'untracked fixture');
  return {repo,webroot,backups,source,target:path.join(webroot,'games/office_picnic')};
}
test('deployment installs only staged runtime bytes, verifies drift and preserves local files through update/rollback',async t=>{
  assert.equal(typeof installer.deploy,'function');const f=fixture(t);
  await installer.deploy({...f,dryRun:true});assert.equal(fs.existsSync(f.webroot),false);
  await installer.deploy(f);assert.equal(fs.readFileSync(path.join(f.target,'index.html'),'utf8'),'synthetic game');
  assert.equal(fs.existsSync(path.join(f.target,'private.txt')),false);
  fs.writeFileSync(path.join(f.target,'local.txt'),'local state');
  fs.writeFileSync(path.join(f.source,'index.html'),'updated fixture');execFileSync('git',['-C',f.repo,'add','.']);
  // Keep the intentionally private source outside the inventory.
  execFileSync('git',['-C',f.repo,'rm','--cached','web_games/office_picnic/dist/private.txt']);
  await assert.rejects(installer.deploy({...f,check:true}),/differs|missing/);
  const backup=await installer.deploy(f);assert.ok(backup);await installer.deploy({...f,check:true});
  fs.writeFileSync(path.join(f.source,'main.js'),'third release module');execFileSync('git',['-C',f.repo,'add','web_games/office_picnic/dist/main.js']);
  await installer.deploy(f);
  fs.writeFileSync(path.join(f.source,'index.html'),'unfinished source edit');
  const retained=fs.readdirSync(f.backups);
  await installer.deploy({...f,rollback:backup});
  assert.ok(retained.every(name=>fs.existsSync(path.join(f.backups,name))),'rollback preserves recovery history');
  assert.equal(fs.readFileSync(path.join(f.target,'index.html'),'utf8'),'synthetic game');
  assert.equal(fs.readFileSync(path.join(f.target,'main.js'),'utf8'),'synthetic module');
  assert.equal(fs.readFileSync(path.join(f.target,'local.txt'),'utf8'),'local state');
});
test('deployment refuses unstaged source, destination symlinks and repository overlap',async t=>{
  assert.equal(typeof installer.deploy,'function');const f=fixture(t);
  fs.writeFileSync(path.join(f.source,'main.js'),'unstaged edit');
  await assert.rejects(installer.deploy(f),/index|stage/i);assert.equal(fs.existsSync(f.webroot),false);
  execFileSync('git',['-C',f.repo,'add','web_games/office_picnic/dist/main.js']);
  await assert.rejects(installer.deploy({...f,webroot:f.repo}),/outside|overlap/i);
  fs.mkdirSync(path.dirname(f.target),{recursive:true});fs.symlinkSync(f.source,f.target);
  await assert.rejects(installer.deploy(f),/symlink|directory/i);
});
test('actual deployment CLI installs, checks and rolls back a synthetic runtime',t=>{
  const f=fixture(t),script=fileURLToPath(new URL('../scripts/deploy.mjs',import.meta.url));
  const cli=(...args)=>execFileSync(process.execPath,[script,'--repo',f.repo,'--webroot',f.webroot,'--backups',f.backups,...args],{encoding:'utf8'});
  assert.match(cli('--dry-run'),/2 runtime files/);cli();assert.match(cli('--check'),/matches/);
  fs.writeFileSync(path.join(f.source,'index.html'),'second CLI release');execFileSync('git',['-C',f.repo,'add','web_games/office_picnic/dist/index.html']);
  const output=cli(),backup=output.match(/Recovery backup: (.+)/)[1];
  execFileSync('git',['-C',f.repo,'rm','--cached','-r','web_games/office_picnic/dist']);
  fs.writeFileSync(path.join(f.target,'local.txt'),'preserved');cli('--rollback',backup);
  assert.equal(fs.readFileSync(path.join(f.target,'index.html'),'utf8'),'synthetic game');
  assert.equal(fs.readFileSync(path.join(f.target,'local.txt'),'utf8'),'preserved');
});
