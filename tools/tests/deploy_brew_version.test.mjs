import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync, spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {buildInput, sourceInventory, appTreeHash} from '../deploy_brew_version.mjs';
import {sha} from '../deployment_files.mjs';
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
  const scripts=path.join(home,'Library/Scripts'),apps=path.join(home,'Applications');
  fs.mkdirSync(project,{recursive:true}); fs.mkdirSync(scripts,{recursive:true}); fs.mkdirSync(apps);
  const write=(n,b)=>{const p=path.join(project,n);fs.mkdirSync(path.dirname(p),{recursive:true});fs.writeFileSync(p,b);};
  const git=(...a)=>execFileSync('git',['-C',repo,...a],{stdio:'pipe'});
  git('init','-q');git('config','user.name','Synthetic Tester');git('config','user.email','tester@example.invalid');
  write('Package.swift','// synthetic package\n');write('Resources/Info.plist',plist);write('Tests/BrewVersionCLITests/Fixtures/expected-help.txt',help);
  write('Makefile',`release:\n\tclang Sources/main.c -o synthetic-command\n\tmkdir -p 'build/release/Brew Version.app/Contents/MacOS' 'build/release/Brew Version.app/Contents/Resources'\n\tcp synthetic-command build/release/brew-version\n\tcp synthetic-command 'build/release/Brew Version.app/Contents/MacOS/BrewVersion'\n\tcp Resources/Info.plist 'build/release/Brew Version.app/Contents/Info.plist'\n\tcp Sources/main.c 'build/release/Brew Version.app/Contents/Resources/synthetic.txt'\n\tchmod 751 'build/release/Brew Version.app'\n\tchmod 711 'build/release/Brew Version.app/Contents/Resources'\n\tchmod 640 'build/release/Brew Version.app/Contents/Resources/synthetic.txt'\n\tcodesign --force --sign - --timestamp=none build/release/brew-version\n\tcodesign --force --sign - --timestamp=none 'build/release/Brew Version.app'\n\trm -rf "$$SYNTHETIC_EXPECTED_RELEASE/Brew Version.app"\n\tcp -pR build/release/. "$$SYNTHETIC_EXPECTED_RELEASE/"\n`);
  function release(label,fail=false) {
    write('Sources/main.c',`#include <stdio.h>\n#include <string.h>\nint main(int argc,char **argv){/* synthetic ${label} */ if(${fail?1:0} && strstr(argv[0],"/Scripts/")) return 1; if(argc==2 && !strcmp(argv[1],"--version")){puts("brew-version ${version}");return 0;} if(argc==2 && (!strcmp(argv[1],"--help") || !strcmp(argv[1],"-h"))){fputs(${JSON.stringify(help.toString())},stdout);return 0;}return 2;}\n`);
    git('add','.');git('commit','-qm','Synthetic '+label);
  }
  release('first');
  const expected=path.join(base,'independent-release');fs.mkdirSync(expected);
  const env={...process.env,HOME:home,TMPDIR:base,BREW_VERSION_DEPLOY_PGREP:"/usr/bin/false",SYNTHETIC_EXPECTED_RELEASE:expected};
  const run=(...args)=>spawnSync(process.execPath,[script,'--repo',repo,'--scripts-dir',scripts,'--apps-dir',apps,...args],{encoding:'utf8',env});
  return {base,repo,home,project,scripts,apps,expected,git,write,release,run,env,target:path.join(scripts,'brew-version'),receipt:path.join(scripts,'.brew-version-native.json'),app:path.join(apps,'Brew Version.app')};
}
const backupPath=r=>r.stdout.trim().split('rollback backup: ')[1].split('\n')[0];
test('buildInputs',()=>{
  for(const n of ['Package.swift','Makefile','Sources/a.swift','Tests/a.txt','Resources/a']) assert.equal(buildInput('brew_version/'+n),true,n);
  for(const n of ['README.md','build/release/a','.build/a']) assert.equal(buildInput('brew_version/'+n),false,n);
  assert.equal(buildInput('other/Makefile'),false);
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
test('runningAppGetsRelaunchNotice',t=>{const f=fixture(t),pgrep=path.join(f.base,'synthetic-pgrep');fs.writeFileSync(pgrep,'#!/bin/sh\nexit 0\n',{mode:0o755});f.env.BREW_VERSION_DEPLOY_PGREP=pgrep;assert.match(succeeds(f.run()).stdout,new RegExp('Quit and reopen Brew Version to use '+version.replaceAll('.','\\.')+'\\.'));});
test('bundleWithSymlinkIsRefused',t=>{const f=fixture(t);f.write('Makefile',fs.readFileSync(path.join(f.project,'Makefile'),'utf8')+"\tln -s Info.plist 'build/release/Brew Version.app/Contents/synthetic-link'\n");f.git('add','.');const r=f.run();assert.equal(r.status,1);assert.match(r.stderr,/symlink|unsupported/i);assert.equal(fs.existsSync(f.target),false);});
test('appTreeHash uses sorted root, entry types, full modes and empty directory content',t=>{
  const f=fixture(t),tree=path.join(f.base,'synthetic-tree');fs.mkdirSync(tree,{mode:0o751});fs.mkdirSync(path.join(tree,'z'),{mode:0o711});fs.writeFileSync(path.join(tree,'a'),'synthetic',{mode:0o640});fs.writeFileSync(path.join(tree,'z.b'),'synthetic sibling',{mode:0o600});fs.writeFileSync(path.join(tree,'z/n'),'synthetic nested',{mode:0o600});
  const records=[['.','directory','751',''],['a','file','640','synthetic'],['z','directory','711',''],['z.b','file','600','synthetic sibling'],['z/n','file','600','synthetic nested']];
  const expected=sha(Buffer.from(records.map(([n,type,mode,bytes])=>[n,type,mode,sha(Buffer.from(bytes)),''].join('\0')).join('')));
  assert.equal(appTreeHash(tree),expected);
});
test('failed move of prior app retains validated backup for restoration',t=>{
  const f=fixture(t);succeeds(f.run());const expected=active(f);f.release('second');
  const hook=path.join(f.base,'synthetic-move-failure.cjs');fs.writeFileSync(hook,`const fs=require('node:fs');const original=fs.renameSync;fs.renameSync=function(a,b){if(a===${JSON.stringify(f.app)})throw Object.assign(Error('synthetic cross-device move'),{code:'EXDEV'});return original(a,b);};`);
  f.env.NODE_OPTIONS='--require='+JSON.stringify(hook);const r=f.run();assert.equal(r.status,1);assert.match(r.stderr,/synthetic cross-device move/);assertActiveDeployment(f,expected);
});
test('missing and drifted command or app rebuild the complete release together',t=>{
  const f=fixture(t);succeeds(f.run());
  for(const mutate of [()=>fs.unlinkSync(f.target),()=>fs.appendFileSync(f.target,'synthetic drift'),()=>fs.rmSync(f.app,{recursive:true}),()=>fs.appendFileSync(path.join(f.app,'Contents/Resources/synthetic.txt'),'synthetic drift')]) {
    mutate();assert.match(succeeds(f.run()).stdout,/rollback backup:/);assert.deepEqual(snapshot(f.target),snapshot(path.join(f.expected,'brew-version')));assert.deepEqual(snapshot(f.app),snapshot(path.join(f.expected,'Brew Version.app')));assertActiveDeployment(f,active(f));succeeds(f.run('--audit'));
  }
});
