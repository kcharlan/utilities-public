import {TIERS} from './tiers.js';
const KEY='office-picnic-v5',OLD_KEY='office-picnic-v4';
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
    const old=JSON.parse(storage?.getItem(OLD_KEY)||'{}');
    return clean({best:{casual:old?.best},muted:old?.muted});
  }catch{return clean({});}
}
export function savePreferences(storage,records){try{storage?.setItem(KEY,JSON.stringify(clean(records)));}catch{/* Storage can be unavailable. */}}
export function saveResult(storage,tier,mode,seconds,current){
  const records=loadRecords(storage),session=clean(current);
  for(const [id,values] of Object.entries(session.best))for(const [key,value] of Object.entries(values)){
    const best=records.best[id]??={};
    if(!best[key]||value<best[key])best[key]=value;
  }
  if(current){records.tier=session.tier;records.muted=session.muted;}
  if(validTier(tier)&&modes.includes(mode)&&Number.isFinite(seconds)&&seconds>0){
    const best=records.best[tier]??={};
    if(!best[mode]||seconds<best[mode])best[mode]=seconds;
    savePreferences(storage,records);
  }
  return records;
}
