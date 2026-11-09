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
  },

  rush:{
    id:'rush',name:'Rush Hour',blurb:'Moving hazards and headwinds make the trip more demanding.',prompts:'warnings',
    encounters:[{slot:0,kind:'pigeon',at:.4},{slot:2,kind:'platform',at:.7},
      {slot:1,kind:'platform',at:.6,only:[1,3]},{slot:1,kind:'pigeon',at:.4,only:[2,4]},
      {slot:3,kind:'squeeze',at:.6,window:45,center:150,only:[3,4]}],
    liftScale:[1,1,1,1,1],
    winds:[1,3].map(j=>({district:3,fromSlot:j,toSlot:j,startAtGap:true,y0:0,y1:400,wind:-3})),
    motion:{platformY:13,pigeonX:9,pigeonY:9,rate:1,phaseStep:1.3,squeezeStatic:true},
    rules:{crashPenaltyTicks:300,respawnTicks:36},ratios:[.56,.64,.73,.81,.92]
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
