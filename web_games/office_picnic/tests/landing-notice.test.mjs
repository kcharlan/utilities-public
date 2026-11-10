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
      assert.equal(run.status,'flying');assert.equal(element('notice').hidden,false);assert.match(element('notice').textContent,/The park/);
      run.plane.x=run.world.length-.1;app.tick();
      assert.equal(run.status,'landing');assert.equal(element('notice').hidden,true,`reduced=${reduced}`);
    }
  }finally{Renderer.prototype.resize=savedResize;for(const [key,value] of Object.entries(original))globalThis[key]=value;}
});

test('landing audio plays the frequencies advertised by eventNotes',()=>{
  const sound=new Sound(),played=[];sound.ctx={currentTime:1};sound.tone=(frequency)=>played.push(frequency);sound.event('landing');
  assert.deepEqual(played,eventNotes.landing);
});
