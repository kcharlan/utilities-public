import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {Renderer} from '../dist/game/render.js';
import {Sound,eventNotes} from '../dist/game/audio.js';

test('live notice remains during park approach and clears on automatic landing',async()=>{
  const savedResize=Renderer.prototype.resize;Renderer.prototype.resize=function(){this.w=844;this.h=390;};
  const elements=new Map();
  function element(id=''){
    if(!elements.has(id))elements.set(id,{hidden:true,style:{},children:[],getContext:()=>({}),focus(){},setAttribute(){},addEventListener(){},append(...v){this.children.push(...v);},replaceChildren(...v){this.children=v;}});
    return elements.get(id);
  }
  const original={document:globalThis.document,window:globalThis.window,location:globalThis.location,matchMedia:globalThis.matchMedia,Image:globalThis.Image,requestAnimationFrame:globalThis.requestAnimationFrame};
  try{
    globalThis.document={getElementById:id=>id==='trace-download'?null:element(id),createElement:()=>element(Symbol()),addEventListener(){}};
    globalThis.window={localStorage:null,addEventListener(){}};globalThis.location={search:''};globalThis.Image=class{};globalThis.requestAnimationFrame=()=>{};
    for(const reduced of [false,true]){
      globalThis.matchMedia=()=>({matches:reduced,addEventListener(){}});
      const base=new URL('../dist/game/',import.meta.url).href;
      const source=readFileSync(new URL('../dist/game/main.js',import.meta.url),'utf8').replaceAll("from './",`from '${base}`)+`\nexport {start,tick}; export const currentRun=()=>run;\n// ${reduced}`;
      const app=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
      app.start('standard');const run=app.currentRun();run.plane.x=run.world.finishStart-.1;run.plane.y=200;app.tick();
      assert.equal(run.status,'flying');assert.equal(element('notice').hidden,false);assert.equal(element('notice').textContent,'The park. Release now and glide down to the table.');
      run.plane.x=run.world.length-.1;app.tick();
      assert.equal(run.status,'landing');assert.equal(element('notice').hidden,true,`reduced=${reduced}`);
    }
  }finally{Renderer.prototype.resize=savedResize;for(const [key,value] of Object.entries(original))globalThis[key]=value;}
});

test('landing audio plays the frequencies advertised by eventNotes',()=>{
  const sound=new Sound(),played=[];sound.ctx={currentTime:1};sound.tone=(frequency)=>played.push(frequency);sound.event('landing');
  assert.deepEqual(played,eventNotes.landing);
});
test('best cue appears during the visible landing settle before the result card',async()=>{
  const savedResize=Renderer.prototype.resize;Renderer.prototype.resize=function(){this.w=844;this.h=390;};
  const elements=new Map(),timers=[];
  function element(id=''){if(!elements.has(id))elements.set(id,{hidden:true,style:{},children:[],getContext:()=>({}),focus(){},setAttribute(){},addEventListener(){},append(...v){this.children.push(...v);},replaceChildren(...v){this.children=v;}});return elements.get(id);}
  const keys=['document','window','location','matchMedia','Image','requestAnimationFrame','setTimeout'];const original=Object.fromEntries(keys.map(key=>[key,globalThis[key]]));
  try{
    globalThis.document={getElementById:id=>id==='trace-download'?null:element(id),createElement:()=>element(Symbol()),addEventListener(){}};
    globalThis.window={localStorage:null,addEventListener(){}};globalThis.location={search:''};globalThis.Image=class{};globalThis.requestAnimationFrame=()=>{};globalThis.setTimeout=(fn,delay)=>{timers.push({fn,delay});};
    for(const reduced of [false,true]){
      timers.length=0;globalThis.matchMedia=()=>({matches:reduced,addEventListener(){}});
      const base=new URL('../dist/game/',import.meta.url).href;
      const source=readFileSync(new URL('../dist/game/main.js',import.meta.url),'utf8').replaceAll("from './",`from '${base}`)+`\nexport {start,tick}; export const currentRun=()=>run; export const currentEffects=()=>effects;\n// best ${reduced}`;
      const app=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
      app.start('standard');const run=app.currentRun();run.plane.x=run.world.length-.1;run.plane.y=200;app.tick();
      while(run.status==='landing')app.tick();
      assert.equal(run.status,'finished');assert.equal(element('result-screen').hidden,true);
      const cue=app.currentEffects().cues.find(c=>c.name==='best');assert.ok(cue);assert.equal(cue.reduced,reduced);
      assert.equal(timers.length,1);timers[0].fn();assert.equal(element('result-screen').hidden,false);
      assert.match(element('result-best').textContent,/Your best flight/);
    }
  }finally{Renderer.prototype.resize=savedResize;for(const [key,value] of Object.entries(original))globalThis[key]=value;}
});

test('pickup notice preserves the still-active opening hazard instruction',async()=>{
  const savedResize=Renderer.prototype.resize;Renderer.prototype.resize=function(){this.w=390;this.h=844;};
  const elements=new Map();function element(id=''){if(!elements.has(id))elements.set(id,{hidden:true,style:{},children:[],getContext:()=>({}),focus(){},setAttribute(){},addEventListener(){},append(...v){this.children.push(...v);},replaceChildren(...v){this.children=v;}});return elements.get(id);}
  const keys=['document','window','location','matchMedia','Image','requestAnimationFrame'],original=Object.fromEntries(keys.map(key=>[key,globalThis[key]]));
  try{
    globalThis.document={getElementById:id=>id==='trace-download'?null:element(id),createElement:()=>element(Symbol()),addEventListener(){}};globalThis.window={localStorage:null,addEventListener(){}};globalThis.location={search:''};globalThis.matchMedia=()=>({matches:false,addEventListener(){}});globalThis.Image=class{};globalThis.requestAnimationFrame=()=>{};
    const base=new URL('../dist/game/',import.meta.url).href,source=readFileSync(new URL('../dist/game/main.js',import.meta.url),'utf8').replaceAll("from './",`from '${base}`)+'\nexport {start,tick}; export const currentRun=()=>run;\n// pickup notice regression';
    const app=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));app.start('standard');const run=app.currentRun();app.tick();assert.match(element('notice').textContent,/Pigeons · climb over/);
    // Stage a pickup announcement while the actual opening warning is still active.
    run.world.pickups[0].announceX=run.plane.x+1;
    while(!run.events.includes('pickupAhead')&&run.worldTicks<100)app.tick();assert.ok(run.events.includes('pickupAhead'));assert.match(element('notice').textContent,/Pigeons · climb over/);assert.match(element('notice').textContent,/Time pickup ahead/);
  }finally{Renderer.prototype.resize=savedResize;for(const [key,value] of Object.entries(original))globalThis[key]=value;}
});

test('simultaneous Rush warning and pickup announcement do not duplicate warning',async()=>{
  const savedResize=Renderer.prototype.resize;Renderer.prototype.resize=function(){this.w=390;this.h=844;};
  const elements=new Map();function element(id=''){if(!elements.has(id))elements.set(id,{hidden:true,style:{},children:[],getContext:()=>({}),focus(){},setAttribute(){},addEventListener(){},append(...v){this.children.push(...v);},replaceChildren(...v){this.children=v;}});return elements.get(id);}
  const keys=['document','window','location','matchMedia','Image','requestAnimationFrame'],original=Object.fromEntries(keys.map(key=>[key,globalThis[key]]));
  try{
    globalThis.document={getElementById:id=>id==='trace-download'?null:element(id),createElement:()=>element(Symbol()),addEventListener(){}};globalThis.window={localStorage:null,addEventListener(){}};globalThis.location={search:''};globalThis.matchMedia=()=>({matches:false,addEventListener(){}});globalThis.Image=class{};globalThis.requestAnimationFrame=()=>{};
    const base=new URL('../dist/game/',import.meta.url).href,source=readFileSync(new URL('../dist/game/main.js',import.meta.url),'utf8').replaceAll("from './",`from '${base}`)+'\nexport {start,tick}; export const currentRun=()=>run; export const selectRush=()=>{records.tier="rush";};\n// rush simultaneous notice';
    const app=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));app.selectRush();app.start('standard');const run=app.currentRun();run.world.pickups[0].announceX=0;app.tick();
    assert.ok(run.events.includes('warning')&&run.events.includes('pickupAhead'));assert.equal(element('notice').textContent,'Pigeons · climb over');
  }finally{Renderer.prototype.resize=savedResize;for(const [key,value] of Object.entries(original))globalThis[key]=value;}
});
