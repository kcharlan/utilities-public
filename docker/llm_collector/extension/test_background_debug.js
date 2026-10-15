const assert = require("node:assert/strict");
const { test } = require("node:test");
const { loadBackground, tick } = require("./background_harness.js");

const PROCESS_SESSION =
  "https://geminiweb-pa.clients6.google.com/v1/processSession?VER=8&SID=SYNTHETIC_SID&RID=1&AID=0&t=1";

test("logs a Gemini processSession POST without a prompt message, uncounted", async () => {
  const bg = loadBackground();
  assert.ok(bg.filterMatches(PROCESS_SESSION), "processSession host is not observed");

  bg.request(PROCESS_SESSION);
  const status = await bg.status();

  assert.deepEqual(
    status.debug.map(({ decision, host, path }) => ({ decision, host, path })),
    [{ decision: "not-prompt", host: "geminiweb-pa.clients6.google.com", path: "/v1/processSession" }]
  );
  assert.deepEqual(status.pending, {});
  assert.ok(!JSON.stringify(status.debug).includes("SYNTHETIC_SID"), "session id leaked into debug");
});

test("keeps the latest 200 debug records", async () => {
  const bg = loadBackground();
  for (let i = 0; i < 205; i++) {
    bg.request(`https://gemini.google.com/_/BardChatUi/data/batchexecute?rpcids=Id${i}`);
  }
  const { debug } = await bg.status();

  assert.equal(debug.length, 200);
  assert.equal(debug[0].rpcids, "Id5");
  assert.equal(debug[199].rpcids, "Id204");
});

test("debug records survive a service-worker restart", async () => {
  const sessionStore = {};
  const localStore = {};
  const first = loadBackground({ sessionStore, localStore });
  first.request(PROCESS_SESSION);
  await first.status();
  await tick();

  const restarted = loadBackground({ sessionStore, localStore });
  restarted.request(`https://gemini.google.com/_/BardChatUi/data/batchexecute?rpcids=AfterRestart`);
  const { debug } = await restarted.status();

  assert.deepEqual(debug.map(d => d.path), ["/v1/processSession", "/_/BardChatUi/data/batchexecute"]);
  assert.ok(!JSON.stringify(localStore).includes("processSession"), "debug log written to persistent local storage");
});

test("debug paths are sanitized before storage and console with capture on or off", async () => {
  for (const enabled of [true, false]) {
    const sessionStore = {};
    const bg = loadBackground({ sessionStore });
    await bg.send({ cmd: 'set_capture', enabled });
    bg.request('https://chatgpt.com/example/user-SYNTHETICUSERID1234/');
    const status = await bg.status();
    await tick();
    assert.equal(status.debug[0].path, '/example/user-REDACTED/');
    for (const source of [sessionStore, bg.consoleRecords]) assert.ok(!JSON.stringify(source).includes('SYNTHETICUSERID1234'));
  }
});

test('expanded paths are omitted in live and restored debug admission', async () => {
  const path = '/' + 'Bearer+a;'.repeat(900);
  const sessionStore = { llm_debug_v1: [{ path, decision: 'synthetic-restored' }] };
  const bg = loadBackground({ sessionStore });
  bg.request('https://chatgpt.com' + path);
  const { debug } = await bg.status();
  await tick();
  assert.equal(debug.length, 2);
  assert.deepEqual(debug.map(rec => rec.path), ['<omitted>', '<omitted>']);
  assert.deepEqual(sessionStore.llm_debug_v1.map(rec => rec.path), ['<omitted>', '<omitted>']);
  const live = bg.consoleRecords.flat().find(rec => rec && rec.decision === 'not-allowlisted');
  assert.ok(live);
  assert.equal(live.path, '<omitted>');
});
