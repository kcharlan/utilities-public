const assert = require("node:assert/strict");
const { test } = require("node:test");
const { loadBackground, tick, encodeChannelMessages } = require("./background_harness.js");

const CHANNEL = "https://geminiweb-pa.clients6.google.com/v1/processSession";
const b64 = bytes => Buffer.from(bytes).toString("base64");
const PROMPT = b64([0x12, 0x0a, 0x08, 0x01, 0x4a, 0x06, 0x0a, 0x04, ...Buffer.from("SYNTHETIC_PROMPT")]);
const SETUP = b64([0x0a, 0x03, 0x01, 0x02, 0x03]);
const END = "IgIIAQ==";

let nextId = 0;
function post(bg, url, requestBody, tabId = 7) {
  bg.fire("onBeforeRequest", {
    requestId: String(++nextId), method: "POST", type: "xmlhttprequest", tabId,
    initiator: "https://gemini.google.com", url, requestBody
  });
}
const channelBody = (data, id=0) => ({ formData: { count: ["1"], ofs: [String(id)], req0___data__: [data] } });

// Synthetic turns follow WireV8: map IDs advance across setup/prompt/end,
// while RID identifies requests and does not identify transport messages.
function geminiTurn(bg, rid) {
  post(bg, `${CHANNEL}?VER=8&RID=${rid}&CVER=22&t=1`, { formData: { count: ["1"] } });
  post(bg, `${CHANNEL}?VER=8&SID=SYNTHETIC_SID&RID=${rid + 1}&AID=0&t=1`, channelBody(SETUP,rid));
  post(bg, `${CHANNEL}?VER=8&SID=SYNTHETIC_SID&RID=${rid + 2}&AID=2&t=1`, channelBody(PROMPT,rid+1));
  post(bg, `${CHANNEL}?VER=8&SID=SYNTHETIC_SID&RID=${rid + 3}&AID=30&t=1`, channelBody(END,rid+2));
  post(bg, `${CHANNEL}?VER=8&SID=SYNTHETIC_SID&RID=${rid + 4}&TYPE=terminate&t=1`, undefined);
}

async function pending(bg) {
  await tick();
  return (await bg.status()).pending;
}

test("counts one Gemini prompt per WebChannel turn, credited to gemini.google.com", async () => {
  const bg = loadBackground({ config: true });
  geminiTurn(bg, 100);

  assert.deepEqual(await pending(bg), { "gemini.google.com": 1 });
});

test("counts each of two turns sent in quick succession", async () => {
  const bg = loadBackground({ config: true });
  geminiTurn(bg, 100);
  geminiTurn(bg, 200);

  assert.deepEqual(await pending(bg), { "gemini.google.com": 2 });
});

test("logs channel posts with their message fields but never their content", async () => {
  const bg = loadBackground({ config: true });
  geminiTurn(bg, 100);
  const { debug } = await bg.status();
  const decisions = debug.map(d => `${d.decision}:${d.reason}`);

  assert.deepEqual(decisions, [
    "not-prompt:channel fields=none",
    "not-prompt:channel fields=none",
    "not-prompt:channel fields=1",
    // Setup and end identities now also commit, preserving their order around
    // the counted prompt. Empty handshake/termination diagnostics run first.
    "counted:channel fields=2; credited to gemini.google.com",
    "not-prompt:channel fields=4"
  ]);
  assert.ok(!JSON.stringify(debug).includes("SYNTHETIC_PROMPT"), "prompt content reached the debug log");
});

test('counted diagnostic waits for the observation storage callback', async () => {
  const localControl = {};
  const bg = loadBackground({config:true,localControl});
  await bg.status();
  localControl.deferWrite = true;
  post(bg,'https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate');
  await tick();
  assert.ok(!JSON.stringify(bg.consoleRecords).includes('counted'));
  localControl.deferWrite = false; localControl.flushWrite(); await tick();
  assert.deepEqual((await bg.status()).debug.map(record => record.decision), ['counted']);
  bg.dispose();
});

test("still counts the StreamGenerate endpoint", async () => {
  const bg = loadBackground({ config: true });
  post(bg, "https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate?bl=x");

  assert.deepEqual(await pending(bg), { "gemini.google.com": 1 });
});

test("overlapping pushes deliver distinct immutable batches", async () => {
  const requests = [];
  let accepted = 0, last = 0;
  const bg = loadBackground({ config: true, fetchImpl: async (url, init) => {
    if (!url.endsWith('/add')) return { ok: true, json: async () => ({ client_id: 'synthetic-client', last_seq: 0, counters: {} }) };
    const batch = JSON.parse(init.body);
    return new Promise(resolve => requests.push({ batch, finish() {
      const applied = batch.seq > last ? Object.values(batch.deltas).reduce((a,b) => a+b, 0) : 0;
      accepted += applied; last = Math.max(last, batch.seq);
      resolve({ ok: true, status: 200, json: async () => ({ ok: true, last_seq: last, applied }) });
    } }));
  } });
  post(bg, `${CHANNEL}?SID=SYNTHETIC_SID`, channelBody(PROMPT,1));
  await tick();
  await bg.send({ cmd: 'force_push' });
  await new Promise(r => setTimeout(r, 280));
  post(bg, `${CHANNEL}?SID=SYNTHETIC_SID`, channelBody(PROMPT,2));
  await tick();
  await bg.send({ cmd: 'force_push' });
  await new Promise(r => setTimeout(r, 280));
  requests[0].finish();
  await tick();
  for (const request of requests.slice(1)) request.finish();
  await tick();
  assert.equal(accepted, 2, 'two observations must reach collector');
  assert.deepEqual((await bg.status()).pending, {});
  assert.deepEqual(requests.map(r => [r.batch.seq, r.batch.deltas['gemini.google.com']]), [[1,1],[2,1]]);
});

test('initialization persists migration before observations and exposes callback failures',async()=>{
  const localStore={llm_client_id_v1:'SYNTHETIC_CLIENT',llm_seq_v1:5,llm_pending_v1:{}};
  const localControl={deferWrite:true};
  const bg=loadBackground({config:true,localStore,localControl});
  post(bg,`${CHANNEL}?SID=SYNTHETIC_SID`,channelBody(PROMPT)); await tick();
  assert.equal(localStore.llm_delivery_v2,undefined);
  localControl.deferWrite=false; localControl.flushWrite(); await tick();
  assert.equal(localStore.llm_delivery_v2.baseline.state,'unresolved');
  assert.deepEqual((await bg.status()).pending,{'gemini.google.com':1});
  localControl.failWrite=true;
  const clear=await bg.send({cmd:'clear_pending'});
  assert.equal(clear.ok,false); assert.match(clear.error,/write failure/);
  assert.deepEqual((await bg.status()).pending,{'gemini.google.com':1}); bg.dispose();
  const unavailable=loadBackground({config:true,localControl:{failRead:true,failKey:"llm_delivery_v2"}});
  assert.equal((await unavailable.status()).available,false);
  assert.equal((await unavailable.send({cmd:'force_push'})).ok,false); unavailable.dispose();
});

test('ordinary worker initialization and wake request the guarded drain',async()=>{
  const calls=[]; const timers=[];
  const bg=loadBackground({config:true,localStore:{llm_delivery_v2:{version:2,clientId:'SYNTHETIC_CLIENT',lastAckSeq:0,baseline:{state:'ready'},queued:{'synthetic.invalid':1},inFlight:null}},
    setTimer(fn,ms){const timer={fn,ms};timers.push(timer);return timer;},clearTimer(timer){timer.cancelled=true;},
    fetchImpl:async(url,init)=>{calls.push({url,init});return {ok:true,status:200,json:async()=>({ok:true,last_seq:1,applied:1})};}});
  await tick(); timers.find(t=>t.ms===250&&!t.cancelled).fn(); await tick();
  assert.equal(calls.length,1); assert.deepEqual((await bg.status()).pending,{});
  bg.wake(); await tick(); assert.ok(timers.filter(t=>t.ms===250).length>=2); bg.dispose();
});

for (const kind of ['regular', 'Gemini channel']) {
  test(`${kind} rejected observation stays visible after empty bootstrap drain`, async () => {
    const timers = [], localStore = {}, sessionStore = {}, localControl = {};
    const bg = loadBackground({config:true,localStore,sessionStore,localControl,
      setTimer(fn,ms) { const timer={fn,ms}; timers.push(timer); return timer; },
      clearTimer(timer) { timer.cancelled=true; }});
    await bg.status(); await tick();
    localControl.failWrite = true;
    if (kind === 'regular') post(bg,'https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate');
    else post(bg,`${CHANNEL}?SID=SYNTHETIC_SID`,channelBody(PROMPT));
    await tick();
    timers.find(timer => timer.ms === 250 && !timer.cancelled).fn(); await tick();
    const status = await bg.status();
    assert.deepEqual(status.pending, {});
    assert.match(status.deliveryError || '', /recording.*write failure/i);
    assert.deepEqual(status.debug.map(record => record.decision), ['recording-failed']);
    bg.dispose();
    const restarted = loadBackground({config:true,localStore,sessionStore});
    assert.deepEqual((await restarted.status()).debug.map(record => record.decision), ['recording-failed']);
    restarted.dispose();
  });
}

test('channel retry counts only unseen message IDs including the audit replay',async()=>{
  const localStore={},bg=loadBackground({config:true,localStore});
  for(const t of [1,2]) post(bg,`${CHANNEL}?SID=SYNTHETIC_SID&RID=7&t=${t}`,channelBody('EgA='));
  assert.deepEqual(await pending(bg),{'gemini.google.com':1});
  // Reordered retry: ofs=0, req0 is old, req2 is new, req1 is setup.
  post(bg,`${CHANNEL}?SID=SYNTHETIC_SID&RID=8`,encodeChannelMessages([{id:2,data:PROMPT},{id:0,data:'EgA='},{id:1,data:SETUP}]));
  assert.deepEqual(await pending(bg),{'gemini.google.com':2});
  const serialized=JSON.stringify(localStore.llm_delivery_v2);
  assert.ok(!serialized.includes('SYNTHETIC_SID')); assert.ok(!serialized.includes(PROMPT));
  const debug=JSON.stringify((await bg.status()).debug);
  assert.ok(!debug.includes('SYNTHETIC_SID')); assert.ok(!debug.includes(PROMPT)); bg.dispose();
});

test('channel identity survives lifecycle with session storage discarded and tabs changed',async()=>{
  const localStore={}; let bg=loadBackground({config:true,localStore});
  post(bg,`${CHANNEL}?SID=SYNTHETIC_SID`,channelBody(PROMPT),7);
  assert.deepEqual(await pending(bg),{'gemini.google.com':1}); bg.dispose();
  for(const boundary of ['installed','installed','startup']) {
    // Reload/update and browser restart lose all worker/session memory.
    bg=loadBackground({config:true,localStore,sessionStore:{}}); bg.wake(boundary);
    post(bg,`${CHANNEL}?SID=SYNTHETIC_SID&t=2`,channelBody(PROMPT),99);
    assert.deepEqual(await pending(bg),{'gemini.google.com':1}); bg.dispose();
  }
  bg=loadBackground({config:true,localStore});
  post(bg,`${CHANNEL}?SID=SYNTHETIC_NEW_SESSION`,channelBody(PROMPT),99);
  assert.deepEqual(await pending(bg),{'gemini.google.com':2}); bg.dispose();
});

test('invalid channel identity reports channel-invalid and never counts',async()=>{
  const bg=loadBackground({config:true});
  post(bg,`${CHANNEL}?SID=SYNTHETIC_SID`,{formData:{ofs:['-1'],req0___data__:[PROMPT]}});
  post(bg,CHANNEL,channelBody(PROMPT));
  assert.deepEqual(await pending(bg),{});
  assert.deepEqual((await bg.status()).debug.map(x=>x.decision),['channel-invalid','channel-invalid']); bg.dispose();
});
