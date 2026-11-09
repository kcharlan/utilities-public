import {PHYSICS} from './physics.js';

function freeze(value){
  if(value&&typeof value==='object'){
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}
export const TIERS=freeze({
  casual:{
    id:'casual',name:'Casual Friday',blurb:'A relaxed flight to the picnic.',prompts:'full',
    encounters:[{slot:0,kind:'pigeon',at:.4},{slot:2,kind:'platform',at:.7}],
    liftScale:[1,1,1,1,1],winds:[],motion:null,
    rules:{crashPenaltyTicks:180,respawnTicks:36},ratios:[.56,.64,.73,.81,.92]
  }
});
function stable(value){
  if(Array.isArray(value))return value.map(stable);
  if(value&&typeof value==='object'){
    return Object.fromEntries(Object.keys(value).sort().map(key=>[key,stable(value[key])]));
  }
  return value;
}
export function tierHash(tier){
  const {name,blurb,prompts,...gameplay}=tier;
  const json=JSON.stringify(stable({tier:gameplay,physics:PHYSICS}));
  let hash=2166136261;
  for(const byte of new TextEncoder().encode(json)){
    hash^=byte;
    hash=Math.imul(hash,16777619);
  }
  return (hash>>>0).toString(16).padStart(8,'0');
}
