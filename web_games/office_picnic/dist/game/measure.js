import {createPlane,advancePlane,PHYSICS} from './physics.js';
export function measureFlight(){
  const steady=createPlane({y:10000,speed:20});
  for(let i=0;i<3600;i++)advancePlane(steady,false);
  const glideRatio=steady.vx/-steady.vy;
  const pull=createPlane({y:0,speed:PHYSICS.maxSpeed,pitch:PHYSICS.divePitch});
  let maxClimb=0, pullRange=0;
  for(let i=0;i<1800;i++){
    advancePlane(pull,true);
    if(pull.y>maxClimb){maxClimb=pull.y;pullRange=pull.x;}
    if(pull.stalled)break;
  }
  // Empirical released descent range for conservative checkpoint entry speeds.
  const envelopes=[];
  for(const speed of [18,22,26,32])for(const drop of [20,30,40,50,60]){
    const p=createPlane({y:drop,speed,pitch:PHYSICS.divePitch});
    while(p.y>0&&p.x<2000)advancePlane(p,false);
    envelopes.push({speed,drop,range:p.x});
  }
  return {units:'meters, seconds',dt:PHYSICS.dt,glideRatio,steadySpeed:steady.speed,stallSpeed:PHYSICS.stallSpeed,maxPullUpClimb:maxClimb,pullUpRange:pullRange,envelopes};
}
