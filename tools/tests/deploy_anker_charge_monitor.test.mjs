import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync,execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {buildInput,sourceInventory} from '../deploy_anker_charge_monitor.mjs';
import {appTreeHash} from '../deploy_brew_version.mjs';
import {fakeDarwinTemp,releaseTempMakefile,assertReleaseTempHygiene} from './release-temp-fixture.mjs';
const script=fileURLToPath(new URL('../deploy_anker_charge_monitor.mjs',import.meta.url));
const repoRoot=fileURLToPath(new URL('../../',import.meta.url));
const plist=fs.readFileSync(path.join(repoRoot,'anker_charge_monitor/Resources/Info.plist'));
const fingerprint='A'.repeat(40);
function fixture(t) {
  const base=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'synthetic-anker-deploy-')));
  t.after(()=>fs.rmSync(base,{recursive:true,force:true}));
  const repo=path.join(base,'invented repo'),home=path.join(base,'invented home'),project=path.join(repo,'anker_charge_monitor'),apps=path.join(home,'apps'),scripts=path.join(home,'Library/Scripts'),bin=path.join(base,'bin');
  for(const p of [project,apps,scripts,bin])fs.mkdirSync(p,{recursive:true});
  const darwin=fakeDarwinTemp(base,bin);
  const write=(name,bytes,mode=0o644)=>{const file=path.join(project,name);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,bytes,{mode});fs.chmodSync(file,mode);};
  fs.mkdirSync(path.join(repo,'tools'));
  for(const name of ['deploy_anker_charge_monitor.mjs','deployment_files.mjs','deploy_brew_version.mjs'])fs.copyFileSync(path.join(repoRoot,'tools',name),path.join(repo,'tools',name));
  for(const name of ['install.sh','resolve_signing_identity.sh'])write('tools/'+name,fs.readFileSync(path.join(repoRoot,'anker_charge_monitor/tools',name)),0o755);
  write('Package.swift','// conspicuously synthetic package\n');write('Resources/Info.plist',plist);
  write('Makefile',`release:\n\tmkdir -p 'build/release/Anker Charge Monitor.app/Contents/MacOS'\n\tclang -mmacosx-version-min=27.0 Sources/main.c -o 'build/release/Anker Charge Monitor.app/Contents/MacOS/PrimeMonitor'\n\tcp Resources/Info.plist 'build/release/Anker Charge Monitor.app/Contents/Info.plist'\n`);
  const env={...process.env,HOME:home,TMPDIR:base,PATH:bin+':'+process.env.PATH,
    GIT_CONFIG_COUNT:'2',GIT_CONFIG_KEY_0:'maintenance.auto',GIT_CONFIG_VALUE_0:'false',GIT_CONFIG_KEY_1:'gc.auto',GIT_CONFIG_VALUE_1:'0'};
  const git=(...args)=>execFileSync('git',['-C',repo,...args],{stdio:'pipe',env});
  git('init','-q');git('config','user.name','Synthetic Test');git('config','user.email','synthetic@example.invalid');
  const release=label=>{write('Sources/main.c',`#include <stdio.h>\nint main(void){puts("synthetic ${label} must never execute");return 91;}\n`);git('add','.');git('commit','-qm','Synthetic '+label);};
  release('first');
  fs.writeFileSync(path.join(bin,'security'),`#!/bin/bash\n[ "\${SYNTHETIC_MISSING:-0}" = 0 ] || exit 0\necho ' Matching identities'\necho ' 1) ${fingerprint} "CodexBar Local"'\nif [ "\${SYNTHETIC_AMBIGUOUS:-0}" = 1 ]; then echo ' 2) ${'B'.repeat(40)} "CodexBar Local"'; fi\n`,{mode:0o755});
  fs.writeFileSync(path.join(bin,'codesign'),`#!/bin/bash\n[ "$#" = 5 ] && [ "$1" = --verify ] && [ "$2" = --strict ] && [ "$3" = -R ] && [ "$4" = '=identifier "local.utilities.prime-monitor" and certificate leaf = H"${fingerprint}"' ] || exit 94\n[ ! -e "\${!#}/synthetic-reject" ] || exit 95\n`,{mode:0o755});
  fs.writeFileSync(path.join(bin,'pgrep'),'#!/bin/sh\nexit 1\n',{mode:0o755});
  const run=(...args)=>spawnSync(process.execPath,[script,'--repo',repo,'--apps-dir',apps,'--scripts-dir',scripts,...args],{env,encoding:'utf8'});
  return {base,repo,home,project,apps,scripts,bin,darwin,write,git,release,env,run,app:path.join(apps,'Anker Charge Monitor.app'),receipt:path.join(scripts,'.anker-charge-monitor-native.json')};
}
function ok(result){assert.equal(result.status,0,result.stdout+result.stderr);return result;}
const backup=result=>/rollback backup: (.+)/.exec(result.stdout)[1];
function state(f){return [fs.existsSync(f.app)?appTreeHash(f.app):null,fs.existsSync(f.receipt)?fs.readFileSync(f.receipt,'utf8'):null];}
function tree(dir){return fs.readdirSync(dir,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name)).map(e=>[e.name,fs.lstatSync(path.join(dir,e.name)).mode,e.isDirectory()?tree(path.join(dir,e.name)):fs.readFileSync(path.join(dir,e.name)).toString('base64')]);}

test('fixture suppresses inherited aggressive Git maintenance while retaining mutation checks',t=>{
  const scratch=fs.mkdtempSync(path.join(os.tmpdir(),'synthetic-git-maintenance-'));t.after(()=>fs.rmSync(scratch,{recursive:true,force:true}));
  const config=path.join(scratch,'gitconfig'),trace=path.join(scratch,'trace');
  fs.writeFileSync(config,'[maintenance]\n auto = true\n autoDetach = false\n[maintenance "loose-objects"]\n enabled = true\n auto = 1\n');
  const previous={GIT_CONFIG_GLOBAL:process.env.GIT_CONFIG_GLOBAL,GIT_TRACE2_EVENT:process.env.GIT_TRACE2_EVENT};
  try {
    process.env.GIT_CONFIG_GLOBAL=config;process.env.GIT_TRACE2_EVENT=trace;
    const f=fixture(t);f.release('maintenance-probe');f.env.SYNTHETIC_MISSING='1';
    const before=tree(f.base),result=f.run();assert.equal(result.status,1);assert.match(result.stderr,/Signing identity missing or ambiguous/);assert.deepEqual(tree(f.base),before);
    const events=fs.readFileSync(trace,'utf8').trim().split('\n').map(line=>JSON.parse(line));
    assert.equal(events.some(e=>e.event==='region_enter'&&e.category==='maintenance'&&e.label==='loose-objects'),false,'inherited auto maintenance ran');
  } finally {
    for(const [key,value] of Object.entries(previous))if(value===undefined)delete process.env[key];else process.env[key]=value;
  }
});

test('app source inventory includes maintained installer/signing and root dependencies',()=>{
  for(const name of ['Package.swift','Makefile','Sources/a.swift','Tests/a.sh','Resources/Info.plist','tools/install.sh','tools/resolve_signing_identity.sh']) assert.equal(buildInput('anker_charge_monitor/'+name),true,name);
  for(const name of ['tools/deployment_files.mjs','tools/deploy_brew_version.mjs','tools/deploy_anker_charge_monitor.mjs']) assert.equal(buildInput(name),true,name);
  for(const name of ['README.md','.build/a','build/release/a']) assert.equal(buildInput('anker_charge_monitor/'+name),false,name);
});

test('first install, update, current, rebuild and independent rollback preserve receipts and held readers',t=>{
  const f=fixture(t);const empty=backup(ok(f.run()));const first=state(f);
  const r=JSON.parse(first[1]);assert.equal(r.sourceHash,sourceInventory(f.repo).sourceHash);assert.equal(r.appTreeHash,first[0]);assert.equal(r.signingIdentity,fingerprint);assert.equal(r.version,'0.4.1');assert.equal(fs.statSync(f.receipt).mode&0o7777,0o600);
  ok(f.run('--audit'));const before=tree(f.home);assert.match(ok(f.run()).stdout,/already current/);assert.deepEqual(tree(f.home),before);
  const exe=path.join(f.app,'Contents/MacOS/PrimeMonitor'),reader=fs.openSync(exe,'r'),old=fs.readFileSync(reader);fs.closeSync(reader);
  const held=fs.openSync(exe,'r');f.release('second');const saved=backup(ok(f.run()));assert.notDeepEqual(state(f),first);assert.deepEqual(fs.readFileSync(held),old);fs.closeSync(held);
  const second=state(f);ok(f.run('--rollback',saved));assert.deepEqual(state(f),first);assert.notDeepEqual(state(f),second);
  ok(f.run('--rollback',empty));assert.deepEqual(state(f),[null,null]);
  ok(f.run());assert.match(ok(f.run('--rebuild')).stdout,/rollback backup:/);
  assert.equal(fs.existsSync(path.join(f.scripts,'PrimeMonitor')),false);
});

for(const fail of [false,true]) test(`a ${fail?'failed':'successful'} release build leaves no temporary entries in TMPDIR or the Darwin user temp dir`,t=>{
  const f=fixture(t);
  assertReleaseTempHygiene({...f,run:fail=>{f.write('Makefile',releaseTempMakefile(fs.readFileSync(path.join(f.project,'Makefile'),'utf8'),fail));f.git('add','.');return f.run();}},'anker-charge-build-',fail);
});

test('dry run and audit do not compile, query identities or change any source/deployment state',t=>{
  const f=fixture(t);ok(f.run());
  for(const name of ['security','make','codesign'])fs.writeFileSync(path.join(f.bin,name),'#!/bin/sh\necho synthetic forbidden mutation >&2\nexit 99\n',{mode:0o755});
  const before=tree(f.base);ok(f.run('--dry-run'));ok(f.run('--audit'));assert.deepEqual(tree(f.base),before);
});

test('source and app/receipt byte and mode drift fail audit',t=>{
  const f=fixture(t);ok(f.run());
  for(const file of [path.join(f.project,'Sources/main.c'),path.join(f.repo,'tools/deployment_files.mjs'),path.join(f.app,'Contents/MacOS/PrimeMonitor'),f.receipt]){
    const bytes=fs.readFileSync(file),mode=fs.statSync(file).mode&0o7777;
    fs.appendFileSync(file,'synthetic drift');assert.equal(f.run('--audit').status,1,file);fs.writeFileSync(file,bytes);
    fs.chmodSync(file,0o600);if(mode!==0o600)assert.equal(f.run('--audit').status,1,file);fs.chmodSync(file,mode);ok(f.run('--audit'));
  }
  fs.chmodSync(f.app,0o700);assert.equal(f.run('--audit').status,1);
});

for(const kind of ['missing','ambiguous'])test(`${kind} signing identity fails before compile or deployment mutation`,t=>{
  const f=fixture(t);f.env['SYNTHETIC_'+kind.toUpperCase()]=1;const before=tree(f.base);const r=f.run();assert.equal(r.status,1);assert.match(r.stderr,/Signing identity missing or ambiguous/);assert.deepEqual(tree(f.base),before);
});

test('rejects wrong new version, runtime, name, identity and signature before activation',t=>{
  const f=fixture(t);ok(f.run());const before=state(f);
  for(const [key,value] of [['CFBundleShortVersionString','0.0.1'],['LSMinimumSystemVersion','14.0'],['CFBundleName','Synthetic Wrong Name'],['CFBundleIdentifier','synthetic.wrong']]){
    const make=fs.readFileSync(path.join(f.project,'Makefile'),'utf8');
    f.write('Makefile',make+`\t/usr/libexec/PlistBuddy -c 'Set :${key} ${value}' 'build/release/Anker Charge Monitor.app/Contents/Info.plist'\n`);f.git('add','.');
    assert.equal(f.run('--rebuild').status,1,key);assert.deepEqual(state(f),before);f.write('Makefile',make);f.git('add','.');
  }
  fs.writeFileSync(path.join(f.app,'synthetic-reject'),'synthetic');const bad=state(f);assert.equal(f.run('--rebuild').status,1);assert.deepEqual(state(f),bad);
});

test('missing app rebuilds; rollback and updates preserve runtime directories',t=>{
  const f=fixture(t),runtime=path.join(f.home,'Library/Application Support/Prime Monitor');fs.mkdirSync(runtime,{recursive:true});fs.writeFileSync(path.join(runtime,'synthetic-state'),'synthetic keep');const before=tree(runtime);
  ok(f.run());fs.rmSync(f.app,{recursive:true});ok(f.run());ok(f.run('--audit'));assert.deepEqual(tree(runtime),before);
});

test('untracked, missing, symlink ancestors and staged deletion cannot supply build inputs',t=>{
  for(const mode of ['missing','link','deletion','untracked']){
    const f=fixture(t),source=path.join(f.project,'Sources');
    if(mode==='missing')fs.unlinkSync(path.join(source,'main.c'));
    if(mode==='link'){fs.renameSync(source,source+'-saved');fs.symlinkSync(source+'-saved',source);}
    if(mode==='deletion')f.git('rm','--cached','anker_charge_monitor/Sources/main.c');
    if(mode==='untracked')fs.appendFileSync(path.join(source,'main.c'),'// unstaged');
    const result=f.run();assert.equal(result.status,1,mode+result.stdout+result.stderr);
  }
});

for(const first of [false,true])test(`receipt publication failure restores ${first?'absent':'prior'} app and receipt`,t=>{
  const f=fixture(t);if(!first)ok(f.run());const before=state(f);f.release('receipt-failure');
  const hook=path.join(f.base,'synthetic-hook.cjs');fs.writeFileSync(hook,`const fs=require('node:fs');const rename=fs.renameSync;let failed=false;fs.renameSync=(a,b)=>{const r=rename(a,b);if(!failed&&b===${JSON.stringify(f.receipt)}){failed=true;throw Error('synthetic receipt failure');}return r;};`);f.env.NODE_OPTIONS='--require='+JSON.stringify(hook);
  const r=f.run();assert.equal(r.status,1);assert.match(r.stderr,/synthetic receipt failure/);assert.deepEqual(state(f),before);
});

test('failed activated signature restores prior bundle and receipt; legacy upgrades permit old versions',t=>{
  const f=fixture(t);ok(f.run());const before=state(f);f.release('activation-failure');
  const mv=path.join(f.bin,'mv');fs.writeFileSync(mv,`#!/bin/bash\n/bin/mv "$@" || exit\nif [[ "$1" = *'.prime-monitor-stage-'*'/Anker Charge Monitor.app' && "\${!#}" = ${JSON.stringify(f.app)} && -e "$SYNTHETIC_FAIL_ONCE" ]]; then rm "$SYNTHETIC_FAIL_ONCE"; touch "\${!#}/synthetic-reject"; fi\n`,{mode:0o755});
  f.env.SYNTHETIC_FAIL_ONCE=path.join(f.base,'fail-once');fs.writeFileSync(f.env.SYNTHETIC_FAIL_ONCE,'synthetic');assert.equal(f.run().status,1);assert.deepEqual(state(f),before);
  fs.renameSync(f.app,path.join(f.apps,'Prime Monitor.app'));execFileSync('/usr/libexec/PlistBuddy',['-c','Set :CFBundleShortVersionString 0.0.1',path.join(f.apps,'Prime Monitor.app/Contents/Info.plist')]);
  ok(f.run());assert.equal(fs.existsSync(path.join(f.apps,'Prime Monitor.app')),false);ok(f.run('--audit'));
});

test('cleanup failure restores prior deployment and retains verified backups',t=>{
  const f=fixture(t);ok(f.run());const before=state(f);f.release('cleanup-failure');const hook=path.join(f.base,'synthetic-cleanup.cjs');
  const old=path.join(f.home,'.utilities-deploy-backups','anker-charge-monitor','copy-old');fs.mkdirSync(old);fs.writeFileSync(path.join(old,'payload'),'invented');fs.utimesSync(old,1,1);
  fs.writeFileSync(hook,`const fs=require('node:fs'),path=require('node:path');const rm=fs.rmSync;let failed=false;fs.rmSync=(p,...args)=>{if(!failed&&path.basename(p).startsWith('anker-charge-build-')){failed=true;throw Error('synthetic cleanup failure');}return rm(p,...args);};`);f.env.NODE_OPTIONS='--require='+JSON.stringify(hook);
  const r=f.run();assert.equal(r.status,1);assert.match(r.stderr,/cleanup failure/);assert.deepEqual(state(f),before);const saved=/Recovery backup: (.+)/.exec(r.stdout)[1];assert.equal(appTreeHash(path.join(saved,'Anker Charge Monitor.app')),before[0]);
  assert.equal(fs.readFileSync(path.join(old,'payload'),'utf8'),'invented');
});

test('rollback receipt failure restores displaced release and retained backup is independent',t=>{
  const f=fixture(t);ok(f.run());f.release('second');const saved=backup(ok(f.run())),before=state(f),savedHash=appTreeHash(path.join(saved,'Anker Charge Monitor.app'));
  const hook=path.join(f.base,'synthetic-rollback.cjs');fs.writeFileSync(hook,`const fs=require('node:fs');const rename=fs.renameSync;let once=false;fs.renameSync=(a,b)=>{const r=rename(a,b);if(!once&&b===${JSON.stringify(f.receipt)}){once=true;throw Error('synthetic rollback receipt failure');}return r;};`);f.env.NODE_OPTIONS='--require='+JSON.stringify(hook);
  const r=f.run('--rollback',saved);assert.equal(r.status,1);assert.match(r.stderr,/synthetic rollback receipt failure/);assert.deepEqual(state(f),before);assert.equal(appTreeHash(path.join(saved,'Anker Charge Monitor.app')),savedHash);
  delete f.env.NODE_OPTIONS;fs.appendFileSync(path.join(saved,'Anker Charge Monitor.app/Contents/MacOS/PrimeMonitor'),'synthetic corrupt saved bytes');const result=f.run('--rollback',saved);assert.equal(result.status,1);assert.match(result.stderr,/Backup app hash mismatch/);assert.deepEqual(state(f),before);
});

test('rejects executable runtime drift even when plist claims the current runtime',t=>{
  const f=fixture(t),make=fs.readFileSync(path.join(f.project,'Makefile'),'utf8');f.write('Makefile',make.replace('-mmacosx-version-min=27.0','-mmacosx-version-min=14.0'));f.git('add','.');const r=f.run();assert.equal(r.status,1);assert.match(r.stderr,/minimum runtime/);assert.deepEqual(state(f),[null,null]);
});

test('failed activation on first install preserves absence and no receipt',t=>{
  const f=fixture(t);fs.writeFileSync(path.join(f.bin,'mv'),`#!/bin/bash\n/bin/mv "$@" || exit\nif [[ "$1" = *'.prime-monitor-stage-'*'/Anker Charge Monitor.app' && "\${!#}" = ${JSON.stringify(f.app)} ]]; then touch "\${!#}/synthetic-reject"; fi\n`,{mode:0o755});const r=f.run();assert.equal(r.status,1);assert.deepEqual(state(f),[null,null]);
});

test('private scratch retains the exact indexed input modes under a restrictive umask',t=>{
  const f=fixture(t),make=fs.readFileSync(path.join(f.project,'Makefile'),'utf8');
  f.write('Makefile',make.replace('release:\n',()=>"release:\n\ttest \"$$(stat -f %Lp Resources/Info.plist)\" = 644\n\ttest \"$$(stat -f %Lp tools/install.sh)\" = 755\n"));f.git('add','.');
  const hook=path.join(f.base,'synthetic-umask.cjs');fs.writeFileSync(hook,'process.umask(0o077);\n');f.env.NODE_OPTIONS='--require='+JSON.stringify(hook);
  ok(f.run());ok(f.run('--audit'));
});

test('canonical make install delegates to the root CLI without a separate release build',()=>{
  const make=fs.readFileSync(new URL('../../anker_charge_monitor/Makefile',import.meta.url),'utf8');
  assert.match(make,/install deploy:\n\tnode ..\/tools\/deploy_anker_charge_monitor\.mjs/);
  assert.match(make,/"\/Applications\/Anker Charge Monitor.app\/Contents\/MacOS\/PrimeMonitor" --live-check/);
});

test('forward deployment prunes older backups while rollback and dry run preserve them', t => {
  const f = fixture(t); ok(f.run());
  const root = path.join(f.home, '.utilities-deploy-backups', 'anker-charge-monitor');
  for (const name of ['copy-old-a','copy-old-b','copy-old-c']) { const dir=path.join(root,name); fs.mkdirSync(dir); fs.writeFileSync(path.join(dir,'payload'),'invented'); fs.utimesSync(dir,1,1); }
  f.release('next'); ok(f.run('--dry-run'));
  const beforeFailure=fs.readdirSync(root).sort();
  fs.appendFileSync(path.join(f.project,'Makefile'),'\\n# invented unstaged change\\n');
  assert.equal(f.run().status,1); f.git('checkout','--','.');
  assert.deepEqual(fs.readdirSync(root).sort(),beforeFailure);
  for (const name of ['copy-old-a','copy-old-b','copy-old-c']) assert.equal(fs.readFileSync(path.join(root,name,'payload'),'utf8'),'invented');
  const result=f.run(); ok(result); const saved=/rollback backup: (.+)/.exec(result.stdout)[1];
  const names=fs.readdirSync(root); assert.equal(names.length,2); assert.ok(names.includes(path.basename(saved)));
  for (const name of ['copy-old-a','copy-old-b','copy-old-c']) {const dir=path.join(root,name);if(!fs.existsSync(dir)){fs.mkdirSync(dir);fs.writeFileSync(path.join(dir,'payload'),'invented');}}
  const before=fs.readdirSync(root).sort(); ok(f.run('--rollback',saved));
  for(const name of before) assert.ok(fs.existsSync(path.join(root,name)),name);
});
