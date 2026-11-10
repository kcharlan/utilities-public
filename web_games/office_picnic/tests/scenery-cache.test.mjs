import test from 'node:test';import assert from 'node:assert/strict';
import {Renderer} from '../dist/game/render.js';import {createRun,stepRun} from '../dist/game/simulation.js';import {referenceInput} from '../dist/game/bot.js';
import {buildWorld,hazardBox,hazardKey} from '../dist/game/world.js';import {TIERS} from '../dist/game/tiers.js';import {cameraFor} from '../dist/game/session.js';

test('resize builds deterministic scenery and grain once; draw reuses them',()=>{
  const old={document:globalThis.document,Image:globalThis.Image,matchMedia:globalThis.matchMedia,devicePixelRatio:globalThis.devicePixelRatio};
  const builds=[];
  function context(log){return new Proxy({createLinearGradient:(...args)=>{log.push(['gradient',...args]);return {addColorStop:(...stop)=>log.push(['stop',...stop])};},measureText:text=>({width:text.length*6})},{get:(o,k)=>k in o?o[k]:(...args)=>log.push([k,...args])});}
  globalThis.document={createElement:()=>{const log=[];builds.push(log);return {getContext:()=>context(log)};}};
  globalThis.Image=class{};globalThis.matchMedia=()=>({matches:false});globalThis.devicePixelRatio=3;
  try{
    const main=[];const canvas={clientWidth:390,clientHeight:844,getContext:()=>context(main)};
    const renderer=new Renderer(canvas);assert.equal(canvas.width,780);
    const first=JSON.stringify(builds);assert.ok(renderer.grain);assert.ok(renderer.scenery);
    const count=builds.length;main.length=0;renderer.draw(createRun(),false);assert.equal(builds.length,count);
    assert.ok(main.some(call=>call[0]==='drawImage'&&call[1]===renderer.grain));
    assert.ok(main.some(call=>call[0]==='drawImage'&&call[1]===renderer.scenery.sky));
    assert.ok(main.some(call=>call[0]==='drawImage'&&call[1]===renderer.scenery.body));
    assert.ok(renderer.cache.every(tile=>main.some(call=>call[0]==='drawImage'&&call[1]===tile)));
    assert.ok(!main.some(call=>call[0]==='gradient'));
    const landing=createRun();landing.status='finished';landing.plane.x=landing.world.length;landing.plane.y=25;
    main.length=0;renderer.draw(landing,false);assert.equal(builds.length,count);
    for(const tile of [renderer.grain,renderer.scenery.ground,renderer.scenery.tree])assert.ok(main.some(call=>call[0]==='drawImage'&&call[1]===tile));
    assert.ok(!main.some(call=>call[0]==='gradient'));
    builds.length=0;renderer.resize();assert.equal(JSON.stringify(builds),first);
  }finally{Object.assign(globalThis,old);}
});

test('real landscape approach guidance does not intersect the plane',()=>{
  const run=createRun();
  for(let tick=1;tick<=1728;tick++){
    stepRun(run,referenceInput(run));if(tick!==295&&tick!==1728)continue;
    const labels=[],sprites=[];let rect;
    const ctx=new Proxy({measureText:text=>({width:text.length*6}),fillRect:(...args)=>{rect=args},fillText:text=>labels.push({text,rect}),drawImage(){}},{get:(o,k)=>k in o?o[k]:()=>{}});
    const renderer=Object.assign(Object.create(Renderer.prototype),{w:844,h:390,ctx,reduced:true,cache:[{},{}],plane:{},washer:{complete:false},sprite:(img,frame,x,y,w,h,rotation)=>{if(img===renderer.plane)sprites.push({x,y,w,h,rotation});}});
    renderer.draw(run,false,1);const label=labels.find(l=>l.text.startsWith(tick===295?'Hold early':'Release to dive'));
    assert.ok(label,`tick ${tick} instruction`);assert.equal(sprites.length,1);
    const p=sprites[0],rx=(Math.abs(Math.cos(p.rotation))*p.w+Math.abs(Math.sin(p.rotation))*p.h)/2,ry=(Math.abs(Math.sin(p.rotation))*p.w+Math.abs(Math.cos(p.rotation))*p.h)/2;
    const [x,y,w,h]=label.rect;assert.ok(x+w<=p.x-rx||x>=p.x+rx||y+h<=p.y-ry||y>=p.y+ry,`tick ${tick} label overlaps plane`);
  }
});

test('landscape squeeze warning leaves both hazards and their passage visible',()=>{
  const world=buildWorld(undefined,TIERS.rush),run=createRun('standard',world),flock=world.hazards.find(h=>h.squeeze&&h.kind==='pigeon'&&h.district===4),key=hazardKey(flock);
  run.district=4;run.plane.x=flock.x-flock.warningDistance-1;run.plane.y=300;
  for(let i=0;i<20&&!run.warningHazards?.some(h=>hazardKey(h)===key);i++)stepRun(run,false);
  assert.ok(run.warningHazards.some(h=>hazardKey(h)===key));run.plane.x=flock.x-40;run.plane.y=150;run.previous=null;
  const labels=[];let rect;const ctx=new Proxy({measureText:text=>({width:text.length*6}),fillRect:(...args)=>{rect=args},fillText:text=>labels.push({text,rect}),drawImage(){}},{get:(o,k)=>k in o?o[k]:()=>{}});
  const renderer=Object.assign(Object.create(Renderer.prototype),{w:844,h:390,ctx,reduced:true,cache:[{},{}],plane:{},washer:{complete:false},sprite:()=>{}});renderer.draw(run,false,1);
  const label=labels.find(l=>l.text.startsWith('Squeeze ·'));assert.ok(label);
  const cam=cameraFor(844,390,run.plane),X=x=>(x-cam.left)*cam.scale,Y=y=>390-(y-cam.bottom)*cam.verticalScale;
  const pair=world.hazards.filter(h=>h.squeeze&&hazardKey(h)===key).map(h=>hazardBox(h,run.worldTicks/60));
  const left=Math.min(...pair.map(b=>X(b.x)))-17,right=Math.max(...pair.map(b=>X(b.x+b.w)))+17,top=Math.min(...pair.map(b=>Y(b.y+b.h)))-17,bottom=Math.max(...pair.map(b=>Y(b.y)))+17;
  const [x,y,w,h]=label.rect;assert.ok(x+w<=left||x>=right||y+h<=top||y>=bottom,'label covers squeeze');
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
