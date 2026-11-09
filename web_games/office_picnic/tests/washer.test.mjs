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
test('a visible squeeze has one label and preserves both hazard sprites',async()=>{
  const {TIERS}=await import('../dist/game/tiers.js');const run=createRun('standard',world.buildWorld(undefined,TIERS.rush));
  const washer=run.world.hazards.find(h=>h.squeeze&&h.kind==='platform'),pair=run.world.hazards.filter(h=>h.squeeze&&h.district===washer.district&&h.slot===washer.slot);
  run.plane.x=washer.x-30;run.plane.y=150;run.world={...run.world,buildings:[],airs:[],winds:[],hazards:pair};
  const labels=[],sprites=[],image={complete:true,naturalWidth:1536},ctx=new Proxy({drawImage(){}},{get:(o,k)=>k in o?o[k]:()=>{}});
  const renderer=Object.assign(Object.create(Renderer.prototype),{w:390,h:844,ctx,washer:image,reduced:true,cache:[{},{}],label:(text)=>labels.push(text),sprite:(...args)=>sprites.push(args)});
  renderer.draw(run,false,1);
  assert.equal(labels.filter(text=>text.startsWith('Squeeze ·')).length,1);assert.ok(sprites.length>=3);
});
test('advance marker identifies a warned squeeze even with a standalone hazard ahead',async()=>{
  const {TIERS}=await import('../dist/game/tiers.js');const run=createRun('standard',world.buildWorld(undefined,TIERS.rush));
  const washer=run.world.hazards.find(h=>h.squeeze&&h.kind==='platform'),pair=run.world.hazards.filter(h=>h.squeeze&&h.district===washer.district&&h.slot===washer.slot);
  const other={...washer,id:'independent',squeeze:false,x:washer.x-100,warningDistance:360};
  run.plane.x=washer.x-330;run.plane.y=150;run.world={...run.world,buildings:[],airs:[],winds:[],hazards:[other,...pair]};run.warned.add(world.hazardKey(washer));
  const labels=[],ctx=new Proxy({drawImage(){}},{get:(o,k)=>k in o?o[k]:()=>{}});
  const renderer=Object.assign(Object.create(Renderer.prototype),{w:390,h:844,ctx,washer:{complete:false},reduced:true,cache:[{},{}],label:(text)=>labels.push(text),sprite:()=>{}});
  renderer.draw(run,false,1);assert.ok(labels.some(text=>text.startsWith('→ Squeeze ·')),labels.join(', '));
});
test('long labels wrap within a narrow canvas',()=>{
  const calls=[],ctx={measureText:text=>({width:text.length*7}),fillRect:(...args)=>calls.push(args),fillText(){}};
  const renderer=Object.assign(Object.create(Renderer.prototype),{w:200,ctx});
  renderer.label('Squeeze · fly between the washer and the flock',180,100,'white',12);
  assert.ok(calls[0][0]>=0);assert.ok(calls[0][0]+calls[0][2]<=200);
});
test('warnings marker follows a moving flock into range on phone',async()=>{
  const {TIERS}=await import('../dist/game/tiers.js');const run=createRun('standard',world.buildWorld(undefined,TIERS.rush));
  const hazard=run.world.hazards.find(h=>h.id==='h1-over');run.worldTicks=60*(Math.PI*1.5-hazard.phase)/(.65*hazard.amp.rate)-1;
  run.plane.x=hazard.x-364;run.plane.y=150;run.world={...run.world,buildings:[],airs:[],winds:[],hazards:[hazard]};
  stepRun(run,false);assert.equal(run.warningHazards[0].id,hazard.id);
  const labels=[],ctx=new Proxy({drawImage(){}},{get:(o,k)=>k in o?o[k]:()=>{}});
  const renderer=Object.assign(Object.create(Renderer.prototype),{w:390,h:844,ctx,washer:{complete:false},reduced:true,cache:[{},{}],label:(text)=>labels.push(text),sprite:()=>{}});
  renderer.draw(run,false,1);assert.ok(labels.some(text=>text.startsWith('→ Pigeons')),labels.join(', '));
});
