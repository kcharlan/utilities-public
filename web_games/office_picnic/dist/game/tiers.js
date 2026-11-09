import {PHYSICS} from './physics.js';

function freeze(value){
  if(value&&typeof value==='object'){
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}
const P=(district,slot,place,v,reward,dx)=>({district,slot,place,...(place==='high'?{above:v}:{dy:v}),...(dx?{dx}:{}),r:4,rewardTicks:reward*60});
export const TIERS=freeze({
  casual:{
    id:'casual',name:'Casual Friday',blurb:'A relaxed flight to the picnic.',prompts:'full',
    encounters:[{slot:0,kind:'pigeon',at:.4},{slot:2,kind:'platform',at:.7}],
    liftScale:[1,1,1,1,1],winds:[],motion:null,
    pickups:[P(0,1,'high',35,4),P(1,2,'roofEdge',9,5,6),P(2,2,'underWasher',6,3),P(3,0,'overFlock',7,3),P(4,0,'overFlock',5,8)],
    rules:{crashPenaltyTicks:180,respawnTicks:24},ratios:[.56,.64,.73,.81,.92]
  },

  rush:{
    id:'rush',name:'Rush Hour',blurb:'Moving hazards and headwinds make the trip more demanding.',prompts:'warnings',
    encounters:[{slot:0,kind:'pigeon',at:.4},{slot:2,kind:'platform',at:.7},
      {slot:1,kind:'platform',at:.6,only:[1,3]},{slot:1,kind:'pigeon',at:.4,only:[2,4]},
      {slot:3,kind:'squeeze',at:.6,window:45,center:150,only:[3,4]}],
    liftScale:[1,1,1,1,1],
    winds:[1,3].map(j=>({district:3,fromSlot:j,toSlot:j,startAtGap:true,y0:0,y1:400,wind:-3})),
    motion:{platformY:13,pigeonX:9,pigeonY:9,rate:1,phaseStep:1.3,squeezeStatic:true},
    pickups:[P(0,0,'overFlock',7,5),P(1,2,'roofEdge',9,5,6),P(2,0,'overFlock',5,12),P(3,2,'roofEdge',9,5,6),P(4,0,'overFlock',7,5)],
    rules:{crashPenaltyTicks:300,respawnTicks:24},ratios:[.56,.64,.73,.81,.92]
  },
  overtime:{
    id:'overtime',name:'Overtime',blurb:'A demanding flight with fewer prompts.',prompts:'quiet',
    encounters:[{slot:0,kind:'pigeon',at:.4},{slot:2,kind:'platform',at:.7},
      {slot:1,kind:'platform',at:.6,only:[1,3]},{slot:1,kind:'pigeon',at:.4,only:[2,4]},
      {slot:3,kind:'squeeze',at:.6,window:30,center:150,from:1}],
    liftScale:[.9,.9,.9,.9,.9],
    winds:[0,1,2,3,4].map(j=>({district:3,fromSlot:j,toSlot:j,startAtGap:true,y0:0,y1:400,wind:-5})),
    motion:{platformY:14,pigeonX:9,pigeonY:11,rate:1.25,phaseStep:1.3,squeezeSync:8},
    pickups:[P(0,0,'overFlock',5,19),P(1,0,'overFlock',7,10),P(2,0,'overFlock',10,10),P(3,0,'overFlock',28,10),P(4,0,'overFlock',7,10)],
    rules:{crashPenaltyTicks:600,respawnTicks:24},ratios:[.56,.64,.73,.81,.92]
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
