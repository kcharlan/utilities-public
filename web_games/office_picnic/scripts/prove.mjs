import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {mkdir,writeFile} from 'node:fs/promises';
import {createPlane,advancePlane} from '../dist/game/physics.js';
import {createRun,stepRun} from '../dist/game/simulation.js';
import {chooseInput,referenceInput} from '../dist/game/bot.js';
import {TIERS} from '../dist/game/tiers.js';
import {buildWorld,hazardBox,hazardKey} from '../dist/game/world.js';
import {validateEncounter,DISTRICT_SPEEDS,DISTRICT_OFFSETS,DISTRICT_DELAYS,GAP_SPEEDS,GAP_OFFSETS} from './proof-checks.mjs';
function prove(tier){
const world=buildWorld(undefined,tier),input=tier.id==='casual'?chooseInput:referenceInput,runs=[],districtTrials=[],gaps=[],actualEntries=new Map(),actualReceivers=new Map();
const checkpointTrials=[];
for(const [index,checkpoint] of world.checkpoints.entries())for(const offset of [0,53,107,163,211,269,331,397]){
  const r=createRun('standard',world);r.district=checkpoint.district;r.checkpoint={...checkpoint};r.plane=createPlane(checkpoint);r.worldTicks=offset;
  const target=world.checkpoints[index+1]?.x,finished=()=>target===undefined?r.status==='finished':r.plane.x>=target;
  for(let n=0;n<60*150&&!finished()&&r.crashes===0;n++)stepRun(r,referenceInput(r));
  assert.equal(r.crashes,0,`checkpoint ${checkpoint.id} offset ${offset}: ${r.crashLog[0]?.where}`);
  assert.ok(finished(),`checkpoint ${checkpoint.id} offset ${offset}: timeout`);
  checkpointTrials.push({checkpoint:checkpoint.id,offset,cleared:true,status:r.status});
}
const encounters=world.hazards.map(h=>({id:h.id,district:h.district,kind:h.kind,pass:h.pass,minClearance:Infinity,warningSeconds:null,arrivalSeconds:null,passed:false}));
const engagement=world.districts.map(d=>({district:d.name,heldTicks:0,totalTicks:0}));
for(const mode of ['standard','nonstop']){
  const r=createRun(mode,world);
  for(let n=0;n<60*900&&r.status!=='finished';n++){
    const before={...r.plane},held=input(r);
    if(mode==='standard'){engagement[r.district].heldTicks+=Number(held);engagement[r.district].totalTicks++;}
    stepRun(r,held);
    if(mode==='standard')for(let i=0;i<world.hazards.length;i++){
      const h=world.hazards[i],record=encounters[i];
      const box=hazardBox(h,r.worldTicks/60);
      if(record.warningSeconds===null&&r.warningHazards.some(w=>hazardKey(w)===hazardKey(h)))record.warningSeconds=r.worldTicks/60;
      if(r.plane.x>=box.x-1.2&&r.plane.x<=box.x+box.w+1.2){
        if(record.arrivalSeconds===null)record.arrivalSeconds=r.worldTicks/60;
        const clearance=h.pass==='above'?r.plane.y-box.y-box.h-1.2:box.y-r.plane.y-1.2;
        record.minClearance=Math.min(record.minClearance,clearance);
      }
      if(record.arrivalSeconds!==null&&r.plane.x>=box.x+box.w+1.2)record.passed=true;
    }
    if(mode==='standard')for(const g of world.gaps){
      if(before.x<g.x&&r.plane.x>=g.x)actualEntries.set(g.id,{height:r.plane.y,speed:r.plane.speed,pitch:r.plane.pitch});
      const receiver=world.buildings.find(b=>Math.abs(b.x-(g.end-10))<.01);
      if(receiver&&before.x<receiver.x-1.2&&r.plane.x>=receiver.x-1.2)actualReceivers.set(g.id,{roof:receiver.y,clearance:r.plane.y-receiver.y-1.2});
    }
  }
  assert.equal(r.status,'finished');assert.equal(r.crashes,0);
  runs.push({mode,seconds:r.ticks/60,distance:world.length,crashes:r.crashes});
}
for(const d of world.districts)for(const speed of DISTRICT_SPEEDS)for(const dy of DISTRICT_OFFSETS)for(const delay of DISTRICT_DELAYS){
  const r=createRun('standard',world);r.district=d.index;r.checkpoint={...d.checkpoint};r.plane=createPlane({...d.checkpoint,speed,y:d.checkpoint.y+dy});
  let held=false;
  for(let n=0;n<60*150&&r.plane.x<d.end&&r.crashes===0;n++){
    if(n%Math.max(1,delay+1)===0)held=input(r);
    stepRun(r,held);
  }
  assert.equal(r.crashes,0,`${d.name}: speed=${speed}, dy=${dy}, delay=${delay}`);
  assert.ok(r.plane.x>=d.end,`${d.name} timeout`);
  districtTrials.push({district:d.name,speed,entryOffset:dy,inputSampleTicks:delay+1,cleared:true});
}
for(const g of world.gaps){
  let minClearance=Infinity,minActualRoofClearance=Infinity,releaseOnlySamples=0;
  const receiver=world.buildings.find(b=>Math.abs(b.x-(g.end-10))<.01);
  const occupied=tier.id!=='casual'&&world.hazards.some(h=>h.x>=g.x&&h.x<=g.end);
  for(const speed of GAP_SPEEDS)for(const dy of GAP_OFFSETS){
    const p=createPlane({x:0,y:g.entryHeight+dy,speed,pitch:g.entryPitch});
    while(p.x<g.length)advancePlane(p,false);
    minClearance=Math.min(minClearance,p.y-g.clearance);
    if(occupied)continue;
    const trial=createRun('standard',world);trial.district=g.district;trial.plane=createPlane({x:g.x,y:g.entryHeight+dy,speed,pitch:g.entryPitch});
    for(let n=0;n<1200&&trial.plane.x<g.end+2&&trial.crashes===0;n++){
      stepRun(trial,false);
      if(receiver&&trial.plane.x>=receiver.x-1.2&&trial.plane.x<=receiver.x+receiver.w+1.2)minActualRoofClearance=Math.min(minActualRoofClearance,trial.plane.y-receiver.y-1.2);
    }
    assert.equal(trial.crashes,0,`${g.id}: real-geometry trial impact`);assert.ok(trial.plane.x>=g.end+2);releaseOnlySamples++;
  }
  assert.ok(g.utilization<=1&&minClearance>=0,`${g.id} over limit`);
  const entry=actualEntries.get(g.id),roof=receiver?.y??2,continuation=createPlane({y:entry.height,speed:entry.speed,pitch:entry.pitch});
  while(continuation.y>roof+1.2&&continuation.x<2000)advancePlane(continuation,false);
  const actualRequiredRange=receiver?receiver.x-1.2-g.x:g.length;
  assert.ok(actualRequiredRange<=continuation.x,`${g.id}: actual-entry continuation over limit`);
  gaps.push({...g,sourceRoofEnd:g.x+10,receiverRoofStart:receiver?.x??null,receiverRoof:roof,clearanceMeaning:`Synthetic ${g.clearance}m envelope target; actual roof and hazard clearances are separate.`,syntheticPerturbedClearance:minClearance,...(tier.id==='casual'?{}:{releaseOnlySkipped:occupied,releaseOnlySamples}),realGeometryMinSampledRoofClearance:Number.isFinite(minActualRoofClearance)?minActualRoofClearance:null,actualBotEntry:entry,actualBotReceiver:actualReceivers.get(g.id)??null,actualEntryMeasuredRange:continuation.x,actualRequiredRange,actualEntryUtilization:actualRequiredRange/continuation.x});
}
for(const e of encounters)e.warningLeadSeconds=validateEncounter(e);
const report={runs,districtTrials,checkpointTrials,gaps,encounters,engagement,summary:{districtTrials:districtTrials.length,gaps:gaps.length,encounters:encounters.length,firstEncounterSeconds:encounters[0].arrivalSeconds,minHazardClearance:Math.min(...encounters.map(e=>e.minClearance)),minWarningLeadSeconds:Math.min(...encounters.map(e=>e.warningLeadSeconds)),maxSyntheticEnvelopeUtilization:Math.max(...gaps.map(g=>g.utilization)),minSyntheticPerturbedClearance:Math.min(...gaps.map(g=>g.syntheticPerturbedClearance)),maxActualEntryUtilization:Math.max(...gaps.map(g=>g.actualEntryUtilization)),minActualBotReceiverClearance:Math.min(...gaps.filter(g=>g.actualBotReceiver).map(g=>g.actualBotReceiver.clearance)),minRealGeometrySampledRoofClearance:Math.min(...gaps.filter(g=>g.realGeometryMinSampledRoofClearance!==null).map(g=>g.realGeometryMinSampledRoofClearance))}};
return report;
}
const reports=Object.fromEntries(Object.entries(TIERS).map(([id,tier])=>[id,prove(tier)]));
const out=process.argv[2]==='--out'&&process.argv[3]?resolve(process.argv[3]):new URL('../reports/',import.meta.url);
await mkdir(out,{recursive:true});
await writeFile(resolve(out instanceof URL?fileURLToPath(out):out,'route-proof.json'),JSON.stringify(reports,null,2)+'\n');
for(const [id,report] of Object.entries(reports)){console.log(id);console.table(report.runs);console.log(report.summary);}
