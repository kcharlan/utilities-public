import test from 'node:test';import assert from 'node:assert/strict';
import {createRun} from '../dist/game/simulation.js';
const module=await import('../dist/game/guidance.js').catch(()=>({}));
test('flight guidance warns to climb over the first flock and dive before the washers',()=>{
  assert.equal(typeof module.flightGuidance,'function');
  const r=createRun();assert.match(module.flightGuidance(r,false).instruction,/climb/i);
  const washer=r.world.hazards.find(h=>h.kind==='platform');r.plane.x=washer.x-200;
  assert.match(module.flightGuidance(r,true).instruction,/release|dive/i);
  r.plane.stalled=true;assert.match(module.flightGuidance(r,true).instruction,/recover/i);
});
test('guidance stops asking for more climb when speed is low or the flock is already below',()=>{
  const r=createRun();r.plane.speed=14;assert.match(module.flightGuidance(r,true).instruction,/release/i);
  r.plane.speed=23;r.plane.y=190;assert.match(module.flightGuidance(r,true).instruction,/release/i);
});
test('between encounters guidance asks to rebuild height only when it is needed',()=>{
  const r=createRun(),a=r.world.airs[4];r.plane.x=a.x+a.w/2;r.plane.y=180;
  assert.match(module.flightGuidance(r,false).instruction,/^Release/i);
  r.plane.y=120;assert.match(module.flightGuidance(r,false).instruction,/^Hold/i);
});
test('guidance does not tell a low plane to glide into a raised receiving roof',()=>{
  const r=createRun(),roof=r.world.buildings.find(b=>b.y===110);r.plane.x=roof.x-20;r.plane.y=116;
  assert.match(module.flightGuidance(r,false).instruction,/^Hold.*roof/i);
});
test('air guidance distinguishes upward push from actual rising or descending motion',()=>{
  const r=createRun();r.plane.vy=-5;const falling=module.flightGuidance(r,false);
  assert.match(falling.airLabel,/upward/i);assert.match(falling.motionLabel,/descending/i);
  r.plane.vy=5;assert.match(module.flightGuidance(r,false).motionLabel,/rising/i);
});
test('a plane already below the washer gets level-out advice instead of an endless dive',()=>{
  const r=createRun(),h=r.world.hazards.find(h=>h.kind==='platform');r.plane.x=h.x-50;r.plane.y=h.y-35;r.plane.vy=-8;
  assert.match(module.flightGuidance(r,false).instruction,/^Hold.*level/i);
});
test('guidance exposes the same vent lull and burst that affect the plane',()=>{
  assert.equal(typeof module.flightGuidance,'function');
  const r=createRun(),vent=r.world.airs.find(a=>a.type===1);r.plane.x=vent.x+vent.w/2;r.plane.y=150;
  r.worldTicks=(Math.PI*1.5-vent.phase)/1.4*60;assert.match(module.flightGuidance(r,false).airLabel,/lull/i);
  r.worldTicks=(Math.PI*.5-vent.phase)/1.4*60;assert.match(module.flightGuidance(r,false).airLabel,/burst/i);
});
test('tailwind guidance identifies its direction and nearby lane',()=>{
  const r=createRun(),a=r.world.airs.find(a=>a.type===3);r.plane.x=a.x+a.w/2;r.plane.y=150;
  const g=module.flightGuidance(r,false);assert.ok(g.air.lift>0);assert.ok(g.air.wind>0);
  assert.match(g.airLabel,/Tailwind · Wind column ↑/i);
  r.plane.y=180;assert.match(module.flightGuidance(r,false).airLabel,/Tailwind lane below/i);
});
test('wind overlapping the Casual vent retains burst and lull guidance',()=>{
  const r=createRun(),lane=r.world.winds.find(z=>z.wind>0&&!z.teaching&&z.district===4);
  const vent=r.world.airs.find(a=>a.type===1&&a.x<lane.x1&&a.x+a.w>lane.x0);
  r.plane.x=Math.max(vent.x,lane.x0)+Math.min(vent.w,20)/2;r.plane.y=(lane.y0+lane.y1)/2;
  r.worldTicks=(Math.PI*.5-vent.phase)/1.4*60;
  assert.match(module.flightGuidance(r,false).airLabel,/tailwind.*burst/i);
  r.worldTicks=(Math.PI*1.5-vent.phase)/1.4*60;
  assert.match(module.flightGuidance(r,false).airLabel,/tailwind.*lull/i);
});
test('zero wind at a solo lane edge falls back to lift or still air',()=>{
  const r=createRun(),lane=r.world.winds.find(z=>z.teaching),air=r.world.airs.find(a=>a.gapId==='4.T');
  r.plane.x=air.x+air.w/2;r.plane.y=lane.y0;
  assert.match(module.flightGuidance(r,false).airLabel,/wind column.*upward/i);
  r.plane.x=air.x+air.w+15;
  assert.equal(module.flightGuidance(r,false).airLabel,'Still air');
});
test('headwind names its effect and squeeze guidance targets the live window',async()=>{
  const {buildWorld,hazardAdvice}=await import('../dist/game/world.js');const {TIERS}=await import('../dist/game/tiers.js');
  const r=createRun('standard',buildWorld(undefined,TIERS.rush)),wind=r.world.winds.find(w=>w.wind<0);
  r.plane.x=wind.x0+20;r.plane.y=300;assert.match(module.flightGuidance(r,false).airLabel,/Headwind · slows you/);
  const h=r.world.hazards.find(h=>h.squeeze);r.plane.x=h.x-40;r.plane.y=110;
  assert.match(hazardAdvice(h),/fly between/);assert.match(module.flightGuidance(r,false).instruction,/climb.*window/i);
  r.plane.y=190;assert.match(module.flightGuidance(r,false).instruction,/dive.*window/i);
});
test('moving hazard guidance uses its live box rather than its authored height',async()=>{
  const {buildWorld,hazardBox}=await import('../dist/game/world.js');const {TIERS}=await import('../dist/game/tiers.js');
  const r=createRun('standard',buildWorld(undefined,TIERS.rush)),h=r.world.hazards.find(h=>h.kind==='platform'&&h.moving);
  r.worldTicks=60*(Math.PI/2-h.phase)/(.8*h.amp.rate);const box=hazardBox(h,r.worldTicks/60);
  r.plane.x=box.x-50;r.plane.y=h.y-25;r.plane.vy=0;
  assert.ok(box.y>h.y+10);assert.match(module.flightGuidance(r,false).instruction,/level out/i);
});
test('simultaneous checkpoint, impact and warning notices retain each message',async()=>{
  const {noticeMessages}=await import('../dist/game/guidance.js');
  const r=createRun();r.district=3;r.events=['district','impact','warning'];r.cause='Impact correction';r.warningHazards=[{squeeze:true}];
  r.world={...r.world,tier:{...r.world.tier,prompts:'warnings'},winds:[{district:3,wind:-3}]};
  const text=noticeMessages(r).join(' ');assert.match(text,/Impact correction/);assert.match(text,/Crosswind Court/);assert.match(text,/Headwinds ahead/);assert.match(text,/Squeeze/);
});
test('quiet notices keep impact and windy checkpoint but suppress respawn and warning',async()=>{
  const {noticeMessages}=await import('../dist/game/guidance.js');
  const {buildWorld}=await import('../dist/game/world.js');const {TIERS}=await import('../dist/game/tiers.js');
  const r=createRun('standard',buildWorld(undefined,TIERS.overtime));
  r.district=3;r.events=['district','impact','respawn','warning'];r.cause='Impact correction';r.warningHazards=[{squeeze:true}];
  assert.deepEqual(noticeMessages(r),['Impact correction','Crosswind Court · Headwinds ahead']);
  r.events=['respawn','warning'];assert.deepEqual(noticeMessages(r),[]);
  assert.ok(module.flightGuidance(r,false).instruction);
});
test('headwind uses still-air flight and rooftop guidance',async()=>{
  const {buildWorld}=await import('../dist/game/world.js');const {TIERS}=await import('../dist/game/tiers.js');
  const r=createRun('standard',buildWorld(undefined,TIERS.rush)),zone=r.world.winds[0];r.plane.x=zone.x0+20;r.plane.y=140;r.world={...r.world,hazards:[],buildings:[]};
  assert.match(module.flightGuidance(r,false).instruction,/level out/i);
});
test('guidance selects hazards by their moving horizontal box',async()=>{
  const {buildWorld,hazardBox}=await import('../dist/game/world.js');const {TIERS}=await import('../dist/game/tiers.js');
  const r=createRun('standard',buildWorld(undefined,TIERS.rush)),h=r.world.hazards.find(h=>h.kind==='pigeon'&&h.moving);
  r.worldTicks=60*(Math.PI/2-h.phase)/(.65*h.amp.rate);const b=hazardBox(h,r.worldTicks/60);r.world={...r.world,hazards:[h],buildings:[]};
  r.plane.x=h.x+h.w+9;r.plane.y=120;assert.ok(b.x>h.x+8);assert.equal(module.flightGuidance(r,false).hazard,h);
});
test('moving introduction waits for its district while warnings and retries remain actionable',async()=>{
  const {buildWorld,hazardAdvice}=await import('../dist/game/world.js');const {TIERS}=await import('../dist/game/tiers.js');
  const {stepRun}=await import('../dist/game/simulation.js');
  for(const tier of [TIERS.rush,TIERS.overtime,{...TIERS.rush,prompts:'full'}]){
    const r=createRun('standard',buildWorld(undefined,tier)),h=r.world.hazards.find(h=>h.firstMoving);
    assert.match(hazardAdvice(h),/climb over/i);
    r.plane.x=h.x-h.warningDistance-15;r.plane.y=300;
    for(let i=0;i<120&&!r.warningHazards?.includes(h);i++)stepRun(r,false);
    assert.equal(r.district,0);assert.ok(r.warningHazards.includes(h));
    const early=module.noticeMessages(r).join(' ');
    assert.doesNotMatch(early,/watch its rhythm/);
    if(tier.prompts!=='quiet')assert.match(early,/climb over/i);
    r.district=1;r.warningHazards=[];r.events=['district'];
    assert.match(module.noticeMessages(r).join(' '),/Moving flock · watch its rhythm/);
    assert.doesNotMatch(module.noticeMessages(r).join(' '),/watch its rhythm/);
    r.plane.x=h.x-30;r.events=['respawn'];
    assert.doesNotMatch(module.noticeMessages(r).join(' '),/watch its rhythm/);
    if(tier.prompts!=='quiet')assert.match(module.noticeMessages(r).join(' '),/climb over/i);
  }
});
test('Nonstop fresh throw can introduce tier features again',async()=>{
  const {buildWorld}=await import('../dist/game/world.js');const {TIERS}=await import('../dist/game/tiers.js');
  const {stepRun}=await import('../dist/game/simulation.js');
  const r=createRun('nonstop',buildWorld(undefined,TIERS.overtime));
  r.district=1;r.events=['district'];assert.match(module.noticeMessages(r).join(' '),/Moving flock/);
  r.plane.y=0;stepRun(r,false);while(r.status==='respawning')stepRun(r,false);
  r.district=1;r.events=['district'];assert.match(module.noticeMessages(r).join(' '),/Moving flock/);
});
