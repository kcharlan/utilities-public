import {pathToFileURL} from 'node:url';
import {buildWorld} from '../dist/game/world.js';
import {TIERS} from '../dist/game/tiers.js';
import {createPlane} from '../dist/game/physics.js';
import {createRun,stepRun} from '../dist/game/simulation.js';
import {REFERENCE,referenceInput,sensible} from '../dist/game/bot.js';

export const PILOT_FAMILY={
  reference:referenceInput,
  slow11:run=>sensible(run,{...REFERENCE,minSpeed:11}),
  slow12:run=>sensible(run,{...REFERENCE,minSpeed:12}),
  slow11tight:run=>sensible(run,{...REFERENCE,minSpeed:11,roofMargin:4,flockMargin:8,washerMargin:12})
};
export function removeFeature(world,type){return {...world,airs:world.airs.filter(a=>a.type!==type)};}
export function completesDistrict(world,district,input){
  const run=createRun('standard',world),cp=world.districts[district].checkpoint;
  run.district=district;run.checkpoint={...cp};run.plane=createPlane(cp);
  for(let n=0;n<18000&&run.crashes<25&&run.plane.x<world.districts[district].end;n++)stepRun(run,input(run));
  return run.plane.x>=world.districts[district].end;
}
if(process.argv[1] && import.meta.url===pathToFileURL(process.argv[1]).href){
  let failed=false;
  for(const [tier,cfg] of Object.entries(TIERS))for(let type=0;type<5;type++){
    const world=removeFeature(buildWorld(undefined,cfg),type),result={};
    for(const [pilot,input] of Object.entries(PILOT_FAMILY)){
      result[pilot]=world.districts.filter((_,d)=>completesDistrict(world,d,input)).map(d=>d.index+1);
      if(result[pilot].includes(type+1))failed=true;
    }
    console.log(tier,'removed',type,JSON.stringify(result));
  }
  for(const cfg of Object.values(TIERS)){
    const world=buildWorld(undefined,cfg),empty={...world,airs:[]};
    for(const input of Object.values(PILOT_FAMILY))for(let d=0;d<5;d++)if(completesDistrict(empty,d,input))failed=true;
  }
  if(failed)process.exitCode=1;
}
