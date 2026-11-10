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
