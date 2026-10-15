const assert = require('node:assert/strict');
const { test } = require('node:test');
const vm = require('node:vm');
const { readFileSync } = require('node:fs');
const clone = x => JSON.parse(JSON.stringify(x));
const tick = () => new Promise(r => setImmediate(r));
function fixture(store = {}) {
  const timers = new Map(), requests = [], observedIds = new Set(), acceptedIds = new Set(), clearedIds = new Set();
  const idsByBatch = new Map(), submittedIds = new Set(), applications = new Map();
  let next = 0, failWrite = false, failRead = false, last = 0;
  const runtime = {};
  const storage = {
    get(keys, cb) { if (failRead) runtime.lastError = {message:'synthetic read failure'}; cb(clone(store)); delete runtime.lastError; },
    set(obj, cb) { if (failWrite) { failWrite = false; runtime.lastError = {message:'synthetic write failure'}; } else Object.assign(store, clone(obj)); cb(); delete runtime.lastError; }
  };
  const context = vm.createContext({ crypto, AbortController, chrome: {runtime}, setTimeout, clearTimeout });
  vm.runInContext(readFileSync(require.resolve('./delivery.js'), 'utf8'), context);
  function worker() { return context.LLMDelivery.createDelivery({storage, collectorUrl:'https://synthetic.invalid', apiKey:'SYNTHETIC_KEY', now: () => 100,
    setTimer(fn, ms) { const id = ++next; timers.set(id, {fn,ms}); return id; }, clearTimer(id) { timers.delete(id); },
    fetchImpl(url, init) { return new Promise((resolve, reject) => {
      if (init.body) for (const id of Object.keys(JSON.parse(init.body).deltas)) submittedIds.add(id);
      requests.push({url, init, resolve, reject}); init.signal.addEventListener('abort', () => reject(new Error('timeout')));
    }); }
  }); }
  function state() { return store.llm_delivery_v2; }
  // Each invented hostname labels one fixture observation; IDs never extend
  // the wire schema. Count aggregation is separately exercised in background.
  async function observe(d, host) { assert.ok(!observedIds.has(host)); await d.increment(host); observedIds.add(host); }
  function sets() {
    const s = state();
    return {queued: new Set(Object.keys(s.queued)), flight: new Set(Object.keys(s.inFlight?.deltas || {}))};
  }
  function oracle(settled = false) {
    const {queued,flight} = sets();
    assert.deepEqual(new Set([...acceptedIds,...queued,...flight,...clearedIds]), observedIds);
    assertAcceptedAtMostOncePerObservation();
    assertQueuedAndInFlightAreDisjoint(queued, flight);
    assertClearedIdsWereNeverSubmitted();
    if (settled) { assert.equal(queued.size + flight.size, 0); assert.deepEqual(acceptedIds, new Set([...observedIds].filter(id => !clearedIds.has(id)))); }
  }
  function assertAcceptedAtMostOncePerObservation() {
    for (const count of applications.values()) assert.equal(count, 1);
  }
  function assertQueuedAndInFlightAreDisjoint(queued, flight) {
    for (const id of queued) assert.ok(!flight.has(id));
  }
  function assertClearedIdsWereNeverSubmitted() {
    for (const id of clearedIds) assert.ok(!submittedIds.has(id));
  }
  function accept(req, lose = false) {
    const batch = JSON.parse(req.init.body), key = batch.seq;
    const ids = Object.keys(batch.deltas);
    let applied = 0;
    if (key > last) {
      assert.equal(key, last + 1, 'synthetic collector rejects sequence gaps');
      for (const id of ids) { applications.set(id, (applications.get(id) || 0) + 1); acceptedIds.add(id); }
      idsByBatch.set(key, ids); last = key; applied = Object.values(batch.deltas).reduce((a,b) => a+b,0);
    } else assert.deepEqual(ids, idsByBatch.get(key));
    if (lose) req.reject(new Error('synthetic lost acknowledgement'));
    else req.resolve({ok:true,status:200,json:async () => ({ok:true,last_seq:last,applied})});
  }
  function baseline(req, seq) {
    last = seq;
    req.resolve({ok:true,status:200,json:async()=>({client_id:'SYNTHETIC_CLIENT',last_seq:seq})});
  }
  return {worker,store,state,requests,timers,observe,oracle,accept,baseline,clearedIds,failWrite(){failWrite=true;},failRead(){failRead=true;}};
}

test('uncertain submission survives new observations and worker restart', async () => {
  const f=fixture(), d=f.worker(); assert.equal((await d.ready).ok,true);
  await f.observe(d,'synthetic-a.invalid'); const push=d.push(); await tick();
  const original=f.requests[0].init.body; f.accept(f.requests[0],true); await push;
  await f.observe(d,'synthetic-b.invalid'); f.oracle();
  const restarted=f.worker(); await restarted.ready; const retry=restarted.push(); await tick();
  assert.equal(f.requests[1].init.body, original); f.accept(f.requests[1]); await tick();
  f.oracle(); f.accept(f.requests[2]); await retry; f.oracle(true);
});
test('offline legacy reconciliation survives worker restart', async () => {
  const f=fixture({llm_client_id_v1:'SYNTHETIC_CLIENT',llm_seq_v1:9,llm_pending_v1:{}}), d=f.worker(); await d.ready;
  const first=d.push(); await tick(); f.requests[0].reject(new Error('offline')); await first;
  await f.observe(d,'synthetic-a.invalid'); assert.equal(f.state().baseline.state,'unresolved');
  const r=f.worker(); await r.ready; const p=r.push(); await tick();
  assert.match(f.requests[1].url,/client_status/); assert.equal(f.state().inFlight,null);
  f.baseline(f.requests[1],12); await tick();
  assert.equal(f.state().baseline.state,'ready'); assert.equal(JSON.parse(f.requests[2].init.body).seq,13);
  f.accept(f.requests[2]); await p; f.oracle(true);
  assert.equal(f.store.llm_seq_v1,9);
  assert.deepEqual(clone((await r.status()).pending),{});
});
test('failed writes do not publish delivery transitions', async () => {
  const f=fixture(),d=f.worker(); await d.ready; await f.observe(d,'synthetic-a.invalid');
  f.failWrite(); await d.push(); assert.equal(f.requests.length,0); f.oracle();
  const p=d.push(); await tick(); f.failWrite(); f.accept(f.requests[0]); await p;
  assert.equal(f.state().lastAckSeq,0); f.oracle();
  const r=d.push(); await tick(); assert.equal(f.requests[1].init.body,f.requests[0].init.body); f.accept(f.requests[1]); await r; f.oracle(true);
});
test('clear affects only queued observations', async () => {
  const f=fixture(),d=f.worker(); await d.ready; await f.observe(d,'synthetic-a.invalid'); const p=d.push(); await tick();
  await f.observe(d,'synthetic-b.invalid'); const result=await d.clearQueued(); f.clearedIds.add('synthetic-b.invalid');
  assert.equal(result.cleared,1); assert.equal(result.inFlight,1); f.oracle();
  await f.observe(d,'synthetic-c.invalid'); f.accept(f.requests[0]); await tick(); f.accept(f.requests[1]); await p; f.oracle(true);
});
test('invalid replies preserve delivery state', async () => {
  for (const reply of [null, {ok:false,last_seq:1,applied:1},{ok:true,last_seq:2,applied:1},{ok:true,last_seq:1,applied:2},'malformed',403,409,503,'timeout']) {
    const f=fixture(),d=f.worker(); await d.ready; await f.observe(d,'synthetic-a.invalid'); const p=d.push(); await tick();
    if (reply==='timeout') [...f.timers.values()].find(t=>t.ms===5000).fn();
    else f.requests[0].resolve({ok:typeof reply!=='number',status:typeof reply==='number'?reply:200,json:async()=>{if(reply==='malformed') throw new Error('bad json'); return reply;}});
    assert.equal((await p).ok,false); assert.ok((await d.status()).deliveryError); f.oracle(); assert.equal(f.state().lastAckSeq,0);
  }
});
test('failed reads leave unavailable counts and reject mutations',async()=>{
  const f=fixture(); f.failRead(); const d=f.worker(); assert.equal((await d.ready).ok,false);
  await assert.rejects(d.increment('synthetic.invalid')); await assert.rejects(d.clearQueued());
  assert.equal((await d.status()).available,false); assert.equal((await d.status()).pending,null);
});
test('accounting rejects unsafe integer transitions without signed 32-bit truncation',async()=>{
  const f=fixture(),d=f.worker(); await d.ready; await d.increment('synthetic.invalid',2**31+1);
  assert.equal((await d.status()).pending['synthetic.invalid'],2147483649);
  await assert.rejects(d.increment('synthetic.invalid',Number.MAX_SAFE_INTEGER));
  await assert.rejects(d.increment('synthetic.invalid',1.5));
});

test('concurrent push calls join immutable drain with disjoint observation identities',async()=>{
  const f=fixture(),d=f.worker(); await d.ready;
  await f.observe(d,'synthetic-a.invalid'); const p=d.push(); await tick();
  await f.observe(d,'synthetic-b.invalid'); const join=d.push(); assert.equal(join,p); f.oracle();
  f.accept(f.requests[0]); await tick(); f.oracle();
  assert.deepEqual(JSON.parse(f.requests[1].init.body).deltas,{'synthetic-b.invalid':1});
  f.accept(f.requests[1]); await p; f.oracle(true);
});
test('retry delays back off while force push expedites an uncertain batch',async()=>{
  const f=fixture(),d=f.worker(); await d.ready; await f.observe(d,'synthetic-a.invalid');
  let p=d.push(); await tick(); let body=f.requests[0].init.body;
  for(const delay of [1000,2000,4000,8000,16000,30000,30000]) {
    f.requests.at(-1).reject(new Error('offline')); await p;
    const [id,timer]=[...f.timers].find(([,t])=>t.ms!==5000); assert.equal(timer.ms,delay);
    f.timers.delete(id); timer.fn(); await tick();
    assert.equal(f.requests.at(-1).init.body,body); p=d.push();
  }
  f.requests.at(-1).reject(new Error('offline')); await p;
  const forced=d.push(); await tick(); assert.equal([...f.timers.values()].filter(t=>t.ms!==5000).length,0);
  f.accept(f.requests.at(-1)); await forced; f.oracle(true);
});
test('failed and invalid baseline probes cannot create a batch',async()=>{
  for(const reply of [null,{client_id:'WRONG',last_seq:2},{client_id:'SYNTHETIC_CLIENT',last_seq:-1},{client_id:'SYNTHETIC_CLIENT',last_seq:1.5},{client_id:'SYNTHETIC_CLIENT',last_seq:Number.MAX_SAFE_INTEGER+1}]) {
    const f=fixture({llm_client_id_v1:'SYNTHETIC_CLIENT',llm_seq_v1:3,llm_pending_v1:{}}),d=f.worker(); await d.ready;
    await f.observe(d,'synthetic-a.invalid'); const p=d.push(); await tick();
    f.requests[0].resolve({ok:true,status:200,json:async()=>reply}); assert.equal((await p).ok,false);
    assert.equal(f.state().baseline.state,'unresolved'); assert.equal(f.state().inFlight,null); f.oracle();
  }
});
test('unsafe sequence and aggregate transitions preserve committed state',async()=>{
  const record={version:2,clientId:'SYNTHETIC_CLIENT',lastAckSeq:Number.MAX_SAFE_INTEGER,baseline:{state:'ready'},queued:{},inFlight:null};
  const f=fixture({llm_delivery_v2:record}),d=f.worker(); await d.ready; await d.increment('synthetic-a.invalid');
  assert.equal((await d.push()).ok,false); assert.equal(f.requests.length,0); assert.equal(f.state().inFlight,null);
  const g=fixture(),e=g.worker(); await e.ready; await e.increment('synthetic-a.invalid',Number.MAX_SAFE_INTEGER);
  await assert.rejects(e.increment('synthetic-b.invalid')); assert.deepEqual(Object.keys(g.state().queued),['synthetic-a.invalid']);
});
