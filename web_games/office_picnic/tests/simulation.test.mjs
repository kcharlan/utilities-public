import test from 'node:test';
import assert from 'node:assert/strict';
const sim=await import('../dist/game/simulation.js').catch(()=>({}));
const worldMod=await import('../dist/game/world.js').catch(()=>({}));
const bot=await import('../dist/game/bot.js').catch(()=>({}));
test('every authored gap fits a measured envelope and final district approaches its limit',()=>{
  assert.equal(typeof worldMod.buildWorld,'function');
  const w=worldMod.buildWorld();
  assert.equal(w.districts.length,5);
  assert.ok(w.gaps.every(g=>g.utilization>0&&g.utilization<=1));
  assert.ok(w.gaps.filter(g=>g.district===4).every(g=>g.utilization>=.85));
});
test('each district teaches its new air feature first and remixes the earlier features',()=>{
  const w=worldMod.buildWorld();
  for(const d of w.districts){
    const airs=w.airs.filter(a=>a.district===d.index);assert.equal(airs[0].type,d.index);
    for(let feature=0;feature<=d.index;feature++)assert.ok(airs.some(a=>a.type===feature),`${d.name} missing feature ${feature}`);
  }
});
test('real hold/release bot finishes both modes without impacts in four to eight minutes',()=>{
  assert.equal(typeof sim.createRun,'function');
  for(const mode of ['standard','nonstop']){
    const r=sim.createRun(mode);
    for(let n=0;n<60*480&&r.status!=='finished';n++)sim.stepRun(r,bot.chooseInput(r));
    assert.equal(r.status,'finished',JSON.stringify({mode,x:r.plane.x,y:r.plane.y,crashes:r.crashes}));
    assert.equal(r.crashes,0); assert.ok(r.ticks/60>=240&&r.ticks/60<=480);
    assert.ok(r.landingStart.y>=25,'nominal approach should settle down into the bowl');
  }
});
test('swept collisions catch thin platforms',()=>{
  assert.equal(typeof sim.segmentHitsBox,'function');
  assert.equal(sim.segmentHitsBox({x:0,y:20},{x:100,y:20},{x:40,y:19,w:2,h:2}),true);
  assert.equal(sim.segmentHitsBox({x:0,y:30},{x:100,y:30},{x:40,y:19,w:2,h:2}),false);
});
test('standard crash restores checkpoint in under one second and keeps time; nonstop restarts',()=>{
  assert.equal(typeof sim.createRun,'function');
  for(const mode of ['standard','nonstop']){
    const r=sim.createRun(mode);r.ticks=600;r.checkpoint={x:500,y:150,speed:26,pitch:-.2};
    r.plane.y=-10;sim.stepRun(r,false); assert.equal(r.status,'respawning');
    for(let n=0;n<48;n++)sim.stepRun(r,false);
    assert.equal(r.status,'flying');
    if(mode==='standard'){assert.ok(r.plane.x>=500);assert.ok(r.ticks>600);}
    else {assert.ok(r.plane.x<30);assert.ok(r.ticks<60);}
  }
});
test('hazards advertise enough distance for at least two seconds at maximum closing speed',()=>{
  assert.equal(typeof worldMod.buildWorld,'function');
  for(const h of worldMod.buildWorld().hazards)assert.ok(h.warningDistance/(32+8+6)>=2);
});
test('later crossings require a pull-up rather than clearing with release alone',()=>{
  const r=sim.createRun();
  for(let n=0;n<60*480&&r.status!=='finished';n++)sim.stepRun(r,false);
  assert.notEqual(r.status,'finished');assert.ok(r.crashes>0);
});
test('park arrival descends continuously into the salad before results',()=>{
  const r=sim.createRun();r.plane.x=r.world.length-.1;r.plane.y=90;
  sim.stepRun(r,false);assert.equal(r.status,'landing');assert.ok(r.plane.y>80);
  for(let n=0;n<60;n++)sim.stepRun(r,false);
  assert.equal(r.status,'landing');assert.ok(r.plane.y>25&&r.plane.y<80);
  for(let n=0;n<60;n++)sim.stepRun(r,false);
  assert.equal(r.status,'finished');assert.equal(r.plane.y,25);assert.ok(r.events.includes('landing'));
});
test('both recognizable hazard types and roofs cause real impacts',()=>{
  for(const kind of ['pigeon','platform','roof']){
    const r=sim.createRun();const x=100,y=100;
    r.world={...r.world,airs:[],buildings:kind==='roof'?[{x:100,y:102,w:10}]:[],hazards:kind==='roof'?[]:[{id:'test',kind,x,y,w:10,h:10,phase:0,warningDistance:130}]};
    r.plane.x=x-1;r.plane.y=y+2;sim.stepRun(r,false);
    assert.equal(r.status,'respawning',kind);assert.equal(r.crashes,1);
  }
});
test('crossing a district saves a safe rooftop and emits a timely hazard warning',()=>{
  const r=sim.createRun(),next=r.world.districts[1];r.plane.x=next.start-.1;r.plane.y=150;
  sim.stepRun(r,false);assert.equal(r.district,1);assert.equal(r.checkpoint.x,next.checkpoint.x);assert.ok(r.events.includes('checkpoint'));
  // Pigeons travel up to 9m horizontally, so start inside the warning range at every phase.
  const h=r.world.hazards[0];r.plane.x=h.x-110;r.plane.y=130;
  sim.stepRun(r,false);assert.ok(r.events.includes('warning'));
});
test('squeeze warning identifies its pair once and wind entry emits no lift',async()=>{
  const {TIERS}=await import('../dist/game/tiers.js');const w=worldMod.buildWorld(undefined,TIERS.rush),r=sim.createRun('standard',w);
  const squeeze=w.hazards.find(h=>h.squeeze),pair=w.hazards.filter(h=>h.squeeze&&h.district===squeeze.district&&h.slot===squeeze.slot);
  r.plane.x=Math.min(...pair.map(h=>h.x-h.warningDistance))+2;r.plane.y=180;
  sim.stepRun(r,false);assert.ok(r.events.includes('warning'));assert.ok(r.warningHazards.some(h=>h.squeeze));
  for(let i=0;i<150;i++){sim.stepRun(r,false);assert.ok(!r.warningHazards.some(h=>h.squeeze));}
  const z=w.winds[0];r.plane.x=z.x0+20;r.plane.y=300;r.lastAir=null;sim.stepRun(r,false);assert.ok(!r.events.includes('lift'));
});
test('squeeze perch impact gives window correction with unchanged crash location',async()=>{
  const {TIERS}=await import('../dist/game/tiers.js');const w=worldMod.buildWorld(undefined,TIERS.rush),flock=w.hazards.find(h=>h.squeeze&&h.kind==='pigeon');
  const perch=w.buildings.find(b=>b.perch&&b.district===flock.district&&b.x===flock.x-6),r=sim.createRun('standard',w);
  r.plane.x=perch.x-1;r.plane.y=perch.y;sim.stepRun(r,false);
  assert.equal(r.status,'respawning');assert.match(r.cause,/window/i);assert.equal(r.crashLog[0].where,'perch 4.4');
});
