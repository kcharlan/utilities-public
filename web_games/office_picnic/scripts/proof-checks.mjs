import assert from 'node:assert/strict';
export function validateEncounter(e){
  assert.ok(e.passed&&Number.isFinite(e.minClearance)&&e.minClearance>0,`${e.id}: avoidance clearance`);
  assert.ok(Number.isFinite(e.warningSeconds)&&e.warningSeconds>=0,`${e.id}: missing warning timestamp`);
  assert.ok(Number.isFinite(e.arrivalSeconds)&&e.arrivalSeconds>=0,`${e.id}: missing arrival timestamp`);
  const lead=e.arrivalSeconds-e.warningSeconds;assert.ok(lead>=2,`${e.id}: late warning`);return lead;
}
