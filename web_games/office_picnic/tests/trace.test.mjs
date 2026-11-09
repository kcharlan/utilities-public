import test from 'node:test';import assert from 'node:assert/strict';
import {createRun,stepRun} from '../dist/game/simulation.js';import {chooseInput} from '../dist/game/bot.js';
import {createTrace,recordInput,finishTrace,replayTrace} from '../dist/game/trace.js';
test('trace replays a Nonstop flight across a restart',()=>{const r=createRun('nonstop'),trace=createTrace(r);for(let n=0;n<50000&&r.status!=='finished';n++){const held=n<800?false:chooseInput(r);recordInput(trace,held);stepRun(r,held);}assert.ok(r.crashes>0);assert.equal(r.status,'finished');finishTrace(trace,r);assert.deepEqual(replayTrace(trace).crashLog,r.crashLog);});
test('trace rejects malformed, stale and inconsistent data',()=>{const r=createRun(),t=createTrace(r);for(const bad of [null,{}, {...t,version:0},{...t,hash:'stale'},{...t,mode:'bogus'},{...t,inputs:[1]}, {...t,finishTicks:1,crashLog:[]}])assert.throws(()=>replayTrace(bad));});
