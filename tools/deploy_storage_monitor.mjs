#!/usr/bin/env node
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {regular, inspectAncestors, externalDirectory, sha, exists, atomicFile,
  parseIndexSnapshot, parseStagedListing, normalizeEntries, hashInventory} from './deployment_files.mjs';

const launcherName = 'storage_monitor/storage_monitor';
const nativeInput = name => name === 'storage_monitor/native/Makefile' || name.startsWith('storage_monitor/native/src/');
const files = ['storage_monitor', 'storage_monitor_walk', '.storage_monitor.json'];
function inventory(repo, snapshot, staged) {
  const listing = snapshot ? parseIndexSnapshot(snapshot) : parseStagedListing(execFileSync('git', ['-C', repo, 'ls-files', '--stage', '--sparse', '-z', '--', 'storage_monitor'], {encoding:'utf8'}));
  const entries = normalizeEntries(listing.filter(e => e.name === launcherName || nativeInput(e.name)));
  for (const required of [launcherName, 'storage_monitor/native/Makefile', 'storage_monitor/native/src/storage_monitor_walk.c']) {
    if (!entries.some(e => e.name === required)) throw new Error('Required native build input missing: ' + required);
  }
  if (entries.find(e => e.name === launcherName).mode !== '100755') throw new Error('Launcher must have mode 100755');
  const all = hashInventory(repo, entries, staged);
  const native = hashInventory(repo, entries.filter(e => nativeInput(e.name)), staged);
  const launcher = entries.find(e => e.name === launcherName).bytes;
  return {...all, nativeSourceHash: native.sourceHash, launcher, launcherHash: sha(launcher)};
}
function protocol(inputs) {
  const launcher = /^WALKER_PROTOCOL = (\d+)$/m.exec(inputs.launcher.toString())?.[1];
  const native = /^#define SMW_PROTOCOL (\d+)$/m.exec(inputs.entries.find(e => e.name.endsWith('/src/storage_monitor_walk.c')).bytes.toString())?.[1];
  if (!launcher || !native || launcher !== native) throw new Error(`launcher expects walker protocol ${launcher ?? 'missing'} but native source declares ${native ?? 'missing'}`);
  return Number(native);
}
function readReceipt(file) {
  try {
    if ((regular(file).mode & 0o7777) !== 0o600) throw new Error();
    const r = JSON.parse(fs.readFileSync(file,'utf8'));
    if (r.schema !== 1 || r.launcherMode !== 0o755 || r.walkerMode !== 0o755 || !Number.isSafeInteger(r.protocol) || r.protocol < 1 ||
        !/^\d+\.\d+\.\d+$/.test(r.walkerVersion) || !['launcherHash','nativeSourceHash','walkerHash'].every(k=>/^[a-f0-9]{64}$/.test(r[k]))) throw new Error();
    return r;
  } catch { throw new Error('receipt invalid'); }
}
function matches(file, hash, mode) {
  return exists(file) && (regular(file).mode & 0o7777) === mode && sha(fs.readFileSync(file)) === hash;
}
function version(file, expectedProtocol) {
  const value = execFileSync(file,['--version'],{encoding:'utf8',timeout:10000}).trim();
  const match = /^storage_monitor_walk (\d+\.\d+\.\d+) protocol (\d+)$/.exec(value);
  if (!match || Number(match[2]) !== expectedProtocol) throw new Error('Walker version activation check failed');
  return match[1];
}
function backup(scripts, repo) {
  const root = externalDirectory(path.join(os.homedir(),'.utilities-deploy-backups/storage_monitor'),repo);
  fs.mkdirSync(root,{recursive:true,mode:0o700}); fs.chmodSync(root,0o700);
  const directory = fs.mkdtempSync(path.join(root,'copy-')); fs.chmodSync(directory,0o700);
  const state = {schema:1, files:{}};
  for (const name of files) {
    const source=path.join(scripts,name);
    state.files[name]=null;
    if (exists(source)) {
      const mode=regular(source).mode & 0o7777, bytes=fs.readFileSync(source);
      fs.writeFileSync(path.join(directory,name),bytes,{mode:0o600});
      state.files[name]={mode,hash:sha(bytes)};
    }
  }
  fs.writeFileSync(path.join(directory,'state.json'),JSON.stringify(state)+'\n',{mode:0o600});
  return directory;
}
function readBackup(directory) {
  inspectAncestors(directory); const metadata=path.join(directory,'state.json'); regular(metadata);
  const state=JSON.parse(fs.readFileSync(metadata,'utf8'));
  if (state.schema !== 1 || !state.files || Object.keys(state.files).length !== files.length) throw new Error('Invalid backup state');
  return files.map(name=>{
    if (!Object.hasOwn(state.files,name)) throw new Error('Invalid backup state');
    const entry=state.files[name]; if (entry === null) return null;
    if (!Number.isInteger(entry.mode) || entry.mode < 0 || entry.mode > 0o7777 || !/^[a-f0-9]{64}$/.test(entry.hash)) throw new Error('Invalid backup mode or hash');
    const file=path.join(directory,name); regular(file); const bytes=fs.readFileSync(file);
    if (sha(bytes)!==entry.hash) throw new Error('Backup hash mismatch');
    return {bytes,mode:entry.mode};
  });
}
function restore(saved,scripts) {
  files.forEach((name,i)=>{
    const target=path.join(scripts,name);
    if (saved[i]) atomicFile(target,saved[i].bytes,saved[i].mode,'.storage-monitor-stage-');
    else if (exists(target)) fs.unlinkSync(target);
  });
}
function build(inputs, repo, expectedProtocol) {
  const scratch=fs.mkdtempSync(path.join(os.tmpdir(),'storage-monitor-build-'));
  try {
    for (const entry of inputs.entries.filter(e=>nativeInput(e.name))) {
      const file=path.join(scratch,entry.name); fs.mkdirSync(path.dirname(file),{recursive:true}); fs.writeFileSync(file,entry.bytes,{mode:entry.permissions});
    }
    const env={...process.env, MAKEFLAGS:'', MFLAGS:'', CFLAGS:'', CPPFLAGS:'', LDFLAGS:''};
    execFileSync('make',['-C',path.join(scratch,'storage_monitor/native'),'BUILD_DIR=build','CC=clang','CFLAGS=','CPPFLAGS=','LDFLAGS=','all'],{env,stdio:'pipe',timeout:300000});
    const built=path.join(scratch,'storage_monitor/native/build/storage_monitor_walk'); regular(built);
    const bytes=fs.readFileSync(built);
    if (bytes.length < 4 || ![0xfeedfacf,0xfeedface,0xcafebabe,0xbebafeca,0xcefaedfe,0xcffaedfe,0xcafebabf,0xbfbafeca].includes(bytes.readUInt32LE(0))) throw new Error('Expected a native Mach-O executable');
    const walkerVersion=version(built,expectedProtocol);
    const tree=path.join(scratch,'synthetic tree'); fs.mkdirSync(path.join(tree,'one'),{recursive:true}); fs.mkdirSync(path.join(tree,'two'));
    fs.writeFileSync(path.join(tree,'one','file'),Buffer.alloc(4096)); fs.writeFileSync(path.join(tree,'two','link-one'),'synthetic'); fs.linkSync(path.join(tree,'two','link-one'),path.join(tree,'two','link-two'));
    const fields=execFileSync(built,['walk','--root',tree,'--workers','2','--large-file-bytes','1073741824','--progress-every','2000'],{timeout:10000}).toString().split('\0');
    if (fields.pop() !== '') throw new Error('Walker smoke record framing failed');
    let hardlinks=0, summary;
    for (let i=0;i<fields.length;) {
      const kind=fields[i], size={D:3,L:5,H:7,P:2,S:5}[kind];
      if (!size || i+size>fields.length || summary) throw new Error('Walker smoke records invalid');
      if (kind==='H') hardlinks++;
      if (kind==='S') summary=fields.slice(i,i+size);
      i+=size;
    }
    if (!summary || summary[1]!=='3' || hardlinks!==2) throw new Error('Walker smoke summary or hardlink count failed');
    if (inventory(repo,undefined,true).sourceHash !== inputs.sourceHash) throw new Error('inputs changed during build');
    return {bytes,walkerVersion};
  } finally { fs.rmSync(scratch,{recursive:true,force:true}); }
}
export function main(argv=process.argv.slice(2)) {
  let repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
  let scripts=path.resolve(process.env.UTILITIES_SCRIPTS_DIR || path.join(os.homedir(),'Library/Scripts'));
  let audit=false,dry=false,rebuild=false,snapshot,rollback;
  for (let i=0;i<argv.length;i++) {
    const arg=argv[i];
    if (arg==='--help') { console.log('Usage: node tools/deploy_storage_monitor.mjs [--dry-run | --audit | --rollback BACKUP] [--rebuild] [--repo DIR] [--scripts-dir DIR] [--source-inventory FILE]'); return; }
    if (arg==='--audit') audit=true;
    else if (arg==='--dry-run') dry=true;
    else if (arg==='--rebuild') rebuild=true;
    else if (['--repo','--scripts-dir','--source-inventory','--rollback'].includes(arg) && argv[i+1]) {
      const value=path.resolve(argv[++i]);
      if (arg==='--repo') repo=value; else if (arg==='--scripts-dir') scripts=value; else if (arg==='--rollback') rollback=value; else snapshot=value;
    } else throw new Error('Unknown or incomplete argument');
  }
  if (Number(audit)+Number(dry)+Number(Boolean(rollback))>1 || (snapshot&&!audit) || (rebuild&&(audit||rollback))) throw new Error('Incompatible deployment options');
  repo=fs.realpathSync(repo); scripts=externalDirectory(scripts,repo);
  const [launcher,walker,receipt]=files.map(n=>path.join(scripts,n));
  for (const file of [launcher,walker,receipt]) if (exists(file)) regular(file);
  if (rollback) { const saved=readBackup(rollback); fs.mkdirSync(scripts,{recursive:true}); backup(scripts,repo); restore(saved,scripts); console.log('Storage Monitor rollback restored'); return; }
  const inputs=inventory(repo,snapshot,!audit);
  if (audit) {
    const r=readReceipt(receipt);
    if (r.nativeSourceHash!==inputs.nativeSourceHash) throw new Error('source drift');
    if (!matches(walker,r.walkerHash,r.walkerMode)) throw new Error('walker drift');
    if (r.launcherHash!==inputs.launcherHash || !matches(launcher,inputs.launcherHash,0o755)) throw new Error('launcher drift');
    console.log('OK: storage_monitor deployment'); return;
  }
  const expectedProtocol=protocol(inputs);
  let reason, r;
  if (rebuild) reason='forced';
  else if (!exists(receipt)) reason='no receipt';
  else {
    try { r=readReceipt(receipt); } catch { reason='receipt invalid'; }
    if (!reason && r.nativeSourceHash!==inputs.nativeSourceHash) reason='source changed';
    if (!reason && !exists(walker)) reason='binary missing';
    if (!reason && !matches(walker,r.walkerHash,r.walkerMode)) reason='binary drift';
    if (!reason) { try { if (r.protocol!==expectedProtocol || version(walker,expectedProtocol)!==r.walkerVersion) reason='binary drift'; } catch { reason='binary drift'; } }
  }
  const launcherCurrent=matches(launcher,inputs.launcherHash,0o755);
  console.log('launcher: '+(launcherCurrent?'current':'update'));
  console.log('walker: '+(reason?`rebuild (${reason})`:'current'));
  if (reason) {
    try { execFileSync('xcrun',['--find','clang'],{stdio:'pipe',timeout:10000}); execFileSync('make',['--version'],{stdio:'pipe',timeout:10000}); }
    catch { throw new Error('Xcode Command Line Tools are required to build storage_monitor_walk: run xcode-select --install'); }
  }
  if (dry) { console.log('Dry run: no files changed'); return; }
  if (!reason && launcherCurrent) { console.log('Storage Monitor already current; nothing changed'); return; }
  const built=reason?build(inputs,repo,expectedProtocol):{bytes:fs.readFileSync(walker),walkerVersion:r.walkerVersion};
  fs.mkdirSync(scripts,{recursive:true,mode:0o755});
  const saved=backup(scripts,repo);
  try {
    atomicFile(walker,built.bytes,0o755,'.storage-monitor-stage-');
    atomicFile(launcher,inputs.launcher,0o755,'.storage-monitor-stage-');
    const receiptBytes=Buffer.from(JSON.stringify({schema:1,launcherHash:inputs.launcherHash,launcherMode:0o755,nativeSourceHash:inputs.nativeSourceHash,walkerHash:sha(built.bytes),walkerMode:0o755,walkerVersion:built.walkerVersion,protocol:expectedProtocol})+'\n');
    atomicFile(receipt,receiptBytes,0o600,'.storage-monitor-stage-');
    if (version(walker,expectedProtocol)!==built.walkerVersion) throw new Error('Walker version activation check failed');
  } catch(error) { restore(readBackup(saved),scripts); throw error; }
  console.log('Storage Monitor deployed; rollback backup: '+saved);
}
if (process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  try { main(); } catch(error) { console.error('Storage Monitor deployment failed: '+error.message); process.exitCode=1; }
}
