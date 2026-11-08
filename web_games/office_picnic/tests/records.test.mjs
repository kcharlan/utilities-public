import test from 'node:test';
import assert from 'node:assert/strict';
const records=await import('../dist/game/records.js').catch(()=>({}));
test('records keep fastest completed result separately by mode',()=>{
  assert.equal(typeof records.saveResult,'function');
  let data=null;const s={getItem:()=>data,setItem:(_,v)=>data=v};
  records.saveResult(s,'standard',320);records.saveResult(s,'standard',340);records.saveResult(s,'nonstop',310);
  assert.deepEqual(records.loadRecords(s).best,{standard:320,nonstop:310});
});
test('corrupt, nonfinite, unknown modes and blocked storage cannot break play or create records',()=>{
  assert.equal(typeof records.loadRecords,'function');
  const bad={getItem:()=>'{oops',setItem:()=>{throw Error('blocked')}};
  assert.deepEqual(records.loadRecords(bad).best,{});
  assert.doesNotThrow(()=>records.saveResult(bad,'standard',300));
  let data='{"best":{"standard":-1,"nonstop":"fast"}}';const s={getItem:()=>data,setItem:(_,v)=>data=v};
  records.saveResult(s,'cheat',1);records.saveResult(s,'standard',NaN);
  assert.deepEqual(records.loadRecords(s).best,{});
});
test('unavailable storage retains the in-session best across slower replays',()=>{
  const first=records.saveResult(null,'standard',300);
  const second=records.saveResult(null,'standard',340,first);
  assert.equal(second.best.standard,300);
});
