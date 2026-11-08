import test from 'node:test';import assert from 'node:assert/strict';
const helpers=await import('../dist/game/session.js').catch(()=>({}));
test('fixed step budget freezes paused time and bounds catch-up after a long frame',()=>{
  assert.equal(typeof helpers.consumeTime,'function');
  const c={accumulator:0};let steps=0;
  helpers.consumeTime(c,1/30,false,()=>steps++);assert.equal(steps,2);
  helpers.consumeTime(c,10,true,()=>steps++);assert.equal(steps,2);
  helpers.consumeTime(c,10,false,()=>steps++);assert.ok(steps<=8);
});
test('time display and camera preserve readable minimum phone lookahead',()=>{
  assert.equal(typeof helpers.cameraFor,'function');
  assert.equal(helpers.formatTime(65.67),'1:05.67');
  for(const width of [320,390,768,1440]){
    const c=helpers.cameraFor(width,740,{x:100,y:150});
    assert.ok((width-c.planeX)/c.scale>=250);
  }
});
test('portrait camera keeps the plane in the middle portion of the screen',()=>{
  const c=helpers.cameraFor(390,844,{x:100,y:150});
  const y=844-(150-c.bottom)*(c.verticalScale??c.scale);
  assert.ok(y>844*.35&&y<844*.7,`plane screen height ${y}`);
});
test('player distances and speeds use American units with useful near-goal precision',()=>{
  assert.equal(typeof helpers.formatDistance,'function');
  assert.equal(helpers.formatDistance(1609.344),'1.00 mi');
  assert.equal(helpers.formatDistance(304.8),'1,000 ft');
  assert.equal(helpers.formatDistance(0),'0 ft');
  assert.equal(helpers.formatDistance(-10),'0 ft');
  assert.equal(helpers.formatSpeed(26),'58 mph');
  assert.equal(helpers.formatSpeed(9),'20 mph');
  assert.equal(typeof helpers.formatVerticalMotion,'function');
  assert.equal(helpers.formatVerticalMotion(-3.048),'↓ Descending 10 ft/s');
  assert.equal(helpers.formatFeet(30.48),'100 ft');
});
