import test from 'node:test';
import assert from 'node:assert/strict';
import {createRun,stepRun} from '../dist/game/simulation.js';
import {sensible,REFERENCE} from '../dist/game/bot.js';
import {createTrace,recordInput,finishTrace,replayTrace} from '../dist/game/trace.js';

function flightWithRestart(){
  const run=createRun('nonstop'),trace=createTrace(run);
  for(let n=0;n<50000&&run.status!=='finished';n++){
    const held=n<800?false:sensible(run,{...REFERENCE,pickups:()=>true});
    recordInput(trace,held);
    stepRun(run,held);
  }
  assert.ok(run.crashes>0);
  assert.ok(run.bonusTicks>0);
  assert.equal(run.status,'finished');
  finishTrace(trace,run);
  return {run,trace};
}
test('trace replays a Nonstop flight across a restart',()=>{
  const {run,trace}=flightWithRestart();
  assert.deepEqual(replayTrace(trace).crashLog,run.crashLog);
  assert.equal(trace.finishNetTicks,trace.finishTicks-run.bonusTicks);
  assert.notEqual(trace.finishNetTicks,trace.finishTicks);
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
test('trace verifies net time separately from raw finish ticks',()=>{
  const {trace}=flightWithRestart();
  assert.equal(replayTrace(trace).ticks-replayTrace(trace).bonusTicks,trace.finishNetTicks);
  assert.throws(()=>replayTrace({...trace,finishNetTicks:trace.finishNetTicks+1}),/does not match/);
  assert.throws(()=>replayTrace({...trace,finishNetTicks:trace.finishTicks}),/does not match/);
});
test('Standard trace replays a rooftop respawn',()=>{
  const run=createRun('standard'),trace=createTrace(run);let forced=false,respawnCheckpoint=0;
  for(let n=0;n<50000&&run.status!=='finished';n++){
    const held=run.checkpoint.x>0&&!forced?false:sensible(run,{...REFERENCE,pickups:()=>true});
    recordInput(trace,held);stepRun(run,held);
    if(run.crashes>0&&!forced){forced=true;respawnCheckpoint=run.checkpoint.x;}
  }
  assert.ok(run.crashes>0);assert.ok(respawnCheckpoint>0);assert.equal(run.status,'finished');
  finishTrace(trace,run);assert.deepEqual(replayTrace(trace).crashLog,run.crashLog);
});
