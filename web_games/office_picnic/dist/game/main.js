import {createRun,stepRun} from './simulation.js';
import {airAt,upcomingHazard,hazardAdvice} from './world.js';
import {flightGuidance} from './guidance.js';
import {Renderer} from './render.js';
import {Sound} from './audio.js';
import {consumeTime,formatTime,formatDistance,formatSpeed,formatFeet} from './session.js';
import {loadRecords,saveResult,savePreferences} from './records.js';
const $=id=>document.getElementById(id),canvas=$('flight'),renderer=new Renderer(canvas);
let storage;try{storage=window.localStorage;}catch{storage=null;}
let records=loadRecords(storage),sound=new Sound(records.muted),run=null,paused=false,held=false,last=0,clock={accumulator:0},noticeEnd=0,lastDistrict=-1,lastVent=null,lastVentActive=false,resultShown=false;
const reduced=matchMedia('(prefers-reduced-motion: reduce)');reduced.addEventListener('change',()=>renderer.reduced=reduced.matches);
function titleBests(){
  const a=records.best.standard,b=records.best.nonstop;
  $('best-title').textContent=a||b?`Best standard: ${a?formatTime(a):'—'}   /   Nonstop: ${b?formatTime(b):'—'}`:'A short flight. A long way from your desk.';
}
function muteUI(){$('mute').textContent=records.muted?'Sound off':'Sound on';$('mute').setAttribute('aria-pressed',String(records.muted));$('mute').setAttribute('aria-label',records.muted?'Unmute sound':'Mute sound');}
function notice(text,seconds=6){$('notice').textContent=text;$('notice').hidden=false;noticeEnd=(run?.worldTicks||0)+seconds*60;}
function setHeld(value){if(held!==value&&run&&!paused&&run.status==='flying')sound.event(value?'pitch':'release');held=value;}
function start(mode){
  run=createRun(mode);paused=false;held=false;clock.accumulator=0;last=performance.now();lastDistrict=-1;lastVent=null;lastVentActive=false;resultShown=false;sound.district=0;sound.setPaused(false);sound.unlock().then(()=>sound.event('launch'));
  for(const id of ['title-screen','pause-screen','result-screen'])$(id).hidden=true;
  for(const id of ['hud','route-hud','flight-hud'])$(id).hidden=false;
  $('district-dots').replaceChildren(...Array.from({length:5},()=>document.createElement('i')));
  $('run-mode').textContent=mode==='standard'?'Standard · impacts +3s':'Nonstop · no checkpoints';
  canvas.focus({preventScroll:true});notice('Hold to climb over the first flock. Release to dive and regain speed.',8);updateHUD();
}
function pause(){if(!run||run.status==='finished'||paused)return;setHeld(false);paused=true;clock.accumulator=0;sound.event('pause');sound.setPaused(true);$('pause-screen').hidden=false;$('resume').focus();}
function resume(){if(!run)return;paused=false;held=false;clock.accumulator=0;last=performance.now();sound.setPaused(false);sound.unlock().then(()=>sound.event('resume'));$('pause-screen').hidden=true;canvas.focus({preventScroll:true});}
function home(){held=false;paused=true;run=null;sound.setPaused(true);for(const id of ['pause-screen','result-screen','hud','route-hud','flight-hud','notice'])$(id).hidden=true;$('title-screen').hidden=false;titleBests();$('start').focus();}
function finish(){
  if(resultShown)return;resultShown=true;held=false;const seconds=run.finishTicks/60,previous=records.best[run.mode];records=saveResult(storage,run.mode,seconds,records);records.muted=sound.muted;
  $('result-time').textContent=formatTime(seconds);$('result-distance').textContent=formatDistance(run.world.length);
  $('result-best').textContent=`${run.mode==='standard'?'Standard':'Nonstop'} · ${!previous||seconds<previous?'Your best flight.':`Best ${formatTime(previous)}`}`;
  $('notice').hidden=true;
  // Let the visible landing settle before revealing the invitation card.
  setTimeout(()=>{if(run?.status==='finished'&&resultShown){$('result-screen').hidden=false;$('replay').focus();if(!previous||seconds<previous)sound.event('best');}},reduced.matches?300:1400);
}
function tick(){
  run.previous={x:run.plane.x,y:run.plane.y};stepRun(run,held);sound.district=run.district;
  for(const event of run.events)sound.event(event);
  if(run.events.includes('impact')){held=false;notice(run.cause,5);}
  if(run.events.includes('respawn'))notice(run.mode==='standard'?'Back at the last rooftop. Build height for the flock.':'A fresh throw. Climb over the first flock.',4);
  if(run.events.includes('warning')){const hazard=upcomingHazard(run.world,run.plane.x);if(hazard)notice(hazardAdvice(hazard),4);}
  if(run.events.includes('checkpoint'))notice(`${run.world.districts[run.district].name}. ${run.mode==='standard'?'Rooftop checkpoint saved. ':''}${run.world.districts[run.district].tip}`,8);
  const air=airAt(run.world,run.plane,run.worldTicks/60),source=air.source;
  const ventActive=source?.type===1&&air.activity>.35;
  if(ventActive&&(lastVent!==source||!lastVentActive))sound.event('vent');lastVent=source;lastVentActive=ventActive;
  if(run.status==='finished')finish();
}
function updateHUD(){
  if(!run)return;
  $('timer').textContent=formatTime(run.ticks/60);$('district-name').textContent=run.world.districts[run.district].name;$('height-status').textContent=formatFeet(run.plane.y)+' above street';
  $('remaining').textContent=formatDistance(run.world.length-run.plane.x)+' to the picnic';
  $('route-fill').style.width=Math.min(100,run.plane.x/run.world.length*100)+'%';
  if(lastDistrict!==run.district){lastDistrict=run.district;[...$('district-dots').children].forEach((el,i)=>el.className=i<=run.district?'done':'');}
  const p=run.plane;$('speed-text').textContent=p.stalled?'Stall!':formatSpeed(p.speed)+' airspeed';$('speed-fill').style.width=p.speed/32*100+'%';$('speed-fill').style.background=p.speed<12?'#f1a290':'#d9dfd4';
  const guidance=flightGuidance(run,held);$('input-hint').textContent=guidance.instruction;$('air-status').textContent=guidance.airLabel;$('motion-status').textContent=guidance.motionLabel;
  if(run.worldTicks>noticeEnd)$('notice').hidden=true;
}
function frame(now){
  const delta=last?(now-last)/1000:0;last=now;
  if(run){consumeTime(clock,delta,paused||run.status==='finished',tick);renderer.draw(run,held,clock.accumulator*60);if(run.worldTicks%6===0||paused||run.status==='finished')updateHUD();}
  requestAnimationFrame(frame);
}
$('start').onclick=()=>start('standard');$('nonstop').onclick=()=>start('nonstop');$('pause').onclick=pause;$('resume').onclick=resume;$('restart').onclick=()=>start(run.mode);$('home').onclick=home;$('result-home').onclick=home;$('replay').onclick=()=>start(run.mode);
$('mute').onclick=()=>{records.muted=!records.muted;sound.setMuted(records.muted);savePreferences(storage,records);muteUI();sound.unlock();sound.event('ui');};
canvas.addEventListener('pointerdown',e=>{if(e.button!==0||!run||paused||run.status!=='flying')return;e.preventDefault();canvas.setPointerCapture(e.pointerId);setHeld(true);sound.unlock();});
canvas.addEventListener('pointerup',()=>setHeld(false));canvas.addEventListener('pointercancel',pause);canvas.addEventListener('lostpointercapture',()=>setHeld(false));
document.addEventListener('keydown',e=>{
  if(e.code==='Space'&&run&&!paused&&run.status==='flying'&&e.target.tagName!=='BUTTON'){e.preventDefault();if(!e.repeat)setHeld(true);}
  if(e.code==='Escape'||e.code==='KeyP'){e.preventDefault();if(paused&&run)resume();else pause();}
  if(e.code==='KeyM'&&!e.repeat)$('mute').click();
});document.addEventListener('keyup',e=>{if(e.code==='Space')setHeld(false);});
window.addEventListener('blur',pause);document.addEventListener('visibilitychange',()=>{if(document.hidden)pause();});window.addEventListener('resize',()=>renderer.resize());
titleBests();muteUI();requestAnimationFrame(frame);
