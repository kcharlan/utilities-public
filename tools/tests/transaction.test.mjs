import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {runTransaction} from '../transaction.mjs';

test('explicit recovery runs before admission', async () => {
  const result = await runTransaction({name: 'synthetic', recovery: () => 'restored', admit: () => { throw Error('dirty source'); }});
  assert.equal(result, 'restored');
});

test('failed verification restores the prior installation and removes scratch', async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'synthetic-transaction-'));
  t.after(() => fs.rmSync(root, {recursive:true, force:true}));
  const target = path.join(root, 'installed'), scratch = path.join(root, 'scratch');
  fs.writeFileSync(target, 'previous');
  await assert.rejects(runTransaction({name:'synthetic', admit:()=>{}, isCurrent:()=>false,
    build:()=>{fs.mkdirSync(scratch); return {value:'new', cleanup:()=>fs.rmSync(scratch, {recursive:true})};},
    install:value=>{fs.writeFileSync(target,value); return ()=>fs.writeFileSync(target,'previous');},
    verify:()=>{throw Error('verification failed');}}), /verification failed/);
  assert.equal(fs.readFileSync(target,'utf8'), 'previous');
  assert.equal(fs.existsSync(scratch), false);
});
test('a failed installation restores changes made before it threw', async t => {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'synthetic-transaction-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const target=path.join(root,'installed'); fs.writeFileSync(target,'previous');
  await assert.rejects(runTransaction({name:'synthetic',admit:()=>{},isCurrent:()=>false,
    build:()=>({value:'new'}), install:(value,saveRecovery)=>{saveRecovery(()=>fs.writeFileSync(target,'previous')); fs.writeFileSync(target,value); throw Error('install failed');},verify:()=>{}}),/install failed/);
  assert.equal(fs.readFileSync(target,'utf8'),'previous');
});
test('interrupted build cleans registered scratch before returning the error', async t => {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'synthetic-transaction-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const scratch=path.join(root,'scratch');
  await assert.rejects(runTransaction({name:'synthetic',admit:()=>{},isCurrent:()=>false,
    build:register=>{fs.mkdirSync(scratch);register(()=>fs.rmSync(scratch,{recursive:true}));throw Error('interrupted build');},
    install:()=>{throw Error('unexpected install');},verify:()=>{}}),/interrupted build/);
  assert.equal(fs.existsSync(scratch),false);
});
test('recovery failure reports both the original and restoration errors', async () => {
  await assert.rejects(runTransaction({name:'synthetic',admit:()=>{},isCurrent:()=>false,
    build:()=>({value:'synthetic'}),install:(_value,register)=>{register(()=>{throw Error('restore failed');});throw Error('install failed');},verify:()=>{}}),/install failed; restoration failed: restore failed/);
});
test('SIGTERM during a build cleans scratch and does not install', async t => {
  const {spawn}=await import('node:child_process');
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'synthetic-transaction-signal-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const scratch=path.join(root,'scratch'), installed=path.join(root,'installed');
  const moduleUrl=new URL('../transaction.mjs',import.meta.url).href;
  const code=`import {runTransaction} from ${JSON.stringify(moduleUrl)}; import fs from 'node:fs'; import {spawnSync} from 'node:child_process';
    try {await runTransaction({name:'synthetic',admit:()=>{},isCurrent:()=>false,build:register=>{fs.mkdirSync(${JSON.stringify(scratch)});register(()=>fs.rmSync(${JSON.stringify(scratch)},{recursive:true}));console.log('ready');spawnSync('sleep',['1']);return {value:'new'};},install:()=>fs.writeFileSync(${JSON.stringify(installed)},'new'),verify:()=>{}});} catch {process.exitCode=1;}`;
  const child=spawn(process.execPath,['--input-type=module','-e',code],{stdio:['ignore','pipe','pipe']});
  child.stdout.once('data',()=>child.kill('SIGTERM'));
  const [codeOut,signal]=await new Promise(resolve=>child.once('exit',(...args)=>resolve(args)));
  assert.ok(codeOut!==0||signal); assert.equal(fs.existsSync(installed),false); assert.equal(fs.existsSync(scratch),false);
});
test('failed backup publication restores the displaced app', async t => {
  const {replaceAppFromBackup}=await import('../deploy_brew_version.mjs');
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'synthetic-app-restore-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const source=path.join(root,'backup'),target=path.join(root,'installed');
  fs.mkdirSync(source);fs.writeFileSync(path.join(source,'file'),'backup');
  fs.mkdirSync(target);fs.writeFileSync(path.join(target,'file'),'previous');
  const rename=fs.renameSync;let once=false;
  try {fs.renameSync=(from,to)=>{rename(from,to);if(!once&&to===target){once=true;throw Error('synthetic after publication');}};
    assert.throws(()=>replaceAppFromBackup(source,target,root,'backup path'),/synthetic after publication/);
  } finally {fs.renameSync=rename;}
  assert.equal(fs.readFileSync(path.join(target,'file'),'utf8'),'previous');
});
