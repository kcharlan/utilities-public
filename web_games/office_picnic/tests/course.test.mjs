import test from 'node:test';
import assert from 'node:assert/strict';
import {buildWorld} from '../dist/game/world.js';
import {TIERS} from '../dist/game/tiers.js';

function teachingImpacts(world,log,d){
  const start=world.checkpoints.findIndex(cp=>cp.id===`${d}.T`);
  return log.filter(c=>c.x>=world.checkpoints[start].x&&c.x<world.checkpoints[start+1].x);
}

test('each district introduces its feature on a clear teaching crossing',()=>{
  for(const tier of Object.values(TIERS)){
    const world=buildWorld(undefined,tier);
    for(let d=0;d<5;d++){
      const air=world.airs.find(a=>a.district===d),gap=world.gaps.find(g=>g.district===d);
      assert.equal(air.gapId,`${d+1}.T`);
      assert.equal(air.type,d);
      assert.equal(world.hazards.some(h=>h.x>=gap.x&&h.x<gap.end),false);
      assert.equal(world.winds.some(w=>w.x0<gap.end&&w.x1>gap.x),false);
      assert.equal(world.pickups.some(p=>p.x>=gap.x&&p.x<gap.end),false);
      const next=world.buildings.find(b=>!b.perch&&b.x>air.x);
      assert.ok(next.y<=world.buildings.find(b=>b.x===air.x-10).y);
    }
  }
});

test('tier elements are staged after the first district',()=>{
  for(const tier of [TIERS.rush,TIERS.overtime]){
    const world=buildWorld(undefined,tier);
    assert.ok(world.hazards.filter(h=>h.district===0).every(h=>!h.moving&&!h.squeeze));
    assert.ok(world.hazards.some(h=>h.district===1&&h.moving));
    assert.ok(world.hazards.some(h=>h.squeeze&&h.district===(tier.id==='rush'?4:2)&&!h.moving));
    assert.deepEqual([...new Set(world.winds.map(w=>w.district))],tier.id==='rush'?[3]:[3,4]);
    if(tier.id==='overtime'){
      assert.ok(world.winds.some(w=>w.district===4&&w.wind<0&&w.y0<=0&&w.y1>=400));
      assert.ok(world.hazards.some(h=>h.district===4&&h.moving));
      assert.ok(world.hazards.some(h=>h.district===4&&h.squeeze));
    }
  }
});

test('first moving hazard and squeeze are marked for introduction',()=>{
  for(const tier of [TIERS.rush,TIERS.overtime]){
    const world=buildWorld(undefined,tier);
    assert.equal(world.hazards.filter(h=>h.firstMoving).length,1);
    assert.equal(world.hazards.filter(h=>h.firstSqueeze).length,2);
    assert.equal(world.winds.filter(w=>w.firstHeadwind).length,1);
  }
});

test('earlier features introduce first encounters and every feature recurs',()=>{
  for(const tier of Object.values(TIERS)){
    const world=buildWorld(undefined,tier);
    for(let d=0;d<5;d++){
      const airs=world.airs.filter(a=>a.district===d),hazards=world.hazards.filter(h=>h.district===d);
      const flock=hazards.find(h=>h.kind==='pigeon'),washer=hazards.find(h=>h.kind==='platform');
      const feeding=airs.find(a=>a.gapId===`${d+1}.${flock.slot+1}`);
      const recovery=airs.find(a=>a.gapId===`${d+1}.${washer.slot+2}`);
      if(d){assert.ok(feeding.type<d);assert.ok(recovery.type<d);}
      assert.ok(airs.some(a=>a.gapId!==`${d+1}.T`&&a.type===d&&(hazards.some(h=>h.kind==='pigeon'&&a.gapId===`${d+1}.${h.slot+1}`)||a.gapId===`${d+1}.${washer.slot+2}`)));
      for(let type=0;type<d;type++)assert.ok(airs.some(a=>a.type===type));
    }
  }
});

test('teaching crossings are forgiving for seeded novices',async()=>{
  const {playOnce}=await import('../scripts/flight-study.mjs');
  const world=buildWorld(undefined,TIERS.casual);
  const runs=Array.from({length:80},(_,i)=>playOnce(world,'novice',1000+i));
  for(let d=1;d<=5;d++){
    const impacts=teachingImpacts(world,runs.flatMap(r=>r.log),d).length;
    assert.ok(impacts/80<=.15,`${d}.T: ${impacts}/80`);
  }
});

test('teaching impact attribution uses position even when the location label is unknown',()=>{
  const world=buildWorld(),start=world.checkpoints.find(cp=>cp.id==='2.T').x;
  assert.equal(teachingImpacts(world,[{x:Math.ceil(start),where:'roof ?'}],2).length,1);
});

test('each feature is necessary to its introducing district and all lift is necessary',async()=>{
  const {PILOT_FAMILY,removeFeature,completesDistrict}=await import('../scripts/ablation.mjs');
  for(const tier of Object.values(TIERS)){
    const world=buildWorld(undefined,tier),empty={...world,airs:[]};
    for(const [name,input] of Object.entries(PILOT_FAMILY))for(let d=0;d<5;d++){
      assert.equal(completesDistrict(removeFeature(world,d),d,input),false,`${tier.id} ${name} type ${d}`);
      assert.equal(completesDistrict(empty,d,input),false,`${tier.id} ${name} no lift district ${d+1}`);
    }
  }
});

test('tier elements debut in separate districts and crossings',()=>{
  for(const tier of [TIERS.rush,TIERS.overtime]){
    const world=buildWorld(undefined,tier);
    const moving=world.hazards.find(h=>h.firstMoving),squeeze=world.hazards.find(h=>h.firstSqueeze),wind=world.winds.find(w=>w.firstHeadwind);
    assert.deepEqual([moving.district,squeeze.district,wind.district],tier.id==='rush'?[1,4,3]:[1,2,3]);
    assert.notEqual(moving.district,squeeze.district);
    assert.notEqual(squeeze.district,wind.district);
  }
});

test('quiet mode announces first tier hazards once in their district',async()=>{
  const {createRun}=await import('../dist/game/simulation.js');
  const {noticeMessages}=await import('../dist/game/guidance.js');
  const run=createRun('standard',buildWorld(undefined,TIERS.overtime));
  for(const flag of ['firstMoving','firstSqueeze']){
    const hazard=run.world.hazards.find(h=>h[flag]);
    run.district=hazard.district;run.warningHazards=[];run.events=['district'];
    assert.equal(noticeMessages(run).length,2,flag);
    assert.equal(noticeMessages(run).length,1,flag);
  }
  run.district=3;run.events=['district'];run.warningHazards=[];
  assert.match(noticeMessages(run).join(' '),/Headwinds/);
  assert.doesNotMatch(noticeMessages(run).join(' '),/Headwinds/);
});
