import {createRun,stepRun,netTicks} from '../dist/game/simulation.js';
import {createPlane} from '../dist/game/physics.js';
import {referenceInput} from '../dist/game/bot.js';
import {makePilot,PROFILES} from './pilot.mjs';

export function playOnce(world,profile,seed,{mode='standard',capSeconds=1200,extra={}}={}){
  const run=createRun(mode,world),pilot=makePilot(PROFILES[profile],seed,extra);
  let steps=0;
  for(;steps<60*capSeconds&&run.status!=='finished';steps++)stepRun(run,pilot(run));
  return {
    finished:run.status==='finished',seconds:run.ticks/60,net:netTicks(run)/60,collected:run.collected.size,crashes:run.crashes,
    log:run.crashLog,attempts:run.attempts,wall:steps/60
  };
}

export function quantile(values,p){
  const sorted=[...values].sort((a,b)=>a-b);
  return sorted[Math.min(sorted.length-1,Math.floor(p*(sorted.length-1)+.5))];
}

export function referenceProof(world){
  const full={};
  for(const mode of ['standard','nonstop']){
    const run=createRun(mode,world);
    for(let n=0;n<54000&&run.status!=='finished';n++)stepRun(run,referenceInput(run));
    full[mode]={finished:run.status==='finished',crashes:run.crashes,ticks:run.finishTicks};
  }
  let trials=0;
  const failures=[];
  for(const district of world.districts)for(const speed of [22,26,30])for(const dy of [-6,0,6])for(const delay of [0,3,6]){
    const run=createRun('standard',world);
    run.district=district.index;
    run.checkpoint={...district.checkpoint};
    run.plane=createPlane({...district.checkpoint,speed,y:district.checkpoint.y+dy});
    let held=false;
    for(let n=0;n<9000&&run.plane.x<district.end&&!run.crashes;n++){
      if(n%(delay+1)===0)held=referenceInput(run);
      stepRun(run,held);
    }
    trials++;
    if(run.crashes||run.plane.x<district.end){
      failures.push({district:district.index,speed,dy,delay,where:run.crashLog[0]?.where??'timeout'});
    }
  }
  return {full,trials,failures};
}

export const shortcuts={
  passive:()=>false,
  launchHold126:(run,n)=>n<126,
  launchHold3s:(run,n)=>n<180,
  ...Object.fromEntries([130,150,155,185,230,300].map(height=>[
    `cruise${height}`,run=>run.plane.speed>14&&run.plane.y<height
  ]))
};

export function shortcutOutcomes(world){
  return Object.fromEntries(Object.entries(shortcuts).map(([name,policy])=>{
    let cleared=0;
    for(const district of world.districts){
      const run=createRun('standard',world);
      run.district=district.index;
      if(district.index>0){
        run.plane.x=district.checkpoint.x;
        run.plane.y=district.checkpoint.y;
        run.plane.speed=district.checkpoint.speed;
        run.plane.pitch=district.checkpoint.pitch;
      }
      for(let n=0;n<9000&&!run.crashes&&run.plane.x<district.end;n++)stepRun(run,policy(run,n));
      if(!run.crashes&&run.plane.x>=district.end)cleared++;
    }
    return [name,cleared];
  }));
}
