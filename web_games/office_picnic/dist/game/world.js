import {measureFlight} from './measure.js';
import {clamp,PHYSICS} from './physics.js';
export const THEMES=[
  {name:'Glass Mile',feature:'AC updraft',tip:'Climb over the flock, then release early to pass under the washers.',color:'#9eabc9'},
  {name:'Boiler Row',feature:'Pulsing vents',tip:'Steam bursts push upward automatically; the lull gives little lift.',color:'#efb391'},
  {name:'Sunward Roofs',feature:'Rooftop heat',tip:'Warm roofs add gentle upward push. Pitching up still spends airspeed.',color:'#edc583'},
  {name:'Crosswind Court',feature:'Wind lanes',tip:'Follow the ribbons. Tailwinds carry you farther.',color:'#b7c5bd'},
  {name:'Park Approach',feature:'Fading thermals',tip:'Lift fades near the dotted ceiling. Save height for the park.',color:'#b8c699'}
];
export function buildWorld(limits=measureFlight()){
  const safeRange=limits.envelopes.find(e=>e.speed===18&&e.drop===50).range;
  const world={districts:[],airs:[],buildings:[],hazards:[],gaps:[],length:0,limits};
  let x=0;
  const ratios=[.56,.64,.73,.81,.92];
  for(let d=0;d<5;d++){
    const start=x, gap=Math.floor(safeRange*ratios[d]);
    const district={...THEMES[d],index:d,start,checkpoint:{x:start+12,y:150,speed:26,pitch:PHYSICS.divePitch}};
    for(let j=0;j<5;j++){
      const type=j===0?d:(j-1)%(d+1);
      // Weak, broad heat needs more recovery distance than concentrated AC.
      const width=j===0&&d===0?200:type===2?220:type===1?200:type===4?210:170;
      // After the opening dive, receiving roofs require rebuilding height in lift.
      const roof=d===0&&j>=3?(j===4?110:85):[40,45,55,65,75][d];
      const entryHeight=j===0?184:j===2?142:170;
      const air={x,w:width,y:roof+4,top:230,type,phase:j*.7,district:d,targetExit:entryHeight,gapId:`${d+1}.${j+1}`};
      world.airs.push(air);
      world.buildings.push({x:x-10,y:roof,w:width+20,h:100,type,district:d});
      const release=x+width;
      world.gaps.push({id:`${d+1}.${j+1}`,district:d,x:release,end:release+gap,length:gap,entryHeight,entrySpeed:18,entryPitch:PHYSICS.divePitch,clearance:entryHeight-50,drop:50,measuredRange:safeRange,utilization:gap/safeRange});
      if(j===0){
        const top=170-gap*.4/limits.glideRatio-8;
        const hazard={id:`h${d}-over`,district:d,kind:'pigeon',pass:'above',x:release+gap*.4,y:top-16,w:24,h:16,phase:0,warningDistance:360,moving:false};
        world.hazards.push(hazard);
        // A flock lifting from a raised roof makes the low route visibly solid.
        world.buildings.push({x:hazard.x-6,y:hazard.y-2,w:hazard.w+12,h:100,type:0,district:d,perch:true});
      }
      if(j===2){
        const upperSuspension=230+limits.maxPullUpClimb+20;
        world.hazards.push({id:`h${d}-under`,district:d,kind:'platform',pass:'below',x:release+gap*.7,y:144,w:45,h:30,suspensionTop:upperSuspension,phase:0,warningDistance:250,moving:false});
      }
      x+=width+gap;
    }
    district.end=x;world.districts.push(district);
  }
  // A generous final park descent follows the last technical crossing.
  world.finishStart=x;world.length=x+140;
  return world;
}
export function airAt(world,p,time){
  let lift=0,wind=0,source=null,activity=0;
  for(const a of world.airs){
    if(p.x<a.x||p.x>a.x+a.w||p.y<a.y||p.y>a.top)continue;
    const edge=Math.min(1,(p.x-a.x)/12,(a.x+a.w-p.x)/12);
    const effect=airEffect(a,p.y,time);
    lift+=effect.lift*edge;wind+=effect.wind*edge;source=a;activity=effect.activity;
  }
  return {lift,wind,source,activity};
}
export function airEffect(a,height,time){
  const pulse=Math.max(0,Math.sin(time*1.4+a.phase))**2;
  const fade=clamp((a.top-height)/100,0,1);
  return {lift:[6.5,1.5+11*pulse,5.3,5,9*fade][a.type],wind:a.type===3?6:0,activity:a.type===1?pulse:a.type===4?fade:1};
}
export function upcomingHazard(world,x,lookahead){return world.hazards.find(h=>h.x+h.w+8>x&&h.x-x<(lookahead??h.warningDistance));}
export function hazardAdvice(h){return h.kind==='pigeon'?'Pigeons · climb over':'Window washers · dive under';}
export function hazardBox(h,time){
  if(h.moving===false)return {x:h.x,y:h.y,w:h.w,h:h.h};
  return {x:h.x+(h.kind==='pigeon'?Math.sin(time*.65+h.phase)*9:0),y:h.y+Math.sin(time*.8+h.phase)*(h.kind==='platform'?13:9),w:h.w,h:h.h};
}
export function hazardParts(h,time){
  const b=hazardBox(h,time);
  if(h.kind!=='platform'||!Number.isFinite(h.suspensionTop))return [b];
  const y=b.y+b.h*.5,height=Math.max(0,h.suspensionTop-y);
  return [b,{x:b.x+2,y,w:.8,h:height,part:'cable'},{x:b.x+b.w-2.8,y,w:.8,h:height,part:'cable'}];
}
