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
  assert.equal(menuCandidates('casual',3).length,30);
  assert.equal(menuCandidates('overtime',2).length,30);
  assert.equal(menuCandidates('overtime',3).length,40);
});

test('menu uses 100 paired samples by default and identifies each candidate',async()=>{
  const {menuSampleSize,pickupMenu}=await import('../scripts/pickup-study.mjs');
  assert.equal(menuSampleSize(150,false),100);assert.equal(menuSampleSize(3,true),3);
  const rows=pickupMenu({...TIERS.casual,pickups:[]},1);
  assert.ok(rows.every(row=>row.samples===1&&row.r===5&&Number.isInteger(row.slot)&&typeof row.place==='string'));
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
    await cp(new URL('../tests/',import.meta.url),join(root,'tests'),{recursive:true});
    await cp(new URL('../package.json',import.meta.url),join(root,'package.json'));
    const path=join(root,'dist/game/tiers.js'),source=await readFile(path,'utf8');
    const changed=source.replace("P(2,0,'overFlock',36,3)","P(2,1,'underWasher',6,3)");assert.notEqual(changed,source);await writeFile(path,changed);
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

test('pickup notices have tiered lead distances and fire once across respawns',()=>{
  const leads=[600,450,300];
  for(const [tier,lead] of Object.values(TIERS).map((tier,i)=>[tier,leads[i]])){
    const world=buildWorld(undefined,tier);
    for(const pk of world.pickups){assert.equal(pk.r,5);assert.ok(pk.announceX>=0);assert.equal(pk.x-pk.announceX,lead);assert.ok(pk.hint);}
    world.buildings=[];world.hazards=[];world.airs=[];world.winds=[];
    const pk=world.pickups[0];world.pickups=[{...pk,attach:null}];const run=createRun('standard',world);run.plane.x=pk.announceX-.1;run.plane.y=300;
    stepRun(run,false);assert.ok(run.events.includes('pickupAhead'));assert.deepEqual(run.announcedPickups.map(p=>p.id),[pk.id]);
    run.status='respawning';run.respawnTicks=1;stepRun(run,false);run.plane.x=pk.announceX-.1;run.plane.y=300;stepRun(run,false);assert.ok(!run.events.includes('pickupAhead'));
    const fresh=createRun('nonstop',world);fresh.announced.add(pk.id);fresh.status='respawning';fresh.respawnTicks=1;stepRun(fresh,false);assert.equal(fresh.announced.size,0);
  }
});

test('reference flight receives each notice with sufficient time before passing',async()=>{
  const {referenceInput}=await import('../dist/game/bot.js');
  for(const [tier,minimum] of [[TIERS.casual,25],[TIERS.rush,18],[TIERS.overtime,12]]){
    const run=createRun('standard',buildWorld(undefined,tier)),announced=new Map(),passed=new Map();
    for(let n=0;n<60*900&&run.status!=='finished';n++){
      stepRun(run,referenceInput(run));
      for(const pk of run.announcedPickups)announced.set(pk.id,run.worldTicks);
      for(const pk of run.world.pickups)if(!passed.has(pk.id)&&run.plane.x>=pk.x)passed.set(pk.id,run.worldTicks);
    }
    assert.equal(run.status,'finished');assert.equal(run.crashes,0);
    for(const pk of run.world.pickups){assert.ok(announced.has(pk.id),`${tier.id} ${pk.id} notice`);assert.ok(passed.has(pk.id));assert.ok((passed.get(pk.id)-announced.get(pk.id))/60>=minimum,`${tier.id} ${pk.id} lead`);}
  }
});

test('collected pickups do not announce and Nonstop restart announces again',()=>{
  const world=buildWorld(),pk={...world.pickups[0],attach:null};world.pickups=[pk];world.buildings=[];world.hazards=[];world.airs=[];world.winds=[];
  const run=createRun('nonstop',world);run.collected.add(pk.id);run.plane.x=pk.announceX-.1;run.plane.y=300;stepRun(run,false);assert.ok(!run.events.includes('pickupAhead'));
  run.status='respawning';run.respawnTicks=1;stepRun(run,false);run.plane.x=pk.announceX-.1;run.plane.y=300;stepRun(run,false);assert.ok(run.events.includes('pickupAhead'));stepRun(run,false);assert.ok(!run.events.includes('pickupAhead'));
});

test('authored pickups have tier clearance, three placement kinds, and complete notice',async()=>{
  const {pickupClearance}=await import('../scripts/pickup-study.mjs');
  for(const [tier,minimum] of [[TIERS.casual,8],[TIERS.rush,6],[TIERS.overtime,4]]){
    const world=buildWorld(undefined,tier);
    assert.equal(world.pickups.length,5);
    assert.deepEqual(world.pickups.map(pk=>pk.district),[0,1,2,3,4]);
    assert.ok(new Set(world.pickups.map(pk=>pk.place)).size>=3,`${tier.id} kinds`);
    for(const pk of world.pickups){assert.ok(pk.announceX>=0);assert.ok(pickupClearance(world,pk)>=minimum,`${tier.id} ${pk.id} clearance`);}
  }
});

test('unsafe Rush flock pickup fails the strengthened pricing rule',async()=>{
  const {pricePickup}=await import('../scripts/pickup-study.mjs');
  const tier={...TIERS.rush,pickups:[{district:2,slot:0,place:'overFlock',dy:5,r:5,rewardTicks:300}]};
  const world=buildWorld(undefined,tier),row=pricePickup(world,world.pickups[0],100);
  assert.equal(row.qualifies,false);assert.ok(row.clearance<6);
});

test('clearance includes padded hazards, roof boxes and attached motion',async()=>{
  const {pickupClearance}=await import('../scripts/pickup-study.mjs');
  const pk={x:0,y:10,r:1};
  const world={buildings:[{x:4,y:6,w:2}],hazards:[]};
  assert.equal(pickupClearance(world,pk),Math.hypot(3,3));
  world.buildings=[];world.hazards=[{id:'bird',kind:'pigeon',x:0,y:0,w:2,h:2,moving:false}];
  assert.ok(Math.abs(pickupClearance(world,pk)-5.8)<1e-9);
  world.hazards[0]={...world.hazards[0],moving:true,phase:0,amp:{pigeonX:0,pigeonY:4,rate:1}};
  assert.ok(pickupClearance(world,pk)<1.81);
  const attached={...pk,attach:'bird',ox:1,oy:10};
  assert.ok(Math.abs(pickupClearance(world,attached)-5.8)<1e-9);
});

test('isolating a priced pickup preserves its paired study results',async()=>{
  const {pricePickup}=await import('../scripts/pickup-study.mjs');
  for(const tier of Object.values(TIERS)){
    const world=buildWorld(undefined,tier);
    for(const pk of world.pickups)assert.deepEqual(pricePickup({...world,pickups:[pk]},pk,1),pricePickup(world,pk,1));
  }
});
