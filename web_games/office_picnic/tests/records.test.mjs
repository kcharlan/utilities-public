import test from 'node:test';
import assert from 'node:assert/strict';
import {loadRecords,saveResult,savePreferences} from '../dist/game/records.js';
function storage(initial={}){const data={...initial};return {data,getItem:k=>data[k]??null,setItem:(k,v)=>data[k]=v};}
test('records migrate v4 and v5 takes precedence',()=>{
  const s=storage({'office-picnic-v4':JSON.stringify({best:{standard:320,nonstop:310},muted:true})});
  assert.deepEqual(loadRecords(s),{best:{casual:{standard:320,nonstop:310}},tier:'casual',muted:true});
  savePreferences(s,{best:{rush:{standard:200}},tier:'rush',muted:false});
  assert.deepEqual(loadRecords(s),{best:{rush:{standard:200}},tier:'rush',muted:false});
  assert.ok(s.data['office-picnic-v4']);
});
test('records validate values, tiers and storage and preserve in-session best',()=>{
  const s=storage({'office-picnic-v5':JSON.stringify({best:{rush:{standard:-1,nonstop:'fast'},bogus:{standard:1}},tier:'bogus'})});
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
test('v4 migration persists once, without overwriting v4, and survives blocked writes',()=>{
  const v4=JSON.stringify({best:{standard:321},muted:true}),s=storage({'office-picnic-v4':v4});
  const migrated=loadRecords(s);assert.deepEqual(JSON.parse(s.data['office-picnic-v5']),migrated);assert.equal(s.data['office-picnic-v4'],v4);
  const blocked={getItem:k=>k==='office-picnic-v4'?v4:null,setItem(){throw Error('blocked')}};
  assert.deepEqual(loadRecords(blocked),migrated);
});
