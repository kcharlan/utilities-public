import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRun,stepRun} from '../dist/game/simulation.js';
import {eventNotes} from '../dist/game/audio.js';
import {FEEDBACK,createEffects,spawnEffects,stepEffects} from '../dist/game/effects.js';

const gameplay=['launch','pitch','release','lift','vent','stall','recovery','impact','respawn','checkpoint','district','pickup','warning','landing','best'];
test('event feedback covers sound and visible gameplay cues',()=>{
  for(const name of [...gameplay,'ui','pause','resume']){
    assert.ok(FEEDBACK[name],name);assert.ok(eventNotes[name],name);
    if(gameplay.includes(name)){
      assert.ok(FEEDBACK[name].visual,name);
      const fx=createEffects(),run=createRun();spawnEffects(fx,run,[name],{});
      assert.ok(fx.cues.length||fx.particles.length,name);
    }
  }
});
test('literal simulation and main event names are represented in the feedback table',()=>{
  const simulation=readFileSync(new URL('../dist/game/simulation.js',import.meta.url),'utf8');
  const main=readFileSync(new URL('../dist/game/main.js',import.meta.url),'utf8');
  const names=[...simulation.matchAll(/events(?:\.push\(|=\[)'([a-z]+)'/g),...main.matchAll(/(?:sound\.event|feedback)\('([a-z]+)'/g)].map(m=>m[1]);
  for(const name of names){assert.ok(FEEDBACK[name],name);assert.ok(eventNotes[name],name);}
});
test('reduced motion retains static cues without camera motion or moving particles',()=>{
  const fx=createEffects(),run=createRun();spawnEffects(fx,run,gameplay,{reduced:true});
  assert.equal(fx.particles.length,0);assert.equal(fx.bump,0);
  assert.equal(fx.cues.length,gameplay.length);
});
test('particles are bounded and expire',()=>{
  const fx=createEffects(),run=createRun();for(let i=0;i<100;i++)spawnEffects(fx,run,['impact'],{});
  assert.ok(fx.particles.length<=96);for(let i=0;i<120;i++)stepEffects(fx);
  assert.equal(fx.particles.length,0);assert.equal(fx.cues.length,0);
});
test('Nonstop respawn clears effects from the previous throw',()=>{
  const fx=createEffects(),run=createRun('nonstop');run.plane.y=0;stepRun(run,false);
  assert.ok(run.events.includes('impact'));spawnEffects(fx,run,run.events,{});
  while(!run.events.includes('respawn'))stepRun(run,false);
  spawnEffects(fx,run,run.events,{});
  assert.equal(fx.particles.length,0);assert.deepEqual(fx.cues.map(c=>c.name),['respawn']);
});

test('warnings retain the emitted encounter identity even when an earlier hazard remains',async()=>{
  const {hazardKey}=await import('../dist/game/world.js');
  const run=createRun(),hazard=run.world.hazards[1],fx=createEffects();
  run.warningHazards=[hazard];spawnEffects(fx,run,['warning'],{});
  assert.equal(fx.cues[0].hazardKey,hazardKey(hazard));
});
test('real roof, flock and washer collisions select distinct particle shapes',()=>{
  for(const [kind,expected] of [['roof','sheet'],['pigeon','feather'],['platform','drop']]){
    const run=createRun(),x=100,y=100;
    run.world={...run.world,airs:[],buildings:kind==='roof'?[{x,y:102,w:10}]:[],hazards:kind==='roof'?[]:[{id:'synthetic-impact',kind,x,y,w:10,h:10,phase:0,warningDistance:130}]};
    run.plane.x=x-1;run.plane.y=y+2;stepRun(run,false);assert.ok(run.events.includes('impact'),kind);
    const fx=createEffects();spawnEffects(fx,run,run.events,{});assert.ok(fx.particles.length);assert.ok(fx.particles.every(p=>p.kind===expected),kind);
  }
});
test('finished feedback expires on a bounded presentation clock and pauses cleanly',async()=>{
  const {advanceFinishedEffects}=await import('../dist/game/effects.js');
  assert.equal(typeof advanceFinishedEffects,'function');
  const run=createRun(),fx=createEffects(),clock={accumulator:0};run.status='finished';spawnEffects(fx,run,['landing','best'],{});
  advanceFinishedEffects(clock,10,true,run,fx);assert.equal(fx.cues[0].age,0);
  advanceFinishedEffects(clock,10,false,run,fx);assert.equal(fx.cues[0].age,6);
  for(let i=0;i<10;i++)advanceFinishedEffects(clock,.1,false,run,fx);
  assert.equal(fx.cues.length,0);assert.equal(run.worldTicks,0);
});
test('district card uses lower playfield space instead of notice area',async()=>{
  const {Renderer}=await import('../dist/game/render.js'),run=createRun(),fx=createEffects(),labels=[];
  spawnEffects(fx,run,['district'],{});
  const ctx=new Proxy({},{get:(o,k)=>k in o?o[k]:()=>{}}),renderer=Object.assign(Object.create(Renderer.prototype),{ctx,w:390,h:844,reduced:false,label:(text,x,y)=>labels.push({text,y})});
  renderer.drawEffects(fx,x=>x,y=>y);assert.ok(labels[0].y>300);
});
test('impact particle shapes render with different canvas operations',async()=>{
  const {Renderer}=await import('../dist/game/render.js'),drawn=[];
  const ctx=new Proxy({fillRect(){drawn.push('rect');},ellipse(){drawn.push('ellipse');},arc(){drawn.push('arc');}},{get:(o,k)=>k in o?o[k]:()=>{}});
  const renderer=Object.assign(Object.create(Renderer.prototype),{ctx,w:390,h:844,reduced:false,label:()=>{}});
  for(const kind of ['sheet','feather','drop'])renderer.drawEffects({particles:[{kind,x:0,y:0,age:0,life:30}],cues:[]},x=>x,y=>y);
  assert.deepEqual(drawn,['rect','ellipse','arc']);
});
test('renderer highlights the warned hazard instead of an earlier marker',async()=>{
  const {Renderer}=await import('../dist/game/render.js'),{hazardKey}=await import('../dist/game/world.js');
  const run=createRun(),warned=run.world.hazards[1],fx=createEffects(),highlighted=[];
  run.warningHazards=[warned];spawnEffects(fx,run,['warning'],{reduced:true});
  const ctx=new Proxy({drawImage(){}},{get:(o,k)=>k in o?o[k]:()=>{}});
  const renderer=Object.assign(Object.create(Renderer.prototype),{ctx,w:390,h:844,washer:{complete:false},reduced:true,cache:[{},{}],label:()=>{},sprite:()=>{},drawWarningCue:(hazard)=>highlighted.push(hazardKey(hazard))});
  renderer.draw(run,false,1,fx);assert.deepEqual(highlighted,[hazardKey(warned)]);
});
test('warning cue outlines the matching visible hazard and labels it offscreen',async()=>{
  const {Renderer}=await import('../dist/game/render.js'),run=createRun(),hazard=run.world.hazards[1],rects=[],labels=[];
  const ctx=new Proxy({strokeRect:(...args)=>rects.push(args)},{get:(o,k)=>k in o?o[k]:()=>{}});
  const renderer=Object.assign(Object.create(Renderer.prototype),{ctx,w:390,h:844,reduced:true,label:text=>labels.push(text)});
  const cue={reduced:true,age:8,life:45};
  renderer.drawWarningCue(hazard,cue,run,x=>x-hazard.x+100,y=>400-y);
  assert.equal(rects.length,1);assert.equal(labels.length,0);
  renderer.drawWarningCue(hazard,cue,run,x=>x+1000,y=>400-y);
  assert.equal(rects.length,1);assert.ok(labels[0].includes('washer'));
});
