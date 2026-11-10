import {COURSE} from './course.js';
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
    tailwinds:[{district:3,fromSlot:3,toSlot:3,y0:70,y1:110,wind:8},{district:4,fromSlot:1,toSlot:1,y0:90,y1:130,wind:8}],
    pickups:[P(0,1,'high',35,4),P(1,2,'underWasher',9,3),P(2,2,'underWasher',6,3),P(3,0,'overFlock',7,9),P(4,0,'overFlock',5,4)],
    rules:{crashPenaltyTicks:180,respawnTicks:24},ratios:[.56,.64,.73,.81,.92]
  },

  rush:{
    id:'rush',name:'Rush Hour',blurb:'Moving hazards and headwinds make the trip more demanding.',prompts:'warnings',
    encounters:[{slot:0,kind:'pigeon',at:.4},{slot:2,kind:'platform',at:.7},
      {slot:1,kind:'platform',at:.6,only:[3]},{slot:1,kind:'pigeon',at:.4,only:[2,4]},
      {slot:3,kind:'squeeze',at:.6,window:45,center:150,only:[4]}],
    liftScale:[1,1,1,1,1],
    tailwinds:[{district:3,fromSlot:4,toSlot:4,y0:100,y1:140,wind:8,lead:100}],
    winds:[1,3].map(j=>({district:3,fromSlot:j,toSlot:j,startAtGap:true,y0:0,y1:400,wind:-3})),
    motion:{from:1,platformY:13,pigeonX:9,pigeonY:9,rate:1,phaseStep:1.3,squeezeStatic:true},
    pickups:[P(0,0,'overFlock',7,6),P(1,1,'high',35,5),P(2,0,'overFlock',5,5),P(3,2,'roofEdge',9,5,6),P(4,0,'overFlock',7,7)],
    rules:{crashPenaltyTicks:300,respawnTicks:24},ratios:[.56,.64,.73,.81,.92]
  },
  overtime:{
    id:'overtime',name:'Overtime',blurb:'A demanding flight with fewer prompts.',prompts:'quiet',
    encounters:[{slot:0,kind:'pigeon',at:.4},{slot:2,kind:'platform',at:.7},
      {slot:1,kind:'platform',at:.6,only:[3]},{slot:1,kind:'pigeon',at:.4,only:[2,4]},
      {slot:3,kind:'squeeze',at:.6,window:30,center:130,only:[2],static:true},
      {slot:3,kind:'squeeze',at:.6,window:30,center:150,only:[3]},
      {slot:3,kind:'squeeze',at:.6,window:30,center:130,only:[4]}],
    washerHeights:{2:155,3:155},roofHeights:{3:{4:60}},flockTops:{4:164},
    tailwinds:[{district:3,fromSlot:2,toSlot:2,y0:70,y1:110,wind:8}],
    liftScale:[.9,.9,.9,.9,.9],
    winds:[...[0,1,2,3,4].map(j=>({district:3,fromSlot:j,toSlot:j,startAtGap:true,y0:0,y1:400,wind:-5})),
      {district:4,fromSlot:4,toSlot:4,startAtGap:true,y0:0,y1:400,wind:-3}],
    motion:{from:1,platformY:14,pigeonX:9,pigeonY:11,rate:1.25,phaseStep:1.3,squeezeSync:8},
    pickups:[P(0,0,'overFlock',5,15),P(1,0,'overFlock',7,18),P(2,0,'overFlock',10,10),P(3,0,'overFlock',32,10),P(4,0,'overFlock',32,10)],
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
  const json=JSON.stringify(stable({tier:gameplay,physics:PHYSICS,course:COURSE}));
  let hash=2166136261;
  for(const byte of new TextEncoder().encode(json)){
    hash^=byte;
    hash=Math.imul(hash,16777619);
  }
  return (hash>>>0).toString(16).padStart(8,'0');
}
