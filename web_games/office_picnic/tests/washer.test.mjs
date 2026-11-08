import test from 'node:test';import assert from 'node:assert/strict';
import * as world from '../dist/game/world.js';import {createRun,stepRun} from '../dist/game/simulation.js';
import {Renderer} from '../dist/game/render.js';import {cameraFor} from '../dist/game/session.js';
test('washer collision consists of a compact deck and actual suspension cables, with open space between',()=>{
  assert.equal(typeof world.hazardParts,'function');
  const h={kind:'platform',x:100,y:130,w:45,h:30,suspensionTop:280,moving:false};
  const parts=world.hazardParts(h,0);assert.equal(parts.length,3);
  function runAt(x,y){const r=createRun();r.world={...r.world,buildings:[],airs:[],hazards:[h]};r.plane.x=x;r.plane.y=y;stepRun(r,false);return r;}
  assert.equal(runAt(110,140).status,'respawning','solid deck');
  assert.equal(runAt(101,200).status,'respawning','left cable');
  assert.equal(runAt(122,200).status,'flying','empty space is not a mesh wall');
});
test('washer art uses the collision body dimensions on desktop, portrait and landscape',()=>{
  for(const [w,h] of [[1280,800],[390,844],[844,390]]){
    const run=createRun(),hazard=run.world.hazards.find(h=>h.kind==='platform');
    run.plane.x=hazard.x-50;run.world={...run.world,buildings:[],airs:[],hazards:[hazard]};
    const washer={complete:true,naturalWidth:1536,naturalHeight:1024},calls=[];
    const ctx=new Proxy({drawImage:(...args)=>{if(args[0]===washer)calls.push(args)}},{get:(o,k)=>k in o?o[k]:()=>{}});
    const renderer=Object.assign(Object.create(Renderer.prototype),{w,h,ctx,washer,reduced:true,cache:[{},{}],label:()=>{},sprite:()=>{}});
    renderer.draw(run,false,1);assert.equal(calls.length,1);
    const cam=cameraFor(w,h,run.plane),b=world.hazardBox(hazard,0),[,x,y,width,height]=calls[0];
    assert.equal(width,b.w*cam.scale);assert.equal(height,b.h*cam.verticalScale);
    assert.ok(Math.abs(x-(b.x-cam.left)*cam.scale)<1e-9);
    assert.ok(Math.abs(y-(h-(b.y+b.h-cam.bottom)*cam.verticalScale))<1e-9);
  }
});
