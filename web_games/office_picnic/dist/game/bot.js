import {hazardBox,upcomingHazard} from './world.js';
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
