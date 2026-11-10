import test from 'node:test';
import assert from 'node:assert/strict';
import {createRun,stepRun} from '../dist/game/simulation.js';
import {buildWorld} from '../dist/game/world.js';
import {TIERS} from '../dist/game/tiers.js';

for(const tier of Object.values(TIERS)) test(`${tier.id}: park captures an approach before street level`,()=>{
  const world=buildWorld(undefined,tier),run=createRun('standard',world);
  run.plane.x=world.finishStart+10;run.plane.y=29;
  stepRun(run,false);
  assert.equal(run.status,'landing');assert.equal(run.landingKind,'floor');
  const start=run.plane.x;
  while(run.status==='landing'){
    const before={...run.plane};stepRun(run,false);
    assert.ok(run.plane.x>before.x);assert.ok(before.y-run.plane.y<=Math.tan(40*Math.PI/180)*(run.plane.x-before.x)+1e-8);
  }
  assert.ok(run.plane.x>start);assert.equal(run.plane.y,25);
});

import {createPlane} from '../dist/game/physics.js';
import {makePilot,PROFILES} from '../scripts/pilot.mjs';
function checkPath(run){
  const kind=run.landingKind,duration=run.landingDurationTicks;
  assert.ok(duration>=60&&duration<=360,`${kind} duration ${duration}`);
  while(run.status==='landing'){
    const before={...run.plane};stepRun(run,false);
    if(kind!=='overhead'){
      assert.ok(run.plane.x>before.x,`${kind} x`);
      assert.ok(before.y-run.plane.y<=Math.tan(40*Math.PI/180)*(run.plane.x-before.x)+1e-7,`${kind} slope`);
    }
  }
  assert.equal(run.status,'finished');assert.equal(run.plane.y,run.world.park.bowlY);
}
function startAtFlock(world,speed){
  const flock=world.hazards.filter(h=>h.kind==='pigeon').at(-1);
  const x=flock.x+flock.w+(flock.amp?.pigeonX??0)+3,y=flock.y+flock.h+(flock.amp?.pigeonY??0)+12;
  const run=createRun('standard',world);run.plane=createPlane({x,y,speed,pitch:0});return run;
}
for(const tier of Object.values(TIERS)){
  test(`${tier.id}: release and delayed release reach the bowl on a shallow approach`,()=>{
    const world=buildWorld(undefined,tier);
    for(const speed of [20,26,30])for(const delay of [0,100]){
      const run=startAtFlock(world,speed),x=run.plane.x,y=run.plane.y;
      for(let n=0;n<3000&&run.status==='flying';n++)stepRun(run,run.plane.x<x+delay&&run.plane.y<y);
      assert.ok(delay?run.landingKind==='cone':['cone','floor'].includes(run.landingKind),`${speed}, ${delay}: ${run.landingKind} ${run.status}`);
      checkPath(run);
    }
  });
  test(`${tier.id}: seeded pilots land safely in the park`,()=>{
    const world=buildWorld(undefined,tier);
    for(const profile of ['regular','novice']){
      let finished=0,safe=0;
      for(let seed=1000;seed<1150;seed++){
        const run=createRun('standard',world),pilot=makePilot(PROFILES[profile],seed);
        for(let n=0;n<72000&&(run.status==='flying'||run.status==='respawning');n++){
          stepRun(run,pilot(run));
        }
        assert.ok(run.crashLog.every(c=>c.x<=world.finishStart),`${profile} ${seed}: park impact`);
        if(run.status==='landing'){
          finished++;if(['cone','floor'].includes(run.landingKind))safe++;checkPath(run);
        }
      }
      assert.ok(finished>0&&safe/finished>=.95,`${profile}: ${safe}/${finished}`);
    }
  });
  test(`${tier.id}: sustained hold flutters down more slowly than release`,()=>{
    const world=buildWorld(undefined,tier),released=startAtFlock(world,26),held=createRun('standard',world);
    held.plane=createPlane({x:world.finishStart+.1,y:300,speed:12,pitch:0});
    const elapsed=[];
    for(const [run,hold] of [[released,false],[held,true]]){
      while(run.status==='flying'&&run.plane.x<=world.finishStart)stepRun(run,hold);
      const entered=run.ticks;
      while(run.status==='flying'&&run.ticks<12000)stepRun(run,hold);
      assert.equal(run.status,'landing');checkPath(run);elapsed.push(run.finishTicks-entered);
    }
    assert.equal(held.landingKind,'overhead');assert.ok(elapsed[1]>elapsed[0]);
  });
}
test('park floor beats street and park obstacles cannot cause an impact',()=>{
  const run=createRun(),world=run.world;
  run.world={...world,buildings:[{x:world.finishStart,y:500,w:200}],hazards:[{id:'synthetic',kind:'pigeon',x:world.finishStart,y:0,w:200,h:500,moving:false,warningDistance:0}]};
  run.plane.x=world.finishStart+20;run.plane.y=-1;stepRun(run,false);
  assert.equal(run.status,'landing');assert.equal(run.landingKind,'floor');assert.equal(run.crashes,0);
});
