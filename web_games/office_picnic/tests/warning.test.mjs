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
  assert.ok(noticeMessages(r).every(text=>!text.includes('Squeeze')));
  assert.ok(!r.warned.has(key));r.plane.x=flock.x-flock.warningDistance+1;r.plane.y=300;stepRun(r,false);
  assert.ok(r.warningHazards.some(h=>hazardKey(h)===key));
  assert.ok(noticeMessages(r).every(text=>!text.includes('Squeeze')));
});
test('first squeeze is introduced once on its warning during a clean flight',async()=>{
  const {referenceInput}=await import('../dist/game/bot.js');
  for(const tier of [TIERS.rush,TIERS.overtime,{...TIERS.overtime,prompts:'warnings'}]){
    const run=createRun('standard',buildWorld(undefined,tier)),notices=[];
    let laterWarning=false,laterNotice=false;
    let firstWarningTick=null,entryTick=null;
    for(let n=0;n<54000&&run.status!=='finished';n++){
      stepRun(run,referenceInput(run));
      if(run.events.includes('district')&&run.district===(tier.id==='rush'?4:2))entryTick=run.worldTicks;
      if(firstWarningTick===null&&run.warningHazards.some(h=>h.firstSqueeze))firstWarningTick=run.worldTicks;
      if(run.warningHazards.some(h=>h.squeeze&&!h.firstSqueeze))laterWarning=true;
      for(const message of noticeMessages(run))if(message.startsWith('Squeeze')){
        if(laterWarning)laterNotice=true;else notices.push({tick:run.worldTicks,message});
      }
    }
    assert.equal(run.status,'finished');assert.equal(run.crashes,0);
    assert.notEqual(entryTick,null);assert.notEqual(firstWarningTick,null);
    assert.deepEqual(notices,[{tick:firstWarningTick,message:'Squeeze · fly between the washer and the flock'}],`${tier.id} ${tier.prompts}`);
    if(tier.id==='overtime'&&tier.prompts==='warnings')assert.ok(laterNotice,'later squeeze still warns');
  }
});
test('real squeeze warning draws one outline around the shared passage',async()=>{
  const {createEffects,spawnEffects}=await import('../dist/game/effects.js');
  const world=buildWorld(undefined,TIERS.rush),run=createRun('standard',world);
  const pair=world.hazards.filter(h=>h.squeeze&&h.district===4),flock=pair.find(h=>h.kind==='pigeon'),washer=pair.find(h=>h.kind==='platform'),key=hazardKey(flock);
  run.district=4;run.plane.x=flock.x-flock.warningDistance-1;run.plane.y=300;
  for(let i=0;i<20&&!run.warningHazards?.some(h=>hazardKey(h)===key);i++)stepRun(run,false);
  assert.ok(run.warningHazards.some(h=>hazardKey(h)===key&&h.kind==='pigeon'));
  const fx=createEffects();spawnEffects(fx,run,run.events,{reduced:true});assert.equal(fx.cues.filter(c=>c.hazardKey===key).length,1);
  const rects=[],ctx=new Proxy({strokeRect:(...args)=>rects.push(args)},{get:(o,k)=>k in o?o[k]:()=>{}}),renderer=Object.assign(Object.create(Renderer.prototype),{w:1000,h:1000,ctx,reduced:true,label:()=>{}});
  const a=hazardBox(washer,run.worldTicks/60),b=hazardBox(flock,run.worldTicks/60),X=x=>x-a.x+100,Y=y=>500-y;
  renderer.drawWarningCue(washer,fx.cues.find(c=>c.hazardKey===key),run,X,Y);
  assert.deepEqual(rects,[[X(Math.max(a.x,b.x)),Y(a.y),Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x),a.y-(b.y+b.h)]]);
});
