import {TIERS,tierHash} from './tiers.js';
import {buildWorld} from './world.js';
import {createRun,stepRun,netTicks} from './simulation.js';

// Increment when changes to the simulation or format invalidate old replays.
export const TRACE_VERSION=4;

export function createTrace(run){
  return {version:TRACE_VERSION,tier:run.world.tier.id,hash:tierHash(run.world.tier),mode:run.mode,inputs:[]};
}
export function recordInput(trace,held){
  trace.inputs.push(Boolean(held));
}
export function finishTrace(trace,run){
  trace.finishTicks=run.finishTicks;
  trace.finishNetTicks=netTicks(run);
  trace.crashLog=run.crashLog.map(c=>({...c}));
  return trace;
}
function validCrash(crash){
  return crash && typeof crash==='object' && !Array.isArray(crash) &&
    typeof crash.where==='string' && Number.isInteger(crash.x) &&
    Number.isInteger(crash.y) && Number.isInteger(crash.district);
}
export function replayTrace(trace){
  if(!trace || typeof trace!=='object' || Array.isArray(trace) ||
    trace.version!==TRACE_VERSION || typeof trace.tier!=='string' ||
    !Object.hasOwn(TIERS,trace.tier) || !['standard','nonstop'].includes(trace.mode) ||
    trace.hash!==tierHash(TIERS[trace.tier]) || !Array.isArray(trace.inputs) ||
    !trace.inputs.every(v=>typeof v==='boolean') || !Number.isInteger(trace.finishTicks) ||
    trace.finishTicks<=0 || !Number.isInteger(trace.finishNetTicks) || !Array.isArray(trace.crashLog) || !trace.crashLog.every(validCrash)){
    throw new Error('Invalid or incompatible trace');
  }
  const run=createRun(trace.mode,buildWorld(undefined,TIERS[trace.tier]));
  for(const input of trace.inputs){
    if(run.status==='finished')throw new Error('Inputs after finish');
    stepRun(run,input);
  }
  const matchingCrashes=run.crashLog.length===trace.crashLog.length &&
    run.crashLog.every((crash,i)=>['where','x','y','district'].every(key=>crash[key]===trace.crashLog[i][key]));
  if(run.status!=='finished' || run.finishTicks!==trace.finishTicks || netTicks(run)!==trace.finishNetTicks || !matchingCrashes){
    throw new Error('Trace result does not match replay');
  }
  return run;
}
