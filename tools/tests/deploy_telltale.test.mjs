// Port: tools/tests/deploy_anker_charge_monitor.test.mjs, every test case, be26b1b.
// Adaptation: Telltale's names, identifiers and required font inputs. Anker's legacy app name
// (`Prime Monitor.app`) has no Telltale counterpart, so these Anker assertions are dropped:
// - "failed activated signature ... legacy upgrades": the rename of the installed bundle to the
//   legacy name, and the check that the legacy name is gone afterwards. The older-version
//   upgrade it also covered is kept, on the canonical name.
// - "canonical make install": the `--live-check` line, since Telltale has no live-check target
//   (its Makefile says so). The test instead checks that neither install path calls launchctl.
// Added: the deploy contract against TelltaleRelease and Info.plist, required font inputs, and a
// launchctl double that fails the lifecycle if the tool ever calls it.
// Every fixture lives in one mkdtemp directory that t.after removes, and every child process
// gets TMPDIR inside it, so nothing is left in the real temporary directory (ruling R28).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync,execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {buildInput,sourceInventory,contract,requiredInputs} from '../deploy_telltale.mjs';
import {appTreeHash} from '../deploy_brew_version.mjs';
const script=fileURLToPath(new URL('../deploy_telltale.mjs',import.meta.url));
const repoRoot=fileURLToPath(new URL('../../',import.meta.url));
const plist=fs.readFileSync(path.join(repoRoot,'telltale/Resources/Info.plist'));
const release=Object.fromEntries([...fs.readFileSync(path.join(repoRoot,'telltale/Sources/TelltaleCore/Release.swift'),'utf8').matchAll(/static let (\w+) = "([^"]+)"/g)].map(m=>[m[1],m[2]]));
const fingerprint='A'.repeat(40);
const fonts=['Resources/Fonts/BarlowSemiCondensed-Medium.ttf','Resources/Fonts/BarlowSemiCondensed-Regular.ttf','Resources/Fonts/OFL.txt'];
function fixture(t) {
  const base=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'synthetic-telltale-deploy-')));
  t.after(()=>fs.rmSync(base,{recursive:true,force:true}));
  const repo=path.join(base,'invented repo'),home=path.join(base,'invented home'),project=path.join(repo,'telltale'),apps=path.join(home,'apps'),scripts=path.join(home,'Library/Scripts'),bin=path.join(base,'bin');
  for(const p of [project,apps,scripts,bin])fs.mkdirSync(p,{recursive:true});
  const write=(name,bytes,mode=0o644)=>{const file=path.join(project,name);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,bytes,{mode});fs.chmodSync(file,mode);};
  fs.mkdirSync(path.join(repo,'tools'));
  for(const name of ['deploy_telltale.mjs','deployment_files.mjs','deploy_brew_version.mjs'])fs.copyFileSync(path.join(repoRoot,'tools',name),path.join(repo,'tools',name));
  for(const name of ['install.sh','resolve_signing_identity.sh'])write('tools/'+name,fs.readFileSync(path.join(repoRoot,'telltale/tools',name)),0o755);
  write('Package.swift','// conspicuously synthetic package\n');write('Resources/Info.plist',plist);
  for(const name of fonts)write(name,'conspicuously synthetic '+path.basename(name)+'\n');
  write('Makefile',`release:\n\tmkdir -p 'build/release/Telltale.app/Contents/MacOS' 'build/release/Telltale.app/Contents/Resources/Fonts'\n\tclang -mmacosx-version-min=27.0 Sources/main.c -o 'build/release/Telltale.app/Contents/MacOS/Telltale'\n\tcp Resources/Info.plist 'build/release/Telltale.app/Contents/Info.plist'\n\tcp -p Resources/Fonts/*.ttf Resources/Fonts/OFL.txt 'build/release/Telltale.app/Contents/Resources/Fonts/'\n`);
  const git=(...args)=>execFileSync('git',['-C',repo,...args],{stdio:'pipe'});
  git('init','-q');git('config','user.name','Synthetic Test');git('config','user.email','synthetic@example.invalid');
  const release=label=>{write('Sources/main.c',`#include <stdio.h>\nint main(void){puts("synthetic ${label} must never execute");return 91;}\n`);git('add','.');git('commit','-qm','Synthetic '+label);};
  release('first');
  fs.writeFileSync(path.join(bin,'security'),`#!/bin/bash\n[ "\${SYNTHETIC_MISSING:-0}" = 0 ] || exit 0\necho ' Matching identities'\necho ' 1) ${fingerprint} "CodexBar Local"'\nif [ "\${SYNTHETIC_AMBIGUOUS:-0}" = 1 ]; then echo ' 2) ${'B'.repeat(40)} "CodexBar Local"'; fi\n`,{mode:0o755});
  fs.writeFileSync(path.join(bin,'codesign'),`#!/bin/bash\n[ "$#" = 5 ] && [ "$1" = --verify ] && [ "$2" = --strict ] && [ "$3" = -R ] && [ "$4" = '=identifier "local.utilities.telltale" and certificate leaf = H"${fingerprint}"' ] || exit 94\n[ ! -e "\${!#}/synthetic-reject" ] || exit 95\n`,{mode:0o755});
  fs.writeFileSync(path.join(bin,'pgrep'),'#!/bin/sh\nexit 1\n',{mode:0o755});
  const launchctlCalls=path.join(base,'launchctl-called');
  fs.writeFileSync(path.join(bin,'launchctl'),`#!/bin/sh\necho "$@" >> ${JSON.stringify(launchctlCalls)}\nexit 97\n`,{mode:0o755});
  const env={...process.env,HOME:home,TMPDIR:base,PATH:bin+':'+process.env.PATH};
  const run=(...args)=>spawnSync(process.execPath,[script,'--repo',repo,'--apps-dir',apps,'--scripts-dir',scripts,...args],{env,encoding:'utf8'});
  return {base,repo,home,project,apps,scripts,bin,write,git,release,env,run,launchctlCalls,app:path.join(apps,'Telltale.app'),receipt:path.join(scripts,'.telltale-native.json')};
}
function ok(result){assert.equal(result.status,0,result.stdout+result.stderr);return result;}
const backup=result=>/rollback backup: (.+)/.exec(result.stdout)[1];
function state(f){return [fs.existsSync(f.app)?appTreeHash(f.app):null,fs.existsSync(f.receipt)?fs.readFileSync(f.receipt,'utf8'):null];}
function tree(dir){return fs.readdirSync(dir,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name)).map(e=>[e.name,fs.lstatSync(path.join(dir,e.name)).mode,e.isDirectory()?tree(path.join(dir,e.name)):fs.readFileSync(path.join(dir,e.name)).toString('base64')]);}

test('deploy contract restates TelltaleRelease and the tracked Info.plist',()=>{
  const info=JSON.parse(execFileSync('/usr/bin/plutil',['-convert','json','-o','-','--','-'],{input:plist,encoding:'utf8'}));
  assert.equal(contract.CFBundleIdentifier,release.bundleIdentifier);
  assert.equal(contract.CFBundleName,release.displayName);assert.equal(contract.CFBundleDisplayName,release.displayName);
  assert.equal(info.CFBundleShortVersionString,release.version);
  for(const [key,value] of Object.entries(contract)) assert.equal(info[key],value,key);
  assert.equal(release.collectorLabel,release.bundleIdentifier+'.collector');
});

test('app source inventory includes maintained installer/signing, fonts and root dependencies',()=>{
  for(const name of ['Package.swift','Makefile','Sources/a.swift','Tests/a.sh','Resources/Info.plist',...fonts,'Resources/Fonts/SOURCE.md','tools/install.sh','tools/resolve_signing_identity.sh']) assert.equal(buildInput('telltale/'+name),true,name);
  for(const name of ['tools/deployment_files.mjs','tools/deploy_brew_version.mjs','tools/deploy_telltale.mjs']) assert.equal(buildInput(name),true,name);
  for(const name of ['README.md','docs/telltale_design_spec.md','.gitignore','.build/a','build/release/a']) assert.equal(buildInput('telltale/'+name),false,name);
  for(const name of fonts) assert.ok(requiredInputs.includes('telltale/'+name),name);
});

test('first install, update, current, rebuild and independent rollback preserve receipts and held readers',t=>{
  const f=fixture(t);const empty=backup(ok(f.run()));const first=state(f);
  const r=JSON.parse(first[1]);assert.equal(r.sourceHash,sourceInventory(f.repo).sourceHash);assert.equal(r.appTreeHash,first[0]);assert.equal(r.signingIdentity,fingerprint);assert.equal(r.version,release.version);assert.equal(fs.statSync(f.receipt).mode&0o7777,0o600);
  ok(f.run('--audit'));const before=tree(f.home);assert.match(ok(f.run()).stdout,/already current/);assert.deepEqual(tree(f.home),before);
  const exe=path.join(f.app,'Contents/MacOS/Telltale'),reader=fs.openSync(exe,'r'),old=fs.readFileSync(reader);fs.closeSync(reader);
  const held=fs.openSync(exe,'r');f.release('second');const saved=backup(ok(f.run()));assert.notDeepEqual(state(f),first);assert.deepEqual(fs.readFileSync(held),old);fs.closeSync(held);
  const second=state(f);ok(f.run('--rollback',saved));assert.deepEqual(state(f),first);assert.notDeepEqual(state(f),second);
  ok(f.run('--rollback',empty));assert.deepEqual(state(f),[null,null]);
  ok(f.run());assert.match(ok(f.run('--rebuild')).stdout,/rollback backup:/);
  assert.equal(fs.existsSync(path.join(f.scripts,'Telltale')),false);
  assert.equal(fs.existsSync(f.launchctlCalls),false,'the deploy tool must never call launchctl');
});

test('dry run and audit do not compile, query identities or change any source/deployment state',t=>{
  const f=fixture(t);ok(f.run());
  for(const name of ['security','make','codesign'])fs.writeFileSync(path.join(f.bin,name),'#!/bin/sh\necho synthetic forbidden mutation >&2\nexit 99\n',{mode:0o755});
  const before=tree(f.base);ok(f.run('--dry-run'));ok(f.run('--audit'));assert.deepEqual(tree(f.base),before);
});

test('source and app/receipt byte and mode drift fail audit',t=>{
  const f=fixture(t);ok(f.run());
  for(const file of [path.join(f.project,'Sources/main.c'),path.join(f.project,fonts[0]),path.join(f.repo,'tools/deployment_files.mjs'),path.join(f.app,'Contents/MacOS/Telltale'),path.join(f.app,'Contents/Resources/Fonts/OFL.txt'),f.receipt]){
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
    f.write('Makefile',make+`\t/usr/libexec/PlistBuddy -c 'Set :${key} ${value}' 'build/release/Telltale.app/Contents/Info.plist'\n`);f.git('add','.');
    assert.equal(f.run('--rebuild').status,1,key);assert.deepEqual(state(f),before);f.write('Makefile',make);f.git('add','.');
  }
  fs.writeFileSync(path.join(f.app,'synthetic-reject'),'synthetic');const bad=state(f);assert.equal(f.run('--rebuild').status,1);assert.deepEqual(state(f),bad);
});

test('missing app rebuilds; rollback and updates preserve runtime directories and the collector job',t=>{
  const f=fixture(t),runtime=path.join(f.home,'Library');
  for(const [dir,name] of [['Application Support/Telltale','telltale.sqlite'],['Logs/Telltale','collector.log'],['LaunchAgents',release.collectorLabel+'.plist']]){
    fs.mkdirSync(path.join(runtime,dir),{recursive:true});fs.writeFileSync(path.join(runtime,dir,name),'synthetic keep');
  }
  const kept=()=>['Application Support','Logs','LaunchAgents'].map(dir=>tree(path.join(runtime,dir)));const before=kept();
  ok(f.run());fs.rmSync(f.app,{recursive:true});ok(f.run());ok(f.run('--audit'));assert.deepEqual(kept(),before);
  assert.equal(fs.existsSync(f.launchctlCalls),false,'the deploy tool must never call launchctl');
});

test('untracked, missing, symlink ancestors and staged deletion cannot supply build inputs',t=>{
  for(const mode of ['missing','link','deletion','untracked','font']){
    const f=fixture(t),source=path.join(f.project,'Sources');
    if(mode==='missing')fs.unlinkSync(path.join(source,'main.c'));
    if(mode==='link'){fs.renameSync(source,source+'-saved');fs.symlinkSync(source+'-saved',source);}
    if(mode==='deletion')f.git('rm','--cached','telltale/Sources/main.c');
    if(mode==='untracked')fs.appendFileSync(path.join(source,'main.c'),'// unstaged');
    if(mode==='font')f.git('rm','--cached','telltale/'+fonts[1]);
    const result=f.run();assert.equal(result.status,1,mode+result.stdout+result.stderr);
    if(mode==='font')assert.match(result.stderr,/Required app build input missing: telltale\/Resources\/Fonts\/BarlowSemiCondensed-Regular\.ttf/);
  }
});

for(const first of [false,true])test(`receipt publication failure restores ${first?'absent':'prior'} app and receipt`,t=>{
  const f=fixture(t);if(!first)ok(f.run());const before=state(f);f.release('receipt-failure');
  const hook=path.join(f.base,'synthetic-hook.cjs');fs.writeFileSync(hook,`const fs=require('node:fs');const rename=fs.renameSync;let failed=false;fs.renameSync=(a,b)=>{const r=rename(a,b);if(!failed&&b===${JSON.stringify(f.receipt)}){failed=true;throw Error('synthetic receipt failure');}return r;};`);f.env.NODE_OPTIONS='--require='+JSON.stringify(hook);
  const r=f.run();assert.equal(r.status,1);assert.match(r.stderr,/synthetic receipt failure/);assert.deepEqual(state(f),before);
});

test('failed activated signature restores prior bundle and receipt; upgrades permit old versions',t=>{
  const f=fixture(t);ok(f.run());const before=state(f);f.release('activation-failure');
  const mv=path.join(f.bin,'mv');fs.writeFileSync(mv,`#!/bin/bash\n/bin/mv "$@" || exit\nif [[ "$1" = *'.telltale-stage-'*'/Telltale.app' && "\${!#}" = ${JSON.stringify(f.app)} && -e "$SYNTHETIC_FAIL_ONCE" ]]; then rm "$SYNTHETIC_FAIL_ONCE"; touch "\${!#}/synthetic-reject"; fi\n`,{mode:0o755});
  f.env.SYNTHETIC_FAIL_ONCE=path.join(f.base,'fail-once');fs.writeFileSync(f.env.SYNTHETIC_FAIL_ONCE,'synthetic');assert.equal(f.run().status,1);assert.deepEqual(state(f),before);
  execFileSync('/usr/libexec/PlistBuddy',['-c','Set :CFBundleShortVersionString 0.0.1',path.join(f.app,'Contents/Info.plist')]);
  ok(f.run());ok(f.run('--audit'));
});

test('cleanup failure restores prior deployment and retains verified backups',t=>{
  const f=fixture(t);ok(f.run());const before=state(f);f.release('cleanup-failure');const hook=path.join(f.base,'synthetic-cleanup.cjs');
  fs.writeFileSync(hook,`const fs=require('node:fs'),path=require('node:path');const rm=fs.rmSync;let failed=false;fs.rmSync=(p,...args)=>{if(!failed&&path.basename(p).startsWith('telltale-build-')){failed=true;throw Error('synthetic cleanup failure');}return rm(p,...args);};`);f.env.NODE_OPTIONS='--require='+JSON.stringify(hook);
  const r=f.run();assert.equal(r.status,1);assert.match(r.stderr,/cleanup failure/);assert.deepEqual(state(f),before);const saved=/Recovery backup: (.+)/.exec(r.stdout)[1];assert.equal(appTreeHash(path.join(saved,'Telltale.app')),before[0]);
});

test('rollback receipt failure restores displaced release and retained backup is independent',t=>{
  const f=fixture(t);ok(f.run());f.release('second');const saved=backup(ok(f.run())),before=state(f),savedHash=appTreeHash(path.join(saved,'Telltale.app'));
  const hook=path.join(f.base,'synthetic-rollback.cjs');fs.writeFileSync(hook,`const fs=require('node:fs');const rename=fs.renameSync;let once=false;fs.renameSync=(a,b)=>{const r=rename(a,b);if(!once&&b===${JSON.stringify(f.receipt)}){once=true;throw Error('synthetic rollback receipt failure');}return r;};`);f.env.NODE_OPTIONS='--require='+JSON.stringify(hook);
  const r=f.run('--rollback',saved);assert.equal(r.status,1);assert.match(r.stderr,/synthetic rollback receipt failure/);assert.deepEqual(state(f),before);assert.equal(appTreeHash(path.join(saved,'Telltale.app')),savedHash);
  delete f.env.NODE_OPTIONS;fs.appendFileSync(path.join(saved,'Telltale.app/Contents/MacOS/Telltale'),'synthetic corrupt saved bytes');const result=f.run('--rollback',saved);assert.equal(result.status,1);assert.match(result.stderr,/Backup app hash mismatch/);assert.deepEqual(state(f),before);
});

test('rejects executable runtime drift even when plist claims the current runtime',t=>{
  const f=fixture(t),make=fs.readFileSync(path.join(f.project,'Makefile'),'utf8');f.write('Makefile',make.replace('-mmacosx-version-min=27.0','-mmacosx-version-min=14.0'));f.git('add','.');const r=f.run();assert.equal(r.status,1);assert.match(r.stderr,/minimum runtime/);assert.deepEqual(state(f),[null,null]);
});

test('failed activation on first install preserves absence and no receipt',t=>{
  const f=fixture(t);fs.writeFileSync(path.join(f.bin,'mv'),`#!/bin/bash\n/bin/mv "$@" || exit\nif [[ "$1" = *'.telltale-stage-'*'/Telltale.app' && "\${!#}" = ${JSON.stringify(f.app)} ]]; then touch "\${!#}/synthetic-reject"; fi\n`,{mode:0o755});const r=f.run();assert.equal(r.status,1);assert.deepEqual(state(f),[null,null]);
});

test('private scratch retains the exact indexed input modes under a restrictive umask',t=>{
  const f=fixture(t),make=fs.readFileSync(path.join(f.project,'Makefile'),'utf8');
  f.write('Makefile',make.replace('release:\n',()=>"release:\n\ttest \"$$(stat -f %Lp Resources/Info.plist)\" = 644\n\ttest \"$$(stat -f %Lp tools/install.sh)\" = 755\n"));f.git('add','.');
  const hook=path.join(f.base,'synthetic-umask.cjs');fs.writeFileSync(hook,'process.umask(0o077);\n');f.env.NODE_OPTIONS='--require='+JSON.stringify(hook);
  ok(f.run());ok(f.run('--audit'));
});

test('canonical make install delegates to the root CLI without a separate release build or launchd',()=>{
  const make=fs.readFileSync(new URL('../../telltale/Makefile',import.meta.url),'utf8');
  assert.match(make,/^install deploy:\n\tnode ..\/tools\/deploy_telltale\.mjs\n(?!\t)/m);
  for(const file of ['../../telltale/Makefile','../../telltale/tools/install.sh','../deploy_telltale.mjs']) assert.doesNotMatch(fs.readFileSync(new URL(file,import.meta.url),'utf8'),/\blaunchctl\b/,file);
});

test('the release build gets a TMPDIR inside the removed scratch, so the caller TMPDIR gets no Telltale entries',t=>{
  // Stands in for SwiftPM, which writes path-named lock files and TemporaryDirectory.* to TMPDIR
  // (always inside TMPDIR, so even a failing run leaves them in the removed fixture).
  const f=fixture(t),make=fs.readFileSync(path.join(f.project,'Makefile'),'utf8'),log=path.join(f.base,'synthetic-tmpdir.log');
  f.write('Makefile',make.replace('release:\n',()=>"release:\n\tprintf '%s\\n' \"$$TMPDIR\" > \"$$SYNTHETIC_TMPDIR_LOG\"\n\t: > \"$${TMPDIR%/}/_synthetic_telltale_.build.lock\"\n\tmkdir \"$${TMPDIR%/}/TemporaryDirectory.synthetic\"\n"));f.git('add','.');
  f.env.SYNTHETIC_TMPDIR_LOG=log;ok(f.run());
  const child=fs.readFileSync(log,'utf8').trim();
  assert.match(child,new RegExp('^'+f.base.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'/telltale-build-[^/]+/tmp/$'),child);
  assert.equal(fs.existsSync(child),false,'the scratch TMPDIR must be removed with the scratch');
  assert.deepEqual(fs.readdirSync(f.base).filter(name=>/telltale|TemporaryDirectory/i.test(name)),[]);
});
