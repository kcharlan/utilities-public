import test from 'node:test';import assert from 'node:assert/strict';import {execFile} from 'node:child_process';import {promisify} from 'node:util';import {readFile} from 'node:fs/promises';
import {TIERS} from '../dist/game/tiers.js';import {buildWorld} from '../dist/game/world.js';
test('CLI measurement and collision-enabled proof verify every available tier',async()=>{
  const exec=promisify(execFile),cwd=new URL('../',import.meta.url);
  await exec(process.execPath,['scripts/measure.mjs'],{cwd});await exec(process.execPath,['scripts/prove.mjs'],{cwd});
  const reports=JSON.parse(await readFile(new URL('../reports/route-proof.json',import.meta.url)));
  for(const [id,tier] of Object.entries(TIERS)){
    const world=buildWorld(undefined,tier),report=reports[id];
    assert.equal(report.summary.districtTrials,world.districts.length*27);assert.equal(report.gaps.length,world.gaps.length);
    assert.ok(report.runs.every(r=>r.crashes===0&&r.seconds<=900&&(id!=='casual'||r.seconds>=240&&r.seconds<=480)));
    assert.ok(report.gaps.every(g=>g.actualBotEntry&&g.actualEntryUtilization<=1));
    for(const g of report.gaps){
      const occupied=id!=='casual'&&world.hazards.some(h=>h.x>=g.x&&h.x<=g.end);
      assert.equal(g.releaseOnlySkipped,occupied,g.id);
      if(g.receiverRoofStart!==null){assert.ok(g.actualBotReceiver.clearance>0,g.id);if(!occupied)assert.ok(g.realGeometryMinSampledRoofClearance>0,g.id);}
      if(occupied)assert.equal(g.realGeometryMinSampledRoofClearance,null);
    }
    assert.equal(report.encounters.length,world.hazards.length);assert.ok(report.encounters.every(e=>e.passed&&e.minClearance>0&&e.warningLeadSeconds>=2));
    if(id==='casual')assert.ok(report.summary.firstEncounterSeconds<20);
  }
});
