import {hazardBox,upcomingHazard,pickupPos} from './world.js';
export function chooseInput(run){
  const p=run.plane;
  if(p.stalled||p.speed<14)return false;
  if(p.x>run.world.finishStart)return false;
  const column=run.world.airs.find(a=>p.x>=a.x&&p.x<=a.x+a.w);
  const hazard=upcomingHazard(run.world,p.x);
  let target=column?.targetExit??130;
  if(hazard){
    const b=hazardBox(hazard,run.worldTicks/60),distance=b.x-p.x;
    target=hazard.pass==='above'?b.y+b.h+12+Math.max(0,distance)*.05:b.y-18;
    if(hazard.pass==='below'&&!column)return false;
  }else if(!column)return false;
  return p.y+p.vy*.55<target;
}

export const REFERENCE=Object.freeze({reaction:0,jitter:0,minPress:0,sigma:0,lead:.55,predict:true});
export function sensible(run,prof={}){
  const p=run.plane,w=run.world,t=run.worldTicks/60,lead=prof.lead??.55,bias=prof.biasFor?prof.biasFor(run):0;
  if(p.stalled||p.speed<(prof.minSpeed??14))return false;
  if(p.x>w.finishStart)return false;
  const look=prof.lookahead??300;
  const flockM=(prof.flockMargin??12)+(prof.adapt?.(run,'flock')??0);
  const washM=(prof.washerMargin??18)+(prof.adapt?.(run,'washer')??0);
  const roofM=(prof.roofMargin??8)+(prof.adapt?.(run,'roof')??0);
  const planRatio=prof.planRatio??3;
  const column=w.airs.find(a=>p.x>=a.x&&p.x<=a.x+a.w);
  const arrival=x=>t+Math.max(0,x-p.x)/Math.max(8,p.vx||20);
  let floor=-Infinity,ceiling=Infinity,ceilingDist=Infinity,floorDist=Infinity,squeezeAhead=false;
  for(const h of w.hazards){
    if(h.x+h.w+2<p.x||h.x-p.x>look)continue;
    if(h.squeeze&&h.x-p.x<(prof.squeezeLook??160))squeezeAhead=true;
    // Only the nearest hazard of each kind constrains the plan; later ones are dealt with later.
    if(h.pass==='below'&&Number.isFinite(ceiling))continue;
    if(h.pass==='above'&&Number.isFinite(floor)&&!h.squeeze)continue;
    const now=hazardBox(h,t),then=prof.predict?hazardBox(h,arrival(h.x)):now;
    const d=Math.max(0,now.x-p.x);
    if(h.pass==='above'){
      const margin=h.squeeze?Math.min(flockM,(h.windowTop-h.windowBottom)/2-2):flockM;
      const f=Math.max(now.y,then.y)+h.h+margin+(h.squeeze?0:d*.05);
      if(f>floor){floor=f;floorDist=d;}
    }else{
      const margin=h.squeeze?Math.min(washM,(h.windowTop-h.windowBottom)/2-2):washM;
      const c=Math.min(now.y,then.y)-margin;
      if(c<ceiling){ceiling=c;ceilingDist=d;}
    }
  }
  // Next solid roof (receiving building or perch) within planning range.
  for(const b of w.buildings){
    if(b.x+b.w<p.x)continue;
    const d=Math.max(0,b.x-p.x);if(d>200)continue;
    const f=b.y+roofM+(prof.roofFloorBias??0)+d/planRatio;
    if(f>floor){floor=f;floorDist=d;}
  }
  let preferred=column?(column.targetExit+(prof.columnOffset?.(column)??0)):-Infinity;
  const lane=prof.rideLanes===false?null:w.winds.find(z=>z.wind>0&&p.x>=z.x0-60&&p.x<=z.x1);
  if(lane)preferred=(lane.y0+lane.y1)/2;
  // Going for a pickup overrides the safety margins near it: that is the risk being bought.
  if(prof.pickups){
    const found=w.pickups.find(k=>!run.collected.has(k.id)&&k.x+k.r>p.x&&k.x-p.x<(prof.pickupLook??140)&&prof.pickups(k));
    prof.lastPickup=found?.id??null;
    // Aim where it will be on arrival (attached pickups move with their hazard).
    const pk=found&&pickupPos(w,found,prof.predict?arrival(found.x):t);
    if(pk)return p.y+p.vy*lead<pk.y+(prof.pickupAim??0)+bias*(prof.pickupBias??.5);
  }
  let desired=Math.max(preferred,floor);
  if(desired>ceiling){
    if(floor<=ceiling)desired=squeezeAhead?(floor+ceiling)/2:ceiling; // a window exists: stay inside it
    else desired=floorDist<ceilingDist?floor:ceiling;                  // conflict: nearer constraint wins
  }else if(squeezeAhead&&Number.isFinite(ceiling)&&Number.isFinite(floor))desired=(Math.max(floor,-1e9)+ceiling)/2;
  return p.y+p.vy*lead<desired+bias;
}

export const referenceInput=run=>sensible(run,REFERENCE);
