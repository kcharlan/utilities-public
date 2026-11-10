import {hazardKey} from './world.js';
import {consumeTime} from './session.js';
// Feedback is presentation-only; its deterministic random stream never touches physics.
export const FEEDBACK=Object.fromEntries([
  ['launch','sheets'],['pitch','stretch'],['release','stretch'],['lift','motes'],['vent','steam'],
  ['stall','wobble'],['recovery','ring'],['impact','burst'],['respawn','pop'],['checkpoint','pulse'],
  ['district','card'],['pickupAhead','pulse'],['pickup','sparkle'],['warning','pulse'],['landing','splash'],['best','ring'],
  ['ui',null],['pause',null],['resume',null]
].map(([name,visual])=>[name,{visual}]));
export function createEffects(){const fx={particles:[],cues:[],seed:0x51f15e,bump:0};fx.step=()=>stepEffects(fx);return fx;}
function random(fx){fx.seed=(Math.imul(fx.seed,1664525)+1013904223)>>>0;return fx.seed/4294967296;}
export function spawnEffects(fx,run,events,{reduced=false}={}){
  let warning=0;
  for(const name of events){
    const visual=FEEDBACK[name]?.visual;if(!visual||(name==='pickupAhead'&&run.world.tier.prompts==='quiet'))continue;
    if(name==='respawn'&&run.mode==='nonstop'){fx.particles.length=0;fx.cues.length=0;fx.bump=0;}
    const roof=name==='checkpoint'?run.world.airs.find(a=>a.gapId===run.checkpoint.id):null;
    const x=roof?Math.max(roof.x,Math.min(run.checkpoint.x,roof.x+roof.w)):run.plane.x,y=roof?roof.y:run.plane.y;
    if(fx.cues.length>=48)fx.cues.shift();
    const source=name==='warning'?run.warningHazards?.[warning++]:null;
    fx.cues.push({name,visual,x,y,age:0,life:name==='district'?100:45,reduced,reward:run.pickupReward||0,district:run.world.districts[run.district].name,hazardKey:source?hazardKey(source):null});
    if(reduced)continue;
    if(name==='impact')fx.bump=9;
    const count=({launch:9,lift:6,vent:7,impact:12,pickup:8,landing:14})[name]||0;
    const hazard=name==='impact'?run.world.hazards.find(h=>h.id===run.crashLog.at(-1)?.where):null;
    const kind=name==='impact'?(hazard?.kind==='pigeon'?'feather':hazard?.kind==='platform'?'drop':'sheet'):({launch:'sheet',lift:'mote',vent:'steam',pickup:'sparkle',landing:'salad'})[name];
    for(let i=0;i<count&&fx.particles.length<96;i++)fx.particles.push({x,y,vx:(random(fx)-.5)*3,vy:random(fx)*2+.3,age:0,life:30+Math.floor(random(fx)*20),kind});
  }
}
export function advanceFinishedEffects(clock,seconds,paused,run,fx){
  if(run.status!=='finished'){clock.accumulator=0;return;}
  consumeTime(clock,seconds,paused,fx.step);
}
export function stepEffects(fx){
  if(fx.bump>0)fx.bump--;
  let live=0;
  for(let i=0;i<fx.particles.length;i++){const p=fx.particles[i];if(++p.age>=p.life)continue;p.x+=p.vx;p.y+=p.vy;p.vy-=.025;fx.particles[live++]=p;}
  fx.particles.length=live;live=0;
  for(let i=0;i<fx.cues.length;i++){const cue=fx.cues[i];if(++cue.age<cue.life)fx.cues[live++]=cue;}
  fx.cues.length=live;
}
