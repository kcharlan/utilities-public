const assert = require("node:assert/strict");
const { test } = require("node:test");
const { loadBackground, tick } = require("./background_harness.js");

const GEMINI = "https://gemini.google.com";
const BACKCHANNEL = "https://geminiweb-pa.clients6.google.com/v1/processSession" +
  "?VER=8&gsessionid=SYNTHETIC_GSESSION&SID=SYNTHETIC_SID&RID=rpc&TYPE=xmlhttp&t=1";

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
