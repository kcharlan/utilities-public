const assert = require("node:assert/strict");
const { test } = require("node:test");
const { loadBackground, tick } = require("./background_harness.js");

const GEMINI = "https://gemini.google.com";
const BACKCHANNEL = "https://geminiweb-pa.clients6.google.com/v1/processSession" +
  "?VER=8&gsessionid=SYNTHETIC_GSESSION&SID=SYNTHETIC_SID&RID=rpc&TYPE=xmlhttp&t=1";

test('completion waits for restored capture in either read ordering', async () => {
  for (const localFirst of [true, false]) {
    const sessionControl = { deferRead: true }, localControl = { deferRead: true };
    const bg = loadBackground({ sessionControl, localControl, sessionStore: {
      llm_capture_v1: [{ id: 'restored', ts: 1000, url: BACKCHANNEL }]
    } });
    bg.fire('onSendHeaders', { requestId: 'restored', url: BACKCHANNEL, initiator: GEMINI,
      requestHeaders: [{ name: 'Authorization', value: 'SYNTHETIC_SECRET' }] });
    bg.fire('onCompleted', { requestId: 'restored', url: BACKCHANNEL, initiator: GEMINI, statusCode: 201, timeStamp: 1200 });
    if (localFirst) { localControl.flushRead(); await tick(); }
    sessionControl.flushRead(); sessionControl.flushRead();
    if (!localFirst) localControl.flushRead();
    localControl.flushRead();
    const [rec] = await capture(bg);
    assert.equal(rec.statusCode, 201);
    assert.equal(rec.durationMs, 200);
    assert.equal(rec.requestHeaders[0].value, 'REDACTED');
  }
});

test('failed setting read refuses capture and explicit successful set recovers', async () => {
  const bg = loadBackground({ localControl: { failRead: true, failKey: 'llm_capture_enabled_v1' } });
  fullExchange(bg);
  assert.deepEqual(await capture(bg), []);
  assert.equal((await bg.status()).capturePersistence.state, 'error');
  await bg.send({ cmd: 'set_capture', enabled: true });
  fullExchange(bg);
  assert.equal((await capture(bg)).length, 1);
});

test('reload reports a still-unread enable setting as failed', async () => {
  const localControl = { readError: 'synthetic setting read failed', failKey: 'llm_capture_enabled_v1' };
  const bg = loadBackground({ localControl });
  assert.equal((await bg.send({ cmd: 'reload_capture' })).ok, false);
  delete localControl.readError;
  assert.equal((await bg.send({ cmd: 'reload_capture' })).ok, true);
  assert.equal((await bg.status()).captureEnabled, true);
});

test('capture and debug read failures stay visible and clear intentionally recovers capture', async () => {
  for (const key of ['llm_capture_v1', 'llm_debug_v1']) {
    const sessionStore = { [key]: [{ id: 'unread', decision: 'synthetic' }] };
    const bg = loadBackground({ sessionStore, sessionControl: { failRead: true, failKey: key } });
    const status = await bg.status();
    assert.equal(status[key === 'llm_capture_v1' ? 'capturePersistence' : 'debugPersistence'].state, 'error');
    const exported = await bg.send({ cmd: 'get_capture' });
    assert.equal(exported[key === 'llm_capture_v1' ? 'capturePersistence' : 'debugPersistence'].state, 'error');
    if (key === 'llm_capture_v1') {
      assert.equal((await bg.send({ cmd: 'clear_capture' })).ok, true);
      assert.deepEqual(sessionStore[key], []);
    }
  }
});

test('failed record read stages sanitized content and reload merges the unread store', async () => {
  const sessionStore = { llm_capture_v1: [{ id: 'old', url: 'https://example.invalid/?sid=SYNTHETIC_SECRET' }] };
  const bg = loadBackground({ sessionStore, sessionControl: { failRead: true, failKey: 'llm_capture_v1' } });
  fullExchange(bg, { id: 'new' });
  assert.deepEqual((await capture(bg)).map(r => r.id), ['new']);
  assert.deepEqual(sessionStore.llm_capture_v1.map(r => r.id), ['old']);
  assert.equal((await bg.send({ cmd: 'reload_capture' })).ok, true);
  assert.deepEqual((await capture(bg)).map(r => r.id), ['old', 'new']);
  assert.ok(!JSON.stringify((await capture(bg))).includes('SYNTHETIC_SECRET'));
});

test('failed writes give clear and set commands error replies and recover on retry', async () => {
  const sessionControl = {}, localControl = {};
  const bg = loadBackground({ sessionControl, localControl });
  await bg.status();
  sessionControl.writeError = 'synthetic non-quota failure';
  sessionControl.failKey = 'llm_capture_v1';
  const reply = await bg.send({ cmd: 'clear_capture' });
  assert.equal(reply.ok, false);
  assert.match(reply.error, /non-quota/);
  assert.equal((await bg.status()).capturePersistence.state, 'error');
  delete sessionControl.writeError;
  assert.equal((await bg.send({ cmd: 'clear_capture' })).ok, true);
  localControl.failWrite = true;
  localControl.failKey = 'llm_capture_enabled_v1';
  assert.equal((await bg.send({ cmd: 'set_capture', enabled: true })).ok, false);
  assert.equal((await bg.send({ cmd: 'set_capture', enabled: false })).ok, true);
});

test('initialization staging bounds events and content before delayed reads resolve', async () => {
  const sessionControl = { deferRead: true };
  const bg = loadBackground({ sessionControl });
  for (let i = 0; i < 1300; i++) fullExchange(bg, { id: 'staged-' + i });
  sessionControl.flushRead(); sessionControl.flushRead();
  const status = await bg.status();
  assert.ok(status.captureDiagnostics.droppedEvents > 0);
  assert.equal(status.captureDiagnostics.stagedEvents, 0);
  assert.equal(status.captureDiagnostics.stagedBytes, 0);
  assert.ok((await capture(bg)).length <= 1000);
});

test('initialization staging has an aggregate byte bound below the event count limit', async () => {
  const sessionControl = { deferRead: true };
  const bg = loadBackground({ sessionControl });
  for (let i = 0; i < 100; i++) bg.fire('onBeforeRequest', {
    requestId: 'byte-staged-' + i, url: BACKCHANNEL, initiator: GEMINI, method: 'GET',
    requestBody: { formData: { prompt: ['x'.repeat(16384)], at: ['SYNTHETIC_SECRET'] } }
  });
  sessionControl.flushRead(); sessionControl.flushRead();
  const status = await bg.status();
  assert.ok(status.captureDiagnostics.droppedEvents > 0);
  const records = await capture(bg);
  assert.ok(records.length <= 64);
  assert.ok(!JSON.stringify(records).includes('SYNTHETIC_SECRET'));
});

test('omitted oversized URL retains safe request metadata', async () => {
  const bg = loadBackground();
  bg.fire('onBeforeRequest', { requestId: 'synthetic-long-url',
    url: 'https://gemini.google.com/synthetic?note=' + 'x'.repeat(9000),
    initiator: GEMINI, method: 'GET', type: 'xmlhttprequest' });
  const [record] = await capture(bg);
  assert.ok(record, 'safe metadata was lost with the oversized URL');
  assert.equal(record.host, 'gemini.google.com');
  assert.equal(record.method, 'GET');
  assert.equal(record.url, '<omitted>');
  assert.equal(record.truncated, true);
});

test('byte eviction never resurrects an old in-flight record on late completion', async () => {
  const bg = loadBackground();
  const base = { url: 'https://gemini.google.com/synthetic', initiator: GEMINI, method: 'GET' };
  for (let i = 0; i < 420; i++) {
    bg.fire('onBeforeRequest', { ...base, requestId: 'evicted-' + i,
      requestBody: { formData: { prompt: ['synthetic '.repeat(1600)] } } });
    await tick();
  }
  const before = await capture(bg);
  assert.ok(!before.some(r => r.id === 'evicted-0'));
  assert.ok(Buffer.byteLength(JSON.stringify(before)) <= 6 * 1024 * 1024);
  bg.fire('onCompleted', { ...base, requestId: 'evicted-0', statusCode: 200 });
  assert.deepEqual(await capture(bg), before);
  await bg.send({ cmd: 'set_capture', enabled: false });
  await bg.send({ cmd: 'clear_capture' });
  bg.fire('onCompleted', { ...base, requestId: 'evicted-419', statusCode: 200 });
  assert.deepEqual(await capture(bg), []);
});

function fullExchange(bg, { id = "1", url = BACKCHANNEL, initiator = GEMINI, method = "GET" } = {}) {
  const base = { requestId: id, url, initiator, tabId: 7, frameId: 0, type: "xmlhttprequest" };
  bg.fire("onBeforeRequest", { ...base, method, timeStamp: 1000 });
  bg.fire("onSendHeaders", { ...base, requestHeaders: [
    { name: "Authorization", value: "SAPISIDHASH SYNTHETIC_AUTH" },
    { name: "Content-Type", value: "text/plain" }
  ] });
  bg.fire("onCompleted", { ...base, timeStamp: 1250, statusCode: 200, statusLine: "HTTP/1.1 200",
    fromCache: false, ip: "192.0.2.1", responseHeaders: [
      { name: "X-HTTP-Session-Id", value: "SYNTHETIC_SESSION_HEADER" },
      { name: "Content-Type", value: "text/plain" }
    ] });
}

async function capture(bg) {
  await tick();
  return (await bg.send({ cmd: "get_capture" })).capture;
}

test("captures any request an LLM page makes, with headers and response status", async () => {
  const bg = loadBackground();
  fullExchange(bg);
  const [rec, ...rest] = await capture(bg);

  assert.equal(rest.length, 0);
  assert.equal(rec.method, "GET");
  assert.equal(rec.host, "geminiweb-pa.clients6.google.com");
  assert.equal(rec.url, "https://geminiweb-pa.clients6.google.com/v1/processSession" +
    "?VER=8&gsessionid=REDACTED&SID=REDACTED&RID=rpc&TYPE=xmlhttp&t=1");
  assert.equal(rec.initiator, GEMINI);
  assert.equal(rec.statusCode, 200);
  assert.equal(rec.durationMs, 250);
  assert.deepEqual(rec.requestHeaders, [
    { name: "Authorization", value: "REDACTED" }, { name: "Content-Type", value: "text/plain" }
  ]);
  assert.deepEqual(rec.responseHeaders, [
    { name: "X-HTTP-Session-Id", value: "REDACTED" }, { name: "Content-Type", value: "text/plain" }
  ]);
  assert.ok(!JSON.stringify(rec).includes("SYNTHETIC_"), "a secret value reached the capture");
});

test("captures request bodies with sensitive fields redacted", async () => {
  const bg = loadBackground();
  bg.fire("onBeforeRequest", {
    requestId: "b", method: "POST", type: "xmlhttprequest", tabId: 7, initiator: GEMINI, timeStamp: 1,
    url: "https://gemini.google.com/_/BardChatUi/data/batchexecute?rpcids=PCck7e&f.sid=SYNTHETIC_FSID",
    requestBody: { formData: { "f.req": ["[\"synthetic\"]"], at: ["SYNTHETIC_AT"] } }
  });
  const [rec] = await capture(bg);

  assert.deepEqual(rec.body, { formData: { "f.req": ["[\"synthetic\"]"], at: ["REDACTED"] } });
  assert.equal(rec.rpcids, "PCck7e");
});

test("records failures and redirects", async () => {
  const bg = loadBackground();
  const base = { url: BACKCHANNEL, initiator: GEMINI, tabId: 7, type: "xmlhttprequest" };
  bg.fire("onBeforeRequest", { ...base, requestId: "e", method: "GET", timeStamp: 1 });
  bg.fire("onErrorOccurred", { ...base, requestId: "e", timeStamp: 5, error: "net::ERR_ABORTED" });
  bg.fire("onBeforeRequest", { ...base, requestId: "r", method: "GET", timeStamp: 1 });
  bg.fire("onBeforeRedirect", { ...base, requestId: "r", statusCode: 302, redirectUrl: BACKCHANNEL });
  const [failed, redirected] = await capture(bg);

  assert.equal(failed.error, "net::ERR_ABORTED");
  assert.equal(redirected.redirects[0].statusCode, 302);
  assert.ok(!redirected.redirects[0].url.includes("SYNTHETIC"), "redirect URL not redacted");
});

test("ignores requests from pages that are not LLM sites", async () => {
  const bg = loadBackground();
  fullExchange(bg, { url: "https://mail.google.com/sync/u/0/i/s", initiator: "https://mail.google.com" });

  assert.deepEqual(await capture(bg), []);
});

test("full capture can be turned off and on, and the choice persists", async () => {
  const localStore = {};
  const bg = loadBackground({ localStore });
  assert.equal((await bg.status()).captureEnabled, true);

  await bg.send({ cmd: "set_capture", enabled: false });
  fullExchange(bg, { id: "off" });
  assert.deepEqual(await capture(bg), []);

  const restarted = loadBackground({ localStore });
  assert.equal((await restarted.status()).captureEnabled, false);
  await restarted.send({ cmd: "set_capture", enabled: true });
  fullExchange(restarted, { id: "on" });
  assert.equal((await capture(restarted)).length, 1);
});

test("clear_capture empties the capture", async () => {
  const bg = loadBackground();
  fullExchange(bg);
  await capture(bg);
  await bg.send({ cmd: "clear_capture" });

  assert.deepEqual(await capture(bg), []);
});

test("the capture survives a service-worker restart and stays out of disk storage", async () => {
  const sessionStore = {};
  const localStore = {};
  const first = loadBackground({ sessionStore, localStore });
  fullExchange(first, { id: "before" });
  await capture(first);

  const restarted = loadBackground({ sessionStore, localStore });
  fullExchange(restarted, { id: "after" });
  const ids = (await capture(restarted)).map(r => r.id);

  assert.deepEqual(ids, ["before", "after"]);
  assert.ok(!JSON.stringify(localStore).includes("processSession"), "capture written to disk storage");
});

test("status reports the capture size without sending the records", async () => {
  const bg = loadBackground();
  fullExchange(bg);
  await capture(bg);
  const status = await bg.status();

  assert.equal(status.captureCount, 1);
  assert.equal(status.capture, undefined);
});

test("the stored path is redacted like the URL", async () => {
  const bg = loadBackground();
  bg.fire("onBeforeRequest", {
    requestId: "ws", method: "GET", type: "websocket", tabId: 7, timeStamp: 1,
    initiator: "https://chatgpt.com",
    url: "wss://ws.chatgpt.com/p3/ws/user/user-SYNTHETICUSERID1234/?verify=SYNTHETIC_VERIFY"
  });
  const [rec] = await capture(bg);

  assert.equal(rec.path, "/p3/ws/user/user-REDACTED/");
  assert.ok(!JSON.stringify(rec).includes("SYNTHETIC"), "identifier reached the capture");
});

test("restored diagnostics are sanitized before publication", async () => {
  const sessionStore = {
    llm_capture_v1: [{ id: 'synthetic-restored', url: 'https://example.invalid/?sid=SYNTHETIC_SID',
      path: '/example/user-SYNTHETICUSERID1234/', body: { text: '{"at":"SYNTHETIC_AT","prompt":"synthetic prompt"}' },
      responseHeaders: [{ name: 'Content-Location', value: 'https://example.invalid/?sid=SYNTHETIC_SID' }] }, null, 'unsafe'],
    llm_debug_v1: [{ path: '/example/user-SYNTHETICUSERID1234/', decision: 'not-allowlisted' }, null]
  };
  const bg = loadBackground({ sessionStore });
  const status = await bg.status();
  const records = await capture(bg);
  await tick();
  assert.equal(records.length, 1);
  assert.equal(status.debug.length, 1);
  assert.equal(status.captureCount, 1);
  assert.equal(JSON.parse(records[0].body.text).prompt, 'synthetic prompt');
  for (const source of [records, status.debug, sessionStore, bg.consoleRecords]) {
    assert.ok(!/SYNTHETIC_(?:SID|AT)|SYNTHETICUSERID1234/.test(JSON.stringify(source)));
  }
});

test("live admission preserves sanitized long JSON prompts and rejects mixed Link containers", async () => {
  const bg = loadBackground();
  const base = { requestId: 'synthetic-long', url: 'https://chatgpt.com/synthetic', initiator: 'https://chatgpt.com' };
  bg.fire('onBeforeRequest', { ...base, method: 'POST', requestBody: { raw: [{ bytes: new TextEncoder().encode(JSON.stringify({
    sid: 'SYNTHETIC_SID', prompt: 'synthetic prompt '.repeat(1100)
  })).buffer }] } });
  bg.fire('onCompleted', { ...base, responseHeaders: [{ name: 'Link',
    value: '<https://example.invalid/>; rel="next", https://example.invalid/?sid=SYNTHETIC_SID' }] });
  const [rec] = await capture(bg);
  assert.equal(rec.body.truncated, true);
  assert.equal(rec.body.text.length, 16384);
  assert.ok(rec.body.text.startsWith('{"sid":"REDACTED","prompt":"synthetic prompt '));
  assert.equal(rec.responseHeaders[0].value, '<omitted>');
  assert.ok(!JSON.stringify(rec).includes('SYNTHETIC_SID'));
});
