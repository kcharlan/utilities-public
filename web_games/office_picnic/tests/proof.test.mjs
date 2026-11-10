import test from 'node:test';import assert from 'node:assert/strict';import {execFile} from 'node:child_process';import {promisify} from 'node:util';import {readFile,mkdtemp,rm} from 'node:fs/promises';import {tmpdir} from 'node:os';import {join} from 'node:path';
import {DISTRICT_SPEEDS,DISTRICT_OFFSETS,DISTRICT_DELAYS,GAP_SPEEDS,GAP_OFFSETS} from '../scripts/proof-checks.mjs';
import {TIERS} from '../dist/game/tiers.js';import {buildWorld} from '../dist/game/world.js';
test('CLI measurement and collision-enabled proof verify every available tier',async()=>{
  const exec=promisify(execFile),cwd=new URL('../',import.meta.url);
  const out=await mkdtemp(join(tmpdir(),'office-proof-'));
  try {
  await exec(process.execPath,['scripts/measure.mjs','--out',out],{cwd});await exec(process.execPath,['scripts/prove.mjs','--out',out],{cwd});
  const reports=JSON.parse(await readFile(join(out,'route-proof.json')));
  for(const [id,tier] of Object.entries(TIERS)){
    const world=buildWorld(undefined,tier),report=reports[id];
    assert.equal(report.checkpointTrials.length,world.checkpoints.length*8);
    const finalTrials=report.checkpointTrials.filter(t=>t.checkpoint===world.checkpoints.at(-1).id);
    assert.equal(finalTrials.length,8);assert.ok(finalTrials.every(t=>t.status==='finished'));
    assert.equal(report.summary.districtTrials,world.districts.length*DISTRICT_SPEEDS.length*DISTRICT_OFFSETS.length*DISTRICT_DELAYS.length);assert.equal(report.gaps.length,world.gaps.length);
    assert.ok(report.runs.every(r=>r.crashes===0&&r.seconds<=900&&(id!=='casual'||r.seconds>=240&&r.seconds<=480)));
    assert.ok(report.gaps.every(g=>g.actualBotEntry&&g.actualEntryUtilization<=1));
    for(const g of report.gaps){
      const source=world.gaps.find(gap=>gap.id===g.id);assert.ok(source,g.id);
      const occupied=id!=='casual'&&world.hazards.some(h=>h.x>=source.x&&h.x<=source.end);
      if(id==='casual')assert.ok(!Object.hasOwn(g,'releaseOnlySkipped'),g.id);
      else {assert.equal(g.releaseOnlySkipped,occupied,g.id);assert.equal(g.releaseOnlySamples,occupied?0:GAP_SPEEDS.length*GAP_OFFSETS.length,g.id);}
      const receiver=world.buildings.find(b=>Math.abs(b.x-(source.end-10))<.01);
      assert.equal(g.receiverRoofStart,receiver?.x??null,g.id);
      if(receiver){assert.ok(g.actualBotReceiver?.clearance>0,g.id);if(!occupied)assert.ok(g.realGeometryMinSampledRoofClearance>0,g.id);}
      if(occupied)assert.equal(g.realGeometryMinSampledRoofClearance,null);
    }
    assert.equal(report.encounters.length,world.hazards.length);assert.ok(report.encounters.every(e=>e.passed&&e.minClearance>0&&e.warningLeadSeconds>=2));
    if(id==='casual')assert.ok(report.summary.firstEncounterSeconds<20);
  }
  } finally {await rm(out,{recursive:true,force:true});}
});
