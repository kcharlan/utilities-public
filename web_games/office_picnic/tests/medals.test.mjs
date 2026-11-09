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

test('generator imports read-only and preserves per-tier overrides in a private copy',async t=>{
  const {spawnSync}=await import('node:child_process');
  const {cpSync,mkdirSync,mkdtempSync,readFileSync,rmSync,statSync,writeFileSync}=await import('node:fs');
  const {tmpdir}=await import('node:os');
  const {join}=await import('node:path');
  const root=mkdtempSync(join(tmpdir(),'office-medals-test-'));
  t.after(()=>rmSync(root,{recursive:true}));
  mkdirSync(join(root,'dist'));
  mkdirSync(join(root,'scripts'));
  cpSync(new URL('../dist/game',import.meta.url),join(root,'dist/game'),{recursive:true});
  for(const name of ['medals.mjs','flight-study.mjs','pilot.mjs']){
    cpSync(new URL(`../scripts/${name}`,import.meta.url),join(root,'scripts',name));
  }
  writeFileSync(join(root,'package.json'),JSON.stringify({type:'module'}));
  const path=join(root,'dist/game/medals.js');
  const before=readFileSync(path,'utf8');
  const beforeStat=statSync(path,{bigint:true});
  const run=args=>spawnSync(process.execPath,args,{cwd:root,encoding:'utf8'});
  const imported=run(['--input-type=module','-e',"import './scripts/medals.mjs'"]);
  assert.equal(imported.status,0,imported.stderr);
  assert.equal(readFileSync(path,'utf8'),before);
  assert.equal(statSync(path,{bigint:true}).mtimeNs,beforeStat.mtimeNs);
  for(const args of [['--gold-quantile','0.4'],['--tier','rush','--gold-quantile','1.2'],['--tier','rush','--silver-quantile','NaN'],['--tier','rush','--bronze-quantile',''],['--tier','missing'],['--tier']]){
    const invalid=run(['scripts/medals.mjs',...args]);
    assert.notEqual(invalid.status,0,args.join(' '));
    assert.equal(readFileSync(path,'utf8'),before);
  }
  for(const args of [['--tier','casual','--gold-quantile','0.45'],['--tier','casual']]){
    const generated=run(['scripts/medals.mjs',...args]);
    assert.equal(generated.status,0,generated.stderr);
  }
  const result=run(['--input-type=module','-e',
    "import {MEDALS} from './dist/game/medals.js'; console.log(JSON.stringify(MEDALS))"]);
  assert.equal(result.status,0,result.stderr);
  const tables=JSON.parse(result.stdout);
  assert.deepEqual(tables.casual.derived.quantiles,{...MEDALS.casual.derived.quantiles,gold:.45});
  assert.deepEqual(tables.rush,MEDALS.rush);
});

test('medal lookup rejects coerced and inherited tier names',()=>{
  assert.equal(medalFor(['casual'],300),null);
  assert.equal(medalFor('constructor',300),null);
});

test('derivation rejects an empty finished sample rather than generating null thresholds',async()=>{
  const {deriveMedals}=await import('../scripts/medals.mjs');
  assert.throws(()=>deriveMedals(TIERS.casual,undefined,0),/No finished medal derivation samples/);
});

test('title grades both modes from saved v5 tier records',async()=>{
  const {loadRecords,titleBestText}=await import('../dist/game/records.js');
  const {formatTime}=await import('../dist/game/session.js');
  const saved={best:{casual:{standard:MEDALS.casual.gold},rush:{standard:MEDALS.rush.bronze+1,nonstop:MEDALS.rush.silver}},tier:'rush'};
  const storage={getItem:key=>key==='office-picnic-v5'?JSON.stringify(saved):null};
  const records=loadRecords(storage);
  assert.equal(titleBestText(records,'casual'),`Standard: ${formatTime(MEDALS.casual.gold)} · gold / Nonstop: —`);
  assert.equal(titleBestText(records,'rush'),`Standard: ${formatTime(MEDALS.rush.bronze+1)} · no medal / Nonstop: ${formatTime(MEDALS.rush.silver)} · silver`);
});
