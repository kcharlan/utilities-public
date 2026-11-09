import {pricePickup,pickupMenu,pickupCoverage,menuSampleSize} from './pickup-study.mjs';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {MEDALS} from '../dist/game/medals.js';
import {deriveMedals,evaluate,medalGates} from './medals.mjs';
import {TIERS} from '../dist/game/tiers.js';
import {buildWorld} from '../dist/game/world.js';
import {playOnce,quantile,referenceProof,shortcutOutcomes} from './flight-study.mjs';

let selected=null,n=150,diagnostic=false,check=false,json=false,menu=false,headwinds=false;
for(let i=2;i<process.argv.length;i++){
  const arg=process.argv[i];
  if(arg==='--tier'){
    selected=process.argv[++i];
    if(!selected||selected.startsWith('--')){
      console.error('Missing tier value');
      process.exit(1);
    }
  }else if(arg==='--n'){
    n=Number(process.argv[++i]);
    diagnostic=true;
  }else if(arg==='--menu')menu=true;
  else if(arg==='--headwinds')headwinds=true;
  else if(arg==='--check')check=true;
  else if(arg==='--json')json=true;
  else{
    console.error(`Unknown option: ${arg}`);
    process.exit(1);
  }
}
if((selected&&!Object.hasOwn(TIERS,selected))||!Number.isInteger(n)||n<1){
  console.error('Unknown tier or invalid sample size');
  process.exit(1);
}
if((diagnostic||menu)&&check){
  console.error('Diagnostic sample size cannot be used with --check');
  process.exit(1);
}

if(menu){
  const samples=menuSampleSize(n,diagnostic),tiers={};
  for(const [id,tier] of Object.entries(TIERS)){
    if(!selected||id===selected){
      tiers[id]=pickupMenu(tier,samples);
    }
  }
  if(json){
    console.log(JSON.stringify({samples,tiers},null,2));
  }else{
    console.dir({samples,tiers},{depth:null});
  }
  await new Promise((resolve,reject)=>process.stdout.write('',error=>error?reject(error):resolve()));
  process.exit(0);
}
const out={},gates=[];
const gate=(name,pass)=>gates.push({name,pass});
if(check){
  const course=spawnSync(process.execPath,['--test',fileURLToPath(new URL('../tests/course.test.mjs',import.meta.url))],{encoding:'utf8'});
  gate('course introduction and ablation',course.status===0);
  if(course.status!==0)console.error(course.stdout,course.stderr);
}
for(const [id,tier] of Object.entries(TIERS)){
  if(selected&&selected!==id)continue;
  const world=buildWorld(undefined,tier),row={};
  const covered=pickupCoverage(tier,world);
  gate(`${id} pickup coverage`,covered);
  if(!covered){
    out[id]={pickupCoverage:false};
    continue;
  }
  for(const profile of ['expert','regular','novice']){
    const runs=Array.from({length:n},(_,i)=>playOnce(world,profile,1000+i));
    const where={};
    for(const run of runs)for(const crash of run.log)where[crash.where]=(where[crash.where]||0)+1;
    row[profile]={
      finish:runs.filter(run=>run.finished).length/n,
      clean:runs.filter(run=>run.finished&&!run.crashes).length/n,
      crashMean:runs.reduce((sum,run)=>sum+run.crashes,0)/n,
      crashMedian:quantile(runs.map(run=>run.crashes),.5),
      worstSpot:Math.max(0,...Object.values(where))/n,
      medianSeconds:quantile(runs.filter(run=>run.finished).map(run=>run.seconds),.5)
    };
  }
  row.nonstop={};
  for(const profile of ['expert','regular']){
    const count=diagnostic?n:100;
    const runs=Array.from({length:count},(_,i)=>playOnce(world,profile,90000+i,{mode:'nonstop',capSeconds:2700,extra:{pickups:()=>true}}));
    const finished=runs.filter(run=>run.finished);
    row.nonstop[profile]={
      finish:finished.length/count,
      meanAttempts:finished.reduce((sum,run)=>sum+run.attempts,0)/Math.max(1,finished.length)
    };
  }
  row.pickups=world.pickups.map(pk=>pricePickup(world,pk,diagnostic?n:100));
  for(let i=0;i<row.pickups.length;i++)gate(`${id} pickup ${i+1}`,row.pickups[i].qualifies&&row.pickups[i].reward*60===world.pickups[i].rewardTicks);
  const table=MEDALS[id];
  const derived=deriveMedals(tier,table.derived.quantiles);
  row.medals={table,holdout:evaluate(world,table)};
  gate(`${id} medal derivation`,JSON.stringify(derived)===JSON.stringify(table));
  for(const [name,pass] of Object.entries(medalGates(id,row.medals.holdout)))gate(`${id} medal ${name}`,pass);
  row.medals.reference={};
  for(const mode of ['standard','nonstop']){
    const run=playOnce(world,'ideal',1,{mode,capSeconds:mode==='nonstop'?2700:1200,extra:{pickups:()=>true}});
    row.medals.reference[mode]=run;
    gate(`${id} ${mode} reference gold`,run.finished&&run.crashes===0&&run.net<=table.gold);
  }
  if(headwinds&&tier.winds.length){
    const count=100,baseline=deriveMedals(tier,table.derived.quantiles,count);
    const baselineRates=evaluate(world,baseline,count);
    row.headwinds={baseline:{table:baseline,rates:baselineRates,verdicts:medalGates(id,baselineRates)}};
    for(const wind of id==='rush'?[0,-5]:[-3,-7]){
      const variant={...tier,winds:tier.winds.map(zone=>({...zone,wind}))};
      const variantWorld=buildWorld(undefined,variant);
      const fresh=deriveMedals(variant,table.derived.quantiles,count);
      const staleRates=evaluate(variantWorld,baseline,count),freshRates=evaluate(variantWorld,fresh,count);
      row.headwinds[wind]={
        stale:{table:baseline,rates:staleRates,verdicts:medalGates(id,staleRates)},
        fresh:{table:fresh,rates:freshRates,verdicts:medalGates(id,freshRates)}
      };
    }
  }
  row.reference=referenceProof(world);
  row.shortcuts=shortcutOutcomes(world);
  out[id]=row;
  gate(`${id} reference`,Object.values(row.reference.full).every(run=>run.finished&&!run.crashes)&&!row.reference.failures.length);
  gate(`${id} shortcuts`,Object.values(row.shortcuts).every(value=>value===0));
  gate(`${id} worst spot`,row.regular.worstSpot<=.45);
  gate(`${id} expert nonstop`,row.nonstop.expert.finish>=.9);
  if(id==='casual'){
    gate('casual expert clean',row.expert.clean>=.95);
    gate('casual regular clean',row.regular.clean>=.55);
    gate('casual novice finish',row.novice.finish>=.95);
    gate('casual regular nonstop',row.nonstop.regular.finish>=.9);
  }else if(id==='rush'){
    gate('rush expert clean',row.expert.clean>=.8&&row.expert.clean<=.97);
    gate('rush regular finish',row.regular.finish>=.98);
    gate('rush regular clean',row.regular.clean>=.25&&row.regular.clean<=.55);
    gate('rush regular crashes',row.regular.crashMean>=.7&&row.regular.crashMean<=1.6);
    gate('rush novice finish',row.novice.finish>=.95);
    gate('rush regular nonstop',row.nonstop.regular.finish>=.9);
  }else if(id==='overtime'){
    gate('overtime expert finish',row.expert.finish===1);
    gate('overtime expert clean',row.expert.clean>=.6&&row.expert.clean<=.9);
    gate('overtime regular finish',row.regular.finish>=.95);
    gate('overtime regular crashes',row.regular.crashMean>=1.8&&row.regular.crashMean<=4);
    gate('overtime novice finish',row.novice.finish>=.8);
    gate('overtime regular nonstop',row.nonstop.regular.finish>=.5);
  }
}
if(!selected){
  const rows=Object.entries(out);
  for(let i=1;i<rows.length;i++)for(const [profile,metric] of [['expert','crashMean'],['regular','crashMean'],['novice','crashMedian']]){
    gate(`${rows[i-1][0]} to ${rows[i][0]} ${profile} crashes rise`,rows[i][1][profile]?.[metric]>rows[i-1][1][profile]?.[metric]);
  }
}
if(json)console.log(JSON.stringify({tiers:out,gates},null,2));
else{
  console.dir(out,{depth:null});
  if(check)for(const result of gates)console.log(`${result.pass?'PASS':'FAIL'} ${result.name}`);
}
if(check&&gates.some(result=>!result.pass))process.exitCode=1;
