// Browser-only verification harness, separate from the shipped play flow.
import {medalFor,MEDALS} from './medals.js';
import {TIERS} from './tiers.js';import {buildWorld,hazardBox,hazardKey} from './world.js';
import {createRun,stepRun} from './simulation.js';import {chooseInput,referenceInput} from './bot.js';import {Renderer} from './render.js';import {Sound} from './audio.js';import {saveResult,loadRecords} from './records.js';import {formatTime,formatDistance} from './session.js';
import {createEffects,spawnEffects,stepEffects} from './effects.js';
const output=document.getElementById('output'),canvas=document.getElementById('preview'),renderer=new Renderer(canvas),scenes=[],select=document.getElementById('scene');
// The harness checkbox explicitly selects either path, independent of system preference.
renderer.reduced=document.getElementById('reduced').checked;
for(const [value,text] of [['6','Vent · steam burst'],['7','Vent · lull'],['8','Window-washer approach'],['9','Rush · moving washer'],['10','Rush · squeeze'],['11','Rush · headwind'],['12','Pickup · moving washer'],['13','Tailwind lane'],['14','Roof impact'],['15','Pickup feedback'],['16','Flock impact'],['17','Washer impact'],['18','District transition'],['19','Squeeze warning feedback']]){const option=document.createElement('option');option.value=value;option.textContent=text;select.append(option);}
const check=(condition,message)=>{if(!condition)throw Error(message);};
function capture(r){return {...r,plane:{...r.plane},previous:null};}
const sceneEffects=[];
function prepareEffects(){for(const i of [14,15,16,17,18,19]){if(!scenes[i])continue;sceneEffects[i]=createEffects();spawnEffects(sceneEffects[i],scenes[i],scenes[i].events,{reduced:renderer.reduced});for(let n=0;n<8;n++)stepEffects(sceneEffects[i]);}}
function draw(){const i=Number(select.value);if(scenes[i])renderer.draw(scenes[i],false,1,sceneEffects[i]);}
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
  const overtimeWorld=buildWorld(undefined,TIERS.overtime);
  for(const course of [world,overtimeWorld])for(const mode of ['standard','nonstop']){
    const flight=createRun(mode,course);
    for(let n=0;n<60*900&&flight.status!=='finished';n++)stepRun(flight,referenceInput(flight));
    check(flight.status==='finished'&&!flight.crashes,`${course.tier.name} ${mode} failed`);
  }
  for(const [index,feature] of [[9,world.hazards.find(h=>h.kind==='platform'&&h.moving)],[10,world.hazards.find(h=>h.squeeze)],[11,world.winds.find(w=>w.wind<0)],[13,world.winds.find(w=>w.wind>0)]]){
    const preview=createRun('standard',world);preview.plane.x=(feature.x??feature.x0)-90;preview.plane.y=150;preview.worldTicks=240;scenes[index]=capture(preview);
  }
  const pickupWorld=buildWorld(undefined,{...TIERS.rush,pickups:[{district:2,slot:2,place:'underWasher',dy:6,r:4,rewardTicks:540}]});
  const pickupScene=createRun('standard',pickupWorld),pk=pickupWorld.pickups[0];pickupScene.plane.x=pk.x-90;pickupScene.plane.y=pk.y;pickupScene.worldTicks=240;scenes[12]=capture(pickupScene);
  const impact=createRun();impact.plane.x=impact.world.buildings[1].x+2;impact.plane.y=impact.world.buildings[1].y-2;stepRun(impact,false);check(impact.events.includes('impact'),'Impact scene did not collide');scenes[14]=capture(impact);
  const pickup=createRun();const target=pickup.world.pickups[0];pickup.plane.x=target.x;pickup.plane.y=target.y;stepRun(pickup,false);check(pickup.events.includes('pickup'),'Pickup scene did not collect');scenes[15]=capture(pickup);
  for(const [index,kind] of [[16,'pigeon'],[17,'platform']]){
    const flight=createRun(),hazard=flight.world.hazards.find(h=>h.kind===kind),box=hazardBox(hazard,1/60);
    flight.plane.x=box.x+box.w/2;flight.plane.y=box.y+box.h/2;stepRun(flight,false);
    check(flight.events.includes('impact')&&flight.crashLog.at(-1).where===hazard.id,`${kind} impact scene did not collide`);scenes[index]=capture(flight);
  }
  const district=createRun();district.plane.x=district.world.districts[1].start-.1;district.plane.y=300;stepRun(district,false);check(district.events.includes('district'),'District scene did not transition');scenes[18]=capture(district);
  const warning=createRun('standard',world),flock=world.hazards.find(h=>h.squeeze&&h.kind==='pigeon'&&h.district===4),key=hazardKey(flock);
  warning.district=4;warning.plane.x=flock.x-flock.warningDistance-1;warning.plane.y=300;
  for(let i=0;i<20&&!warning.warningHazards?.some(h=>hazardKey(h)===key);i++)stepRun(warning,false);
  check(warning.warningHazards.some(h=>hazardKey(h)===key),'Squeeze warning scene did not emit');
  scenes[19]=capture(warning);scenes[19].plane.x=flock.x-40;scenes[19].plane.y=150;
  prepareEffects();
  return r;
}
select.onchange=draw;document.getElementById('reduced').onchange=e=>{renderer.reduced=e.target.checked;prepareEffects();draw();};window.addEventListener('resize',()=>{renderer.resize();draw();});
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
    store.setItem('office-picnic-v5',JSON.stringify({best:{casual:{standard:320}},tier:'rush',muted:true}));
    check(Object.keys(loadRecords(store).best).length===0&&loadRecords(store).tier==='rush'&&loadRecords(store).muted,'Migration failed');
    saveResult(store,'rush','nonstop',MEDALS.rush.silver);
    saveResult(store,'overtime','standard',MEDALS.overtime.gold);
    saveResult(store,'overtime','nonstop',MEDALS.overtime.silver);
    const saved=loadRecords(store);
    check(saved.best.rush.nonstop===MEDALS.rush.silver&&!saved.best.casual,'Browser storage failed');
    check(saved.best.overtime.standard===MEDALS.overtime.gold&&saved.best.overtime.nonstop===MEDALS.overtime.silver,'Overtime records failed');
    check(medalFor('rush',saved.best.rush.nonstop)==='silver','Stored Nonstop medal failed');
    check(medalFor('casual',MEDALS.casual.bronze+.01)===null,'Medal cutoff failed');
    localStorage.removeItem(prefix+'office-picnic-v5');localStorage.removeItem(prefix+'office-picnic-v6');
    if(sound.ctx){check(sound.ctx.state==='running','Audio did not unlock');sound.setMuted(false);sound.event('checkpoint');sound.setPaused(true);await sound.ctx.suspend();check(sound.ctx.state==='suspended','Audio pause failed');sound.setPaused(false);await sound.ctx.resume();sound.setMuted(true);check(sound.master.gain.value>=0,'Invalid gain');}
    // Measure actual draw work; this is not a physical-phone FPS claim.
    const draws=[],frameIntervals=[];let last=0;
    for(let i=0;i<90;i++)await new Promise(resolve=>requestAnimationFrame(now=>{
      if(last)frameIntervals.push(now-last);last=now;const index=i%scenes.length,start=performance.now();renderer.draw(scenes[index],false,1,sceneEffects[index]||sceneEffects[14]);draws.push(performance.now()-start);resolve();
    }));
    draws.sort((a,b)=>a-b);frameIntervals.sort((a,b)=>a-b);draw();sound.setPaused(true);if(sound.interval)clearInterval(sound.interval);if(sound.ctx)await sound.ctx.close();
    output.textContent=`PASS: Casual + Rush + Overtime, both modes, real collisions, ${formatTime(r.ticks/60)}, ${formatDistance(r.world.length)}.\nPASS: ${scenes.length} scenes including pickup, moving washer, squeeze and headwind, decoded sprites, session + browser records.\n${sound.ctx?'PASS: Web Audio unlock, event synthesis, pause, resume, mute.':'LIMIT: Web Audio unavailable.'}\n90-frame sample: draw p95 ${draws[Math.floor(draws.length*.95)].toFixed(2)} ms; frame interval median ${frameIntervals[Math.floor(frameIntervals.length*.5)].toFixed(2)} ms.\nThis browser sample does not verify physical phone performance or first-time usability.`;
  }catch(error){output.textContent='FAIL: '+error.message;console.error(error);}
};
runRoute();draw();
