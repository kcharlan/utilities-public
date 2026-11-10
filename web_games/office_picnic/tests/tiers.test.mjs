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
test('Casual retains authored geometry and clean route',()=>{
  const world=buildWorld();
  // District checkpoints now identify the first rooftop (including the launch state).
  assert.equal(createHash('sha256').update(JSON.stringify(projection(world))).digest('hex'),'482c0ef825f466af59f2cf417b37a426ad69196e70e23a23fe66a0ee539a4735');
  assert.deepEqual(world.hazards.map(h=>h.id),Array.from({length:5},(_,i)=>[`h${i}-over`,`h${i}-under`,...(i?[`h${i}-4-over`]:[])]).flat());
  assert.equal(world.length,7186);
  for(const mode of ['standard','nonstop']){
    const run=createRun(mode,world);
    while(run.status!=='finished'&&run.ticks<30000)stepRun(run,chooseInput(run));
    assert.equal(run.finishTicks,21881);
    assert.equal(run.crashes,0);
  }
});
test('Casual retains authored wind zones',()=>{
  const winds=buildWorld().winds.map(({x0,x1,y0,y1,wind,lift,district,teaching})=>({x0,x1,y0,y1,wind,lift,district,teaching}));
  assert.equal(createHash('sha256').update(JSON.stringify(winds)).digest('hex'),'bb26e0fa68958be806c9de8942d0ab4f9652cebf761cab3029400a9535468874');
});
test('squeeze geometry matches the authored slot and synced motion preserves the window',()=>{
  const config={...TIERS.casual,encounters:[{slot:1,kind:'squeeze',at:.5,center:130,window:40}],motion:{squeezeSync:8,rate:1}};
  const world=buildWorld(undefined,config),pair=world.hazards.filter(h=>h.district===0);
  assert.equal(pair.length,2);
  const washer=pair.find(h=>h.kind==='platform'),flock=pair.find(h=>h.kind==='pigeon');
  const gap=world.gaps[2],center=gap.x+gap.length*.5;
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
  assert.equal(tierHash(tier),tierHash({...tier,rules:{respawnTicks:24,crashPenaltyTicks:180}}));
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
  assert.equal(world.winds.filter(w=>w.wind<0).length,2);
  assert.equal(world.hazards.filter(h=>h.squeeze).length,2);
  assert.ok(world.hazards.some(h=>h.moving));
});
test('Overtime has full checkpoints and the authored moving course',()=>{
  const world=buildWorld(undefined,TIERS.overtime);
  assert.equal(world.tier.prompts,'quiet');
  assert.equal(world.rules.crashPenaltyTicks,600);
  assert.equal(world.winds.filter(w=>w.wind<0).length,6);
  assert.equal(world.hazards.length,23);
  assert.equal(world.districts.filter(d=>d.checkpoint).length,5);
  for(const mode of ['standard','nonstop']){
    const proof=referenceProof(world).full[mode];
    assert.equal(proof.finished,true);
    assert.equal(proof.crashes,0);
    assert.equal(proof.ticks,23860);
  }
});
test('tier washer overrides apply only to selected districts',()=>{
  const base=buildWorld(undefined,TIERS.casual);
  const edited=buildWorld(undefined,{...TIERS.casual,washerHeights:{2:155,3:155}});
  for(const hazard of base.hazards.filter(h=>h.kind==='platform')){
    const actual=edited.hazards.find(h=>h.id===hazard.id);
    assert.equal(actual.y,hazard.district===2||hazard.district===3?155:hazard.y,hazard.id);
  }
});
test('tier roof overrides change only authored receiving roofs',()=>{
  const base=buildWorld(undefined,TIERS.casual),edited=buildWorld(undefined,{...TIERS.casual,roofHeights:{3:{4:60}}});
  const roofs=world=>world.buildings.filter(b=>!b.perch).map(b=>b.y);
  const expected=roofs(base);expected[22]=60;
  assert.deepEqual(roofs(edited),expected);
});
test('Overtime retains authored geometry and wind zones',()=>{
  const world=buildWorld(undefined,TIERS.overtime);
  const winds=world.winds.map(({x0,x1,y0,y1,wind,lift,district,teaching})=>({x0,x1,y0,y1,wind,lift,district,teaching}));
  assert.equal(createHash('sha256').update(JSON.stringify({geometry:projection(world),winds})).digest('hex'),'8b2a8970bc2cfc4f5073312a94b65ed7ea6cfe784fa485a20b182b3f8f078f6b');
});
test('tier flock overrides apply only to selected districts',()=>{
  const base=buildWorld(undefined,TIERS.casual),edited=buildWorld(undefined,{...TIERS.casual,flockTops:{4:156}});
  for(const hazard of base.hazards.filter(h=>h.kind==='pigeon'&&h.slot===0)){
    const actual=edited.hazards.find(h=>h.id===hazard.id);
    assert.equal(actual.y+actual.h,hazard.district===4?156:hazard.y+hazard.h,hazard.id);
  }
});
test('Rush retains authored geometry and wind zones',()=>{
  const world=buildWorld(undefined,TIERS.rush);
  const winds=world.winds.map(({x0,x1,y0,y1,wind,lift,district,teaching})=>({x0,x1,y0,y1,wind,lift,district,teaching}));
  assert.equal(createHash('sha256').update(JSON.stringify({geometry:projection(world),winds})).digest('hex'),'e171184fc78ce8b17e1203ca83cd2e6da0eb4947391c5516a902f7703a3fd548');
});
test('shared authored course changes alter tier fingerprints',async()=>{
  const {COURSE}=await import('../dist/game/world.js');const before=tierHash(TIERS.casual);
  COURSE[0].widths[1]+=20;
  try{assert.notEqual(tierHash(TIERS.casual),before);}finally{COURSE[0].widths[1]-=20;}
});
