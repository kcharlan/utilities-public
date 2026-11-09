import test from 'node:test';
import assert from 'node:assert/strict';
import {loadRecords,saveResult,savePreferences,finishResult} from '../dist/game/records.js';
function storage(initial={}){const data={...initial};return {data,getItem:k=>data[k]??null,setItem:(k,v)=>data[k]=v};}
test('records migrate preferences from v5 and v6 takes precedence',()=>{
  const s=storage({'office-picnic-v5':JSON.stringify({best:{casual:{standard:320}},tier:'rush',muted:true})});
  assert.deepEqual(loadRecords(s),{best:{},tier:'rush',muted:true});
  savePreferences(s,{best:{rush:{standard:200}},tier:'rush',muted:false},{tier:'rush',muted:false});
  assert.deepEqual(loadRecords(s),{best:{rush:{standard:200}},tier:'rush',muted:false});
  assert.ok(s.data['office-picnic-v5']);
});
test('records validate values, tiers and storage and preserve in-session best',()=>{
  const s=storage({'office-picnic-v6':JSON.stringify({best:{rush:{standard:-1,nonstop:'fast'},bogus:{standard:1}},tier:'bogus'})});
  assert.deepEqual(loadRecords(s),{best:{},tier:'casual',muted:false});
  let r=saveResult(null,'rush','standard',300);
  r=saveResult(null,'rush','standard',340,r);
  r=saveResult(null,'casual','nonstop',310,r);
  assert.deepEqual(r.best,{rush:{standard:300},casual:{nonstop:310}});
  assert.deepEqual(saveResult(null,'bogus','standard',1,r).best,r.best);
  assert.doesNotThrow(()=>saveResult({getItem(){throw Error()},setItem(){throw Error()}},'rush','standard',300));
});
test('array tier IDs cannot select a registered tier through coercion',()=>{
  const s=storage({'office-picnic-v5':JSON.stringify({tier:['rush']})});
  assert.equal(loadRecords(s).tier,'casual');
  assert.deepEqual(saveResult(null,['rush'],'standard',1).best,{});
  assert.equal(finishResult(null,['rush'],'standard',1,{best:{rush:{standard:200}}}).previous,undefined);
});
test('persisted results keep fastest time separately by tier and mode',()=>{
  const s=storage();saveResult(s,'casual','standard',320);saveResult(s,'casual','standard',340);saveResult(s,'casual','nonstop',310);saveResult(s,'rush','standard',330);
  assert.deepEqual(loadRecords(s).best,{casual:{standard:320,nonstop:310},rush:{standard:330}});
});
test('corrupt storage, unknown modes and nonfinite results do not create records',()=>{
  const bad={getItem:()=>'{oops',setItem:()=>{throw Error('blocked')}};
  assert.deepEqual(loadRecords(bad).best,{});assert.doesNotThrow(()=>saveResult(bad,'casual','standard',300));
  const s=storage();saveResult(s,'casual','cheat',1);saveResult(s,'casual','standard',NaN);assert.deepEqual(loadRecords(s).best,{});
});
test('v5 migration persists once, without overwriting v5, and survives blocked writes',()=>{
  const v5=JSON.stringify({best:{casual:{standard:321}},tier:'overtime',muted:true}),s=storage({'office-picnic-v5':v5});
  const migrated=loadRecords(s);assert.deepEqual(JSON.parse(s.data['office-picnic-v6']),migrated);assert.equal(s.data['office-picnic-v5'],v5);
  const blocked={getItem:k=>k==='office-picnic-v5'?v5:null,setItem(){throw Error('blocked')}};
  assert.deepEqual(loadRecords(blocked),migrated);
});
test('v4 alone is ignored and an existing v6 record wins over v5',()=>{
  const s=storage({'office-picnic-v4':JSON.stringify({best:{standard:123},muted:true})});
  assert.deepEqual(loadRecords(s),{best:{},tier:'casual',muted:false});
  s.data['office-picnic-v5']=JSON.stringify({tier:'rush',muted:true});
  s.data['office-picnic-v6']=JSON.stringify({tier:'overtime',best:{overtime:{standard:456}}});
  assert.deepEqual(loadRecords(s),{best:{overtime:{standard:456}},tier:'overtime',muted:false});
});
test('Overtime selection and records round trip separately by mode',()=>{
  const s=storage();
  savePreferences(s,{best:{},tier:'overtime',muted:false},{tier:'overtime'});
  saveResult(s,'overtime','standard',400);
  saveResult(s,'overtime','nonstop',390);
  const r=loadRecords(s);
  assert.equal(r.tier,'overtime');
  assert.deepEqual(r.best.overtime,{standard:400,nonstop:390});
});
test('stale tabs merge bests and change only the intended preference',()=>{
  const s=storage();let a=loadRecords(s),b=loadRecords(s);
  b=saveResult(s,'casual','standard',200,b);
  a=savePreferences(s,a,{tier:'rush'});
  assert.equal(loadRecords(s).best.casual.standard,200);
  b=savePreferences(s,b,{muted:true});
  assert.equal(loadRecords(s).tier,'rush');
  const finished=finishResult(s,'casual','standard',250,b);
  assert.equal(finished.previous,200);
  assert.equal(finished.records.tier,'casual');
  assert.equal(finished.records.muted,true);
  assert.deepEqual(loadRecords(s),{best:{casual:{standard:200}},tier:'rush',muted:true});
  a=savePreferences(s,a,{muted:false});
  assert.equal(loadRecords(s).tier,'rush');
  assert.equal(loadRecords(s).best.casual.standard,200);
  a=saveResult(s,'rush','nonstop',190,a);
  b=savePreferences(s,b,{tier:'overtime'});
  assert.equal(loadRecords(s).best.rush.nonstop,190);
  assert.equal(loadRecords(s).muted,false);
  const fasterSession=finishResult(s,'rush','nonstop',210,{...b,best:{rush:{nonstop:180}}});
  assert.equal(fasterSession.previous,180);
  assert.equal(loadRecords(s).best.rush.nonstop,180);
  assert.equal(loadRecords(s).tier,'overtime');
});
test('unavailable storage keeps session bests and local preferences',()=>{
  const s={getItem(){throw Error('blocked')},setItem(){throw Error('blocked')}};
  let r=loadRecords(s);r=savePreferences(s,r,{tier:'rush'});r=savePreferences(s,r,{muted:true});
  r=saveResult(s,'rush','standard',220,r);
  const finished=finishResult(s,'rush','standard',240,r);
  assert.equal(finished.previous,220);
  assert.deepEqual(finished.records,{best:{rush:{standard:220}},tier:'rush',muted:true});
});
