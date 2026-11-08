import test from 'node:test';import assert from 'node:assert/strict';import {execFile} from 'node:child_process';import {promisify} from 'node:util';import {readFile} from 'node:fs/promises';
test('CLI measurement and collision-enabled proof verify the shipped world',async()=>{
  const exec=promisify(execFile),cwd=new URL('../',import.meta.url);
  await exec(process.execPath,['scripts/measure.mjs'],{cwd});await exec(process.execPath,['scripts/prove.mjs'],{cwd});
  const report=JSON.parse(await readFile(new URL('../reports/route-proof.json',import.meta.url)));
  assert.equal(report.summary.districtTrials,135);assert.equal(report.gaps.length,25);
  assert.ok(report.runs.every(r=>r.crashes===0&&r.seconds>=240&&r.seconds<=480));
  assert.ok(report.gaps.every(g=>g.actualBotEntry&&g.actualEntryUtilization<=1));
  assert.ok(report.gaps.filter(g=>g.receiverRoofStart!==null).every(g=>g.actualBotReceiver.clearance>0&&g.realGeometryMinSampledRoofClearance>0));
  assert.equal(report.encounters.length,10);assert.ok(report.encounters.every(e=>e.passed&&e.minClearance>0&&e.warningLeadSeconds>=2));
  assert.ok(report.summary.firstEncounterSeconds<20);
});
