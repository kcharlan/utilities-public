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
  const context = vm.createContext({ crypto, URL, TextEncoder, AbortController, chrome: {runtime}, setTimeout, clearTimeout });
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
  return {worker,store,state,requests,timers,observe,oracle,accept,baseline,clearedIds,observedIds,failWrite(){failWrite=true;},failRead(){failRead=true;}};
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

const channelMessage = (id,isPrompt=true) => ({id,isPrompt});
const channelRecord = (history={}) => ({version:2,clientId:'SYNTHETIC_CLIENT',lastAckSeq:0,baseline:{state:'ready'},queued:{},inFlight:null,channelIdentitySalt:'SYNTHETIC_SALT',channelHistory:history});
test('channel replay accounting atomically tracks non-prompts and queued observations',async()=>{
  const f=fixture(),d=f.worker(); await d.ready;
  assert.equal(typeof d.recordChannelMessages,'function');
  const key='SYNTHETIC_CHANNEL';
  const record=messages=>d.recordChannelMessages({channelKey:key,host:'synthetic-a.invalid',messages});
  assert.equal(await record([channelMessage(0,false),channelMessage(1)]),1);
  // A setup previously observed cannot become a new prompt through replay.
  assert.equal(await record([channelMessage(0),channelMessage(1),channelMessage(3)]),1);
  assert.equal(await record([channelMessage(2,false)]),0);
  assert.deepEqual(f.state().channelHistory[key],[[0,3]]);
  assert.equal(f.state().queued['synthetic-a.invalid'],2);
  // Oracle gives each logical prompt its own host identity so set conservation
  // remains valid through collector receipts, without adding IDs to the wire.
  const g=fixture(),e=g.worker(); await e.ready;
  for(const [id,host] of [[1,'synthetic-a.invalid'],[3,'synthetic-b.invalid']]) {
    await e.recordChannelMessages({channelKey:key,host,messages:[channelMessage(id)]});
    g.observedIds.add(host); g.oracle();
  }
  const p=e.push(); await tick(); g.accept(g.requests[0],true); await p; g.oracle();
  const restarted=g.worker(); await restarted.ready;
  assert.equal(await restarted.recordChannelMessages({channelKey:key,host:'synthetic-a.invalid',messages:[channelMessage(1)]}),0);
  g.oracle();
  const retry=restarted.push(); await tick();
  assert.equal(g.requests[1].init.body,g.requests[0].init.body);
  g.accept(g.requests[1]); await retry; g.oracle(true);
  // Clearing queued counts is an explicit discard, never identity eviction.
  await restarted.recordChannelMessages({channelKey:key,host:'synthetic-c.invalid',messages:[channelMessage(5)]});
  g.observedIds.add('synthetic-c.invalid'); await restarted.clearQueued();
  g.clearedIds.add('synthetic-c.invalid'); g.oracle(true);
  assert.equal(await restarted.recordChannelMessages({channelKey:key,host:'synthetic-c.invalid',messages:[channelMessage(5)]}),0);
  g.oracle(true);
  assert.deepEqual(JSON.parse(g.requests[0].init.body).deltas,{'synthetic-a.invalid':1,'synthetic-b.invalid':1});
});

test('failed channel accounting leaves history and counts retryable',async()=>{
  const f=fixture(),d=f.worker(); await d.ready;
  assert.equal(typeof d.recordChannelMessages,'function');
  const before=clone(f.state()); f.failWrite();
  const event={channelKey:'SYNTHETIC_CHANNEL',host:'synthetic-a.invalid',messages:[channelMessage(1)]};
  await assert.rejects(d.recordChannelMessages(event),/write failure/);
  assert.deepEqual(f.state(),before); assert.deepEqual(clone((await d.status()).pending),{});
  f.oracle();
  assert.equal(await d.recordChannelMessages(event),1);
  f.observedIds.add('synthetic-a.invalid'); f.oracle();
  assert.equal(await d.recordChannelMessages(event),0);
  f.oracle();
  assert.equal(f.state().queued['synthetic-a.invalid'],1);
  assert.match((await d.status()).deliveryError,/recording.*write failure/i);
});

test('known channel replays do not require a new persistence write',async()=>{
  const f=fixture(),d=f.worker(); await d.ready;
  const event={channelKey:'SYNTHETIC_CHANNEL',host:'synthetic.invalid',messages:[channelMessage(1)]};
  await d.recordChannelMessages(event); const before=clone(f.state()); f.failWrite();
  assert.equal(await d.recordChannelMessages(event),0);
  assert.deepEqual(f.state(),before);
  // The refused write is still armed: replay performed no storage operation.
  await assert.rejects(d.increment('synthetic-new.invalid'),/write failure/);
});

test('channel salt and endpoint identity persist across workers without raw SID',async()=>{
  const f=fixture(),d=f.worker(); await d.ready;
  assert.equal(typeof d.channelKey,'function');
  const endpoint='https://synthetic.invalid/v1/processSession?RID=2&t=1';
  const key=await d.channelKey(endpoint,'SYNTHETIC_SID');
  const expected=Buffer.from(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify([f.state().channelIdentitySalt,'https://synthetic.invalid','/v1/processSession','SYNTHETIC_SID'])))).toString('hex');
  assert.equal(key,expected); assert.match(key,/^[a-f0-9]{64}$/);
  const r=f.worker(); await r.ready;
  assert.equal(await r.channelKey(endpoint,'SYNTHETIC_SID'),key);
  assert.notEqual(await r.channelKey(endpoint,'SYNTHETIC_REPLACEMENT'),key);
  assert.notEqual(await r.channelKey('https://synthetic.invalid/v2/processSession','SYNTHETIC_SID'),key);
  assert.notEqual(await r.channelKey('https://other-synthetic.invalid/v1/processSession','SYNTHETIC_SID'),key);
  assert.ok(!JSON.stringify(f.store).includes('SYNTHETIC_SID'));
});

for(const bound of ['channels','per-channel intervals','total intervals','bytes']) {
  test(`history ${bound} bound refuses new identities and preserves replays`,async()=>{
    const history={}; let key='SYNTHETIC_CHANNEL',id=2;
    if(bound==='channels') for(let i=0;i<4096;i++) history[`SYNTHETIC_${i}`]=[[0,0]];
    if(bound==='per-channel intervals') history[key]=Array.from({length:128},(_,i)=>[i*2,i*2]);
    if(bound==='total intervals') for(let c=0;c<128;c++) history[`SYNTHETIC_${c}`]=Array.from({length:128},(_,i)=>[i*2,i*2]);
    if(bound==='bytes') key='SYNTHETIC_'.repeat(110000);
    const f=fixture({llm_delivery_v2:channelRecord(history)}),d=f.worker(); await d.ready;
    assert.equal(typeof d.recordChannelMessages,'function');
    if(bound==='per-channel intervals') id=256;
    const before=clone(f.state());
    await assert.rejects(d.recordChannelMessages({channelKey:key,host:'synthetic.invalid',messages:[channelMessage(id)]}),/channel-history-full/);
    assert.deepEqual(f.state(),before);
    assert.match((await d.status()).deliveryError,/channel-history-full/);
    if(bound!=='bytes') {
      const existing=Object.keys(history)[0];
      assert.equal(await d.recordChannelMessages({channelKey:existing,host:'synthetic.invalid',messages:[channelMessage(0)]}),0);
      assert.deepEqual(f.state(),before);
    }
    if(bound==='per-channel intervals') {
      // Filling a hole compacts intervals and admits future identities.
      await d.recordChannelMessages({channelKey:key,host:'synthetic.invalid',messages:[channelMessage(1,false)]});
      assert.equal(f.state().channelHistory[key].length,127);
      await d.recordChannelMessages({channelKey:key,host:'synthetic.invalid',messages:[channelMessage(256)]});
      assert.equal(f.state().channelHistory[key].length,128);
    }
  });
}
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

for (const phase of ['acknowledgement', 'baseline']) {
  for (const failure of ['timeout', 'network', 'malformed']) {
    test(`${phase} body ${failure} preserves state and classifies retry`, async () => {
      const legacy = phase === 'baseline';
      const f = fixture(legacy ? {llm_client_id_v1:'SYNTHETIC_CLIENT',llm_seq_v1:0,llm_pending_v1:{}} : {});
      const d = f.worker();
      await d.ready;
      await f.observe(d, 'synthetic-body.invalid');
      const push = d.push();
      await tick();
      const original = clone(f.state());
      const request = f.requests[0];
      let rejectBody;
      request.resolve({ok:true,status:200,json:() => new Promise((resolve,reject) => { rejectBody = reject; })});
      await tick(); // Headers have arrived, but body consumption has not finished.
      if (failure === 'timeout') {
        request.init.signal.addEventListener('abort', () => rejectBody(Object.assign(new Error('synthetic abort'), {name:'AbortError'})));
        [...f.timers.values()].find(t => t.ms === 5000).fn();
      } else rejectBody(failure === 'network' ? new TypeError('synthetic body transport failure') : new SyntaxError('synthetic invalid JSON'));
      const result = await push;
      assert.equal(result.ok, false);
      assert.deepEqual(f.state(), original);
      f.oracle();
      const retry = [...f.timers].find(([,timer]) => timer.ms === 1000);
      assert.equal(!!retry, failure !== 'malformed', 'only timeout/transport errors schedule retries');
      if (failure === 'malformed') assert.match(result.error, /Invalid collector JSON/);
      else {
        assert.match(result.error, failure === 'timeout' ? /timed out/ : /network failure/);
        const [id,timer] = retry;
        f.timers.delete(id); timer.fn(); await tick();
        const settled = d.push();
        if (legacy) { f.baseline(f.requests[1], 0); await tick(); f.accept(f.requests[2]); }
        else {
          assert.equal(f.requests[1].init.body, request.init.body);
          f.accept(f.requests[1]);
        }
        await settled; f.oracle(true);
      }
    });
  }
}

test('recording failure remains visible after empty and unrelated successful drains', async () => {
  const f = fixture(), d = f.worker(); await d.ready;
  f.failWrite(); await assert.rejects(d.increment('synthetic-rejected.invalid'), /write failure/);
  await d.push();
  assert.match((await d.status()).deliveryError, /recording.*write failure/i);
  await f.observe(d, 'synthetic-accepted.invalid'); const push = d.push(); await tick();
  f.accept(f.requests[0]); await push; f.oracle(true);
  assert.match((await d.status()).deliveryError, /recording.*write failure/i);
});
