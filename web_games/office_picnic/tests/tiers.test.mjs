import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {buildWorld,airAt,airEffect,hazardBox} from '../dist/game/world.js';
import {createRun,stepRun} from '../dist/game/simulation.js';
import {createPlane,advancePlane} from '../dist/game/physics.js';
import {chooseInput} from '../dist/game/bot.js';
import {TIERS,tierHash} from '../dist/game/tiers.js';
import {referenceProof,shortcutOutcomes} from '../scripts/flight-study.mjs';

const keys={
  hazards:['id','district','kind','pass','x','y','w','h','suspensionTop','phase','warningDistance','moving'],
  buildings:['x','y','w','h','type','district','perch'],
  airs:['x','w','y','top','type','phase','district','targetExit','gapId'],
  gaps:['id','district','x','end','length','entryHeight','entrySpeed','entryPitch','clearance','drop','measuredRange','utilization'],
  districts:['name','feature','tip','color','index','start','checkpoint','end']
};
function projection(world){
  return Object.fromEntries([
    ...Object.entries(keys).map(([key,fields])=>[
      key,world[key].map(item=>Object.fromEntries(fields.filter(field=>field in item).map(field=>[field,item[field]])))
    ]),
    ['length',world.length]
  ]);
}
test('Casual retains shipped geometry and clean route',()=>{
  const world=buildWorld();
  assert.equal(createHash('sha256').update(JSON.stringify(projection(world))).digest('hex'),'51e86ce090aa730f09a3fa3a8ae087a4dbf30531e1db88091109129d47cd43ec');
  assert.deepEqual(world.hazards.map(h=>h.id),Array.from({length:5},(_,i)=>[`h${i}-over`,`h${i}-under`]).flat());
  assert.equal(world.length,6245);
  for(const mode of ['standard','nonstop']){
    const run=createRun(mode,world);
    while(run.status!=='finished'&&run.ticks<30000)stepRun(run,chooseInput(run));
    assert.equal(run.finishTicks,18321);
    assert.equal(run.crashes,0);
  }
});
test('squeeze geometry matches the authored slot and synced motion preserves the window',()=>{
  const config={...TIERS.casual,encounters:[{slot:1,kind:'squeeze',at:.5,center:130,window:40}],motion:{squeezeSync:8,rate:1}};
  const world=buildWorld(undefined,config),pair=world.hazards.filter(h=>h.district===0);
  assert.equal(pair.length,2);
  const washer=pair.find(h=>h.kind==='platform'),flock=pair.find(h=>h.kind==='pigeon');
  const gap=world.gaps[1],center=gap.x+gap.length*.5;
  assert.deepEqual({x:washer.x,y:washer.y,w:washer.w,h:washer.h},{x:center-22.5,y:150,w:45,h:30});
  assert.deepEqual({x:flock.x,y:flock.y,w:flock.w,h:flock.h},{x:center-12,y:94,w:24,h:16});
  for(let t=0;t<100;t+=.1){
    assert.ok(Math.abs(hazardBox(washer,t).y-(hazardBox(flock,t).y+flock.h)-40)<1e-9);
  }
  const fixed=buildWorld(undefined,{...config,motion:{squeezeStatic:true}}).hazards.filter(h=>h.district===0);
  for(const hazard of fixed)assert.deepEqual(hazardBox(hazard,0),hazardBox(hazard,10));
  for(const kind of ['platform','squeeze']){
    assert.throws(()=>buildWorld(undefined,{...config,encounters:[{slot:4,kind,at:.5,window:40}]}));
  }
});
test('tier hash reflects gameplay, not presentation or key insertion order',()=>{
  const tier=TIERS.casual;
  assert.equal(tierHash(tier),tierHash({...tier,name:'Other',blurb:'Different',prompts:'quiet'}));
  assert.equal(tierHash(tier),tierHash({...tier,rules:{respawnTicks:36,crashPenaltyTicks:180}}));
  assert.notEqual(tierHash(tier),tierHash({...tier,ratios:[...tier.ratios.slice(0,4),.8]}));
});
test('rules control crashes and nonstop retains the history',()=>{
  const world=buildWorld(undefined,{...TIERS.casual,rules:{crashPenaltyTicks:25,respawnTicks:2}});
  for(const mode of ['standard','nonstop']){
    const run=createRun(mode,world);
    run.plane.y=0;
    stepRun(run,false);
    assert.equal(run.respawnTicks,2);
    assert.match(run.crashLog[0].where,/^street /);
    assert.equal(run.ticks,mode==='standard'?26:1);
    stepRun(run,false);stepRun(run,false);
    assert.equal(run.crashLog.length,1);
    assert.equal(run.attempts,mode==='nonstop'?2:1);
  }
});
test('wind ramps at edges and authored lift scale reduces column lift',()=>{
  const config={...TIERS.casual,liftScale:[.5,1,1,1,1],winds:[{district:0,fromSlot:0,toSlot:0,startAtGap:true,y0:0,y1:400,wind:-4}]};
  const world=buildWorld(undefined,config),zone=world.winds[0];
  assert.equal(airAt(world,{x:zone.x0-1,y:300},0).wind,0);
  assert.equal(airAt(world,{x:zone.x0+6,y:300},0).wind,-2);
  assert.equal(airAt(world,{x:zone.x0+20,y:300},0).wind,-4);
  const still=createPlane({x:zone.x0+20,y:300,speed:26}),headwind=createPlane({x:zone.x0+20,y:300,speed:26});
  advancePlane(still,false);advancePlane(headwind,false,airAt(world,headwind,0));
  assert.ok(headwind.x<still.x);
  const air=world.airs[0];
  assert.equal(airEffect(air,150,0).lift,3.25);
  assert.equal(airAt(world,{x:air.x+air.w/2,y:150},0).lift,3.25);
});
test('reference pilot finishes both modes and clears district perturbations',()=>{
  const proof=referenceProof(buildWorld());
  for(const mode of ['standard','nonstop']){
    assert.equal(proof.full[mode].finished,true);
    assert.equal(proof.full[mode].crashes,0);
  }
  assert.equal(proof.trials,135);
  assert.deepEqual(proof.failures,[]);
});
test('shared shortcut runner rejects each passive policy in every district',()=>{
  const results=shortcutOutcomes(buildWorld());
  assert.ok(Object.keys(results).length>=9);
  assert.ok(Object.values(results).every(n=>n===0));
});
test('Rush has the authored moving hazards, squeeze and headwinds',()=>{
  const world=buildWorld(undefined,TIERS.rush);
  assert.equal(world.rules.crashPenaltyTicks,300);
  assert.equal(world.winds.length,2);
  assert.equal(world.hazards.filter(h=>h.squeeze).length,4);
  assert.ok(world.hazards.some(h=>h.moving));
});
