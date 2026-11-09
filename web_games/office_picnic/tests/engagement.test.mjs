import test from 'node:test';import assert from 'node:assert/strict';
import {createRun,stepRun} from '../dist/game/simulation.js';
import {createPlane,advancePlane} from '../dist/game/physics.js';
import {buildWorld,airAt,hazardBox} from '../dist/game/world.js';
import {chooseInput} from '../dist/game/bot.js';

test('passive release fails during the opening district within forty seconds',()=>{
  const r=createRun();for(let n=0;n<60*40&&r.crashes===0;n++)stepRun(r,false);
  assert.ok(r.crashes>0,'opening permits passive gliding');assert.equal(r.district,0);
});
test('a single launch pull-up cannot coast through the entire opening district',()=>{
  for(const initialHoldTicks of [126,180]){
    const r=createRun();for(let n=0;n<60*120&&r.crashes===0&&r.district===0;n++)stepRun(r,n<initialHoldTicks);
    assert.ok(r.crashes>0&&r.district===0,`${initialHoldTicks/60}s launch hold bypasses all later input`);
  }
});
test('a height-only cruise policy encounters a real hazard in the opening district',()=>{
  const r=createRun();for(let n=0;n<60*120&&r.crashes===0&&r.district===0;n++)stepRun(r,r.plane.speed>14&&r.plane.y<155);
  assert.ok(r.crashes>0&&/Pigeon|Window/.test(r.cause),`no avoidance needed: ${r.cause}`);
});
test('opening route makes the pilot clear hazards both above and below',()=>{
  const r=createRun(),passed=[];let held=0;
  for(let n=0;n<60*130&&r.district===0&&r.crashes===0;n++){
    const before=r.plane.x,input=chooseInput(r);held+=Number(input);stepRun(r,input);
    for(const h of r.world.hazards.filter(h=>h.district===0)){
      const b=hazardBox(h,r.worldTicks/60);
      if(before<b.x+b.w&&r.plane.x>=b.x+b.w)passed.push({pass:h.pass,y:r.plane.y,box:b});
    }
  }
  assert.equal(r.crashes,0);assert.ok(held>0);
  assert.ok(passed.some(h=>h.pass==='above'&&h.y>h.box.y+h.box.h+1.2),'missing real climb-over encounter');
  assert.ok(passed.some(h=>h.pass==='below'&&h.y<h.box.y-1.2),'missing real dive-under encounter');
});
test('vent lull lets the plane descend while its visible burst raises it',()=>{
  const w=buildWorld(),a=w.airs.find(a=>a.type===1),p={x:a.x+a.w/2,y:150};
  const low=airAt(w,p,(Math.PI*1.5-a.phase)/1.4),high=airAt(w,p,(Math.PI*.5-a.phase)/1.4);
  const descending=createPlane({...p,speed:26,pitch:-.2}),rising=createPlane({...p,speed:26,pitch:-.2});
  advancePlane(descending,false,low);advancePlane(rising,false,high);
  assert.ok(descending.vy<0,`vent never releases: ${descending.vy}`);assert.ok(rising.vy>4,`burst not meaningful: ${rising.vy}`);
});
test('wide heat, fading lift and wind produce distinct physical responses',()=>{
  const w=buildWorld();
  function sample(type,y=150){const a=w.airs.find(a=>a.type===type);return airAt(w,{x:a.x+a.w/2,y},0);}
  const ac=createPlane({speed:26,pitch:-.2}),heat=createPlane({speed:26,pitch:-.2});
  advancePlane(ac,false,sample(0));advancePlane(heat,false,sample(2));
  assert.ok(ac.vy-heat.vy>=1,'rooftop heat feels the same as AC');
  assert.ok(sample(4,140).lift-sample(4,210).lift>5,'fading thermal has no meaningful height falloff');
  const still=createPlane({speed:26,pitch:-.2}),wind=createPlane({speed:26,pitch:-.2});
  advancePlane(still,false);advancePlane(wind,false,sample(3));assert.ok(wind.x-still.x>.08,'tailwind does not advance the plane');
});
test('staying high throughout the opening cannot bypass the dive-under encounter',()=>{
  for(const height of [185,230,300]){
    const r=createRun();for(let n=0;n<60*120&&r.crashes===0&&r.district===0;n++)stepRun(r,r.plane.speed>14&&r.plane.y<height);
    assert.ok(r.crashes>0&&/Window/.test(r.cause),`${height}m high cruise bypasses washers: ${r.cause}`);
  }
});
test('a player at normal cruising height can react to the advertised washer warning',()=>{
  const r=createRun(),flock=r.world.hazards[0],washer=r.world.hazards[1];let reacting=false,delay=24;
  for(let n=0;n<60*100&&r.crashes===0&&r.plane.x<washer.x+washer.w+3;n++){
    if(r.warned.has(washer.id))reacting=true;
    // Diving is now effective: descend, then briefly pitch up to level below the platform.
    const input=r.plane.x<flock.x+flock.w+8?chooseInput(r):reacting&&delay--<=0?r.plane.speed>14&&r.plane.y<washer.y-24:r.plane.speed>14&&r.plane.y<170;
    stepRun(r,input);
  }
  assert.equal(r.crashes,0,`warning arrives too late: ${r.cause}`);assert.ok(r.plane.x>washer.x+washer.w);
});
test('a high nose-up approach can dive through AC and level below the washer',()=>{
  for(const height of [170,200,230]){
    const r=createRun(),h=r.world.hazards.find(h=>h.kind==='platform');
    r.plane=createPlane({x:h.x-220,y:height,speed:23,pitch:.46});
    for(let n=0;n<60*25&&r.crashes===0&&r.plane.x<h.x+h.w+3;n++)stepRun(r,r.plane.speed>14&&r.plane.y+r.plane.vy*.5<h.y-18);
    assert.equal(r.crashes,0,`${height}m approach cannot recover: ${r.cause}`);assert.ok(r.plane.x>h.x+h.w);
  }
});
test('all shortcut policies fail every district in every available tier',async()=>{
  const {TIERS}=await import('../dist/game/tiers.js');const {shortcutOutcomes}=await import('../scripts/flight-study.mjs');
  for(const tier of Object.values(TIERS))assert.ok(Object.values(shortcutOutcomes(buildWorld(undefined,tier))).every(n=>n===0),tier.id);
});
