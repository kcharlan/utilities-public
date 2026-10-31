#!/usr/bin/env node
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {execFileSync, spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {regular, inspectAncestors, externalDirectory, sha, exists, atomicFile, parseIndexSnapshot,
  parseStagedListing, normalizeEntries, hashInventory, cleanupDirectories, finishCleanup, pruneBackups} from './deployment_files.mjs';

export const buildInput = name => ['brew_version/Package.swift','brew_version/Makefile'].includes(name) || /^brew_version\/(Resources|Sources|Tests)\//.test(name);
export function sourceInventory(repo, snapshot, requireStaged = false) {
  const listing = snapshot ? parseIndexSnapshot(snapshot) : parseStagedListing(execFileSync('git',['-C',repo,'ls-files','--stage','--sparse','-z','--','brew_version'],{encoding:'utf8'}));
  const entries=normalizeEntries(listing.filter(e=>buildInput(e.name)));
  for(const name of ['Package.swift','Makefile','Resources/Info.plist','Tests/BrewVersionCLITests/Fixtures/expected-help.txt']) {
    if(!entries.some(e=>e.name==='brew_version/'+name)) throw new Error('Required native build input missing: '+name);
  }
  return hashInventory(repo,entries,requireStaged);
}
// This identity includes every entry's complete permission bits, including the root.
export function appTreeHash(bundleDirectory) {
  inspectAncestors(path.dirname(bundleDirectory));
  const hash=crypto.createHash('sha256');
  const entries=[];
  function visit(file,relative) {
    const stat=fs.lstatSync(file);
    if(stat.isSymbolicLink() || (!stat.isDirectory() && !stat.isFile())) throw new Error('App bundle contains symlink or unsupported entry');
    const type=stat.isDirectory()?'directory':'file';
    entries.push({relative,type,mode:stat.mode & 0o7777,content:sha(stat.isFile()?fs.readFileSync(file):Buffer.alloc(0))});
    if(stat.isDirectory()) for(const name of fs.readdirSync(file).sort()) visit(path.join(file,name),relative==='.'?name:relative+'/'+name);
  }
  if(!fs.lstatSync(bundleDirectory).isDirectory()) throw new Error('App bundle must be a directory');
  visit(bundleDirectory,'.');
  entries.sort((a,b)=>a.relative<b.relative?-1:a.relative>b.relative?1:0);
  for(const entry of entries) hash.update(entry.relative+'\0'+entry.type+'\0'+entry.mode.toString(8)+'\0'+entry.content+'\0');
  return hash.digest('hex');
}
// Shared by the native app deployers. SwiftPM writes path-named lock files and TemporaryDirectory.*
// folders to TMPDIR, so the toolchain gets a TMPDIR inside the scratch, removed with it. Each
// compile also leaves a TemporaryDirectory.* holding only an empty .keep-directory in the Darwin
// user temp dir whatever TMPDIR says; after `make release`, even a failed one, new ones holding
// nothing else are removed, as telltale/tools/check_no_temp_leaks.sh does.
export function scratchTmpdir(scratch) {
  const tmp=path.join(scratch,'tmp');
  if(!exists(tmp)) fs.mkdirSync(tmp,{mode:0o700});
  return tmp+'/';
}
export function makeRelease(scratch,project,env={}) {
  const tmp=scratchTmpdir(scratch);
  const darwin=execFileSync('getconf',['DARWIN_USER_TEMP_DIR'],{encoding:'utf8',stdio:'pipe',timeout:10000}).trim();
  const markers=()=>fs.readdirSync(darwin).filter(name=>name.startsWith('TemporaryDirectory.'));
  const before=new Set(markers());
  try {execFileSync('make',['-C',path.join(scratch,project),'release'],{env:{...process.env,...env,TMPDIR:tmp,MAKEFLAGS:'',MFLAGS:'',CFLAGS:'',CPPFLAGS:'',LDFLAGS:''},stdio:'pipe',timeout:900000});}
  finally {
    const kept=[];
    for(const name of markers().filter(name=>!before.has(name))) {
      const directory=path.join(darwin,name),keep=path.join(directory,'.keep-directory');
      try {
        const stat=fs.lstatSync(directory),marker=fs.lstatSync(keep);
        if(!stat.isDirectory() || !marker.isFile() || marker.size || fs.readdirSync(directory).join('/')!=='.keep-directory') {kept.push(name);continue;}
        fs.unlinkSync(keep);fs.rmdirSync(directory);
      } catch {kept.push(name);}
    }
    if(kept.length) console.error('Left '+kept.length+' new TemporaryDirectory.* with other content in '+darwin+': '+kept.join(', '));
  }
}
function copyTree(source,destination) {
  const stat=fs.lstatSync(source);
  if(stat.isSymbolicLink() || (!stat.isDirectory() && !stat.isFile())) throw new Error('App bundle contains symlink or unsupported entry');
  if(stat.isDirectory()) {
    fs.mkdirSync(destination,{mode:0o700});
    for(const name of fs.readdirSync(source)) copyTree(path.join(source,name),path.join(destination,name));
  } else fs.copyFileSync(source,destination);
  fs.chmodSync(destination,stat.mode & 0o7777);
}
function plist(bytes) { return JSON.parse(execFileSync('/usr/bin/plutil',['-convert','json','-o','-','--','-'],{input:bytes,timeout:10000})); }
function expectations(inputs) {
  const info=plist(inputs.entries.find(e=>e.name==='brew_version/Resources/Info.plist').bytes);
  if(!/^\d+\.\d+\.\d+$/.test(info.CFBundleShortVersionString)) throw new Error('Invalid tracked release version');
  return {version:info.CFBundleShortVersionString,help:inputs.entries.find(e=>e.name==='brew_version/Tests/BrewVersionCLITests/Fixtures/expected-help.txt').bytes,info};
}
function diagnostic(command,expected) {
  const bytes=fs.readFileSync(command);
  if(bytes.length<4 || ![0xfeedfacf,0xfeedface,0xcafebabe,0xbebafeca,0xcefaedfe,0xcffaedfe,0xcafebabf,0xbfbafeca].includes(bytes.readUInt32LE(0))) throw new Error('Expected a native Mach-O command');
  for(const flag of ['--version','--help','-h']) {
    const result=spawnSync(command,[flag],{timeout:10000});
    if(result.error) throw result.error;
    if(result.status!==0 || result.signal) throw new Error('Command '+flag+' activation check failed');
    if(result.stderr.length) throw new Error('Command '+flag+' activation check returned unexpected stderr');
    const output=flag==='--version'?Buffer.from('brew-version '+expected.version+'\n'):expected.help;
    if(!result.stdout.equals(output)) throw new Error('Command '+flag+' activation output check failed');
  }
  execFileSync('codesign',['--verify','--strict',command],{stdio:'pipe',timeout:10000});
}
function appDiagnostic(app,expected) {
  appTreeHash(app);
  const info=plist(fs.readFileSync(path.join(app,'Contents/Info.plist')));
  for(const [key,value] of Object.entries({CFBundleShortVersionString:expected.version,CFBundleIdentifier:'local.utilities.brew-version',CFBundleExecutable:'BrewVersion',LSUIElement:true,LSMinimumSystemVersion:'27.0'})) {
    if(info[key]!==value) throw new Error('App Info.plist release contract mismatch: '+key);
  }
  execFileSync('codesign',['--verify','--strict',app],{stdio:'pipe',timeout:10000});
}
function readReceipt(file) {
  if((regular(file).mode & 0o7777)!==0o600) throw new Error('Native receipt must have mode 0600');
  const r=JSON.parse(fs.readFileSync(file));
  if(Object.keys(r).sort().join()!==['schema','sourceHash','version','commandHash','commandMode','appTreeHash'].sort().join() || r.schema!==1 || r.commandMode!==0o755 || !/^\d+\.\d+\.\d+$/.test(r.version) || !['sourceHash','commandHash','appTreeHash'].every(k=>/^[0-9a-f]{64}$/.test(r[k]))) throw new Error('Invalid native deployment receipt');
  return r;
}
function verify(inputs,expected,command,app,receipt) {
  const r=readReceipt(receipt);
  if(r.sourceHash!==inputs.sourceHash || r.version!==expected.version) throw new Error('Native build source drift');
  if((regular(command).mode & 0o7777)!==r.commandMode || sha(fs.readFileSync(command))!==r.commandHash) throw new Error('Command bytes or mode drift');
  if(appTreeHash(app)!==r.appTreeHash) throw new Error('App bytes or mode drift');
}
function backup(command,app,receipt,repo) {
  const root=externalDirectory(path.join(os.homedir(),'.utilities-deploy-backups/brew-version'),repo);
  fs.mkdirSync(root,{recursive:true,mode:0o700});fs.chmodSync(root,0o700);
  const directory=fs.mkdtempSync(path.join(root,'copy-'));fs.chmodSync(directory,0o700);
  const state={schema:1,command:null,receipt:null,appTreeHash:null};
  for(const [key,file,name] of [['command',command,'brew-version'],['receipt',receipt,'receipt.json']]) if(exists(file)) {
    const mode=regular(file).mode & 0o7777,bytes=fs.readFileSync(file);
    fs.writeFileSync(path.join(directory,name),bytes,{mode:0o600});fs.chmodSync(path.join(directory,name),0o600);
    state[key]={mode,hash:sha(bytes)};
  }
  // Capture source identity, then independently re-read every copied payload.
  if(exists(app)) {state.appTreeHash=appTreeHash(app);copyTree(app,path.join(directory,'Brew Version.app'));}
  const metadata=path.join(directory,'state.json'),bytes=Buffer.from(JSON.stringify(state)+'\n');
  fs.writeFileSync(metadata,bytes,{mode:0o600});
  if(!fs.readFileSync(metadata).equals(bytes)) throw new Error('Backup metadata hash mismatch');
  readBackup(directory);
  return directory;
}
function readBackup(directory) {
  inspectAncestors(directory);const metadata=path.join(directory,'state.json');regular(metadata);
  const state=JSON.parse(fs.readFileSync(metadata));
  if(state.schema!==1 || !['command','receipt','appTreeHash'].every(k=>Object.hasOwn(state,k))) throw new Error('Invalid backup state');
  const value={command:null,receipt:null,app:null};
  for(const [key,name] of [['command','brew-version'],['receipt','receipt.json']]) if(state[key]!==null) {
    const entry=state[key];if(!Number.isInteger(entry.mode) || entry.mode<0 || entry.mode>0o7777) throw new Error('Invalid backup mode');
    const file=path.join(directory,name);regular(file);const bytes=fs.readFileSync(file);
    if(sha(bytes)!==entry.hash) throw new Error('Backup file hash mismatch');value[key]={bytes,mode:entry.mode};
  }
  if(state.appTreeHash!==null) {value.app=path.join(directory,'Brew Version.app');if(appTreeHash(value.app)!==state.appTreeHash) throw new Error('Backup app hash mismatch');}
  return value;
}
function stageApp(source,apps,cleanupErrors) {
  const directory=fs.mkdtempSync(path.join(apps,'.brew-version-stage-'));
  try {
    const candidate=source?path.join(directory,'Brew Version.app'):null;
    if(source) {copyTree(source,candidate);if(appTreeHash(candidate)!==appTreeHash(source)) throw new Error('App staging identity mismatch');}
    return {directory,candidate};
  }
  catch(error) {cleanupErrors.push(...cleanupDirectories([directory]));throw error;}
}
function displaceApp(app,staged) {
  if(exists(app)) fs.renameSync(app,path.join(staged.directory,'displaced-app'));
}
function restore(saved,command,app,receipt,apps,cleanupErrors) {
  let staged;
  try {
    if(saved.app || exists(app)) {
      staged=stageApp(saved.app,apps,cleanupErrors);
      displaceApp(app,staged);
      if(staged.candidate) fs.renameSync(staged.candidate,app);
    }
    for(const [key,file] of [['command',command],['receipt',receipt]]) {
      if(saved[key]) atomicFile(file,saved[key].bytes,saved[key].mode,'.brew-version-stage-');else if(exists(file)) fs.unlinkSync(file);
    }
  } finally {if(staged) cleanupErrors.push(...cleanupDirectories([staged.directory]));}
}
function relaunchNotice(version) {
  const r=spawnSync(process.env.BREW_VERSION_DEPLOY_TEST_ONLY_PGREP || 'pgrep',['-f','Brew Version.app/Contents/MacOS/BrewVersion'],{stdio:'pipe',timeout:10000});
  if(r.status===0) console.log('Quit and reopen Brew Version to use '+version+'.');
}
function recover(error,directory,command,app,receipt,apps,cleanupErrors) {
  try {restore(readBackup(directory),command,app,receipt,apps,cleanupErrors);}
  catch(restorationError) {
    throw new AggregateError([error,restorationError], 'Activation failed: '+error.message+'; restoration failed: '+restorationError.message);
  }
  throw error;
}
function finishOperation(primary,cleanupErrors,completedMessage,backup) {
  try {finishCleanup(primary,cleanupErrors,completedMessage,backup);}
  catch(error) {if(!primary) error.deploymentCompleted=true;throw error;}
}
export function main(argv=process.argv.slice(2)) {
  let repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),scripts=path.resolve(process.env.UTILITIES_SCRIPTS_DIR || path.join(os.homedir(),'Library/Scripts')),apps=path.resolve(process.env.UTILITIES_APPS_DIR || path.join(os.homedir(),'Applications'));
  let audit=false,dry=false,rebuild=false,snapshot,rollback;
  for(let i=0;i<argv.length;i++) {
    const arg=argv[i];
    if(arg==='--help') {console.log('Usage: node tools/deploy_brew_version.mjs [--dry-run | --audit | --rollback BACKUP] [--rebuild] [--repo DIR] [--scripts-dir DIR] [--apps-dir DIR] [--source-inventory FILE]');return;}
    if(arg==='--audit') audit=true;else if(arg==='--dry-run') dry=true;else if(arg==='--rebuild') rebuild=true;
    else if(['--repo','--scripts-dir','--apps-dir','--source-inventory','--rollback'].includes(arg) && argv[i+1]) {
      const value=path.resolve(argv[++i]);if(arg==='--repo')repo=value;else if(arg==='--scripts-dir')scripts=value;else if(arg==='--apps-dir')apps=value;else if(arg==='--rollback')rollback=value;else snapshot=value;
    } else throw new Error('Unknown or incomplete argument');
  }
  if(Number(audit)+Number(dry)+Number(Boolean(rollback))>1 || (snapshot&&!audit) || (rebuild&&(audit||rollback))) throw new Error('Incompatible deployment options');
  repo=fs.realpathSync(repo);scripts=externalDirectory(scripts,repo);apps=externalDirectory(apps,repo);
  const command=path.join(scripts,'brew-version'),receipt=path.join(scripts,'.brew-version-native.json'),app=path.join(apps,'Brew Version.app');
  for(const file of [command,receipt]) if(exists(file)) regular(file);
  if(exists(app)) appTreeHash(app);
  if(rollback) {
    const saved=readBackup(rollback);fs.mkdirSync(scripts,{recursive:true});fs.mkdirSync(apps,{recursive:true});
    const current=backup(command,app,receipt,repo);
    console.log('Recovery backup: '+current);
    const cleanupErrors=[];let primary;
    try {
      try {restore(saved,command,app,receipt,apps,cleanupErrors);} catch(error) {recover(error,current,command,app,receipt,apps,cleanupErrors);}
      console.log('Brew Version rollback restored; rollback backup: '+current);
      if(saved.app) relaunchNotice('the restored release');
    } catch(error) {primary=error;}
    finishOperation(primary,cleanupErrors,'Rollback completed, but cleanup failed',current);return;
  }
  const inputs=sourceInventory(repo,snapshot,!audit),expected=expectations(inputs);
  if(audit) {verify(inputs,expected,command,app,receipt);console.log('OK: brew-version native deployment');return;}
  if(dry) {console.log('Dry run: validated tracked native build inputs; no files changed');return;}
  let current=false;
  if(!rebuild) try {verify(inputs,expected,command,app,receipt);diagnostic(command,expected);appDiagnostic(app,expected);current=true;} catch {}
  if(current) {console.log('Brew Version already current; nothing changed');return;}
  const scratch=fs.mkdtempSync(path.join(os.tmpdir(),'brew-version-build-'));
  const cleanupErrors=[];let staged,saved,primary;
  try {
    // `swift --version` also leaves a TemporaryDirectory.* in TMPDIR.
    const env={...process.env,TMPDIR:scratchTmpdir(scratch)};
    try {
      execFileSync('xcrun',['--find','swift'],{env,stdio:'pipe',timeout:10000});
      const swift=execFileSync('xcrun',['swift','--version'],{env,encoding:'utf8',stdio:'pipe',timeout:10000});
      if(!/Swift version ([6-9]|[1-9]\d+)\./.test(swift)) throw new Error('Swift 6 required');
      execFileSync('make',['--version'],{env,stdio:'pipe',timeout:10000});
    } catch {throw new Error('Swift 6 and Xcode Command Line Tools plus make are required; see brew_version/README.md Requirements');}
    for(const entry of inputs.entries) {const file=path.join(scratch,entry.name);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,entry.bytes,{mode:entry.permissions});}
    makeRelease(scratch,'brew_version');
    const built=path.join(scratch,'brew_version/build/release'),builtCommand=path.join(built,'brew-version'),builtApp=path.join(built,'Brew Version.app');
    regular(builtCommand);diagnostic(builtCommand,expected);appDiagnostic(builtApp,expected);
    const bytes=fs.readFileSync(builtCommand),treeHash=appTreeHash(builtApp);
    if(sourceInventory(repo,undefined,true).sourceHash!==inputs.sourceHash) throw new Error('Native inputs changed during build');
    fs.mkdirSync(scripts,{recursive:true,mode:0o755});fs.mkdirSync(apps,{recursive:true,mode:0o755});
    staged=stageApp(builtApp,apps,cleanupErrors);saved=backup(command,app,receipt,repo);
    console.log('Recovery backup: '+saved);
    try {
      atomicFile(command,bytes,0o755,'.brew-version-stage-');diagnostic(command,expected);
      // The existing app is moved, not overwritten; the verified copy protects recovery
      // even if moving or publishing the new bundle fails.
      displaceApp(app,staged);
      fs.renameSync(staged.candidate,app);appDiagnostic(app,expected);
      atomicFile(receipt,Buffer.from(JSON.stringify({schema:1,sourceHash:inputs.sourceHash,version:expected.version,commandHash:sha(bytes),commandMode:0o755,appTreeHash:treeHash})+'\n'),0o600,'.brew-version-stage-');
      verify(inputs,expected,command,app,receipt);diagnostic(command,expected);
    } catch(error) {recover(error,saved,command,app,receipt,apps,cleanupErrors);}
    console.log('Brew Version deployed; rollback backup: '+saved);relaunchNotice(expected.version);
  } catch(error) {primary=error;}
  finally {cleanupErrors.push(...cleanupDirectories([...(staged?[staged.directory]:[]),scratch]));}
  finishOperation(primary,cleanupErrors,'Deployment completed, but cleanup failed',saved);
  if(saved) pruneBackups(path.dirname(saved));
}
if(process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  try {main();} catch(error) {console.error((error.deploymentCompleted?'Brew Version operation completed with cleanup failures: ':'Brew Version deployment failed: ')+error.message);process.exitCode=1;}
}
