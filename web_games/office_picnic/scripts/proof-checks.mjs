import assert from 'node:assert/strict';
export const DISTRICT_SPEEDS=[22,26,30],DISTRICT_OFFSETS=[-6,0,6],DISTRICT_DELAYS=[0,3,6];
export const GAP_SPEEDS=[18,22,26],GAP_OFFSETS=[-2,0,2];
export function validateEncounter(e){
  assert.ok(e.passed&&Number.isFinite(e.minClearance)&&e.minClearance>0,`${e.id}: avoidance clearance`);
  assert.ok(Number.isFinite(e.warningSeconds)&&e.warningSeconds>=0,`${e.id}: missing warning timestamp`);
  assert.ok(Number.isFinite(e.arrivalSeconds)&&e.arrivalSeconds>=0,`${e.id}: missing arrival timestamp`);
  const lead=e.arrivalSeconds-e.warningSeconds;assert.ok(lead>=2,`${e.id}: late warning`);return lead;
}
