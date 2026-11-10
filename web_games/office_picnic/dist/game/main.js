import {TIERS} from './tiers.js';
import {MEDALS,medalFor} from './medals.js';
import {buildWorld} from './world.js';
import {createTrace,recordInput,finishTrace} from './trace.js';
import {createRun,stepRun,netTicks} from './simulation.js';
import {airAt,hazardAdvice} from './world.js';
import {flightGuidance,noticeMessages} from './guidance.js';
import {Renderer} from './render.js';
import {Sound,dispatchRunEvents} from './audio.js';
import {createEffects,spawnEffects,stepEffects,advanceFinishedEffects} from './effects.js';
import {dialogTabTarget,shouldRetry,consumeTime,rebaseNoticeDeadline,formatTime,formatDistance,formatSpeed,formatFeet} from './session.js';
import {loadRecords,finishResult,savePreferences,titleBestText} from './records.js';
const $=id=>document.getElementById(id),canvas=$('flight'),renderer=new Renderer(canvas);
const tracing=new URLSearchParams(location.search).has('trace');let trace=null;
let storage;try{storage=window.localStorage;}catch{storage=null;}
let records=loadRecords(storage),sound=new Sound(records.muted),run=null,paused=false,held=false,last=0,clock={accumulator:0},noticeEnd=0,lastDistrict=-1,lastVent=null,lastVentActive=false,resultShown=false,rewardEnd=0;
let effects=createEffects(),effectClock={accumulator:0};
const reduced=matchMedia('(prefers-reduced-motion: reduce)');reduced.addEventListener('change',()=>{renderer.reduced=reduced.matches;if(reduced.matches){effects.particles.length=0;effects.bump=0;}});
function titleBests(){
  for(const tier of Object.values(TIERS)){
    $(`best-${tier.id}`).textContent=titleBestText(records,tier.id);
  }
}
function muteUI(){$('mute').textContent=records.muted?'Sound off':'Sound on';$('mute').setAttribute('aria-pressed',String(records.muted));$('mute').setAttribute('aria-label',records.muted?'Unmute sound':'Mute sound');}
let hazardNotice='',hazardNoticeEnd=0;
function notice(text,seconds=6){$('notice').textContent=text;$('notice').hidden=false;noticeEnd=(run?.worldTicks||0)+seconds*60;}
function feedback(name){sound.event(name);if(run)spawnEffects(effects,run,[name],{reduced:reduced.matches});}
function setHeld(value){if(held!==value&&run&&!paused&&run.status==='flying')feedback(value?'pitch':'release');held=value;}
function clearTraceDownload(){
  const link=$('trace-download');
  if(link){URL.revokeObjectURL(link.href);link.remove();}
}
const worlds=new Map();
function modeText(world,mode){return `${world.tier.name} · ${mode==='standard'?`Standard · impacts +${world.rules.crashPenaltyTicks/60}s`:'Nonstop · restart from the office'}`;}
function modalOpen(open){for(const id of ['flight','hud','route-hud','flight-hud'])$(id).inert=open;}
function start(mode){
  modalOpen(false);
  clearTraceDownload();
  let world=worlds.get(records.tier);if(!world){world=buildWorld(undefined,TIERS[records.tier]);worlds.set(records.tier,world);}
  run=createRun(mode,world);effects=createEffects();effectClock.accumulator=0;spawnEffects(effects,run,['launch'],{reduced:reduced.matches});trace=tracing?createTrace(run):null;paused=false;held=false;clock.accumulator=0;last=performance.now();lastDistrict=-1;lastVent=null;lastVentActive=false;resultShown=false;rewardEnd=0;sound.district=0;sound.setPaused(false);sound.unlock().then(()=>sound.event('launch'));
  for(const id of ['title-screen','pause-screen','result-screen'])$(id).hidden=true;
  for(const id of ['hud','route-hud','flight-hud'])$(id).hidden=false;
  $('district-dots').replaceChildren(...Array.from({length:5},()=>document.createElement('i')));
  $('run-mode').textContent=modeText(world,mode);$('pause-mode').textContent=modeText(world,mode);
  hazardNotice='';hazardNoticeEnd=0;$('notice').hidden=true;canvas.focus({preventScroll:true});if(world.tier.prompts!=='quiet')notice('Hold to climb over the first flock. Release to dive and regain speed.',8);updateHUD();
}
function pause(){if(!run||run.status==='finished'||paused)return;setHeld(false);paused=true;clock.accumulator=0;sound.event('pause');sound.setPaused(true);$('pause-screen').hidden=false;modalOpen(true);$('resume').focus();}
function resume(){if(!run)return;paused=false;held=false;clock.accumulator=0;last=performance.now();sound.setPaused(false);sound.unlock().then(()=>sound.event('resume'));$('pause-screen').hidden=true;modalOpen(false);canvas.focus({preventScroll:true});}
function home(){modalOpen(false);clearTraceDownload();held=false;paused=true;run=null;sound.setPaused(true);for(const id of ['pause-screen','result-screen','hud','route-hud','flight-hud','notice'])$(id).hidden=true;$('title-screen').hidden=false;titleBests();$('start').focus();}
function finish(){
  if(resultShown)return;
  resultShown=true;held=false;
  const seconds=netTicks(run)/60;
  const result=finishResult(storage,run.world.tier.id,run.mode,seconds,records),previous=result.previous;
  records=result.records;
  $('result-time').textContent=formatTime(seconds);$('result-distance').textContent=formatDistance(run.world.length);
  const penalty=run.mode==='standard'?run.crashes*run.world.rules.crashPenaltyTicks:0;
  const impacts=run.mode==='standard'?`Impacts: ${run.crashes} · +${formatTime(penalty/60)}`:`Restarts: ${run.crashes} · no time penalty`;
  $('result-breakdown').replaceChildren(...[`Flight: ${formatTime((run.finishTicks-penalty)/60)}`,impacts,`Pickups: ${run.collected.size}/${run.world.pickups.length} · −${formatTime(run.bonusTicks/60)}`].map(text=>{const row=document.createElement('div');row.textContent=text;return row;}));
  const medal=medalFor(run.world.tier.id,seconds);
  const table=MEDALS[run.world.tier.id];
  const next=medal==='gold'?null:medal==='silver'?'gold':medal==='bronze'?'silver':'bronze';
  $('result-medal').textContent=medal?`${medal[0].toUpperCase()+medal.slice(1)} medal earned`:'No medal earned';
  $('result-target').textContent=next?`Next: ${next} at ${formatTime(table[next])} or faster`:'Gold is the highest medal.';
  $('result-best').textContent=`${run.mode==='standard'?'Standard':'Nonstop'} · ${!previous||seconds<previous?'Your best flight.':`Best ${formatTime(previous)}`}`;
  $('notice').hidden=true;
  if(trace){finishTrace(trace,run);const link=document.createElement('a');link.textContent='Download flight trace';link.download='office-picnic-trace.json';link.href=URL.createObjectURL(new Blob([JSON.stringify(trace)],{type:'application/json'}));link.id='trace-download';clearTraceDownload();$('result-screen').querySelector('.modal').append(link);}
  if(!previous||seconds<previous)feedback('best');
  // Let the visible landing settle before revealing the invitation card.
  setTimeout(()=>{if(run?.status==='finished'&&resultShown){$('result-screen').hidden=false;modalOpen(true);$('replay').focus();}},reduced.matches?300:1400);
}
function tick(){
  run.previous={x:run.plane.x,y:run.plane.y};if(trace)recordInput(trace,held);const before=run.worldTicks;stepRun(run,held);noticeEnd=rebaseNoticeDeadline(noticeEnd,before,run.worldTicks);sound.district=run.district;
  dispatchRunEvents(sound,run);
  stepEffects(effects);if(run.events.length)spawnEffects(effects,run,run.events,{reduced:reduced.matches});
  if(run.events.includes('impact'))held=false;
  if(run.events.includes('respawn')){hazardNotice='';hazardNoticeEnd=0;}
  if(run.mode==='nonstop'&&run.events.includes('respawn')){rewardEnd=0;$('pickup-reward').hidden=true;$('pickup-reward').textContent='';}
  if(run.events.includes('pickup')){rewardEnd=run.worldTicks+150;$('pickup-reward').textContent=`−${run.pickupReward/60}s pickup`;}
  const messages=noticeMessages(run);
  const emittedHazard=(run.warningHazards||[]).map(hazardAdvice).find(text=>messages.includes(text));
  if(emittedHazard){hazardNotice=emittedHazard;hazardNoticeEnd=run.worldTicks+8*60;}
  if(run.world.tier.notice?.banner&&run.announcedPickups.length&&messages.length===run.announcedPickups.length&&hazardNotice&&run.worldTicks<=hazardNoticeEnd)messages.unshift(hazardNotice);
  if(run.previous.x<=run.world.finishStart&&run.plane.x>run.world.finishStart)messages.push('The park. Release now and glide down to the table.');
  if(messages.length)notice(messages.join(' · '),8);
  if(run.status==='landing')$('notice').hidden=true;
  const air=airAt(run.world,run.plane,run.worldTicks/60),source=air.source;
  const ventActive=source?.type===1&&air.activity>.35;
  if(ventActive&&(lastVent!==source||!lastVentActive))feedback('vent');lastVent=source;lastVentActive=ventActive;
  if(run.status==='finished')finish();
}
function updateHUD(){
  if(!run)return;
  $('timer').textContent=formatTime(netTicks(run)/60);$('pickup-reward').hidden=run.worldTicks>rewardEnd||!rewardEnd;$('district-name').textContent=run.world.districts[run.district].name;$('height-status').textContent=formatFeet(run.plane.y)+' above street';
  $('remaining').textContent=formatDistance(run.world.length-run.plane.x)+' to the picnic';
  $('route-fill').style.width=Math.min(100,run.plane.x/run.world.length*100)+'%';
  $('pickup-ticks').replaceChildren(...(run.world.tier.notice?.ticks?run.world.pickups.filter(pk=>!run.collected.has(pk.id)).map(pk=>{const tick=document.createElement('i');tick.className='pickup-tick';tick.style.left=(pk.x/run.world.length*100)+'%';return tick;}):[]));
  if(lastDistrict!==run.district){lastDistrict=run.district;[...$('district-dots').children].forEach((el,i)=>el.className=i<=run.district?'done':'');}
  const p=run.plane;$('speed-text').textContent=p.stalled?'Stall!':formatSpeed(p.speed)+' airspeed';$('speed-fill').style.width=p.speed/32*100+'%';$('speed-fill').style.background=p.speed<12?'#f1a290':'#d9dfd4';
  const guidance=flightGuidance(run,held);$('input-hint').textContent=guidance.instruction;$('air-status').textContent=guidance.airLabel;$('motion-status').textContent=guidance.motionLabel;
  if(run.worldTicks>noticeEnd)$('notice').hidden=true;
}
function frame(now){
  const delta=last?(now-last)/1000:0;last=now;
  if(run){if(run.status==='finished')advanceFinishedEffects(effectClock,delta,paused,run,effects);else consumeTime(clock,delta,paused,tick);renderer.draw(run,held,clock.accumulator*60,effects);if(run.worldTicks%6===0||paused||run.status==='finished')updateHUD();}
  requestAnimationFrame(frame);
}
$('start').onclick=()=>start('standard');$('nonstop').onclick=()=>start('nonstop');$('pause').onclick=pause;$('resume').onclick=resume;$('restart').onclick=()=>start(run.mode);$('home').onclick=home;$('result-home').onclick=home;$('replay').onclick=()=>start(run.mode);
$('mute').onclick=()=>{records=savePreferences(storage,records,{muted:!records.muted});sound.setMuted(records.muted);muteUI();sound.unlock();sound.event('ui');};
canvas.addEventListener('pointerdown',e=>{if(e.button!==0||!run||paused||run.status!=='flying')return;e.preventDefault();canvas.setPointerCapture(e.pointerId);setHeld(true);sound.unlock();});
canvas.addEventListener('pointerup',()=>setHeld(false));canvas.addEventListener('pointercancel',pause);canvas.addEventListener('lostpointercapture',()=>setHeld(false));
document.addEventListener('keydown',e=>{
  if(e.code==='Tab'){
    const dialog=['pause-screen','result-screen'].map(id=>document.getElementById(id)).find(el=>!el.hidden);
    if(dialog){const items=[...dialog.querySelectorAll('button:not([disabled]),a[href]')],target=dialogTabTarget(items.indexOf(document.activeElement),items.length,e.shiftKey);if(target!==null){e.preventDefault();items[target].focus();}return;}
  }
  if(e.code==='KeyR'&&!e.repeat&&run&&shouldRetry({mode:run.mode,paused,finished:!$('result-screen').hidden})){e.preventDefault();start(run.mode);return;}
  if(e.code==='Space'&&run&&!paused&&run.status==='flying'&&e.target.tagName!=='BUTTON'){e.preventDefault();if(!e.repeat)setHeld(true);}
  if(e.code==='Escape'||e.code==='KeyP'){e.preventDefault();if(paused&&run)resume();else pause();}
  if(e.code==='KeyM'&&!e.repeat)$('mute').click();
});document.addEventListener('keyup',e=>{if(e.code==='Space')setHeld(false);});
window.addEventListener('blur',pause);document.addEventListener('visibilitychange',()=>{if(document.hidden)pause();});window.addEventListener('resize',()=>renderer.resize());
for(const tier of Object.values(TIERS)){
  const label=document.createElement('label');label.className='tier-row';
  const radio=document.createElement('input');radio.type='radio';radio.name='tier';radio.value=tier.id;radio.checked=records.tier===tier.id;
  const copy=document.createElement('span');const name=document.createElement('strong');name.textContent=tier.name;
  const detail=document.createElement('small');detail.textContent=`${tier.blurb} Standard impacts +${tier.rules.crashPenaltyTicks/60}s.`;
  const thresholds=document.createElement('small');
  const table=MEDALS[tier.id];
  thresholds.textContent=`Gold ${formatTime(table.gold)} · Silver ${formatTime(table.silver)} · Bronze ${formatTime(table.bronze)}`;
  const best=document.createElement('small');
  best.id=`best-${tier.id}`;
  copy.append(name,detail,thresholds,best);label.append(radio,copy);$('tier-picker').append(label);
  radio.addEventListener('change',()=>{if(radio.checked){records=savePreferences(storage,records,{tier:tier.id});titleBests();}});
}
titleBests();muteUI();$('start').focus();requestAnimationFrame(frame);
