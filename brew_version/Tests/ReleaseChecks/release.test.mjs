import {before, after, test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync,spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const project=fileURLToPath(new URL('../..',import.meta.url));
let scratch,snapshotScratch,app,command,held=[];
const run=(name,args)=>execFileSync(name,args,{stdio:'pipe',timeout:900000});
function assertMinimumRuntime(executable) {
  const metadata=run('vtool',['-show-build',executable]).toString();
  assert.match(metadata,/\bminos 27\.0\b/,executable+'\n'+metadata);
}
before(()=>{
  scratch=fs.mkdtempSync(path.join(os.tmpdir(),'brew-version-synthetic-build-'));fs.chmodSync(scratch,0o700);
  for(const name of ['Package.swift','Makefile','Sources','Resources','Tests']) fs.cpSync(path.join(project,name),path.join(scratch,name),{recursive:true});
  run('make',['-C',scratch,'release']);
  command=path.join(scratch,'build/release/brew-version');app=path.join(scratch,'build/release/Brew Version.app');
  fs.writeFileSync(path.join(app,'Contents/Resources/synthetic-stale.txt'),'synthetic stale signed resource');
  // Use unmistakably invented prior executables, with valid old signatures.
  const prior=path.join(scratch,'synthetic-prior.c');
  fs.writeFileSync(prior,'#include <stdio.h>\nint main(void){puts("synthetic prior executable");return 0;}\n');
  for(const executable of [command,path.join(app,'Contents/MacOS/BrewVersion')]) {
    fs.unlinkSync(executable);run('clang',[prior,'-o',executable]);
    run('codesign',['--force','--sign','-','--timestamp=none',executable]);
  }
  run('codesign',['--force','--sign','-','--timestamp=none',app]);
  for(const executable of [command,path.join(app,'Contents/MacOS/BrewVersion')]) {
    const fd=fs.openSync(executable,'r');held.push({executable,fd,ino:fs.fstatSync(fd).ino,bytes:fs.readFileSync(executable)});
  }
  run('make',['-C',scratch,'release']);
});
after(()=>{
  for(const old of held)fs.closeSync(old.fd);
  if(scratch)fs.rmSync(scratch,{recursive:true});
  if(snapshotScratch)fs.rmSync(snapshotScratch,{recursive:true});
});
test('release removes stale signed resources before sealing the new bundle',()=>{
  assert.equal(fs.existsSync(path.join(app,'Contents/Resources/synthetic-stale.txt')),false);
  run('codesign',['--verify','--strict',app]);run('codesign',['--verify','--strict',command]);
});
test('release preserves previous executable inodes and bytes for existing readers',()=>{
  for(const old of held) {
    assert.notEqual(fs.statSync(old.executable).ino,old.ino,old.executable);
    const bytes=Buffer.alloc(old.bytes.length);assert.equal(fs.readSync(old.fd,bytes,0,bytes.length,0),bytes.length);
    assert.deepEqual(bytes,old.bytes);assert.notDeepEqual(fs.readFileSync(old.executable),old.bytes);
  }
});
test('release plist and both Mach-O products require the supported runtime',()=>{
  const info=JSON.parse(run('plutil',['-convert','json','-o','-',path.join(app,'Contents/Info.plist')]));
  assert.equal(info.LSMinimumSystemVersion,'27.0');
  for(const executable of [command,path.join(app,'Contents/MacOS/BrewVersion')]) assertMinimumRuntime(executable);
});
test('acceptance and prototype builders keep only signed bundles in fresh private homes',()=>{
  // The builders honor TMPDIR, so their own homes land inside this scratch.
  const temporary=path.join(scratch,'tmp'),home=path.join(scratch,'synthetic-home');
  fs.mkdirSync(temporary,{mode:0o700});fs.mkdirSync(home,{mode:0o700});
  for(const [builder,label] of [['build.sh','Private synthetic home: '],['build-settings-prototype.sh','Settings prototype: ']]) {
    const output=execFileSync('zsh',[path.join(scratch,'Tests/Acceptance',builder)],{
      encoding:'utf8',env:{...process.env,HOME:home,TMPDIR:temporary},stdio:'pipe',timeout:900000});
    const value=output.split('\n').find(line=>line.startsWith(label))?.slice(label.length);
    assert.ok(value,output);
    const directory=builder==='build.sh'?value:path.dirname(value);
    assert.equal(path.dirname(fs.realpathSync(directory)),fs.realpathSync(temporary));
    assert.match(path.basename(directory),/^brew-version-acceptance\./);
    assert.equal(fs.statSync(directory).mode & 0o7777,0o700);
    assert.equal(fs.existsSync(path.join(directory,'package')),false,'scratch package must be removed');
    assert.ok(output.includes('Remove when finished: rm -r -- '+directory),output);
    const bundle=builder==='build.sh'?path.join(directory,'Brew Version Synthetic Acceptance.app'):value;
    assertMinimumRuntime(path.join(bundle,'Contents/MacOS/Acceptance'));
  }
  // SwiftPM's lock files and TemporaryDirectory.* folders stay in each home, removed with it.
  const left=fs.readdirSync(temporary);
  assert.equal(left.length,2,left.join('\n'));
  for(const name of left) assert.match(name,/^brew-version-acceptance\.[^.]+$/,'builder left '+name+' in TMPDIR');
});
test('maintained snapshot builder uses the same supported runtime',()=>{
  // A caller-owned home keeps the build for inspection; scratch removal owns it. The renderer
  // requires its home in Foundation's temporary directory, the Darwin user temp dir whatever
  // TMPDIR says (`make test` points TMPDIR into .build/tmp), so this scratch is made there.
  snapshotScratch=fs.mkdtempSync(path.join(execFileSync('getconf',['DARWIN_USER_TEMP_DIR'],{encoding:'utf8'}).trim(),'brew-version-snapshot-test-'));
  fs.chmodSync(snapshotScratch,0o700);
  const home=path.join(snapshotScratch,'snapshots'),temporary=path.join(scratch,'snapshots-tmp');
  fs.mkdirSync(temporary,{mode:0o700});
  const output=execFileSync('zsh',[path.join(scratch,'Tests/Snapshots/build.sh')],{
    encoding:'utf8',env:{...process.env,BREW_VERSION_HARNESS_HOME:home,TMPDIR:temporary},stdio:'pipe',timeout:900000});
  // SwiftPM's lock files and TemporaryDirectory.* folders stay in the caller-owned home.
  assert.deepEqual(fs.readdirSync(temporary),[]);
  assert.ok(output.split('\n').includes('Private snapshots: '+home),output);
  assert.equal(output.includes('Remove when finished'),false,output);
  assert.equal(fs.statSync(home).mode & 0o7777,0o700);
  const binaries=execFileSync('swift',['build','--package-path',path.join(home,'package'),'-c','release','--show-bin-path'],
    {env:{...process.env,TMPDIR:path.join(home,'tmp')+'/'},stdio:'pipe',timeout:900000}).toString().trim();
  assertMinimumRuntime(path.join(binaries,'Snapshots'));
});
test('failed harness builds remove their whole home',()=>{
  const bin=path.join(scratch,'failing-bin'),temporary=path.join(scratch,'failing-tmp');
  fs.mkdirSync(bin,{mode:0o700});fs.mkdirSync(temporary,{mode:0o700});
  fs.writeFileSync(path.join(bin,'swift'),'#!/bin/sh\nexit 7\n',{mode:0o700});
  for(const builder of ['Snapshots/build.sh','Acceptance/build.sh','Acceptance/build-settings-prototype.sh']) {
    const result=spawnSync('zsh',[path.join(scratch,'Tests',builder)],{
      encoding:'utf8',env:{...process.env,PATH:bin+':'+process.env.PATH,TMPDIR:temporary},timeout:60000});
    assert.equal(result.status,7,builder+'\n'+result.stderr);
    assert.deepEqual(fs.readdirSync(temporary),[],builder);
  }
});
