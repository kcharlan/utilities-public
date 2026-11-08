import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {atomicFile,externalDirectory,inspectAncestors,regular,exists,parseStagedListing,hashInventory,sha,pruneBackups} from '../../../tools/deployment_files.mjs';
import {runTransaction} from '../../../tools/transaction.mjs';
const prefix='web_games/office_picnic/dist/';
const defaultRepo=fileURLToPath(new URL('../../../',import.meta.url));

export async function deploy({repo=defaultRepo,webroot=process.env.UTILITIES_WEBROOT_DIR||path.join(os.homedir(),'webroot'),backups=path.join(os.homedir(),'.utilities-deploy-backups/office-picnic'),dryRun=false,check=false,rollback}={}){
  if([dryRun,check,Boolean(rollback)].filter(Boolean).length>1)throw Error('Choose one of dry-run, check or rollback');
  repo=fs.realpathSync(repo);webroot=externalDirectory(path.resolve(webroot),repo);
  backups=externalDirectory(path.resolve(backups),repo);
  const target=path.join(webroot,'games/office_picnic');inspectAncestors(target);
  if(backups===webroot||backups.startsWith(webroot+path.sep)||webroot.startsWith(backups+path.sep))throw Error('Backups must be outside webroot');
  let source=[];
  if(!rollback){
    const raw=execFileSync('git',['-C',repo,'ls-files','--stage','-z','--',prefix],{encoding:'utf8'});
    const entries=parseStagedListing(raw);
    if(!entries.some(e=>e.name===prefix+'index.html'))throw Error('Stage the game runtime before deployment');
    for(const e of entries){if(!e.name.startsWith(prefix))throw Error('Invalid runtime path');inspectAncestors(path.dirname(path.join(repo,e.name)));}
    source=hashInventory(repo,entries,true).entries.map(e=>({rel:e.name.slice(prefix.length),bytes:e.bytes,mode:e.permissions}));
  }
  const allowed=new Set(source.map(e=>e.rel));
  const safe=rel=>typeof rel==='string'&&rel.length>0&&!path.isAbsolute(rel)&&!/[\\\x00-\x1f\x7f]/.test(rel)&&rel.split('/').every(p=>p&&p!=='.'&&p!=='..');
  function destination(rel){
    if(!allowed.has(rel)||!safe(rel))throw Error('Invalid deployment inventory');
    const file=path.join(target,rel);inspectAncestors(path.dirname(file));if(exists(file))regular(file);return file;
  }
  function current(rel){const file=destination(rel);return exists(file)?{rel,bytes:fs.readFileSync(file),mode:regular(file).mode&0o7777}:{rel,bytes:null};}
  function matches(item){const old=current(item.rel);return item.bytes===null?old.bytes===null:old.bytes!==null&&old.mode===item.mode&&old.bytes.equals(item.bytes);}
  function publish(items){
    for(const item of items){const file=destination(item.rel);if(item.bytes===null){if(exists(file))fs.unlinkSync(file);}else{fs.mkdirSync(path.dirname(file),{recursive:true,mode:0o755});atomicFile(file,item.bytes,item.mode,'.office-picnic-stage-');}}
  }
  let desired=source;
  if(rollback){
    rollback=path.resolve(rollback);inspectAncestors(rollback);
    if(path.dirname(rollback)!==backups)throw Error('Rollback must name an office-picnic backup');
    const records=JSON.parse(fs.readFileSync(path.join(rollback,'state.json'),'utf8'));const seen=new Set();
    if(!Array.isArray(records)||!records.length)throw Error('Invalid backup');
    desired=records.map(r=>{
      if(!r||!safe(r.rel)||seen.has(r.rel))throw Error('Invalid backup inventory');seen.add(r.rel);allowed.add(r.rel);
      if(r.absent===true)return{rel:r.rel,bytes:null};
      if(!Number.isInteger(r.mode)||r.mode<0||r.mode>0o777||typeof r.hash!=='string')throw Error('Invalid backup metadata');
      const file=path.join(rollback,'payload',r.rel);inspectAncestors(path.dirname(file));regular(file);
      const bytes=fs.readFileSync(file);if(sha(bytes)!==r.hash)throw Error('Backup hash mismatch');return{rel:r.rel,bytes,mode:r.mode};
    });
  }
  const changed=desired.filter(item=>!matches(item));
  if(check){if(changed.length)throw Error('Installed game differs from source or is missing');console.log('Office Picnic installed runtime matches staged source');return;}
  if(dryRun){console.log(`Dry run: ${changed.length} runtime files would change`);return;}
  if(!changed.length){console.log('Office Picnic already matches source');return;}
  const prior=desired.map(item=>current(item.rel));let backup;
  await runTransaction({name:'Office Picnic',admit:()=>{},isCurrent:()=>false,build:()=>({}),
    install:(_value,recover)=>{
      inspectAncestors(backups);fs.mkdirSync(backups,{recursive:true,mode:0o700});fs.chmodSync(backups,0o700);
      backup=fs.mkdtempSync(path.join(backups,'copy-'));fs.chmodSync(backup,0o700);
      const records=prior.map(item=>{
        if(item.bytes===null)return{rel:item.rel,absent:true};
        const file=path.join(backup,'payload',item.rel);fs.mkdirSync(path.dirname(file),{recursive:true,mode:0o700});fs.writeFileSync(file,item.bytes,{mode:0o600});
        return{rel:item.rel,mode:item.mode,hash:sha(item.bytes)};
      });
      fs.writeFileSync(path.join(backup,'state.json'),JSON.stringify(records,null,2)+'\n',{mode:0o600});
      recover(()=>publish(prior));publish(changed);
    },verify:()=>{if(desired.some(item=>!matches(item)))throw Error('Installed bytes or modes failed verification');}
  });
  if(!rollback)pruneBackups(backups);console.log('Office Picnic deployed to /games/office_picnic/index.html');console.log('Recovery backup: '+backup);return backup;
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const options={};
  try{
    for(let i=2;i<process.argv.length;i++){
      const arg=process.argv[i];
      if(arg==='--help'){console.log('Usage: npm run deploy -- [--dry-run | --check | --rollback BACKUP] [--webroot DIR] [--backups DIR]');process.exit(0);}
      if(arg==='--dry-run')options.dryRun=true;
      else if(arg==='--check')options.check=true;
      else if(['--webroot','--backups','--rollback','--repo'].includes(arg)&&process.argv[i+1])options[arg.slice(2)]=process.argv[++i];
      else throw Error('Unknown or incomplete option: '+arg);
    }
    await deploy(options);
  }catch(error){console.error('Office Picnic deployment failed: '+error.message);process.exitCode=1;}
}
