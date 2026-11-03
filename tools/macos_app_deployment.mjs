import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {regular, inspectAncestors, externalDirectory, sha, exists, atomicFile, parseIndexSnapshot,
  parseStagedListing, normalizeEntries, hashInventory, cleanupDirectories, finishCleanup, pruneBackups, requireMain} from './deployment_files.mjs';
import {appTreeHash,makeRelease,replaceAppFromBackup} from './deploy_brew_version.mjs';
import {runTransaction} from './transaction.mjs';

export function createMacosAppDeployment(config) {
  const {project, appName, executable, contract, helpers, requiredInputs, label, envPrefix, receiptName, backupName, removePrefix, receiptPrefix, buildPrefix, scriptName, repoRoot} = config;
  const buildInput=name=>helpers.includes(name) || ['Package.swift','Makefile'].some(n=>name===project+'/'+n) || new RegExp('^'+project+'/(Sources|Resources|Tests|tools)/').test(name);
function sourceInventory(repo,snapshot) {
  const listing=snapshot?parseIndexSnapshot(snapshot):parseStagedListing(execFileSync('git',['-C',repo,'ls-files','--stage','--sparse','-z','--',project,...helpers],{encoding:'utf8'}));
  const entries=normalizeEntries(listing.filter(e=>buildInput(e.name)));
  for(const name of requiredInputs) {
    if(!entries.some(e=>e.name===name)) throw Error('Required app build input missing: '+name);
  }
  if(!entries.some(e=>e.name.startsWith(project+'/Sources/'))) throw Error('Required app Sources inputs missing');
  // Check every ancestor before hashInventory opens working files.
  for(const entry of entries) inspectAncestors(path.dirname(path.join(repo,entry.name)));
  return hashInventory(repo,entries,true);
}
function info(app) {return JSON.parse(execFileSync('/usr/bin/plutil',['-convert','json','-o','-','--',app],{encoding:'utf8',timeout:10000}));}
function expected(inputs) {
  const bytes=inputs.entries.find(e=>e.name===project+'/Resources/Info.plist').bytes;
  const value=JSON.parse(execFileSync('/usr/bin/plutil',['-convert','json','-o','-','--','-'],{input:bytes,timeout:10000}));
  if(!/^\d+\.\d+\.\d+$/.test(value.CFBundleShortVersionString)) throw Error('Invalid tracked release version');
  for(const [key,wanted] of Object.entries(contract)) if(value[key]!==wanted)throw Error('Tracked Info.plist contract mismatch: '+key);
  return value;
}
function validate(app,expectation,identity,signature=true) {
  appTreeHash(app);
  const value=info(path.join(app,'Contents/Info.plist'));
  const wanted={CFBundleIdentifier:contract.CFBundleIdentifier,CFBundleExecutable:executable,LSMinimumSystemVersion:contract.LSMinimumSystemVersion,LSUIElement:true,CFBundlePackageType:'APPL'};
  if(expectation) for(const key of ['CFBundleName','CFBundleDisplayName','CFBundleShortVersionString','CFBundleVersion']) wanted[key]=expectation[key];
  for(const [key,item] of Object.entries(wanted)) if(value[key]!==item) throw Error('App Info.plist contract mismatch: '+key);
  if(!(regular(path.join(app,'Contents/MacOS',executable)).mode & 0o111)) throw Error('App executable is not executable');
  if(signature) {
    const runtime=execFileSync('vtool',['-show-build',path.join(app,'Contents/MacOS',executable)],{encoding:'utf8',stdio:'pipe',timeout:10000});
    if(!/\bminos 27\.0\b/.test(runtime))throw Error('App executable minimum runtime must be 27.0');
    execFileSync('codesign',['--verify','--strict','-R',`=identifier "${contract.CFBundleIdentifier}" and certificate leaf = H"${identity}"`,app],{stdio:'pipe',timeout:10000});
  }
}
function readReceipt(file) {
  if((regular(file).mode & 0o7777)!==0o600) throw Error('App receipt must have mode 0600');
  const r=JSON.parse(fs.readFileSync(file));
  if(Object.keys(r).sort().join()!==['schema','sourceHash','version','appTreeHash','signingIdentity'].sort().join() || r.schema!==1 || !/^\d+\.\d+\.\d+$/.test(r.version) || !/^[A-F0-9]{40}$/.test(r.signingIdentity) || !['sourceHash','appTreeHash'].every(k=>/^[a-f0-9]{64}$/.test(r[k]))) throw Error('Invalid app deployment receipt');
  return r;
}
function verify(inputs,expectation,app,receipt) {
  const r=readReceipt(receipt);
  if(r.sourceHash!==inputs.sourceHash || r.version!==expectation.CFBundleShortVersionString) throw Error('App source drift');
  if(appTreeHash(app)!==r.appTreeHash) throw Error('App bytes or mode drift');
  validate(app,expectation,r.signingIdentity,false);
  return r;
}
function copy(source,destination) {
  const stat=fs.lstatSync(source);
  if(stat.isSymbolicLink() || (!stat.isDirectory()&&!stat.isFile())) throw Error('Unsupported backup entry');
  if(stat.isDirectory()) {fs.mkdirSync(destination,{mode:0o700});for(const name of fs.readdirSync(source))copy(path.join(source,name),path.join(destination,name));}
  else fs.copyFileSync(source,destination);
  fs.chmodSync(destination,stat.mode & 0o7777);
}
function backup(app,receipt,repo) {
  const root=externalDirectory(path.join(os.homedir(),'.utilities-deploy-backups/'+backupName),repo);
  fs.mkdirSync(root,{recursive:true,mode:0o700});fs.chmodSync(root,0o700);
  const directory=fs.mkdtempSync(path.join(root,'copy-'));fs.chmodSync(directory,0o700);
  const state={schema:1,name:app?path.basename(app):null,appTreeHash:app?appTreeHash(app):null,receipt:null};
  if(app) copy(app,path.join(directory,state.name));
  if(exists(receipt)) {const bytes=fs.readFileSync(receipt);state.receipt={hash:sha(bytes),mode:regular(receipt).mode & 0o7777};fs.writeFileSync(path.join(directory,'receipt.json'),bytes,{mode:0o600});}
  fs.writeFileSync(path.join(directory,'state.json'),JSON.stringify(state)+'\n',{mode:0o600});
  readBackup(directory);return directory;
}
function readBackup(directory) {
  inspectAncestors(directory);if((regular(path.join(directory,'state.json')).mode&0o7777)!==0o600)throw Error('Backup metadata must be private');
  const state=JSON.parse(fs.readFileSync(path.join(directory,'state.json')));
  if(Object.keys(state).sort().join()!==['schema','name','appTreeHash','receipt'].sort().join() || state.schema!==1 || ![null,appName].includes(state.name) || (state.name===null)!==(state.appTreeHash===null)) throw Error('Invalid app backup');
  const app=state.name?path.join(directory,state.name):null;
  if(app && appTreeHash(app)!==state.appTreeHash) throw Error('Backup app hash mismatch');
  let receipt=null;
  if(state.receipt!==null) {
    regular(path.join(directory,'receipt.json'));receipt=fs.readFileSync(path.join(directory,'receipt.json'));
    if(sha(receipt)!==state.receipt.hash || !Number.isInteger(state.receipt.mode) || state.receipt.mode<0 || state.receipt.mode>0o7777) throw Error('Backup receipt hash/mode mismatch');
  }
  return {app,receipt,state};
}
function installed(apps) {
  const current=path.join(apps,appName);
  return exists(current)?current:null;
}
function installer(repo,source,apps,saved,identity,restore=false) {
  execFileSync('bash',[path.join(repo,project,'tools/install.sh'),source],{env:{...process.env,[envPrefix+'_APPS_DIR']:apps,[envPrefix+'_TRANSACTION_BACKUP']:saved,SIGN_IDENTITY:identity,[envPrefix+'_EXPECTED_PLIST']:restore?path.join(source,'Contents/Info.plist'):''},stdio:'pipe',timeout:900000});
}
function restore(repo,value,apps,receipt,saved,identity) {
  const current=installed(apps);
  // Remove a first installation by displacement on the same volume, preserving readers.
  if(!value.app) {
    if(current) {const stage=fs.mkdtempSync(path.join(apps,removePrefix));fs.renameSync(current,path.join(stage,'displaced-app'));finishCleanup(null,cleanupDirectories([stage]),'Restoration cleanup failed',saved);}
  } else {
    const target=path.join(apps,value.state.name);
    replaceAppFromBackup(value.app,target,apps,saved);
    if(appTreeHash(path.join(apps,value.state.name))!==value.state.appTreeHash) throw Error('Restored app hash mismatch');
  }
  if(value.receipt) atomicFile(receipt,value.receipt,value.state.receipt.mode,receiptPrefix);
  else if(exists(receipt)) fs.unlinkSync(receipt);
}
async function main(argv=process.argv.slice(2)) {
  let repo=repoRoot,scripts=path.resolve(process.env.UTILITIES_SCRIPTS_DIR||path.join(os.homedir(),'Library/Scripts')),apps=path.resolve(process.env.UTILITIES_APPS_DIR||'/Applications');
  let dry=false,audit=false,rebuild=false,snapshot,rollback;
  for(let i=0;i<argv.length;i++) {
    const arg=argv[i];
    if(arg==='--help') {console.log('Usage: node tools/'+scriptName+' [--dry-run | --audit | --rollback BACKUP] [--rebuild] [--repo DIR] [--scripts-dir DIR] [--apps-dir DIR] [--source-inventory FILE]');return;}
    if(arg==='--dry-run')dry=true;else if(arg==='--audit')audit=true;else if(arg==='--rebuild')rebuild=true;
    else if(['--repo','--scripts-dir','--apps-dir','--source-inventory','--rollback'].includes(arg)&&argv[i+1]) {const value=path.resolve(argv[++i]);if(arg==='--repo')repo=value;else if(arg==='--scripts-dir')scripts=value;else if(arg==='--apps-dir')apps=value;else if(arg==='--rollback')rollback=value;else snapshot=value;}
    else throw Error('Unknown or incomplete argument');
  }
  if(Number(dry)+Number(audit)+Number(Boolean(rollback))>1 || (snapshot&&!audit) || (rebuild&&(audit||rollback))) throw Error('Incompatible deployment options');
  repo=fs.realpathSync(repo);scripts=externalDirectory(scripts,repo);apps=externalDirectory(apps,repo);
  const receipt=path.join(scripts,receiptName),app=path.join(apps,appName);
  if(audit||dry) {
    const inputs=sourceInventory(repo,snapshot),expectation=expected(inputs);
    if(audit) {if(installed(apps)!==app)throw Error('Canonical app missing');verify(inputs,expectation,app,receipt);console.log('OK: '+backupName+' native deployment');}
    else console.log('Dry run: validated tracked app build inputs; no files changed');
    return;
  }
  let inputs,expectation,identity,previous,saved,scratch;
  const resolveIdentity=bytes=>{
    const value=execFileSync('bash',['-s','--',process.env.SIGN_IDENTITY??'CodexBar Local'],{input:bytes,encoding:'utf8',stdio:'pipe',timeout:10000}).trim();
    if(!/^[A-F0-9]{40}$/.test(value)) throw Error('Invalid signing identity resolver result');
    return value;
  };
  const result=await runTransaction({name:label,
    recovery:rollback?()=>{
      identity=resolveIdentity(execFileSync('git',['-C',repo,'show','HEAD:'+project+'/tools/resolve_signing_identity.sh'],{timeout:10000}));
      const restored=readBackup(externalDirectory(rollback,repo));
      if(restored.app) {validate(restored.app,null,identity);if(restored.receipt){const r=readReceipt(path.join(rollback,'receipt.json'));if(r.appTreeHash!==restored.state.appTreeHash)throw Error('Backup receipt/app provenance mismatch');}}
      previous=installed(apps); if(exists(receipt)) regular(receipt);
      fs.mkdirSync(scripts,{recursive:true,mode:0o755});fs.mkdirSync(apps,{recursive:true,mode:0o755});
      saved=backup(previous,receipt,repo);console.log('Recovery backup: '+saved);
      try {restore(repo,restored,apps,receipt,saved,identity);}
      catch(error) {try {restore(repo,readBackup(saved),apps,receipt,saved,identity);} catch(restoration) {throw new AggregateError([error,restoration],error.message+'; restoration failed: '+restoration.message);} throw error;}
      return saved;
    }:null,
    admit:()=>{requireMain(repo);inputs=sourceInventory(repo);expectation=expected(inputs);identity=resolveIdentity(inputs.entries.find(e=>e.name===project+'/tools/resolve_signing_identity.sh').bytes);previous=installed(apps);if(previous)validate(previous,null,identity);if(exists(receipt))regular(receipt);},
    isCurrent:()=>{if(!rebuild)try {const r=verify(inputs,expectation,app,receipt);if(r.signingIdentity===identity){validate(app,expectation,identity);console.log(label+' already current; nothing changed');return true;}}catch{} return false;},
    build:registerCleanup=>{scratch=fs.mkdtempSync(path.join(os.tmpdir(),buildPrefix));registerCleanup(()=>finishCleanup(null,cleanupDirectories([scratch]),'Deployment cleanup failed',saved));
      for(const entry of inputs.entries) {const file=path.join(scratch,entry.name);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,entry.bytes,{mode:entry.permissions});fs.chmodSync(file,entry.permissions);}
      makeRelease(scratch,project,{SIGN_IDENTITY:identity});const built=path.join(scratch,project,'build/release',appName);validate(built,expectation,identity);if(sourceInventory(repo).sourceHash!==inputs.sourceHash)throw Error('App inputs changed during build');return {value:built};},
    install:(built,registerRecovery)=>{fs.mkdirSync(scripts,{recursive:true,mode:0o755});fs.mkdirSync(apps,{recursive:true,mode:0o755});saved=backup(previous,receipt,repo);console.log('Recovery backup: '+saved);registerRecovery(()=>restore(repo,readBackup(saved),apps,receipt,saved,identity));
      const hash=appTreeHash(built);installer(scratch,built,apps,saved,identity);validate(app,expectation,identity);atomicFile(receipt,Buffer.from(JSON.stringify({schema:1,sourceHash:inputs.sourceHash,version:expectation.CFBundleShortVersionString,appTreeHash:hash,signingIdentity:identity})+'\n'),0o600,receiptPrefix);return saved;},
    verify:()=>verify(inputs,expectation,app,receipt)
  });
  if(result&&!rollback)pruneBackups(path.dirname(result));
  if(result)console.log(label+' '+(rollback?'rollback restored':'deployed')+'; rollback backup: '+result+'\nQuit and reopen '+label+' when convenient; the current process remains running.');
}
  return {buildInput, sourceInventory, main};
}
