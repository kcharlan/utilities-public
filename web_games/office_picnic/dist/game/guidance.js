import {airAt,hazardBox,hazardAdvice,upcomingHazard} from './world.js';
import {formatVerticalMotion} from './session.js';
export function flightGuidance(run,held){
  const p=run.plane,time=run.worldTicks/60,air=airAt(run.world,p,time);
  const hazard=run.world.hazards.find(h=>{
    const box=hazardBox(h,time);
    return box.x+box.w+8>p.x&&box.x-p.x<h.warningDistance;
  });
  let instruction=p.y>=160?'Release = dive · gain speed':air.source&&air.source.type!==5?'Hold = climb · costs speed':'Hold briefly · level out';
  const roof=run.world.buildings.find(b=>b.x>p.x&&b.x-p.x<200);
  if((!air.source||air.source.type===5)&&roof&&p.y-(roof.x-p.x)/run.world.limits.glideRatio<roof.y+8)instruction='Hold to clear the rooftop';
  const box=hazard?hazardBox(hazard,run.worldTicks/60):null;
  if(hazard&&!hazard.squeeze)instruction=hazard.pass==='above'?'Hold: climb over pigeons':'Release early: dive under';
  if(hazard&&!hazard.squeeze&&hazard.pass==='above'&&p.y>box.y+box.h+20)instruction='Release = dive · gain speed';
  if(hazard&&!hazard.squeeze&&hazard.pass==='below'&&p.y+Math.min(0,p.vy)*.5<box.y-26)instruction='Hold briefly · level out';
  if(hazard?.squeeze){
    const pair=run.world.hazards.filter(h=>h.squeeze&&h.district===hazard.district&&h.slot===hazard.slot);
    const washer=hazardBox(pair.find(h=>h.kind==='platform'),run.worldTicks/60);
    const flock=hazardBox(pair.find(h=>h.kind==='pigeon'),run.worldTicks/60);
    const center=(washer.y+flock.y+flock.h)/2;
    instruction=p.y<center-5?'Hold: climb into the squeeze window':p.y>center+5?'Release: dive into the squeeze window':'Fly between the washer and the flock';
  }
  if(p.speed<16)instruction='Build speed · release';
  if(p.stalled)instruction='Release to recover';
  const names=['AC · upward push',air.activity>.35?'Steam burst · upward push':'Vent lull · little push', 'Roof heat · gentle upward push','Wind column · upward push',air.activity<.45?'Thermal · upward push fading':'Thermal · upward push','Headwind · slows you'];
  let motionLabel=formatVerticalMotion(p.vy);
  if(run.status==='landing'){instruction='Landing · no input needed';motionLabel='Final approach';}
  if(run.status==='finished'){instruction='Landed';motionLabel='At the picnic';}
  const lane=run.world.winds.find(z=>z.wind>0&&p.x>=z.x0-60&&p.x<=z.x1&&(p.y<z.y0||p.y>z.y1));
  const lift=air.source&&air.source.type!==5?names[air.source.type]:null;
  const compactLift=['AC ↑',air.activity>.35?'Steam burst ↑':'Vent lull','Roof heat ↑','Wind column ↑',air.activity<.45?'Thermal fading':'Thermal ↑'];
  const wind=air.wind>0?'Tailwind':air.wind<0?'Headwind':null;
  const current=wind&&lift?`${wind} · ${compactLift[air.source.type]}`:wind?(air.wind>0?'Tailwind · forward push':'Headwind · slows you'):lift;
  const airLabel=lane?[current,`Tailwind lane ${p.y<lane.y0?'above':'below'}`].filter(Boolean).join(' · '):current??'Still air';
  return {instruction,airLabel,motionLabel,air,hazard};
}

export function noticeMessages(run){
  const messages=[],prompts=run.world.tier.prompts;
  const introduced=run.introducedElements??=new Set();
  if(run.events.includes('impact'))messages.push(run.cause);
  if(run.events.includes('respawn')&&prompts!=='quiet'){const hazard=upcomingHazard(run.world,run.plane.x);messages.push(run.mode==='standard'?`Back at the last rooftop.${hazard&&!hazard.firstSqueeze?' '+hazardAdvice(hazard):''}`:'A fresh throw. Climb over the first flock.');}
  if(run.events.includes('district')){
    const district=run.world.districts[run.district];
    let message=prompts==='full'?`${district.name}. ${district.tip}`:district.name;
    if(run.world.winds.some(z=>z.district===run.district&&z.wind<0)&&!introduced.has('headwind')){message+=' · Headwinds ahead';introduced.add('headwind');}
    messages.push(message);
    const moving=run.world.hazards.find(h=>h.firstMoving&&h.district===run.district);
    if(moving&&!introduced.has('moving')){messages.push(`Moving ${moving.kind==='pigeon'?'flock':'washer'} · watch its rhythm`);introduced.add('moving');}
  }
  for(const hazard of run.warningHazards||[]){
    if(hazard.firstSqueeze){
      if(!introduced.has('squeeze')){messages.push(hazardAdvice(hazard));introduced.add('squeeze');}
    }else if(prompts!=='quiet')messages.push(hazardAdvice(hazard));
  }
  return messages;
}
