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
test('quiet Nonstop impact notice expires on the rebased clock after a real restart',async()=>{
  const {TIERS}=await import('../dist/game/tiers.js');
  const {buildWorld}=await import('../dist/game/world.js');
  const {createRun,stepRun}=await import('../dist/game/simulation.js');
  const {noticeMessages}=await import('../dist/game/guidance.js');
  const run=createRun('nonstop',buildWorld(undefined,TIERS.overtime));
  run.worldTicks=1000;run.plane.y=0;stepRun(run,false);
  assert.ok(noticeMessages(run).length);let deadline=run.worldTicks+480;
  while(!run.events.includes('respawn')){
    const before=run.worldTicks;stepRun(run,false);
    deadline=helpers.rebaseNoticeDeadline(deadline,before,run.worldTicks);
  }
  assert.equal(run.worldTicks,0);assert.deepEqual(noticeMessages(run),[]);
  assert.equal(deadline,456);
  for(let i=0;i<456;i++)stepRun(run,true);
  assert.equal(run.worldTicks,456);assert.ok(run.worldTicks<=deadline);
  stepRun(run,true);assert.ok(run.worldTicks>deadline);
});
test('retry is available only in safe states or Nonstop',()=>{
  for(const mode of ['standard','nonstop'])for(const paused of [false,true])for(const finished of [false,true])for(const flying of [false,true])
    assert.equal(helpers.shouldRetry({mode,paused,finished,flying}),mode==='nonstop'||paused||finished);
});
test('dialog tab navigation wraps at either end and includes optional links',()=>{
  assert.equal(helpers.dialogTabTarget(0,3,true),2);
  assert.equal(helpers.dialogTabTarget(2,3,false),0);
  assert.equal(helpers.dialogTabTarget(1,3,false),null);
  assert.equal(helpers.dialogTabTarget(2,4,false),null);
  assert.equal(helpers.dialogTabTarget(3,4,false),0);
});
