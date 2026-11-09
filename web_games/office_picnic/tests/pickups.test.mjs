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

test('pricing uses the impact penalty floor',async()=>{
  const pricing=await import('../scripts/pickup-study.mjs');
  assert.equal(pricing.rewardPrice(3,1.2),3);
  assert.equal(pricing.rewardPrice(5,8.1),9);
  assert.equal(pricing.rewardPrice(5,null),null);
});

test('reference pilot targeting a pickup clears the district across the entry grid',async()=>{
  const {pickupGrid}=await import('../scripts/pickup-study.mjs');
  const world=buildWorld();assert.ok(pickupGrid(world,world.pickups[0])>=20);
});

test('configured pickup coverage rejects a placement whose hazard is absent',async()=>{
  const {pickupCoverage}=await import('../scripts/pickup-study.mjs');
  const tier={...TIERS.casual,pickups:[...TIERS.casual.pickups,{district:0,slot:1,place:'underWasher',dy:6,rewardTicks:180}]};
  assert.equal(pickupCoverage(tier,buildWorld(undefined,tier)),false);
  assert.equal(pickupCoverage(TIERS.casual,buildWorld()),true);
});

test('pickup grid requires reaching the district end even when pickup was collected',async()=>{
  const {pickupGrid,pricePickup}=await import('../scripts/pickup-study.mjs');
  const world=buildWorld(),d=world.districts[0];
  world.hazards=[];world.buildings=[];world.airs=[];world.winds=[];
  const pk={id:'test',district:0,slot:0,place:'high',label:'test',x:d.checkpoint.x+.1,y:d.checkpoint.y,r:20,rewardTicks:180};world.pickups=[pk];
  d.end=d.checkpoint.x+1;world.length=d.end;
  assert.equal(pickupGrid(world,pk),27);
  d.end=1e6;
  assert.equal(pickupGrid(world,pk),0);
  const result=pricePickup(world,pk,1);assert.equal(result.collected,1);assert.equal(result.onPath,1);assert.equal(result.timeouts,1);assert.equal(result.qualifies,false);
});

test('menu extension belongs only to Overtime Crosswind Court',async()=>{
  const {menuCandidates}=await import('../scripts/pickup-study.mjs');
  assert.equal(menuCandidates('casual',3).length,9);
  assert.equal(menuCandidates('overtime',2).length,9);
  assert.equal(menuCandidates('overtime',3).length,19);
});

test('menu uses 100 paired samples by default and identifies each candidate',async()=>{
  const {menuSampleSize,pickupMenu}=await import('../scripts/pickup-study.mjs');
  assert.equal(menuSampleSize(150,false),100);assert.equal(menuSampleSize(3,true),3);
  const rows=pickupMenu({...TIERS.casual,pickups:[]},1);
  assert.ok(rows.every(row=>row.samples===1&&Number.isInteger(row.slot)&&typeof row.place==='string'));
  const roof=rows.find(row=>row.place==='roofEdge');assert.equal(roof.dx,6);assert.equal(typeof roof.dy,'number');
});

test('menu JSON is a single parseable document with its paired sample size',async()=>{
  const {execFile}=await import('node:child_process');const {promisify}=await import('node:util');
  const {stdout}=await promisify(execFile)(process.execPath,['scripts/playtest.mjs','--tier','casual','--menu','--json','--n','1'],{cwd:new URL('../',import.meta.url)});
  const result=JSON.parse(stdout);assert.equal(result.samples,1);assert.ok(result.tiers.casual.length>0);assert.equal(result.tiers.casual[0].samples,1);
});

test('playtest check fails when an authored pickup cannot be built',async()=>{
  const {mkdtemp,cp,readFile,writeFile,rm}=await import('node:fs/promises');
  const {tmpdir}=await import('node:os');const {join}=await import('node:path');
  const {execFile}=await import('node:child_process');const {promisify}=await import('node:util');
  const root=await mkdtemp(join(tmpdir(),'office-pickup-test-'));
  try{
    await cp(new URL('../dist/',import.meta.url),join(root,'dist'),{recursive:true});
    await cp(new URL('../scripts/',import.meta.url),join(root,'scripts'),{recursive:true});
    await cp(new URL('../package.json',import.meta.url),join(root,'package.json'));
    const path=join(root,'dist/game/tiers.js'),source=await readFile(path,'utf8');
    const changed=source.replace("P(2,2,'underWasher',6,9)","P(2,1,'underWasher',6,9)");assert.notEqual(changed,source);await writeFile(path,changed);
    await assert.rejects(promisify(execFile)(process.execPath,['scripts/playtest.mjs','--tier','casual','--check'],{cwd:root}),error=>error.code===1&&error.stdout.includes('FAIL casual pickup coverage'));
  }finally{await rm(root,{recursive:true,force:true});}
});

test('menu JSON is complete when stdout is backpressured',async()=>{
  const {execFile}=await import('node:child_process');const {promisify}=await import('node:util');
  const command='{ head -c 60000 /dev/zero; "$1" scripts/playtest.mjs --tier casual --menu --json --n 1; } | { sleep 12; cat; }';
  const {stdout}=await promisify(execFile)('sh',['-c',command,'sh',process.execPath],{cwd:new URL('../',import.meta.url),maxBuffer:1024*1024});
  const result=JSON.parse(stdout.slice(60000));
  assert.equal(result.samples,1);assert.ok(result.tiers.casual.length>0);
});
