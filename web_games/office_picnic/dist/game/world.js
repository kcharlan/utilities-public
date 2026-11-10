import {TIERS} from './tiers.js';
import {measureFlight} from './measure.js';
import {clamp,PHYSICS} from './physics.js';
export const THEMES=[
  {name:'Glass Mile',feature:'AC updraft',tip:'Climb over the flock, then release early to pass under the washers.',color:'#9eabc9'},
  {name:'Boiler Row',feature:'Pulsing vents',tip:'Steam bursts push upward automatically; the lull gives little lift.',color:'#efb391'},
  {name:'Sunward Roofs',feature:'Rooftop heat',tip:'Warm roofs add gentle upward push. Pitching up still spends airspeed.',color:'#edc583'},
  {name:'Crosswind Court',feature:'Wind lanes',tip:'Follow the ribbons. Tailwinds carry you farther.',color:'#b7c5bd'},
  {name:'Park Approach',feature:'Fading thermals',tip:'Lift fades near the dotted ceiling. Save height for the park.',color:'#b8c699'}
];
// Each row starts with the teaching crossing, followed by the five numbered slots.
export const COURSE=[
  {types:[0,0,0,0,0,0],widths:[30,200,170,170,170,170],roofs:[40,40,40,40,85,110],entries:[150,184,170,142,170,170],flockTop:151.04477807272335,washerY:144},
  {types:[1,0,1,0,0,1],widths:[30,170,200,170,170,350],roofs:[45,45,45,45,45,45],entries:[150,184,170,142,170,210],flockTop:149.5161424549638,washerY:144,laterFlock:160},
  {types:[2,0,2,1,1,2],widths:[30,170,220,200,200,280],roofs:[55,55,55,55,55,55],entries:[150,184,170,142,170,210],flockTop:147.73273423424436,washerY:144,laterFlock:160},
  {types:[3,1,0,2,2,3],widths:[30,200,170,220,220,350],roofs:[65,65,65,65,65,65],entries:[150,184,170,142,170,210],flockTop:146.20409861648483,washerY:144,laterFlock:160,lanes:[{slot:-1,y0:130,y1:170,wind:2,teaching:true}]},
  {types:[4,0,1,2,3,4],widths:[30,170,200,220,170,280],roofs:[75,75,75,75,75,75],entries:[150,184,170,142,170,210],flockTop:143.91114518984554,washerY:144,laterFlock:160}
];
export function buildWorld(limits=measureFlight(),cfg=TIERS.casual){
  const safeRange=limits.envelopes.find(e=>e.speed===18&&e.drop===50).range;
  const world={districts:[],airs:[],buildings:[],hazards:[],gaps:[],winds:[],pickups:[],length:0,limits,rules:cfg.rules,tier:cfg};
  if(cfg.encounters.some(e=>e.slot===4&&(e.kind==='platform'||e.kind==='squeeze')))throw new Error('Unsafe encounter in final slot');
  let x=0;const slots=[];
  for(let d=0;d<5;d++){
    const start=x, gap=Math.floor(safeRange*cfg.ratios[d]);
    const district={...THEMES[d],index:d,start,checkpoint:{x:start+12,y:150,speed:26,pitch:PHYSICS.divePitch}};
    for(let j=-1;j<5;j++){
      const row=COURSE[d],k=j+1,type=row.types[k],width=row.widths[k],roof=row.roofs[k],entryHeight=row.entries[k];
      const gapId=`${d+1}.${j<0?'T':j+1}`;
      const air={x,w:width,y:roof+4,top:230,type,phase:j*.7,district:d,targetExit:entryHeight,gapId,liftScale:cfg.liftScale[type]};
      world.airs.push(air);
      const building={x:x-10,y:roof,w:width+20,h:100,type,district:d};
      world.buildings.push(building);
      const release=x+width;
      world.gaps.push({id:gapId,district:d,x:release,end:release+gap,length:gap,entryHeight,entrySpeed:18,entryPitch:PHYSICS.divePitch,clearance:entryHeight-50,drop:50,measuredRange:safeRange,utilization:gap/safeRange});
      slots.push({d,j,x,width,release,gap,building,slotHazards:[]});
      const encounters=j===4&&d>0?[...cfg.encounters,{slot:4,kind:'pigeon',at:.4,top:row.laterFlock}]:cfg.encounters;
      for(const e of encounters){
        if(e.slot!==j||(e.from??0)>d||(e.until??9)<d||(e.only&&!e.only.includes(d)))continue;
        const slot=slots[slots.length-1];
        if(e.kind==='pigeon'){
          const top=e.top??row.flockTop;
          const hazard={id:j===0?`h${d}-over`:`h${d}-${j}-over`,district:d,slot:j,kind:'pigeon',pass:'above',x:release+gap*e.at,y:top-16,w:24,h:16,phase:0,warningDistance:360,moving:false};
          world.hazards.push(hazard);slot.slotHazards.push(hazard);
          // A flock lifting from a raised roof makes the low route visibly solid.
          world.buildings.push({x:hazard.x-6,y:hazard.y-2,w:hazard.w+12,h:100,type:0,district:d,perch:true});
        }else if(e.kind==='platform'){
          const upperSuspension=230+limits.maxPullUpClimb+20;
          const hazard={id:j===2?`h${d}-under`:`h${d}-${j}-under`,district:d,slot:j,kind:'platform',pass:'below',x:release+gap*e.at,y:e.y??row.washerY,w:45,h:30,suspensionTop:upperSuspension,phase:0,warningDistance:250,moving:false};
          world.hazards.push(hazard);slot.slotHazards.push(hazard);
        }else if(e.kind==='squeeze'){
          // A perched flock directly under a washer: the only route threads the window.
          const washerY=e.center!=null?e.center+e.window/2:(e.y??row.washerY),cx=release+gap*e.at,flockTop=washerY-e.window;
          const upperSuspension=230+limits.maxPullUpClimb+20;
          const flock={id:`h${d}-${j}-sq-over`,district:d,slot:j,kind:'pigeon',pass:'above',squeeze:true,static:e.static===true,windowTop:washerY,windowBottom:flockTop,x:cx-12,y:flockTop-16,w:24,h:16,phase:0,warningDistance:360,moving:false};
          const washer={id:`h${d}-${j}-sq-under`,district:d,slot:j,kind:'platform',pass:'below',squeeze:true,static:e.static===true,windowTop:washerY,windowBottom:flockTop,x:cx-22.5,y:washerY,w:45,h:30,suspensionTop:upperSuspension,phase:0,warningDistance:250,moving:false};
          world.hazards.push(washer,flock);slot.slotHazards.push(washer,flock);
          world.buildings.push({x:flock.x-6,y:flock.y-2,w:flock.w+12,h:100,type:0,district:d,perch:true,squeeze:true});
        }
      }
      x+=width+gap;
    }
    district.end=x;world.districts.push(district);
  }
  world.hazards.sort((a,b)=>a.x-b.x);
  if(cfg.motion){
    world.hazards.forEach((h,i)=>{
      if(h.district<(cfg.motion.from??0)||h.static||(h.squeeze&&cfg.motion.squeezeStatic))return;
      h.moving=true;h.phase=i*(cfg.motion.phaseStep??1.3);h.amp=cfg.motion;
      // A synced squeeze: both parts share phase and amplitude, so the window keeps its size.
      if(h.squeeze&&cfg.motion.squeezeSync!=null){h.phase=h.district*2.1;h.amp={platformY:cfg.motion.squeezeSync,pigeonY:cfg.motion.squeezeSync,pigeonX:0,rate:cfg.motion.rate};}
    });
  }
  const firstMoving=world.hazards.find(h=>h.moving);
  if(firstMoving)firstMoving.firstMoving=true;
  const firstSqueeze=world.hazards.find(h=>h.squeeze);
  if(firstSqueeze)for(const h of world.hazards)if(h.squeeze&&h.district===firstSqueeze.district&&h.slot===firstSqueeze.slot)h.firstSqueeze=true;
  world.checkpoints=world.airs.map((air,i)=>{
    if(i===0)return {id:air.gapId,district:air.district,x:0,y:130,speed:26,pitch:PHYSICS.divePitch};
    let x=air.x+12;
    for(const h of world.hazards){
      const reach=(h.amp?.pigeonX??0)+2;
      if(h.x-reach<x+10&&h.x+h.w+reach>air.x-5)x=Math.max(x,h.x+h.w+reach+15);
    }
    return {id:air.gapId,district:air.district,x,y:150,speed:26,pitch:PHYSICS.divePitch};
  });
  for(const d of world.districts)d.checkpoint=world.checkpoints.find(cp=>cp.district===d.index);
  for(const w of [...cfg.winds,...COURSE.flatMap((row,district)=>(row.lanes??[]).map(lane=>({district,fromSlot:lane.slot,toSlot:lane.slot,...lane}))),...(cfg.tailwinds??[])]){
    const from=slots.find(s=>s.d===w.district&&s.j===w.fromSlot),to=slots.find(s=>s.d===w.district&&s.j===w.toSlot);
    world.winds.push({x0:(w.startAtGap?from.release:from.x)-(w.lead??0),x1:to.release+(w.includeGap===false?0:to.gap),y0:w.y0,y1:w.y1,wind:w.wind,lift:w.lift??0,district:w.district,teaching:w.teaching??false});
  }
  const firstHeadwind=world.winds.find(w=>w.wind<0);
  if(firstHeadwind)firstHeadwind.firstHeadwind=true;
  let pid=0;
  for(const [sourceIndex,pk] of (cfg.pickups??[]).entries()){
    const slot=slots.find(s=>s.d===pk.district&&s.j===pk.slot);if(!slot)continue;
    const next=slots[slots.indexOf(slot)+1];
    let px,py;
    const flock=slot.slotHazards.find(h=>h.kind==='pigeon'),washer=slot.slotHazards.find(h=>h.kind==='platform');
    let attach=null,ox=0,oy=0;
    if(pk.place==='overFlock'){if(!flock)continue;px=flock.x+flock.w/2;py=flock.y+flock.h+pk.dy;attach=flock.id;ox=flock.w/2;oy=flock.h+pk.dy;}
    else if(pk.place==='underWasher'){if(!washer)continue;px=washer.x+washer.w/2;py=washer.y-pk.dy;attach=washer.id;ox=washer.w/2;oy=-pk.dy;}
    else if(pk.place==='roofEdge'){if(!next)continue;px=next.building.x+(pk.dx??6);py=next.building.y+pk.dy;}
    else if(pk.place==='gapLow'){px=slot.release+slot.gap*(pk.at??.5);py=pk.y;}
    else if(pk.place==='high'){px=slot.x+slot.width*(pk.at??.5);py=pk.y??(world.airs.find(a=>a.x===slot.x).targetExit+pk.above);}
    world.pickups.push({sourceIndex,placement:{...pk},id:`p${pid++}`,district:pk.district,slot:pk.slot,place:pk.place,x:px,y:py,r:pk.r??4,rewardTicks:pk.rewardTicks,label:`${pk.place}${pk.dy??pk.above??pk.y}`,attach:pk.attach===false?null:attach,ox,oy});
  }
  // A generous final park descent follows the last technical crossing.
  world.finishStart=x;world.length=x+140;
  return world;
}
export function airAt(world,p,time){
  let lift=0,wind=0,source=null,activity=0,zone=null;
  for(const a of world.airs){
    if(p.x<a.x||p.x>a.x+a.w||p.y<a.y||p.y>a.top)continue;
    const edge=Math.min(1,(p.x-a.x)/12,(a.x+a.w-p.x)/12);
    const effect=airEffect(a,p.y,time);
    lift+=effect.lift*edge;wind+=effect.wind*edge;source=a;activity=effect.activity;
  }
  for(const z of world.winds){
    if(p.x<z.x0||p.x>z.x1||p.y<z.y0||p.y>z.y1)continue;
    const edge=Math.min(1,(p.x-z.x0)/12,(z.x1-p.x)/12,(p.y-z.y0)/6,(z.y1-p.y)/6);
    wind+=z.wind*edge;lift+=z.lift*edge;zone=z;
  }
  if(!source&&zone)source={type:5,zone};
  return {lift,wind,source,activity,zone};
}
export function airEffect(a,height,time){
  const pulse=Math.max(0,Math.sin(time*1.4+a.phase))**2;
  const fade=clamp((a.top-height)/100,0,1);
  const s=a.liftScale??1;
  return {lift:[6.5,1.5+11*pulse,5.3,5,9*fade][a.type]*s,wind:0,activity:a.type===1?pulse:a.type===4?fade:1};
}
export function upcomingHazard(world,x,lookahead){return world.hazards.find(h=>h.x+h.w+8>x&&h.x-x<(lookahead??h.warningDistance));}
export function hazardKey(h){return h.squeeze?`squeeze-${h.district}-${h.slot}`:h.id;}
export function hazardAdvice(h){return h.squeeze?'Squeeze · fly between the washer and the flock':h.kind==='pigeon'?'Pigeons · climb over':'Window washers · dive under';}
export function hazardBox(h,time){
  if(h.moving===false)return {x:h.x,y:h.y,w:h.w,h:h.h};
  const m=h.amp??{platformY:13,pigeonX:9,pigeonY:9,rate:1},r=m.rate??1;
  return {x:h.x+(h.kind==='pigeon'?Math.sin(time*.65*r+h.phase)*m.pigeonX:0),y:h.y+Math.sin(time*.8*r+h.phase)*(h.kind==='platform'?m.platformY:m.pigeonY),w:h.w,h:h.h};
}
export function hazardParts(h,time){
  const b=hazardBox(h,time);
  if(h.kind!=='platform'||!Number.isFinite(h.suspensionTop))return [b];
  const y=b.y+b.h*.5,height=Math.max(0,h.suspensionTop-y);
  return [b,{x:b.x+2,y,w:.8,h:height,part:'cable'},{x:b.x+b.w-2.8,y,w:.8,h:height,part:'cable'}];
}

// Pickups attached to a hazard ride with it, so their risk does not depend on the hazard's phase.
export function pickupPos(world,pk,time){
  if(!pk.attach)return pk;
  const h=world.hazards.find(h=>h.id===pk.attach),b=hazardBox(h,time);
  return {...pk,x:b.x+pk.ox,y:b.y+pk.oy};
}
