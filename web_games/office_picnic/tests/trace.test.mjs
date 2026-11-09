import test from 'node:test';
import assert from 'node:assert/strict';
import {createRun,stepRun} from '../dist/game/simulation.js';
import {chooseInput} from '../dist/game/bot.js';
import {createTrace,recordInput,finishTrace,replayTrace} from '../dist/game/trace.js';

function flightWithRestart(){
  const run=createRun('nonstop'),trace=createTrace(run);
  for(let n=0;n<50000&&run.status!=='finished';n++){
    const held=n<800?false:chooseInput(run);
    recordInput(trace,held);
    stepRun(run,held);
  }
  assert.ok(run.crashes>0);
  assert.equal(run.status,'finished');
  finishTrace(trace,run);
  return {run,trace};
}
test('trace replays a Nonstop flight across a restart',()=>{
  const {run,trace}=flightWithRestart();
  assert.deepEqual(replayTrace(trace).crashLog,run.crashLog);
});
test('trace rejects malformed, stale and inconsistent data',()=>{
  const trace=createTrace(createRun());
  for(const bad of [null,{}, {...trace,version:0},{...trace,hash:'stale'},
    {...trace,mode:'bogus'},{...trace,inputs:[1]}, {...trace,finishTicks:1,crashLog:[]}]){
    assert.throws(()=>replayTrace(bad));
  }
});
test('trace rejects coerced tier IDs and compares crash fields independently of object order',()=>{
  const {run,trace}=flightWithRestart();
  assert.throws(()=>replayTrace({...trace,tier:['casual']}));
  const reordered={...trace,crashLog:trace.crashLog.map(({where,x,y,district})=>({district,y,x,where}))};
  assert.equal(replayTrace(reordered).finishTicks,run.finishTicks);
  assert.throws(()=>replayTrace({...trace,crashLog:[{...trace.crashLog[0],x:'0'}]}));
});
