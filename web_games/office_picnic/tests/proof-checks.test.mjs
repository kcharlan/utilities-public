import test from 'node:test';import assert from 'node:assert/strict';
const checks=await import('../scripts/proof-checks.mjs').catch(()=>({}));
test('encounter proof rejects a missing warning instead of treating null as time zero',()=>{
  assert.equal(typeof checks.validateEncounter,'function');
  const encounter={id:'h',passed:true,minClearance:3,warningSeconds:10,arrivalSeconds:14};
  assert.equal(checks.validateEncounter(encounter),4);
  for(const missing of [null,undefined,NaN])assert.throws(()=>checks.validateEncounter({...encounter,warningSeconds:missing}),/warning/);
  assert.throws(()=>checks.validateEncounter({...encounter,warningSeconds:13}),/late warning/);
});
