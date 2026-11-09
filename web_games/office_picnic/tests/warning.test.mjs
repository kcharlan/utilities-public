import test from 'node:test';import assert from 'node:assert/strict';
import {TIERS} from '../dist/game/tiers.js';import {buildWorld,hazardBox,hazardKey} from '../dist/game/world.js';
import {createRun,stepRun} from '../dist/game/simulation.js';import {noticeMessages} from '../dist/game/guidance.js';
import {Sound,dispatchRunEvents} from '../dist/game/audio.js';import {Renderer} from '../dist/game/render.js';
test('warning audio throttles by encounter identity while ordinary event names work',()=>{
  const sound=new Sound(),tones=[];sound.ctx={currentTime:1};sound.tone=(...args)=>tones.push(args);
  sound.event('warning','pair-a');sound.event('warning','pair-a');sound.event('warning','pair-b');
  assert.equal(tones.length,4);sound.event('pickup');assert.ok(tones.length>4);
});
test('real squeeze cue passes its pair identity through audio, notice and marker until respawn',()=>{
  const world=buildWorld(undefined,TIERS.rush),r=createRun('standard',world);
  const pair=world.hazards.filter(h=>h.squeeze&&h.district===4),flock=pair.find(h=>h.kind==='pigeon'),washer=pair.find(h=>h.kind==='platform');
  const key=hazardKey(flock),standalone=world.hazards.find(h=>h.id==='h4-under');
  r.district=4;r.plane.x=flock.x-flock.warningDistance-1;r.plane.y=300;r.checkpoint={...r.plane,x:r.plane.x,district:r.district};
  const sound=new Sound(),keys=[],labels=[];sound.event=(name,identity)=>keys.push([name,identity]);
  let cue=null;
  for(let i=0;i<20&&!cue;i++){stepRun(r,false);if(r.warningHazards.some(h=>hazardKey(h)===key))cue=r.warningHazards.find(h=>hazardKey(h)===key);}
  assert.ok(cue);assert.ok(standalone.x>r.plane.x);dispatchRunEvents(sound,r);
  assert.ok(keys.some(([name,identity])=>name==='warning'&&identity===key));assert.ok(noticeMessages(r).some(text=>text.startsWith('Squeeze')));
  const ctx=new Proxy({drawImage(){}},{get:(o,k)=>k in o?o[k]:()=>{}}),renderer=Object.assign(Object.create(Renderer.prototype),{w:390,h:844,ctx,washer:{complete:false},reduced:true,cache:[{},{}],label:text=>labels.push(text),sprite:()=>{}});
  renderer.draw(r,false,1);assert.ok(labels.some(text=>text.startsWith('→ Squeeze')));
  let crossedSecond=false;
  for(let i=0;i<1200&&!crossedSecond;i++){
    r.plane.y=300;stepRun(r,false);assert.ok(!r.warningHazards.some(h=>hazardKey(h)===key));
    crossedSecond=hazardBox(washer,r.worldTicks/60).x-r.plane.x<washer.warningDistance;
  }
  assert.ok(crossedSecond,'second member trigger was reached');
  r.plane.y=0;stepRun(r,false);while(r.status==='respawning')stepRun(r,false);
  assert.ok(!r.warned.has(key));r.plane.x=flock.x-flock.warningDistance+1;r.plane.y=300;stepRun(r,false);
  assert.ok(r.warningHazards.some(h=>hazardKey(h)===key));
});
