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
  // Compare controlled still-air flight across the same entry speeds as the dive envelopes.
  const entryHeight=184,roofHeight=73;
  const controlled=[18,22,26,32].map(speed=>{
    const p=createPlane({y:entryHeight,speed,pitch:PHYSICS.divePitch});
    while(p.y>roofHeight&&p.x<10000)advancePlane(p,p.y<entryHeight&&p.speed>11);
    return {speed,range:p.x};
  });
  const bestStillAirRange={entryHeight,roofHeight,policy:'hold below entry height while speed exceeds 11 m/s',...controlled.reduce((a,b)=>a.range>b.range?a:b)};
  return {bestStillAirRange,units:'meters, seconds',dt:PHYSICS.dt,glideRatio,steadySpeed:steady.speed,stallSpeed:PHYSICS.stallSpeed,maxPullUpClimb:maxClimb,pullUpRange:pullRange,envelopes};
}
