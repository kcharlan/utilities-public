import test from 'node:test';import assert from 'node:assert/strict';
import {Renderer} from '../dist/game/render.js';import {createRun} from '../dist/game/simulation.js';

test('resize builds deterministic scenery and grain once; draw reuses them',()=>{
  const old={document:globalThis.document,Image:globalThis.Image,matchMedia:globalThis.matchMedia,devicePixelRatio:globalThis.devicePixelRatio};
  const builds=[];
  function context(log){return new Proxy({createLinearGradient:(...args)=>{log.push(['gradient',...args]);return {addColorStop:(...stop)=>log.push(['stop',...stop])};},measureText:text=>({width:text.length*6})},{get:(o,k)=>k in o?o[k]:(...args)=>log.push([k,...args])});}
  globalThis.document={createElement:()=>{const log=[];builds.push(log);return {getContext:()=>context(log)};}};
  globalThis.Image=class{};globalThis.matchMedia=()=>({matches:false});globalThis.devicePixelRatio=3;
  try{
    const canvas={clientWidth:390,clientHeight:844,getContext:()=>context([])};
    const renderer=new Renderer(canvas);assert.equal(canvas.width,780);
    const first=JSON.stringify(builds);assert.ok(renderer.grain);assert.ok(renderer.scenery);
    const count=builds.length;renderer.draw(createRun(),false);assert.equal(builds.length,count);
    builds.length=0;renderer.resize();assert.equal(JSON.stringify(builds),first);
  }finally{Object.assign(globalThis,old);}
});

test('adjacent labels retain their text without overlapping on a portrait canvas',()=>{
  const boxes=[],texts=[],ctx={measureText:text=>({width:text.length*6}),fillRect:(...box)=>boxes.push(box),fillText:text=>texts.push(text)};
  const renderer=Object.assign(Object.create(Renderer.prototype),{w:390,h:844,ctx,labelRects:[]});
  for(const text of ['AC · steady upward push','Vent · pulsing steam','Wind column · upward push'])renderer.label(text,20,180,'white',11);
  assert.equal(texts.length,3);
  for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++){
    const [x,y,w,h]=boxes[i],[a,b,c,d]=boxes[j];assert.ok(x+w<=a||a+c<=x||y+h<=b||b+d<=y);
  }
});
