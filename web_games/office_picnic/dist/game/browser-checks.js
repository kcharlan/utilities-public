// Browser-only verification harness, separate from the shipped play flow.
import {TIERS} from './tiers.js';import {buildWorld} from './world.js';
import {createRun,stepRun} from './simulation.js';import {chooseInput,referenceInput} from './bot.js';import {Renderer} from './render.js';import {Sound} from './audio.js';import {saveResult,loadRecords} from './records.js';import {formatTime,formatDistance} from './session.js';
const output=document.getElementById('output'),canvas=document.getElementById('preview'),renderer=new Renderer(canvas),scenes=[],select=document.getElementById('scene');
for(const [value,text] of [['6','Vent · steam burst'],['7','Vent · lull'],['8','Window-washer approach'],['9','Rush · moving washer'],['10','Rush · squeeze'],['11','Rush · headwind'],['12','Pickup · moving washer']]){const option=document.createElement('option');option.value=value;option.textContent=text;select.append(option);}
const check=(condition,message)=>{if(!condition)throw Error(message);};
function capture(r){return {...r,plane:{...r.plane},previous:null};}
function draw(){if(scenes[Number(select.value)])renderer.draw(scenes[Number(select.value)],false,1);}
function runRoute(){
  const r=createRun(),washer=r.world.hazards.find(h=>h.kind==='platform');for(let n=0;n<60*480&&r.status!=='finished';n++){
    stepRun(r,chooseInput(r));const d=r.world.districts[r.district];
    if(!scenes[r.district]&&r.plane.x>d.start+80)scenes[r.district]=capture(r);
    if(!scenes[8]&&r.plane.x>washer.x-120)scenes[8]=capture(r);
  }
  check(r.status==='finished'&&r.crashes===0,'Standard route failed');scenes[5]=capture(r);
  const vent=r.world.airs.find(a=>a.type===1);
  for(const [index,phase] of [[6,Math.PI*.5],[7,Math.PI*1.5]]){
    const preview=capture(r);preview.status='flying';preview.plane={...r.plane,x:vent.x+vent.w/2,y:155,pitch:-.2,speed:26};preview.worldTicks=(phase-vent.phase)/1.4*60;scenes[index]=preview;
  }
  const nonstop=createRun('nonstop');for(let n=0;n<60*480&&nonstop.status!=='finished';n++)stepRun(nonstop,chooseInput(nonstop));check(nonstop.status==='finished'&&nonstop.crashes===0,'Nonstop route failed');
  const world=buildWorld(undefined,TIERS.rush);
  for(const mode of ['standard','nonstop']){
    const rush=createRun(mode,world);
    for(let n=0;n<60*900&&rush.status!=='finished';n++)stepRun(rush,referenceInput(rush));
    check(rush.status==='finished'&&!rush.crashes,`Rush ${mode} failed`);
  }
  for(const [index,feature] of [[9,world.hazards.find(h=>h.kind==='platform'&&h.moving)],[10,world.hazards.find(h=>h.squeeze)],[11,world.winds[0]]]){
    const preview=createRun('standard',world);preview.plane.x=(feature.x??feature.x0)-90;preview.plane.y=150;preview.worldTicks=240;scenes[index]=capture(preview);
  }
  const pickupWorld=buildWorld(undefined,{...TIERS.rush,pickups:[{district:2,slot:2,place:'underWasher',dy:6,r:4,rewardTicks:540}]});
  const pickupScene=createRun('standard',pickupWorld),pk=pickupWorld.pickups[0];pickupScene.plane.x=pk.x-90;pickupScene.plane.y=pk.y;pickupScene.worldTicks=240;scenes[12]=capture(pickupScene);
  return r;
}
select.onchange=draw;document.getElementById('reduced').onchange=e=>{renderer.reduced=e.target.checked;draw();};window.addEventListener('resize',()=>{renderer.resize();draw();});
document.getElementById('landing').onclick=()=>{
  const r=createRun();for(let n=0;n<60*480&&r.status==='flying';n++)stepRun(r,chooseInput(r));check(r.status==='landing','Landing approach did not clear');
  output.textContent='Playing the actual two-second landing state…';
  const animate=()=>{stepRun(r,false);renderer.draw(r,false,1);if(r.status!=='finished')requestAnimationFrame(animate);else output.textContent='PASS: continuous landing completed at the potato salad.';};requestAnimationFrame(animate);
};
document.getElementById('run').onclick=async()=>{
  try{
    output.textContent='Running…';const sound=new Sound(true);await sound.unlock();
    const r=runRoute();draw();
    check(renderer.plane.complete&&renderer.plane.naturalWidth>0,'Plane sprite did not decode');check(renderer.pigeon.complete&&renderer.pigeon.naturalWidth>0,'Pigeon sprite did not decode');
    check(renderer.washer.complete&&renderer.washer.naturalWidth>0,'Washer illustration did not decode');
    const current=saveResult(null,'rush','standard',300);check(saveResult(null,'rush','standard',340,current).best.rush.standard===300,'Session records regressed');
    const prefix='office-picnic-browser-check-',store={getItem:k=>localStorage.getItem(prefix+k),setItem:(k,v)=>localStorage.setItem(prefix+k,v)};
    store.setItem('office-picnic-v4',JSON.stringify({best:{standard:320},muted:true}));
    check(loadRecords(store).best.casual.standard===320&&loadRecords(store).muted,'Migration failed');
    saveResult(store,'rush','nonstop',310);check(loadRecords(store).best.rush.nonstop===310&&loadRecords(store).best.casual.standard===320,'Browser storage failed');
    localStorage.removeItem(prefix+'office-picnic-v4');localStorage.removeItem(prefix+'office-picnic-v5');
    if(sound.ctx){check(sound.ctx.state==='running','Audio did not unlock');sound.setMuted(false);sound.event('checkpoint');sound.setPaused(true);await sound.ctx.suspend();check(sound.ctx.state==='suspended','Audio pause failed');sound.setPaused(false);await sound.ctx.resume();sound.setMuted(true);check(sound.master.gain.value>=0,'Invalid gain');}
    // Measure actual draw work; this is not a physical-phone FPS claim.
    const draws=[],frameIntervals=[];let last=0;
    for(let i=0;i<90;i++)await new Promise(resolve=>requestAnimationFrame(now=>{
      if(last)frameIntervals.push(now-last);last=now;const start=performance.now();renderer.draw(scenes[i%scenes.length],false,1);draws.push(performance.now()-start);resolve();
    }));
    draws.sort((a,b)=>a-b);frameIntervals.sort((a,b)=>a-b);draw();sound.setPaused(true);if(sound.interval)clearInterval(sound.interval);if(sound.ctx)await sound.ctx.close();
    output.textContent=`PASS: Casual + Rush, both modes, real collisions, ${formatTime(r.ticks/60)}, ${formatDistance(r.world.length)}.\nPASS: ${scenes.length} scenes including pickup, moving washer, squeeze and headwind, decoded sprites, session + browser records.\n${sound.ctx?'PASS: Web Audio unlock, event synthesis, pause, resume, mute.':'LIMIT: Web Audio unavailable.'}\n90-frame sample: draw p95 ${draws[Math.floor(draws.length*.95)].toFixed(2)} ms; frame interval median ${frameIntervals[Math.floor(frameIntervals.length*.5)].toFixed(2)} ms.\nThis browser sample does not verify physical phone performance or first-time usability.`;
  }catch(error){output.textContent='FAIL: '+error.message;console.error(error);}
};
runRoute();draw();
