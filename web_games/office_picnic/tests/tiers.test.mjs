import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {buildWorld} from '../dist/game/world.js';
import {createRun,stepRun} from '../dist/game/simulation.js';
import {chooseInput} from '../dist/game/bot.js';

const keys={hazards:['id','district','kind','pass','x','y','w','h','suspensionTop','phase','warningDistance','moving'],buildings:['x','y','w','h','type','district','perch'],airs:['x','w','y','top','type','phase','district','targetExit','gapId'],gaps:['id','district','x','end','length','entryHeight','entrySpeed','entryPitch','clearance','drop','measuredRange','utilization'],districts:['name','feature','tip','color','index','start','checkpoint','end']};
function projection(w){return Object.fromEntries([...Object.entries(keys).map(([k,fields])=>[k,w[k].map(o=>Object.fromEntries(fields.filter(f=>f in o).map(f=>[f,o[f]])))]),['length',w.length]]);}
test('Casual retains shipped geometry and clean route',()=>{
 const w=buildWorld();
 assert.equal(createHash('sha256').update(JSON.stringify(projection(w))).digest('hex'),'51e86ce090aa730f09a3fa3a8ae087a4dbf30531e1db88091109129d47cd43ec');
 assert.deepEqual(w.hazards.map(h=>h.id),Array.from({length:5},(_,i)=>[`h${i}-over`,`h${i}-under`]).flat());
 assert.equal(w.length,6245);
 for(const mode of ['standard','nonstop']){const r=createRun(mode,w);while(r.status!=='finished'&&r.ticks<30000)stepRun(r,chooseInput(r));assert.equal(r.finishTicks,18321);assert.equal(r.crashes,0);}
});

test('tier engine constructs moving squeeze and rejects unsafe last-slot placement',async()=>{
 const {TIERS}=await import('../dist/game/tiers.js');
 const {hazardBox}=await import('../dist/game/world.js');
 const config={...TIERS.casual,encounters:[{slot:1,kind:'squeeze',at:.5,center:130,window:40}],motion:{squeezeSync:8,rate:1}};
 const w=buildWorld(undefined,config), pair=w.hazards.filter(h=>h.district===0);
 assert.equal(pair.length,2);const washer=pair.find(h=>h.kind==='platform'),flock=pair.find(h=>h.kind==='pigeon');
 for(let t=0;t<100;t+=.1)assert.ok(Math.abs(hazardBox(washer,t).y-(hazardBox(flock,t).y+flock.h)-40)<1e-9);
 const fixed=buildWorld(undefined,{...config,motion:{squeezeStatic:true}}).hazards.filter(h=>h.district===0);for(const h of fixed)assert.deepEqual(hazardBox(h,0),hazardBox(h,10));
 for(const kind of ['platform','squeeze'])assert.throws(()=>buildWorld(undefined,{...config,encounters:[{slot:4,kind,at:.5,window:40}]}));
});
test('tier hash reflects gameplay, ignores presentation',async()=>{
 const {TIERS,tierHash}=await import('../dist/game/tiers.js');const t=TIERS.casual;
 assert.equal(tierHash(t),tierHash({...t,name:'Other',blurb:'Different',prompts:'quiet'}));
 assert.notEqual(tierHash(t),tierHash({...t,ratios:[...t.ratios.slice(0,4),.8]}));
});
test('rules control crashes and nonstop retains the history',async()=>{
 const {TIERS}=await import('../dist/game/tiers.js');const w=buildWorld(undefined,{...TIERS.casual,rules:{crashPenaltyTicks:25,respawnTicks:2}});
 for(const mode of ['standard','nonstop']){const r=createRun(mode,w);r.plane.y=0;stepRun(r,false);assert.equal(r.respawnTicks,2);assert.match(r.crashLog[0].where,/^street /);assert.equal(r.ticks,mode==='standard'?26:1);stepRun(r,false);stepRun(r,false);assert.equal(r.crashLog.length,1);assert.equal(r.attempts,mode==='nonstop'?2:1);}
});
test('wind ramps at edges and lift scaling reduces lift',async()=>{
 const {TIERS}=await import('../dist/game/tiers.js');const {airAt,airEffect}=await import('../dist/game/world.js');
 const w=buildWorld(undefined,{...TIERS.casual,winds:[{district:0,fromSlot:0,toSlot:0,startAtGap:true,y0:0,y1:400,wind:-4}]});const z=w.winds[0];
 assert.equal(airAt(w,{x:z.x0-1,y:300},0).wind,0);assert.equal(airAt(w,{x:z.x0+6,y:300},0).wind,-2);assert.equal(airAt(w,{x:z.x0+20,y:300},0).wind,-4);
 const {createPlane,advancePlane}=await import('../dist/game/physics.js');const still=createPlane({x:z.x0+20,y:300,speed:26}),headwind=createPlane({x:z.x0+20,y:300,speed:26});advancePlane(still,false);advancePlane(headwind,false,airAt(w,headwind,0));assert.ok(headwind.x<still.x);
 const a=w.airs[0];assert.equal(airEffect({...a,liftScale:.5},150,0).lift,airEffect(a,150,0).lift/2);
});
test('reference pilot finishes both modes and clears district perturbations',async()=>{
 const {referenceInput}=await import('../dist/game/bot.js');const {createPlane}=await import('../dist/game/physics.js');const w=buildWorld();
 for(const mode of ['standard','nonstop']){const r=createRun(mode,w);for(let n=0;n<54000&&r.status!=='finished';n++)stepRun(r,referenceInput(r));assert.equal(r.status,'finished');assert.equal(r.crashes,0);}
 for(const d of w.districts)for(const speed of [22,26,30])for(const dy of [-6,0,6])for(const delay of [0,3,6]){const r=createRun('standard',w);r.district=d.index;r.plane=createPlane({...d.checkpoint,speed,y:d.checkpoint.y+dy});let held=false;for(let n=0;n<9000&&r.plane.x<d.end&&!r.crashes;n++){if(n%(delay+1)===0)held=referenceInput(r);stepRun(r,held);}assert.equal(r.crashes,0);assert.ok(r.plane.x>=d.end);}
});

test('shared shortcut runner rejects each passive policy in every district',async()=>{const {shortcutOutcomes}=await import('../scripts/flight-study.mjs');const results=shortcutOutcomes(buildWorld());assert.ok(Object.keys(results).length>=9);assert.ok(Object.values(results).every(n=>n===0));});
