// Route version: invalidate development times from the earlier, longer corridor.
const KEY='office-picnic-v4';
export function loadRecords(storage){
  let raw;try{raw=JSON.parse(storage?.getItem(KEY)||'{}');}catch{raw={};}
  const best={};for(const mode of ['standard','nonstop'])if(Number.isFinite(raw?.best?.[mode])&&raw.best[mode]>0)best[mode]=raw.best[mode];
  return {best,muted:raw?.muted===true};
}
export function savePreferences(storage,records){try{storage?.setItem(KEY,JSON.stringify(records));}catch{/* Private browsing may disallow storage. */}}
export function saveResult(storage,mode,seconds,current){
  const records=loadRecords(storage);
  if(current){
    for(const key of ['standard','nonstop']){
      const best=current.best?.[key];
      if(Number.isFinite(best)&&best>0&&(!records.best[key]||best<records.best[key]))records.best[key]=best;
    }
    records.muted=current.muted===true;
  }
  if(['standard','nonstop'].includes(mode)&&Number.isFinite(seconds)&&seconds>0&&(!records.best[mode]||seconds<records.best[mode])){records.best[mode]=seconds;savePreferences(storage,records);}
  return records;
}
