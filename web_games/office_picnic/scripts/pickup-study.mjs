import {buildWorld} from '../dist/game/world.js';
import {createRun,stepRun} from '../dist/game/simulation.js';
import {createPlane} from '../dist/game/physics.js';
import {sensible} from '../dist/game/bot.js';
import {makePilot,PROFILES} from './pilot.mjs';

export const MENU=[
  {slot:0,place:'overFlock',dy:5},{slot:0,place:'overFlock',dy:7},{slot:0,place:'overFlock',dy:10},
  {slot:2,place:'underWasher',dy:6},{slot:2,place:'underWasher',dy:9},
  {slot:2,place:'roofEdge',dy:6,dx:6},{slot:2,place:'roofEdge',dy:9,dx:6},
  {slot:1,place:'high',above:25},{slot:1,place:'high',above:35}
];
const CROSSWIND_EXTENSION=[
  {slot:0,place:'overFlock',dy:14},{slot:0,place:'overFlock',dy:18},{slot:0,place:'overFlock',dy:22},{slot:0,place:'overFlock',dy:28},
  {slot:0,place:'high',above:15},{slot:0,place:'high',above:25},{slot:4,place:'high',above:20},{slot:4,place:'high',above:30},
  {slot:3,place:'roofEdge',dy:9,dx:6},{slot:0,place:'roofEdge',dy:9,dx:6}
];
export const rewardPrice=(penalty,be)=>be===null?null:Math.max(penalty,Math.ceil(be));
export const menuCandidates=(tier,district)=>tier==='overtime'&&district===3?[...MENU,...CROSSWIND_EXTENSION]:MENU;
export const menuSampleSize=(n,diagnostic)=>diagnostic?n:100;
export function pickupCoverage(tier,world){
  const configured=tier.pickups??[];
  return world.pickups.length===configured.length&&world.pickups.every((pk,i)=>pk.sourceIndex===i);
}
function districtRun(world,profile,seed,d,extra={}){
  const r=createRun('standard',world),pilot=makePilot(profile,seed,extra);
  r.district=d.index;
  r.checkpoint={...d.checkpoint};
  r.plane=createPlane({...d.checkpoint});
  for(let n=0;n<60*600&&r.plane.x<d.end;n++){
    stepRun(r,pilot(r));
  }
  return {seconds:r.ticks/60,crashes:r.crashes,ids:r.collected,done:r.plane.x>=d.end};
}
export function pickupGrid(world,pk){
  const d=world.districts[pk.district];
  let successes=0;
  for(const speed of [22,26,30]){
    for(const dy of [-6,0,6]){
      for(const delay of [0,3,6]){
        const r=createRun('standard',world);
        r.district=d.index;
        r.checkpoint={...d.checkpoint};
        r.plane=createPlane({...d.checkpoint,speed,y:d.checkpoint.y+dy});
        const prof={...PROFILES.ideal,pickups:k=>k.id===pk.id};
        let held=false;
        for(let n=0;n<60*150&&r.plane.x<d.end&&!r.crashes;n++){
          if(n%(delay+1)===0){
            held=sensible(r,prof);
          }
          stepRun(r,held);
        }
        if(!r.crashes&&r.collected.has(pk.id)&&r.plane.x>=d.end){
          successes++;
        }
      }
    }
  }
  return successes;
}
export function pricePickup(world,pk,n=100){
  const d=world.districts[pk.district];
  let col=0,inc=0,dt=0,dc=0,timeouts=0;
  for(let i=0;i<n;i++){
    const base=districtRun(world,PROFILES.regular,11000+i,d);
    const target=districtRun(world,PROFILES.regular,11000+i,d,{pickups:k=>k.id===pk.id});
    col+=target.ids.has(pk.id);
    inc+=base.ids.has(pk.id);
    dt+=target.seconds-base.seconds;
    dc+=target.crashes-base.crashes;
    timeouts+=!base.done||!target.done;
  }
  const be=col>inc?+(Math.max(0,dt/n)/((col-inc)/n)).toFixed(1):null;
  const penalty=world.rules.crashPenaltyTicks/60;
  const reward=rewardPrice(penalty,be),grid=pickupGrid(world,pk);
  const qualifies=grid>=20&&inc/n<=.3&&col>inc&&!timeouts&&
    reward!==null&&reward<=3*penalty;
  return {...pk.placement,district:pk.district+1,label:pk.label,samples:n,grid,
    collected:col,onPath:inc,crashDelta:dc/n,be,reward,timeouts,qualifies};
}
export function pickupMenu(tier,n=100){
  const rows=[];
  for(let district=0;district<5;district++){
    const candidates=menuCandidates(tier.id,district).map(m=>({...m,district,r:4,rewardTicks:0}));
    const world=buildWorld(undefined,{...tier,pickups:candidates});
    for(const pk of world.pickups){
      rows.push(pricePickup(world,pk,n));
    }
  }
  return rows;
}
