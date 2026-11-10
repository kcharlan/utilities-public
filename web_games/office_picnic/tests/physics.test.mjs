import test from 'node:test';
import assert from 'node:assert/strict';
const physics = await import('../dist/game/physics.js').catch(() => ({}));

test('holding converts forward energy into height', () => {
  assert.equal(typeof physics.createPlane, 'function', 'flight model is not implemented');
  const p = physics.createPlane({speed:30,y:100});
  for(let n=0;n<90;n++) physics.advancePlane(p,true);
  assert.ok(p.y>108, `height ${p.y}`);
  assert.ok(p.speed<25, `speed ${p.speed}`);
});
test('release gains speed and descends', () => {
  assert.equal(typeof physics.createPlane,'function');
  const p=physics.createPlane({speed:14,y:100});
  for(let n=0;n<240;n++) physics.advancePlane(p,false);
  assert.ok(p.speed>18); assert.ok(p.y<95);
});
test('stall costs height, release recovers, fixed inputs reproduce state', () => {
  assert.equal(typeof physics.createPlane,'function');
  const p=physics.createPlane({speed:8,y:100});
  physics.advancePlane(p,true); assert.equal(p.stalled,true);
  for(let n=0;n<300;n++) physics.advancePlane(p,false);
  assert.equal(p.stalled,false); assert.ok(p.speed>16); assert.ok(p.y<100);
  const a=physics.createPlane(), b=physics.createPlane();
  for(let n=0;n<600;n++){physics.advancePlane(a,n%100<20);physics.advancePlane(b,n%100<20);}
  assert.deepEqual(a,b);
});
test('holding a stalled plane cannot harvest lift for free height',()=>{
  for(const pitch of [-.05,.46]){
    const p=physics.createPlane({speed:8,y:100,pitch});physics.advancePlane(p,true,{lift:18,wind:5});
    assert.equal(p.stalled,true);assert.ok(p.y<100,`stalled height ${p.y}, pitch ${pitch}`);
  }
});
test('released dive can lower altitude and build airspeed inside steady AC lift',()=>{
  const p=physics.createPlane({y:180,speed:20,pitch:-.2});
  for(let n=0;n<120;n++)physics.advancePlane(p,false,{lift:6.5,wind:0});
  assert.ok(p.y<176,`release still cannot descend in AC: ${p.y}`);
  assert.ok(p.speed>24,`released dive does not build speed: ${p.speed}`);
});
test('releasing from nose-up flight produces downward motion within one second in AC',()=>{
  const p=physics.createPlane({y:210,speed:23,pitch:.46});
  for(let n=0;n<60;n++)physics.advancePlane(p,false,{lift:6.5,wind:0});
  assert.ok(p.pitch<-.45,`dive pitch ${p.pitch}`);assert.ok(p.vy< -2,`still rising ${p.vy}`);
});
test('flight measurement reports controlled still-air range alongside released dives',async()=>{
  const {measureFlight}=await import('../dist/game/measure.js');
  const result=measureFlight();
  assert.ok(result.bestStillAirRange.range>1000);
  assert.equal(result.bestStillAirRange.entryHeight,184);
  assert.equal(result.bestStillAirRange.roofHeight,73);
});
