import test from 'node:test';
import assert from 'node:assert/strict';
import {MEDALS,medalFor} from '../dist/game/medals.js';
import {TIERS,tierHash} from '../dist/game/tiers.js';

test('tables match tiers, floors and medal boundaries',()=>{
  for(const [id,tier] of Object.entries(TIERS)){
    const m=MEDALS[id];
    assert.equal(m.configHash,tierHash(tier));
    assert.ok(m.gold<m.silver&&m.silver<m.bronze);
    assert.ok(m.gold>=Math.ceil(m.derived.idealNet*1.02));
    assert.equal(medalFor(id,m.gold),'gold');
    assert.equal(medalFor(id,m.gold+.001),'silver');
    assert.equal(medalFor(id,m.silver),'silver');
    assert.equal(medalFor(id,m.silver+.001),'bronze');
    assert.equal(medalFor(id,m.bronze),'bronze');
    assert.equal(medalFor(id,m.bronze+.001),null);
    assert.equal(medalFor(id,undefined),null);
  }
});

test('generator rejects invalid overrides before writing the table',async()=>{
  const {spawnSync}=await import('node:child_process');
  const {readFileSync}=await import('node:fs');
  const path=new URL('../dist/game/medals.js',import.meta.url);
  const before=readFileSync(path,'utf8');
  for(const args of [['--gold-quantile','0.4'],['--tier','rush','--gold-quantile','1.2'],['--tier','rush','--silver-quantile','NaN'],['--tier','rush','--bronze-quantile',''],['--tier','missing'],['--tier']]){
    const run=spawnSync(process.execPath,['scripts/medals.mjs',...args],{cwd:new URL('..',import.meta.url)});
    assert.notEqual(run.status,0,args.join(' '));
    assert.equal(readFileSync(path,'utf8'),before);
  }
});

test('medal lookup rejects coerced and inherited tier names',()=>{
  assert.equal(medalFor(['casual'],300),null);
  assert.equal(medalFor('constructor',300),null);
});

test('derivation rejects an empty finished sample rather than generating null thresholds',async()=>{
  const {deriveMedals}=await import('../scripts/medals.mjs');
  assert.throws(()=>deriveMedals(TIERS.casual,undefined,0),/No finished medal derivation samples/);
});
