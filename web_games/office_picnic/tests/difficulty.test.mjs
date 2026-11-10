import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

test('difficulty measurement is available as a project command',()=>{
  const pkg=JSON.parse(readFileSync(new URL('../package.json',import.meta.url)));
  assert.equal(pkg.scripts.difficulty,'node scripts/difficulty.mjs');
});

test('difficulty rejects a missing tier',()=>{
  const result=spawnSync(process.execPath,[fileURLToPath(new URL('../scripts/difficulty.mjs',import.meta.url)),'--tier'],{encoding:'utf8'});
  assert.notEqual(result.status,0);
  assert.match(result.stderr,/Missing tier value/);
});

import {difficulty} from '../scripts/difficulty.mjs';
import {buildWorld} from '../dist/game/world.js';
import {TIERS} from '../dist/game/tiers.js';
import {playOnce,laneValue} from '../scripts/flight-study.mjs';

for(const [id,tier] of Object.entries(TIERS)){
  test(`${id}: crossing windows meet ramp and fairness gates`,()=>{
    const rows=difficulty(buildWorld(undefined,tier)),windows=rows.map(row=>row.window);
    assert.equal(rows.length,5);
    for(const [i,row] of rows.entries()){
      assert.equal(row.district,i+1);
      assert.equal(row.crossings.length,6);
      assert.ok(row.crossings.some(c=>c.id===row.tightest&&c.window===row.window));
      assert.equal(row.belowCap,row.crossings.filter(c=>c.window<1500).length);
    }
    if(id!=='casual'){
      assert.ok(windows.every(w=>w>=windows[4]-50),`${id} windows ${windows}`);
      assert.ok(windows[4]<=windows[0]*.6,`${id} windows ${windows}`);
    }
    const floor={casual:400,rush:300,overtime:200}[id];
    for(const row of rows)for(const crossing of row.crossings){
      assert.ok(crossing.window>=floor,`${id} ${crossing.id}: ${crossing.window} ms`);
      if(crossing.id.endsWith('.T'))assert.ok(crossing.window>=1000,`${id} ${crossing.id}: ${crossing.window} ms`);
    }
  });
  test(`${id}: regular pilots crash most in a late district`,()=>{
    const world=buildWorld(undefined,tier),counts=Array(5).fill(0);
    for(let seed=1000;seed<1150;seed++)for(const crash of playOnce(world,'regular',seed).log)counts[crash.district]++;
    assert.ok(counts[3]+counts[4]>=1.5*(counts[1]+counts[2]),`${id}: ${counts}`);
    assert.ok(Math.max(counts[3],counts[4])===Math.max(...counts),`${id}: ${counts}`);
    assert.ok(counts[4]>=counts[0],`${id}: ${counts}`);
  });
  test(`${id}: final tailwind lanes qualify and obey the wind cap`,()=>{
    const world=buildWorld(undefined,tier),lanes=world.winds.filter(w=>w.wind>0&&!w.teaching);
    assert.ok(world.winds.filter(w=>w.wind>0).every(w=>w.wind<=12));
    const values=lanes.map(lane=>laneValue(world,lane));
    assert.ok(values.every(value=>value.qualifies),JSON.stringify(values));
    assert.ok(values.length>=({casual:2,rush:1,overtime:1}[id]),`${id}: ${values.length} choice lanes`);
  });
}
test('casual: no crossing is a novice wall',()=>{
  const world=buildWorld(undefined,TIERS.casual),counts=Array(world.checkpoints.length).fill(0);
  for(let seed=1000;seed<1150;seed++)for(const crash of playOnce(world,'novice',seed).log){
    const index=world.checkpoints.findLastIndex(cp=>cp.x<=crash.x);
    counts[Math.max(0,index)]++;
  }
  assert.ok(Math.max(...counts)<=150,`crossing crashes per 150 runs: ${counts}`);
});
test('last crossing measures impacts before the park',()=>{
  const base=buildWorld(undefined,TIERS.casual);
  const world={...base,buildings:[...base.buildings,{x:base.finishStart-30,y:400,w:20,h:100}]};
  const row=difficulty(world).at(-1),last=row.crossings.find(c=>c.id==='5.5');
  assert.equal(last.window,0,'the pilot cannot reach the finish without hitting the added roof');
});
