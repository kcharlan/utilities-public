import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync, spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {buildInput, sourceInventory, appTreeHash} from '../deploy_brew_version.mjs';
import {sha} from '../deployment_files.mjs';
import {fakeDarwinTemp,releaseTempMakefile,assertReleaseTempHygiene} from './release-temp-fixture.mjs';
const script = fileURLToPath(new URL('../deploy_brew_version.mjs', import.meta.url));
const plist = fs.readFileSync(new URL('../../brew_version/Resources/Info.plist', import.meta.url));
const help = fs.readFileSync(new URL('../../brew_version/Tests/BrewVersionCLITests/Fixtures/expected-help.txt', import.meta.url));
const version = /<key>CFBundleShortVersionString<\/key>\s*<string>([^<]+)<\/string>/.exec(plist.toString())[1];
function snapshot(file) {
  if (!fs.existsSync(file)) return null;
  const s = fs.lstatSync(file);
  const type = s.isDirectory() ? 'directory' : s.isFile() ? 'file' : 'unsupported';
  return {type, mode:s.mode & 0o7777, bytes:type==='file'?fs.readFileSync(file).toString('base64'):null,
    children:type==='directory'?Object.fromEntries(fs.readdirSync(file).sort().map(n=>[n,snapshot(path.join(file,n))])):null};
}
function active(f) { return [snapshot(f.target),snapshot(f.receipt),snapshot(f.app)]; }
function assertActiveDeployment(f, expected) {
  assert.deepEqual(active(f),expected);
  if (expected[1]) {
    const r = JSON.parse(fs.readFileSync(f.receipt));
    assert.deepEqual(Object.keys(r).sort(),['schema','sourceHash','version','commandHash','commandMode','appTreeHash'].sort());
    assert.equal(r.schema,1); assert.equal(r.version,version); assert.equal(r.commandMode,0o755);
    assert.equal(r.commandHash,sha(fs.readFileSync(f.target))); assert.equal(r.appTreeHash,appTreeHash(f.app));
    assert.equal(fs.statSync(f.receipt).mode & 0o7777,0o600);
  }
}
function succeeds(r) { assert.equal(r.status,0,r.stderr+r.stdout); return r; }
function fixture(t) {
  const base=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'synthetic-brew-deploy-')));
  t.after(()=>fs.rmSync(base,{recursive:true,force:true}));
  const repo=path.join(base,'invented repo'),home=path.join(base,'invented home'),project=path.join(repo,'brew_version');
  const scripts=path.join(home,'Library/Scripts'),apps=path.join(home,'Applications'),bin=path.join(base,'bin');
  fs.mkdirSync(project,{recursive:true}); fs.mkdirSync(scripts,{recursive:true}); fs.mkdirSync(apps); fs.mkdirSync(bin);
  const darwin=fakeDarwinTemp(base,bin);
  const write=(n,b)=>{const p=path.join(project,n);fs.mkdirSync(path.dirname(p),{recursive:true});fs.writeFileSync(p,b);};
  const git=(...a)=>execFileSync('git',['-C',repo,...a],{stdio:'pipe'});
  git('init','-q');git('config','user.name','Synthetic Tester');git('config','user.email','tester@example.invalid');
  write('Package.swift','// synthetic package\n');write('Resources/Info.plist',plist);write('Tests/BrewVersionCLITests/Fixtures/expected-help.txt',help);
  write('Makefile',`release:\n\tclang Sources/main.c -o synthetic-command\n\tmkdir -p 'build/release/Brew Version.app/Contents/MacOS' 'build/release/Brew Version.app/Contents/Resources'\n\tcp synthetic-command build/release/brew-version\n\tcp synthetic-command 'build/release/Brew Version.app/Contents/MacOS/BrewVersion'\n\tcp Resources/Info.plist 'build/release/Brew Version.app/Contents/Info.plist'\n\tcp Sources/main.c 'build/release/Brew Version.app/Contents/Resources/synthetic.txt'\n\tchmod 751 'build/release/Brew Version.app'\n\tchmod 711 'build/release/Brew Version.app/Contents/Resources'\n\tchmod 640 'build/release/Brew Version.app/Contents/Resources/synthetic.txt'\n\tcodesign --force --sign - --timestamp=none build/release/brew-version\n\tcodesign --force --sign - --timestamp=none 'build/release/Brew Version.app'\n\trm -rf "$$SYNTHETIC_EXPECTED_RELEASE/Brew Version.app"\n\tcp -pR build/release/. "$$SYNTHETIC_EXPECTED_RELEASE/"\n`);
  function release(label,fail=false,stderrFlag='',installedOnly=false) {
    write('Sources/main.c',`#include <stdio.h>\n#include <string.h>\nint main(int argc,char **argv){/* synthetic ${label} */ if(${fail?1:0} && strstr(argv[0],"/Scripts/")) return 1; if(argc==2 && !strcmp(argv[1],${JSON.stringify(stderrFlag)}) && (${installedOnly?1:0} == 0 || strstr(argv[0],"/Scripts/"))) fputs("synthetic diagnostic warning\\n",stderr); if(argc==2 && !strcmp(argv[1],"--version")){puts("brew-version ${version}");return 0;} if(argc==2 && (!strcmp(argv[1],"--help") || !strcmp(argv[1],"-h"))){fputs(${JSON.stringify(help.toString())},stdout);return 0;}return 2;}\n`);
    git('add','.');git('commit','-qm','Synthetic '+label);
  }
  release('first');
  const expected=path.join(base,'independent-release');fs.mkdirSync(expected);
  const env={...process.env,HOME:home,TMPDIR:base,PATH:bin+':'+process.env.PATH,BREW_VERSION_DEPLOY_TEST_ONLY_PGREP:"/usr/bin/false",SYNTHETIC_EXPECTED_RELEASE:expected};
  const run=(...args)=>spawnSync(process.execPath,[script,'--repo',repo,'--scripts-dir',scripts,'--apps-dir',apps,...args],{encoding:'utf8',env});
  return {base,repo,home,project,scripts,apps,bin,darwin,expected,git,write,release,run,env,target:path.join(scripts,'brew-version'),receipt:path.join(scripts,'.brew-version-native.json'),app:path.join(apps,'Brew Version.app')};
}
const backupPath=r=>r.stdout.trim().split('rollback backup: ')[1].split('\n')[0];
for (const flag of ['--version','--help','-h']) {
  for (const installedOnly of [false,true]) {
    test(`rejects unexpected stderr from ${flag} during ${installedOnly?'activation':'build'} and preserves recovery`,t=>{
      const f=fixture(t);
      const saved=backupPath(succeeds(f.run()));
      const before=active(f),recovery=snapshot(saved);
      f.release('noisy',false,flag,installedOnly);
      const r=f.run();
      assert.equal(r.status,1,r.stdout);
      assert.match(r.stderr,/unexpected stderr/i);
      assertActiveDeployment(f,before);
      assert.deepEqual(snapshot(saved),recovery);
      if(installedOnly) {
        const copies=fs.readdirSync(path.dirname(saved)).filter(n=>path.join(path.dirname(saved),n)!==saved);
        assert.equal(copies.length,1);
        const backup=path.join(path.dirname(saved),copies[0]);
        assert.equal(snapshot(path.join(backup,'brew-version')).bytes,before[0].bytes);
        assert.deepEqual(snapshot(path.join(backup,'Brew Version.app')),before[2]);
        assert.equal(snapshot(path.join(backup,'receipt.json')).bytes,before[1].bytes);
      }
    });
  }
}
test('buildInputs',()=>{
  for(const n of ['Package.swift','Makefile','Sources/a.swift','Tests/a.txt','Resources/a']) assert.equal(buildInput('brew_version/'+n),true,n);
  for(const n of ['README.md','build/release/a','.build/a']) assert.equal(buildInput('brew_version/'+n),false,n);
  assert.equal(buildInput('other/Makefile'),false);
});
for(const fail of [false,true]) test(`a ${fail?'failed':'successful'} release build leaves no temporary entries in TMPDIR or the Darwin user temp dir`,t=>{
  const f=fixture(t);
  assertReleaseTempHygiene({...f,run:fail=>{f.write('Makefile',releaseTempMakefile(fs.readFileSync(path.join(f.project,'Makefile'),'utf8'),fail));f.git('add','.');f.git('commit','-qm','Synthetic temp writes');return f.run();}},'brew-version-build-',fail);
});
test('rejects the retired runtime contract before activation',t=>{
  const f=fixture(t);
  f.write('Resources/Info.plist',plist.toString().replace(/(<key>LSMinimumSystemVersion<\/key>\s*<string>)[^<]+/, (_match,prefix)=>prefix+'14.0'));
  f.git('add','.');f.git('commit','--allow-empty','-qm','Use synthetic retired runtime contract');
  const result=f.run();
  assert.equal(result.status,1,result.stdout+result.stderr);
  assert.match(result.stderr,/LSMinimumSystemVersion/);
  assert.equal(fs.existsSync(f.target),false);
  assert.equal(fs.existsSync(f.app),false);
});
test('firstDeployReplacesExistingScript',t=>{
  const f=fixture(t);fs.writeFileSync(f.target,'#!/bin/bash\necho synthetic previous\n',{mode:0o751});const old=snapshot(f.target);
  const saved=backupPath(succeeds(f.run()));assert.equal(snapshot(path.join(saved,'brew-version')).bytes,old.bytes);
  assert.equal(JSON.parse(fs.readFileSync(path.join(saved,'state.json'))).command.mode,0o751);
  const expected=active(f);assert.deepEqual(expected[0],snapshot(path.join(f.expected,'brew-version')));assert.deepEqual(expected[2],snapshot(path.join(f.expected,'Brew Version.app')));assert.equal(expected[0].mode,0o755);assertActiveDeployment(f,expected);
  assert.equal(JSON.parse(fs.readFileSync(f.receipt)).sourceHash,sourceInventory(f.repo).sourceHash);
  assert.deepEqual(fs.readFileSync(path.join(f.app,'Contents/Resources/synthetic.txt')),fs.readFileSync(path.join(f.project,'Sources/main.c')));
  const before=snapshot(f.home);assert.equal(succeeds(f.run('--audit')).stdout,'OK: brew-version native deployment\n');assert.deepEqual(snapshot(f.home),before);
});
test('updateOverPreviousRelease and rollbackRestoresPrevious and backupModes',t=>{
  const f=fixture(t);succeeds(f.run());const first=active(f);assert.equal(first[2].mode,0o751);assert.equal(first[2].children.Contents.children.Resources.mode,0o711);f.release('second');
  const saved=backupPath(succeeds(f.run()));const second=active(f);assert.notDeepEqual(second,first);assertActiveDeployment(f,second);assert.deepEqual(second[0],snapshot(path.join(f.expected,'brew-version')));assert.deepEqual(second[2],snapshot(path.join(f.expected,'Brew Version.app')));
  assert.equal(snapshot(path.join(saved,'brew-version')).bytes,first[0].bytes);
  assert.equal(snapshot(saved).mode,0o700);for(const n of ['brew-version','receipt.json','state.json'])assert.equal(snapshot(path.join(saved,n)).mode,0o600);
  assert.deepEqual(snapshot(path.join(saved,'Brew Version.app')),first[2]);assert.equal(JSON.parse(fs.readFileSync(path.join(saved,'state.json'))).command.mode,first[0].mode);
  const displaced=backupPath(succeeds(f.run('--rollback',saved)));assertActiveDeployment(f,first);assert.equal(snapshot(path.join(displaced,'brew-version')).bytes,second[0].bytes);assert.equal(snapshot(path.join(displaced,'receipt.json')).bytes,second[1].bytes);
  const backups=path.dirname(saved);assert.ok(fs.readdirSync(backups).some(n=>snapshot(path.join(backups,n,'Brew Version.app'))?.children.Contents.children.Resources.children['synthetic.txt'].bytes===second[2].children.Contents.children.Resources.children['synthetic.txt'].bytes));
});
test('currentDeployChangesNothing and rebuild forces build',t=>{
  const f=fixture(t);succeeds(f.run());const before=snapshot(f.home);
  assert.match(succeeds(f.run()).stdout,/already current; nothing changed/);assert.deepEqual(snapshot(f.home),before);
  assert.match(succeeds(f.run('--rebuild')).stdout,/rollback backup:/);assert.notDeepEqual(snapshot(f.home),before);
});
test('appStateSurvives',t=>{
  const f=fixture(t);for(const n of ['Application Support','Caches']){const p=path.join(f.home,'Library',n,'Brew Version');fs.mkdirSync(p,{recursive:true});fs.writeFileSync(path.join(p,'synthetic-state'),'synthetic keep');}
  const savedState=['Application Support','Caches'].map(n=>snapshot(path.join(f.home,'Library',n)));
  const saved=backupPath(succeeds(f.run()));succeeds(f.run('--audit'));succeeds(f.run('--rollback',saved));assert.equal(f.run('--audit').status,1);
  assert.deepEqual(['Application Support','Caches'].map(n=>snapshot(path.join(f.home,'Library',n))),savedState);assert.equal(fs.existsSync(f.app),false);
});
test('auditDetectsDrift and auditDetectsAppModeDrift',t=>{
  const f=fixture(t);succeeds(f.run());
  for(const [p,mutate] of [[f.target,p=>fs.appendFileSync(p,'synthetic drift')],[f.target,p=>fs.chmodSync(p,0o4755)],[f.receipt,p=>fs.writeFileSync(p,'{}')],[f.receipt,p=>fs.chmodSync(p,0o644)],[path.join(f.app,'Contents/Resources/synthetic.txt'),p=>fs.appendFileSync(p,'synthetic drift')],[path.join(f.app,'Contents/Resources/synthetic.txt'),p=>fs.chmodSync(p,0o600)],[path.join(f.app,'Contents/Resources'),p=>fs.chmodSync(p,0o700)],[f.app,p=>fs.chmodSync(p,0o700)],[path.join(f.project,'Sources/main.c'),p=>fs.appendFileSync(p,'// drift')]]) {
    const stat=fs.statSync(p),bytes=stat.isFile()?fs.readFileSync(p):null;mutate(p);assert.equal(f.run('--audit').status,1,p);if(bytes)fs.writeFileSync(p,bytes);fs.chmodSync(p,stat.mode & 0o7777);succeeds(f.run('--audit'));
  }
});
test('dryRunWritesNothing',t=>{const f=fixture(t),before=snapshot(f.base);succeeds(f.run('--dry-run'));assert.deepEqual(snapshot(f.base),before);});
test('activationFailureRestores command, app and receipt publication',t=>{
  const f=fixture(t);succeeds(f.run());const expected=active(f);f.release('broken',true);assert.equal(f.run().status,1);assertActiveDeployment(f,expected);
  f.release('recovered');
  for(const destination of [f.app,f.receipt]) {
    const hook=path.join(f.base,'synthetic-failure.cjs');fs.writeFileSync(hook,`const fs=require('node:fs');const original=fs.renameSync;let failed=false;fs.renameSync=function(a,b){const r=original(a,b);if(!failed && b===${JSON.stringify(destination)}){failed=true;throw Error('synthetic publication failure');}return r;};`);
    f.env.NODE_OPTIONS='--require='+JSON.stringify(hook);const result=f.run();delete f.env.NODE_OPTIONS;assert.equal(result.status,1,result.stdout);assert.match(result.stderr,/synthetic publication failure/);assertActiveDeployment(f,expected);
  }
});
test('refusesDestinationsInsideRepo including symlinked ancestors',t=>{
  const f=fixture(t);for(const option of ['--scripts-dir','--apps-dir']){assert.equal(f.run(option,f.repo).status,1);const link=path.join(f.base,'synthetic-link-'+option);fs.symlinkSync(f.apps,link);assert.equal(f.run(option,path.join(link,'nested')).status,1);}
});
test('refusesUnstagedChanges',t=>{const f=fixture(t);fs.appendFileSync(path.join(f.project,'Sources/main.c'),'// drift');assert.match(f.run().stderr,/working bytes differ/);});
test('runningAppGetsRelaunchNotice',t=>{const f=fixture(t),pgrep=path.join(f.base,'synthetic-pgrep');fs.writeFileSync(pgrep,'#!/bin/sh\nexit 0\n',{mode:0o755});f.env.BREW_VERSION_DEPLOY_TEST_ONLY_PGREP=pgrep;assert.match(succeeds(f.run()).stdout,new RegExp('Quit and reopen Brew Version to use '+version.replaceAll('.','\\.')+'\\.'));});
test('bundleWithSymlinkIsRefused',t=>{const f=fixture(t);f.write('Makefile',fs.readFileSync(path.join(f.project,'Makefile'),'utf8')+"\tln -s Info.plist 'build/release/Brew Version.app/Contents/synthetic-link'\n");f.git('add','.');const r=f.run();assert.equal(r.status,1);assert.match(r.stderr,/symlink|unsupported/i);assert.equal(fs.existsSync(f.target),false);});
test('appTreeHash uses sorted root, entry types, full modes and empty directory content',t=>{
  const f=fixture(t),tree=path.join(f.base,'synthetic-tree');fs.mkdirSync(tree,{mode:0o751});fs.mkdirSync(path.join(tree,'z'),{mode:0o711});fs.writeFileSync(path.join(tree,'a'),'synthetic',{mode:0o640});fs.writeFileSync(path.join(tree,'z.b'),'synthetic sibling',{mode:0o600});fs.writeFileSync(path.join(tree,'z/n'),'synthetic nested',{mode:0o600});
  const records=[['.','directory','751',''],['a','file','640','synthetic'],['z','directory','711',''],['z.b','file','600','synthetic sibling'],['z/n','file','600','synthetic nested']];
  const expected=sha(Buffer.from(records.map(([n,type,mode,bytes])=>[n,type,mode,sha(Buffer.from(bytes)),''].join('\0')).join('')));
  assert.equal(appTreeHash(tree),expected);
});
test('failed activation move of prior app retains validated backup for restoration',t=>{
  const f=fixture(t);succeeds(f.run());const expected=active(f);f.release('second');
  const hook=path.join(f.base,'synthetic-move-failure.cjs');fs.writeFileSync(hook,`const fs=require('node:fs');const original=fs.renameSync;fs.renameSync=function(a,b){if(a===${JSON.stringify(f.app)})throw Object.assign(Error('synthetic activation move failure'),{code:'EACCES'});return original(a,b);};`);
  f.env.NODE_OPTIONS='--require='+JSON.stringify(hook);const r=f.run();assert.equal(r.status,1);assert.match(r.stderr,/synthetic activation move failure/);assertActiveDeployment(f,expected);
});
test('missing and drifted command or app rebuild the complete release together',t=>{
  const f=fixture(t);succeeds(f.run());
  for(const mutate of [()=>fs.unlinkSync(f.target),()=>fs.appendFileSync(f.target,'synthetic drift'),()=>fs.rmSync(f.app,{recursive:true}),()=>fs.appendFileSync(path.join(f.app,'Contents/Resources/synthetic.txt'),'synthetic drift')]) {
    mutate();assert.match(succeeds(f.run()).stdout,/rollback backup:/);assert.deepEqual(snapshot(f.target),snapshot(path.join(f.expected,'brew-version')));assert.deepEqual(snapshot(f.app),snapshot(path.join(f.expected,'Brew Version.app')));assertActiveDeployment(f,active(f));succeeds(f.run('--audit'));
  }
});

function inject(f, source) {
  const hook=path.join(f.base,'synthetic-io-hook.cjs');
  fs.writeFileSync(hook,source);
  f.env.NODE_OPTIONS='--require='+JSON.stringify(hook);
}
for(const priorApp of [true,false]) {
  test(`rollback stages the displaced live inode before restoring ${priorApp?'a prior app':'an absent app'}`,t=>{
    const f=fixture(t),empty=backupPath(succeeds(f.run()));
    const first=active(f);f.release('second');const previous=backupPath(succeeds(f.run()));
    const before=active(f),inode=fs.statSync(f.app).ino;
    const evidence=path.join(f.base,'synthetic-displacement.json');
    inject(f,`const fs=require('node:fs'),path=require('node:path');const rename=fs.renameSync,remove=fs.rmSync;
      fs.rmSync=(p,...args)=>{if(p===${JSON.stringify(f.app)})throw Error('synthetic live bundle deletion forbidden');return remove(p,...args);};
      fs.renameSync=(a,b)=>{const result=rename(a,b);if(a===${JSON.stringify(f.app)}){
        if(path.dirname(path.dirname(b))!==${JSON.stringify(f.apps)})throw Error('synthetic displacement left apps volume');
        fs.writeFileSync(${JSON.stringify(evidence)},JSON.stringify({inode:fs.statSync(b).ino,bytes:fs.readFileSync(path.join(b,'Contents/Resources/synthetic.txt')).toString('base64')}));}return result;};`);
    const r=succeeds(f.run('--rollback',priorApp?previous:empty));
    assert.deepEqual(JSON.parse(fs.readFileSync(evidence)),{inode,bytes:before[2].children.Contents.children.Resources.children['synthetic.txt'].bytes});
    assertActiveDeployment(f,priorApp?first:[null,null,null]);
    assert.deepEqual(fs.readdirSync(f.apps),priorApp?['Brew Version.app']:[]);
    const recovery=backupPath(r);assert.deepEqual(snapshot(path.join(recovery,'Brew Version.app')),before[2]);
  });
}
test('failed rollback displacement preserves the live inode and validated recovery backup',t=>{
  const f=fixture(t);succeeds(f.run());f.release('second');const saved=backupPath(succeeds(f.run()));
  const before=active(f),inode=fs.statSync(f.app).ino;
  inject(f,`const fs=require('node:fs');const rename=fs.renameSync;
    fs.renameSync=(a,b)=>{if(a===${JSON.stringify(f.app)})throw Error('synthetic rollback displacement failure');return rename(a,b);};`);
  const r=f.run('--rollback',saved);assert.equal(r.status,1);assert.match(r.stderr,/synthetic rollback displacement failure/);
  assertActiveDeployment(f,before);assert.equal(fs.statSync(f.app).ino,inode);
  assert.deepEqual(fs.readdirSync(f.apps),['Brew Version.app']);
  const recovery=/Recovery backup: (.+)/.exec(r.stdout)?.[1];assert.ok(recovery,r.stdout);
  assert.deepEqual(snapshot(path.join(recovery,'Brew Version.app')),before[2]);assert.ok(r.stderr.includes(recovery),r.stderr);
});
test('update succeeds when backup and apps are on different simulated devices',t=>{
  const f=fixture(t);succeeds(f.run());f.release('other-device');
  // Model devices by their containing directory, rather than rejecting every app move.
  inject(f,`const fs=require('node:fs'),path=require('node:path');const rename=fs.renameSync;
    const device=p=>path.resolve(p).startsWith(${JSON.stringify(f.apps+path.sep)})?2:1;
    fs.renameSync=(a,b)=>{if(device(a)!==device(b))throw Object.assign(Error('synthetic EXDEV across device boundary'),{code:'EXDEV'});return rename(a,b);};`);
  const saved=backupPath(succeeds(f.run()));assertActiveDeployment(f,active(f));
  assert.deepEqual(snapshot(f.app),snapshot(path.join(f.expected,'Brew Version.app')));
  assert.deepEqual(fs.readdirSync(f.apps),['Brew Version.app']);
  succeeds(f.run('--rollback',saved));
  assert.deepEqual(snapshot(f.app),snapshot(path.join(saved,'Brew Version.app')));
  assert.deepEqual(fs.readdirSync(f.apps),['Brew Version.app']);
});
for(const payload of ['app','command','receipt','metadata']) for(const failure of ['corrupt','fail']) {
  test(`backup ${payload} ${failure} is rejected before any live mutation`,t=>{
    const f=fixture(t);succeeds(f.run());const before=active(f);
    const inodes=[f.target,f.receipt,f.app].map(p=>fs.statSync(p).ino);f.release('second');
    const suffix=payload==='app'?'/Brew Version.app/Contents/Resources/synthetic.txt':payload==='command'?'/brew-version':payload==='receipt'?'/receipt.json':'/state.json';
    inject(f,`const fs=require('node:fs');const copy=fs.copyFileSync,write=fs.writeFileSync;
      const target=p=>String(p).includes('/.utilities-deploy-backups/')&&String(p).endsWith(${JSON.stringify(suffix)});
      const after=p=>{if(target(p)){${failure==='fail'?"throw Error('synthetic backup write failure');":"write(p,'synthetic corrupt backup');"}}};
      fs.copyFileSync=(a,b,...rest)=>{const result=copy(a,b,...rest);after(b);return result;};
      fs.writeFileSync=(p,...rest)=>{const result=write(p,...rest);after(p);return result;};`);
    const r=f.run();assert.equal(r.status,1,r.stdout);assert.match(r.stderr,/backup.*(hash mismatch|write failure)/i);
    assertActiveDeployment(f,before);assert.deepEqual([f.target,f.receipt,f.app].map(p=>fs.statSync(p).ino),inodes);
  });
}
for(const operation of ['deploy','rollback']) {
  test(`${operation} recovery failure reports both errors and the retained backup`,t=>{
    const f=fixture(t);succeeds(f.run());f.release('second');const saved=backupPath(succeeds(f.run()));
    f.release('third');
    inject(f,`const fs=require('node:fs');const rename=fs.renameSync;let attempts=0;
      fs.renameSync=(a,b)=>{if(b===${JSON.stringify(f.app)})throw Error(++attempts===1?'synthetic original activation error':'synthetic restoration error');return rename(a,b);};`);
    const r=operation==='deploy'?f.run():f.run('--rollback',saved);
    assert.equal(r.status,1);assert.match(r.stderr,/synthetic original activation error/);assert.match(r.stderr,/synthetic restoration error/);
    const backup=/Recovery backup: (.+)/.exec(r.stdout)?.[1];assert.ok(backup,r.stdout);
    assert.ok(r.stderr.includes(backup),r.stderr);assert.ok(fs.existsSync(path.join(backup,'state.json')));
    assert.ok(fs.existsSync(path.join(backup,'Brew Version.app/Contents/Resources/synthetic.txt')));
  });
}
test('running app notice follows replacement and rollback but not already-current deployment',t=>{
  const f=fixture(t),pgrep=path.join(f.base,'synthetic-pgrep');fs.writeFileSync(pgrep,'#!/bin/sh\nexit 0\n',{mode:0o755});
  f.env.BREW_VERSION_DEPLOY_TEST_ONLY_PGREP=pgrep;
  assert.match(succeeds(f.run()).stdout,/Quit and reopen/);
  assert.doesNotMatch(succeeds(f.run()).stdout,/Quit and reopen/);
  f.release('second');const saved=backupPath(succeeds(f.run()));
  assert.match(succeeds(f.run('--rollback',saved)).stdout,/Quit and reopen Brew Version to use/);
});

function cleanupFaults(f,{operation='deploy',activation=false,copy=false,atomic=false}={}) {
  const attempts=path.join(f.base,'synthetic-cleanup-attempts.jsonl');
  inject(f,`const fs=require('node:fs'),path=require('node:path');
    const mkdir=fs.mkdtempSync,remove=fs.rmSync,rename=fs.renameSync,copy=fs.copyFileSync;
    const directories=new Map();let appStages=0,scriptStages=0,activations=0;
    fs.mkdtempSync=(prefix,...args)=>{const directory=mkdir(prefix,...args);
      if(path.dirname(prefix)===${JSON.stringify(f.apps)})directories.set(directory,++appStages===1?${JSON.stringify(operation==='deploy'?'outer-stage':'rollback-stage')}:'restore-stage');
      else if(path.basename(prefix)==='brew-version-build-')directories.set(directory,'scratch');
      else if(path.dirname(prefix)===${JSON.stringify(f.scripts)})directories.set(directory,++scriptStages===1?'atomic-stage':'restore-atomic-stage');
      return directory;};
    fs.rmSync=(directory,...args)=>{const label=directories.get(directory);
      if(label){fs.appendFileSync(${JSON.stringify(attempts)},JSON.stringify({label,directory})+'\\n');
        if(${atomic?"label==='atomic-stage'":"!label.includes('atomic')"})throw Object.assign(Error('synthetic '+label+' cleanup error'),{code:'EIO'});}
      return remove(directory,...args);};
    fs.renameSync=(a,b)=>{
      if(${activation?'true':'false'}&&b===${JSON.stringify(f.app)})throw Error(++activations===1?'synthetic original activation error':'synthetic restoration error');
      if(${atomic?'true':'false'}&&b===${JSON.stringify(f.target)}&&++activations===1)throw Error('synthetic atomic publication error');
      return rename(a,b);};
    fs.copyFileSync=(a,b,...args)=>{if(${copy?'true':'false'}&&String(b).startsWith(${JSON.stringify(f.apps+path.sep)})&&String(b).endsWith('/Resources/synthetic.txt'))throw Error('synthetic app staging copy error');return copy(a,b,...args);};`);
  return ()=>fs.readFileSync(attempts,'utf8').trim().split('\n').map(line=>JSON.parse(line));
}
function assertCleanupEvidence(r,attempts,labels) {
  const cleanup=attempts.filter(entry=>labels.includes(entry.label));
  assert.deepEqual(cleanup.map(entry=>entry.label),labels);
  for(const entry of cleanup) {
    assert.ok(r.stderr.includes('synthetic '+entry.label+' cleanup error'),r.stderr);
    assert.ok(r.stderr.includes(entry.directory),r.stderr);
  }
}
for(const operation of ['deploy','rollback']) {
  test(`${operation} preserves activation and restoration errors through every cleanup failure`,t=>{
    const f=fixture(t);succeeds(f.run());f.release('second');const saved=backupPath(succeeds(f.run())),before=active(f);f.release('third');
    const attempts=cleanupFaults(f,{operation,activation:true});
    const r=operation==='deploy'?f.run():f.run('--rollback',saved);
    assert.equal(r.status,1);assert.match(r.stderr,/synthetic original activation error/);assert.match(r.stderr,/synthetic restoration error/);
    assertCleanupEvidence(r,attempts(),operation==='deploy'?['restore-stage','outer-stage','scratch']:['rollback-stage','restore-stage']);
    const backup=/Recovery backup: (.+)/.exec(r.stdout)?.[1];assert.ok(backup,r.stdout);assert.ok(r.stderr.includes(backup),r.stderr);
    assert.deepEqual(snapshot(path.join(backup,'Brew Version.app')),before[2]);
    assert.equal(snapshot(path.join(backup,'brew-version')).bytes,before[0].bytes);
    assert.equal(snapshot(path.join(backup,'receipt.json')).bytes,before[1].bytes);
  });
  test(`${operation} reports completed activation separately from cleanup failures`,t=>{
    const f=fixture(t);succeeds(f.run());const first=active(f);f.release('second');const saved=backupPath(succeeds(f.run()));
    const attempts=cleanupFaults(f,{operation});
    const r=operation==='deploy'?f.run('--rebuild'):f.run('--rollback',saved);
    assert.equal(r.status,1);assert.match(r.stderr,new RegExp(operation==='deploy'?'Deployment completed':'Rollback completed'));
    assert.match(r.stderr,/cleanup/i);assert.doesNotMatch(r.stderr,/activation failed|restoration failed|deployment failed/i);
    assertCleanupEvidence(r,attempts(),operation==='deploy'?['outer-stage','scratch']:['rollback-stage']);
    const backup=/Recovery backup: (.+)/.exec(r.stdout)?.[1];assert.ok(backup,r.stdout);assert.ok(r.stderr.includes(backup),r.stderr);
    if(operation==='rollback')assertActiveDeployment(f,first);
    else {assert.deepEqual(snapshot(f.app),snapshot(path.join(f.expected,'Brew Version.app')));assertActiveDeployment(f,active(f));delete f.env.NODE_OPTIONS;succeeds(f.run('--audit'));}
  });
}
test('failed app staging copy retains its error while attempting stage and scratch cleanup',t=>{
  const f=fixture(t);succeeds(f.run());const before=active(f);f.release('second');const attempts=cleanupFaults(f,{copy:true});
  const r=f.run();assert.equal(r.status,1);assert.match(r.stderr,/synthetic app staging copy error/);
  assertCleanupEvidence(r,attempts(),['outer-stage','scratch']);assertActiveDeployment(f,before);
});
test('atomic publication error survives atomic cleanup failure and successful recovery',t=>{
  const f=fixture(t);succeeds(f.run());const before=active(f);f.release('second');const attempts=cleanupFaults(f,{atomic:true});
  const r=f.run();assert.equal(r.status,1);assert.match(r.stderr,/synthetic atomic publication error/);
  assertCleanupEvidence(r,attempts(),['atomic-stage']);assertActiveDeployment(f,before);
  const backup=/Recovery backup: (.+)/.exec(r.stdout)?.[1];assert.ok(backup,r.stdout);assert.ok(r.stderr.includes(backup),r.stderr);
});
