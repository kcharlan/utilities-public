import {sensible,REFERENCE} from '../dist/game/bot.js';
import {upcomingHazard} from '../dist/game/world.js';
export function rng(seed){let a=seed>>>0;return()=>{a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};}
export function gaussFrom(r){return()=>{let u=0,v=0;while(u===0)u=r();while(v===0)v=r();return Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*v);};}

export const PROFILES={
  bot:{reaction:0,jitter:0,minPress:0,sigma:0,lead:.55},
  ideal:REFERENCE,
  expert:{reaction:.18,jitter:.06,minPress:.08,sigma:3,lead:.5,predict:true},
  regular:{reaction:.25,jitter:.10,minPress:.12,sigma:6,lead:.4,predict:true},
  novice:{reaction:.35,jitter:.16,minPress:.15,sigma:10,lead:.3,predict:false},
};

export function makePilot(profile,seed,extra={}){
  const r=rng(seed),g=gaussFrom(r),prof={...profile,...extra};
  const delay=Math.round((prof.reaction||0)*60),minHold=Math.round((prof.minPress||0)*60),meanJitter=(prof.jitter||0)*60;
  // Players adapt after crashing: widen the margin for that kind of obstacle in that district.
  const kindOf=w=>/-over$|^perch/.test(w)?"flock":/-under$/.test(w)?"washer":"roof";
  prof.adapt=(run,kind)=>Math.min(prof.learnCap??12,(prof.learn??3)*run.crashLog.filter(c=>c.district===run.district&&kindOf(c.where)===kind).length);
  const queue=[];let held=false,since=1e9,ctxKey=null,bias=0;
  prof.biasFor=run=>{
    const p=run.plane,h=upcomingHazard(run.world,p.x,prof.lookahead??300),c=run.world.airs.find(a=>p.x>=a.x&&p.x<=a.x+a.w);
    const key=h?.id??c?.gapId??'none';
    if(key!==ctxKey){ctxKey=key;bias=g()*(prof.sigma||0);}
    return bias;
  };
  // A player gives up on a pickup after crashing while going for it maxTries times.
  const failures={};let seenCrashes=0;
  if(prof.pickups){const want=prof.pickups;prof.pickups=k=>want(k)&&(failures[k.id]||0)<(prof.maxTries??2);}
  return run=>{
    if(run.crashes>seenCrashes){seenCrashes=run.crashes;if(prof.lastPickup)failures[prof.lastPickup]=(failures[prof.lastPickup]||0)+1;prof.lastPickup=null;}
    if(run.status!=='flying'){queue.length=0;held=false;return false;}
    queue.push((prof.policy??sensible)(run,prof));
    let want=queue.length>delay?queue.shift():held;
    since++;
    if(want!==held){
      if(since<minHold)want=held;
      else if(meanJitter>0&&r()>1/(1+meanJitter))want=held;
    }
    if(want!==held){held=want;since=0;}
    return held;
  };
}
