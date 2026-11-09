import test from 'node:test';import assert from 'node:assert/strict';
import {makePilot,PROFILES} from '../scripts/pilot.mjs';
import {createRun} from '../dist/game/simulation.js';
test('a crash refreshes a pilot observation even at the same hazard',()=>{
  const run=createRun(),observations=[];
  const pilot=makePilot(PROFILES.regular,101,{policy:(r,p)=>{observations.push(p.biasFor(r));return false;}});
  pilot(run);pilot(run);assert.equal(observations[0],observations[1]);
  run.crashes=1;run.crashLog.push({district:0,where:'h0-over'});run.status='respawning';pilot(run);
  run.status='flying';pilot(run);assert.notEqual(observations[2],observations[1]);
});
