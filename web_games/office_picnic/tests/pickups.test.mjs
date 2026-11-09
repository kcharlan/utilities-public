import test from 'node:test';
import assert from 'node:assert/strict';
import {buildWorld} from '../dist/game/world.js';
import {createRun,stepRun} from '../dist/game/simulation.js';
import * as worldModule from '../dist/game/world.js';
import * as simulation from '../dist/game/simulation.js';
import {TIERS} from '../dist/game/tiers.js';

test('swept pickup crossing awards time, but a crash tick awards nothing',()=>{
  const world=buildWorld(); world.buildings=[]; world.hazards=[]; world.airs=[]; world.winds=[];
  world.pickups=[{id:'test',x:0.2,y:130,r:.05,rewardTicks:180}];
  const run=createRun('standard',world); stepRun(run,false);
  assert.equal(run.collected.has('test'),true); assert.equal(run.bonusTicks,180); assert.ok(run.events.includes('pickup'));
  const crash=createRun('standard',world); crash.plane.y=1; world.pickups[0].y=1; stepRun(crash,false);
  assert.equal(crash.collected.size,0); assert.equal(crash.bonusTicks,0);
});

test('attached pickup follows the moving washer',()=>{
  const world=buildWorld(undefined,TIERS.rush), h=world.hazards.find(h=>h.kind==='platform'&&h.moving);
  const pk={attach:h.id,ox:3,oy:-6};
  assert.notEqual(worldModule.pickupPos(world,pk,0).y,worldModule.pickupPos(world,pk,2).y);
});

test('net ticks subtract rewards and nonstop restarts clear collections',()=>{
  const world=buildWorld(),run=createRun('nonstop',world);
  run.ticks=400;run.bonusTicks=180;run.collected.add('test'); assert.equal(simulation.netTicks(run),220);
  run.status='respawning';run.respawnTicks=1;stepRun(run,false);
  assert.equal(run.collected.size,0);assert.equal(run.bonusTicks,0);
  const standard=createRun('standard',world);standard.collected.add('test');standard.bonusTicks=180;standard.status='respawning';standard.respawnTicks=1;stepRun(standard,false);
  assert.equal(standard.collected.has('test'),true);assert.equal(standard.bonusTicks,180);
});

test('pricing uses the impact penalty floor and grid requires a district clear',async()=>{
  const pricing=await import('../scripts/pickup-study.mjs');
  assert.equal(pricing.rewardPrice(3,1.2),3);
  assert.equal(pricing.rewardPrice(5,8.1),9);
  assert.equal(pricing.rewardPrice(5,null),null);
  assert.equal(pricing.gridSuccess({crashes:0,collected:true,done:false}),false);
  assert.equal(pricing.gridSuccess({crashes:0,collected:true,done:true}),true);
});

test('reference pilot targeting a pickup clears the district across the entry grid',async()=>{
  const {pickupGrid}=await import('../scripts/pickup-study.mjs');
  const world=buildWorld();assert.ok(pickupGrid(world,world.pickups[0])>=20);
});
