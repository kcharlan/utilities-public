import {airAt,upcomingHazard} from './world.js';
import {formatVerticalMotion} from './session.js';
export function flightGuidance(run,held){
  const p=run.plane,air=airAt(run.world,p,run.worldTicks/60),hazard=upcomingHazard(run.world,p.x);
  let instruction=p.y>=160?'Release = dive · gain speed':air.source?'Hold = climb · costs speed':'Hold briefly · level out';
  const roof=run.world.buildings.find(b=>b.x>p.x&&b.x-p.x<200);
  if(!air.source&&roof&&p.y-(roof.x-p.x)/run.world.limits.glideRatio<roof.y+8)instruction='Hold to clear the rooftop';
  if(hazard)instruction=hazard.pass==='above'?'Hold: climb over pigeons':'Release early: dive under';
  if(hazard?.pass==='above'&&p.y>hazard.y+hazard.h+20)instruction='Release = dive · gain speed';
  if(hazard?.pass==='below'&&p.y+Math.min(0,p.vy)*.5<hazard.y-26)instruction='Hold briefly · level out';
  if(p.speed<16)instruction='Build speed · release';
  if(p.stalled)instruction='Release to recover';
  const names=['AC · upward push',air.activity>.35?'Steam burst · upward push':'Vent lull · little push', 'Roof heat · gentle upward push','Tailwind · forward + upward push',air.activity<.45?'Thermal · upward push fading':'Thermal · upward push'];
  let motionLabel=formatVerticalMotion(p.vy);
  if(run.status==='landing'){instruction='Landing · no input needed';motionLabel='Final approach';}
  if(run.status==='finished'){instruction='Landed';motionLabel='At the picnic';}
  return {instruction,airLabel:air.source?names[air.source.type]:'Still air',motionLabel,air,hazard};
}
