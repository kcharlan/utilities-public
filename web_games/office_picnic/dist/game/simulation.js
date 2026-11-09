import {createPlane,advancePlane,PHYSICS} from './physics.js';
import {buildWorld,airAt,hazardBox,hazardParts,hazardKey,pickupPos} from './world.js';
export function createRun(mode='standard',world=buildWorld()){
  if(!['standard','nonstop'].includes(mode))mode='standard';
  return {mode,world,plane:createPlane(),ticks:0,worldTicks:0,district:0,checkpoint:{...world.districts[0].checkpoint,x:0,y:130},status:'flying',respawnTicks:0,crashes:0,events:['launch'],warned:new Set(),lastAir:null,lastStall:false,cause:'',finishTicks:0,collected:new Set(),bonusTicks:0,crashLog:[],attempts:1};
}
export const netTicks=r=>r.ticks-r.bonusTicks;
export function segmentHitsBox(a,b,box,pad=1.2){
  let lo=0,hi=1;
  for(const [axis,min,max] of [['x',box.x-pad,box.x+box.w+pad],['y',box.y-pad,box.y+box.h+pad]]){
    const delta=b[axis]-a[axis];
    if(Math.abs(delta)<1e-10){if(a[axis]<min||a[axis]>max)return false;}
    else {let u=(min-a[axis])/delta,v=(max-a[axis])/delta;if(u>v)[u,v]=[v,u];lo=Math.max(lo,u);hi=Math.min(hi,v);if(lo>hi)return false;}
  }
  return true;
}
function crash(r,cause,where){r.crashes++;r.status='respawning';r.respawnTicks=r.world.rules.respawnTicks;r.cause=cause;r.events.push('impact');r.crashLog.push({where,x:Math.round(r.plane.x),y:Math.round(r.plane.y),district:r.district});if(r.mode==='standard')r.ticks+=r.world.rules.crashPenaltyTicks;}
function gapAt(world,x){return world.gaps.find(g=>x>=g.x-10&&x<g.end+10)?.id??'?';}
export function stepRun(r,held){
  r.events=[];r.warningHazards=[];
  if(r.status==='finished')return r;
  r.ticks++;r.worldTicks++;
  if(r.status==='landing'){
    const t=Math.min(1,++r.landingTicks/120),ease=t*t*(3-2*t),p=r.plane;
    p.x=r.landingStart.x+(r.world.length-r.landingStart.x)*ease;
    p.y=r.landingStart.y+(25-r.landingStart.y)*ease;
    p.pitch=r.landingStart.pitch+(-.12-r.landingStart.pitch)*ease;
    if(t===1){r.status='finished';r.finishTicks=r.ticks;r.events.push('landing');}
    return r;
  }
  if(r.status==='respawning'){
    if(--r.respawnTicks<=0){
      if(r.mode==='nonstop'){
        const fresh=createRun(r.mode,r.world),crashes=r.crashes,log=r.crashLog,attempts=r.attempts+1;Object.assign(r,fresh);r.crashes=crashes;r.crashLog=log;r.attempts=attempts;
      }else r.plane=createPlane(r.checkpoint);
      r.status='flying';r.warned.clear();r.lastAir=null;r.lastStall=false;r.events=['respawn'];
    }return r;
  }
  const p=r.plane,previous={x:p.x,y:p.y},time=r.worldTicks*PHYSICS.dt;
  const air=airAt(r.world,p,time);advancePlane(p,held,air);
  if(air.source!==r.lastAir&&air.source&&air.source.type!==5)r.events.push('lift');r.lastAir=air.source;
  if(p.stalled!==r.lastStall)r.events.push(p.stalled?'stall':'recovery');r.lastStall=p.stalled;
  if(p.y<2){crash(r,'Street level — use the rising air over rooftops.',`street ${gapAt(r.world,p.x)}`);return r;}
  for(const b of r.world.buildings){
    if(b.x>p.x+3||b.x+b.w<previous.x-3)continue;
    if(segmentHitsBox(previous,p,{x:b.x,y:-1000,w:b.w,h:1000+b.y})){crash(r,b.squeeze?'Squeeze — fly through the window between the washer and the flock.':'Rooftop — enter the lift earlier and carry more height.',`${b.perch?'perch':'roof'} ${gapAt(r.world,p.x)}`);return r;}
  }
  for(const h of r.world.hazards){
    const box=hazardBox(h,time),dx=box.x-p.x;
    const key=hazardKey(h);
    if(dx>0&&dx<h.warningDistance&&!r.warned.has(key)){r.warned.add(key);r.warningHazards.push(h);r.events.push('warning');}
    if(Math.abs(dx)<8+box.w&&hazardParts(h,time).some(part=>segmentHitsBox(previous,p,part))){crash(r,h.squeeze?'Squeeze — fly through the window between the washer and the flock.':h.kind==='pigeon'?'Pigeons — hold earlier to climb over the flock.':'Window washer or cable — release to dive, then level out below.',h.id);return r;}
  }
  for(const base of r.world.pickups){
    if(r.collected.has(base.id))continue;
    const pk=pickupPos(r.world,base,time);
    if(segmentHitsBox(previous,p,{x:pk.x-pk.r,y:pk.y-pk.r,w:pk.r*2,h:pk.r*2},0)){r.collected.add(pk.id);r.bonusTicks+=base.rewardTicks;r.pickupReward=base.rewardTicks;r.events.push('pickup');}
  }
  const next=r.world.districts[r.district+1];
  if(next&&p.x>=next.start){r.district++;if(r.mode==='standard')r.checkpoint={...next.checkpoint};r.events.push('checkpoint','district');}
  if(p.x>=r.world.length){r.status='landing';r.landingTicks=0;r.landingStart={x:p.x,y:p.y,pitch:p.pitch};}
  return r;
}
