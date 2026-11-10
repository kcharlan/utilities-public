import {TIERS} from './tiers.js';
import {medalFor} from './medals.js';
import {formatTime} from './session.js';
const KEY='office-picnic-v7',OLD_KEY='office-picnic-v6';
const modes=['standard','nonstop'];
function validTier(id){return typeof id==='string'&&Object.hasOwn(TIERS,id);}
function clean(raw){
  const best={};
  for(const tier of Object.keys(TIERS)){
    const values={};
    for(const mode of modes){const n=raw?.best?.[tier]?.[mode];if(Number.isFinite(n)&&n>0)values[mode]=n;}
    if(Object.keys(values).length)best[tier]=values;
  }
  return {best,tier:validTier(raw?.tier)?raw.tier:'casual',muted:raw?.muted===true};
}
export function loadRecords(storage){
  try{
    const saved=storage?.getItem(KEY);
    if(saved!==null&&saved!==undefined)return clean(JSON.parse(saved));
    const previous=storage?.getItem(OLD_KEY);
    if(previous===null||previous===undefined)return clean({});
    const old=JSON.parse(previous),migrated=clean({tier:old?.tier,muted:old?.muted});
    write(storage,migrated);
    return migrated;
  }catch{return clean({});}
}
function write(storage,records){try{storage?.setItem(KEY,JSON.stringify(clean(records)));}catch{/* Storage can be unavailable. */}}
function mergeBests(records,session){
  for(const [id,values] of Object.entries(session.best))for(const [key,value] of Object.entries(values)){
    const best=records.best[id]??={};
    if(!best[key]||value<best[key])best[key]=value;
  }
}
export function savePreferences(storage,current,changes){
  const session=clean(current),records=loadRecords(storage);
  mergeBests(records,session);
  if(validTier(changes?.tier))records.tier=session.tier=changes.tier;
  if(typeof changes?.muted==='boolean')records.muted=session.muted=changes.muted;
  write(storage,records);
  return {...records,tier:session.tier,muted:session.muted};
}
export function finishResult(storage,tier,mode,seconds,current){
  const records=loadRecords(storage),session=clean(current);
  mergeBests(records,session);
  const valid=validTier(tier)&&modes.includes(mode);
  const previous=valid?records.best[tier]?.[mode]:undefined;
  if(valid&&Number.isFinite(seconds)&&seconds>0){
    const best=records.best[tier]??={};
    if(!best[mode]||seconds<best[mode])best[mode]=seconds;
    write(storage,records);
  }
  return {records:current?{...records,tier:session.tier,muted:session.muted}:records,previous};
}
export function saveResult(storage,tier,mode,seconds,current){return finishResult(storage,tier,mode,seconds,current).records;}

export function titleBestText(records,tier){
  const best=records.best[tier]||{};
  const describe=mode=>best[mode]
    ?`${formatTime(best[mode])} · ${medalFor(tier,best[mode])||'no medal'}`
    :'—';
  return `Standard: ${describe('standard')} / Nonstop: ${describe('nonstop')}`;
}
