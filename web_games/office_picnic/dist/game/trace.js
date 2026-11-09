import {TIERS,tierHash} from './tiers.js';
import {buildWorld} from './world.js';
import {createRun,stepRun} from './simulation.js';
export const TRACE_VERSION=1;
export function createTrace(run){return {version:TRACE_VERSION,tier:run.world.tier.id,hash:tierHash(run.world.tier),mode:run.mode,inputs:[]};}
export function recordInput(trace,held){trace.inputs.push(Boolean(held));}
export function finishTrace(trace,run){trace.finishTicks=run.finishTicks;trace.crashLog=run.crashLog.map(c=>({...c}));return trace;}
export function replayTrace(trace){
 if(!trace||typeof trace!=='object'||trace.version!==TRACE_VERSION||!Object.hasOwn(TIERS,trace.tier)||!['standard','nonstop'].includes(trace.mode)||trace.hash!==tierHash(TIERS[trace.tier])||!Array.isArray(trace.inputs)||!trace.inputs.every(v=>typeof v==='boolean')||!Number.isInteger(trace.finishTicks)||trace.finishTicks<=0||!Array.isArray(trace.crashLog))throw new Error('Invalid or incompatible trace');
 const run=createRun(trace.mode,buildWorld(undefined,TIERS[trace.tier]));
 for(const input of trace.inputs){if(run.status==='finished')throw new Error('Inputs after finish');stepRun(run,input);}
 if(run.status!=='finished'||run.finishTicks!==trace.finishTicks||JSON.stringify(run.crashLog)!==JSON.stringify(trace.crashLog))throw new Error('Trace result does not match replay');
 return run;
}
