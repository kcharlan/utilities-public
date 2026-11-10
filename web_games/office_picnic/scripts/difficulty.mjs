import {fileURLToPath} from 'node:url';
import {createPlane} from '../dist/game/physics.js';
import {createRun,stepRun} from '../dist/game/simulation.js';
import {referenceInput} from '../dist/game/bot.js';
import {buildWorld} from '../dist/game/world.js';
import {TIERS} from '../dist/game/tiers.js';
import {CLOCK_OFFSETS} from './flight-study.mjs';

export function survives(world,from,to,offset,delay){
  const run=createRun('standard',world),queue=[];
  run.district=from.district;run.checkpoint={...from};run.plane=createPlane(from);run.worldTicks=offset;
  for(let n=0;n<9000&&run.plane.x<to.x&&!run.crashes;n++){
    queue.push(referenceInput(run));
    stepRun(run,queue.length>delay?queue.shift():false);
  }
  return !run.crashes&&run.plane.x>=to.x;
}
export function crossingWindow(world,from,to,{offsets=CLOCK_OFFSETS,step=3,cap=90}={}){
  let worst=cap;
  for(const offset of offsets){
    let delay=0;
    for(;delay<=cap;delay+=step)if(!survives(world,from,to,offset,delay))break;
    worst=Math.min(worst,delay);
  }
  return Math.min(cap,worst)/60*1000;
}
export function difficulty(world){
  const crossings=world.checkpoints.map((from,i)=>({id:from.id,district:from.district,window:crossingWindow(world,from,world.checkpoints[i+1]??{x:world.finishStart})}));
  return world.districts.map(d=>{
    const items=crossings.filter(c=>c.district===d.index),tightest=items.reduce((a,b)=>a.window<=b.window?a:b);
    return {district:d.index+1,feature:d.feature,tightest:tightest.id,window:tightest.window,belowCap:items.filter(c=>c.window<1500).length,crossings:items};
  });
}
if(process.argv[1]===fileURLToPath(import.meta.url)){
  let tier=null,json=false;
  for(let i=2;i<process.argv.length;i++){
    if(process.argv[i]==='--tier'){
      tier=process.argv[++i];
      if(!tier||tier.startsWith('--'))throw Error('Missing tier value');
    }
    else if(process.argv[i]==='--json')json=true;
    else throw Error(`Unknown option: ${process.argv[i]}`);
  }
  if(tier&&!Object.hasOwn(TIERS,tier))throw Error(`Unknown tier: ${tier}`);
  const result=Object.fromEntries(Object.entries(TIERS).filter(([id])=>!tier||id===tier).map(([id,cfg])=>[id,difficulty(buildWorld(undefined,cfg))]));
  if(json)console.log(JSON.stringify(result,null,2));
  else for(const [id,rows] of Object.entries(result)){console.log(`\n${id}`);console.table(rows.map(({district,feature,tightest,window,belowCap})=>({district,feature,tightest,window,belowCap})));}
}
