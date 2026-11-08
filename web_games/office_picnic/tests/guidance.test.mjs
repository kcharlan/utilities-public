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
  const r=createRun(),a=r.world.airs[3];r.plane.x=a.x+a.w/2;r.plane.y=180;
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
test('tailwind guidance discloses its forward and upward effects',()=>{
  const r=createRun(),a=r.world.airs.find(a=>a.type===3);r.plane.x=a.x+a.w/2;r.plane.y=150;
  const g=module.flightGuidance(r,false);assert.ok(g.air.lift>0);assert.ok(g.air.wind>0);
  assert.match(g.airLabel,/forward.*upward/i);
});
