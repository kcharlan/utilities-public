const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { test } = require("node:test");
const vm = require("node:vm");

function loadPopupStatusRenderer(background = null) {
  const callbacks = {};
  const blobs = [];
  const elements = {
    status: { dataset: {} },
    statusLabel: { textContent: "" },
    statusDetail: { textContent: "" },
    captureToggle: { textContent: "", dataset: {} },
    persistenceStatus: { textContent: '', dataset: {} }
  };
  if (background) {
    for (const id of ['export', 'notice', 'reset', 'forcePush', 'clearCapture']) elements[id] = { dataset: {}, addEventListener(event, fn) { callbacks[id + ':' + event] = fn; } };
    elements.captureToggle.addEventListener = (event, fn) => { callbacks['captureToggle:' + event] = fn; };
  }
  const document = {
    addEventListener(event, fn) { callbacks[event] = fn; },
    createElement() { return { click() {} }; },
    body: { appendChild() {}, removeChild() {} },
    getElementById(id) {
      return elements[id] || null;
    }
  };
  const context = vm.createContext({
    Blob,
    URL: { createObjectURL(blob) { blobs.push(blob); return 'blob:synthetic'; }, revokeObjectURL() {} },
    chrome: { runtime: { sendMessage(msg, cb) { background.send(msg).then(cb); } } },
    clearInterval,
    clearTimeout,
    console,
    document,
    setInterval() { return 1; },
    setTimeout,
    window: { addEventListener() {} }
  });
  vm.runInContext(readFileSync(require.resolve("./popup.js"), "utf8"), context);
  return { context, elements, callbacks, blobs };
}

test("renders a successful authenticated probe as connected", () => {
  const { context, elements } = loadPopupStatusRenderer();

  context.renderConnectionStatus({
    state: "connected",
    checkedAt: Date.now(),
    latencyMs: 24
  });

  assert.equal(elements.status.dataset.state, "connected");
  assert.equal(elements.statusLabel.textContent, "Collector connected");
  assert.match(elements.statusDetail.textContent, /24 ms/);
});

test('debug persistence error remains visible in popup and export', async () => {
  const { loadBackground, tick } = require('./background_harness.js');
  const bg = loadBackground({ sessionControl: { failRead: true, failKey: 'llm_debug_v1' } });
  const popup = loadPopupStatusRenderer(bg);
  popup.callbacks.DOMContentLoaded();
  await tick();
  assert.match(popup.elements.persistenceStatus.textContent, /debug.*error/i);
  assert.match(popup.elements.persistenceStatus.textContent, /synthetic read failure/);
  await popup.callbacks['export:click']();
  const exported = JSON.parse(await popup.blobs[0].text());
  assert.equal(exported.debugPersistence.state, 'error');
  assert.ok(exported.capturePersistence);
});

test('failed capture clear and setting writes cannot show success', async () => {
  const popup = loadPopupStatusRenderer({ send: async () => ({ ok: false, error: 'synthetic capture failure' }) });
  popup.callbacks.DOMContentLoaded();
  await popup.callbacks['clearCapture:click']();
  assert.match(popup.elements.notice.textContent, /Clear capture failed: synthetic capture failure/);
  await popup.callbacks['captureToggle:click']();
  assert.match(popup.elements.notice.textContent, /Capture toggle failed: synthetic capture failure/);
});

test("renders authentication and network failures as errors", () => {
  const { context, elements } = loadPopupStatusRenderer();

  context.renderConnectionStatus({ state: "authentication_error", httpStatus: 403 });
  assert.equal(elements.status.dataset.state, "error");
  assert.equal(elements.statusLabel.textContent, "Authentication failed");
  assert.match(elements.statusDetail.textContent, /HTTP 403/);

  context.renderConnectionStatus({ state: "unreachable", message: "Could not reach the collector." });
  assert.equal(elements.status.dataset.state, "error");
  assert.equal(elements.statusLabel.textContent, "Collector unreachable");
});

test("renders configuration and checking states without relying on color", () => {
  const { context, elements } = loadPopupStatusRenderer();

  context.renderConnectionStatus(
    { state: "configuration_error" },
    "Synthetic configuration is missing."
  );
  assert.equal(elements.status.dataset.state, "error");
  assert.equal(elements.statusLabel.textContent, "Configuration required");
  assert.equal(elements.statusDetail.textContent, "Synthetic configuration is missing.");

  context.showCheckingStatus();
  assert.equal(elements.status.dataset.state, "checking");
  assert.equal(elements.statusLabel.textContent, "Checking…");
});

test("shows whether full capture is on and how much it holds", () => {
  const { context, elements } = loadPopupStatusRenderer();

  context.renderCaptureState({ captureEnabled: true, captureCount: 42 });
  assert.equal(elements.captureToggle.textContent, "Capture: On (42)");
  assert.equal(elements.captureToggle.dataset.enabled, "true");

  context.renderCaptureState({ captureEnabled: false, captureCount: 0 });
  assert.equal(elements.captureToggle.textContent, "Capture: Off (0)");
  assert.equal(elements.captureToggle.dataset.enabled, "false");
});

test("export removes credentials from capture and debug", async () => {
  const { loadBackground, tick } = require('./background_harness.js');
  const bg = loadBackground();
  const popup = loadPopupStatusRenderer(bg);
  popup.callbacks.DOMContentLoaded();
  await tick();
  for (const enabled of [true, false]) {
    await bg.send({ cmd: 'set_capture', enabled });
    const url = 'https://chatgpt.com/example/user-SYNTHETICUSERID1234/?data=%7B%22token%22%3A%22SYNTHETIC_TOKEN%22%7D&note=Bearer%20SYNTHETIC%2FSECRET&%24httpHeaders=X-Server-Token%3ASYNTHETIC_TOKEN';
    bg.fire('onBeforeRequest', { requestId: String(enabled), url, method: 'POST', initiator: 'https://chatgpt.com',
      requestBody: { raw: [{ bytes: new TextEncoder().encode('{"at":"SYNTHETIC_AT","prompt":"synthetic prompt"}').buffer }] } });
    bg.fire('onCompleted', { requestId: String(enabled), url, initiator: 'https://chatgpt.com',
      responseHeaders: [{ name: 'Content-Location', value: 'https://example.invalid/?sid=SYNTHETIC_SID' }] });
    await tick();
    await popup.callbacks['export:click']();
    const text = await popup.blobs.at(-1).text();
    const data = JSON.parse(text);
    assert.equal(data.captureEnabled, enabled);
    assert.ok(!/SYNTHETIC_(?:AT|SID|TOKEN)|SYNTHETICUSERID1234|%2FSECRET/.test(text));
    assert.equal(data.debug.at(-1).path, '/example/user-REDACTED/');
    assert.equal(JSON.parse(data.capture[0].body.text).prompt, 'synthetic prompt');
  }
  await popup.context.refresh({ showChecking: false });
  await popup.callbacks['captureToggle:click']();
  await tick();
  assert.equal((await bg.status()).captureEnabled, true);
});

test("export retains safely truncated JSON prompts and omits malformed Link containers", async () => {
  const { loadBackground, tick } = require('./background_harness.js');
  const bg = loadBackground();
  const popup = loadPopupStatusRenderer(bg);
  popup.callbacks.DOMContentLoaded();
  const base = { requestId: 'synthetic-long-export', url: 'https://chatgpt.com/synthetic', initiator: 'https://chatgpt.com' };
  bg.fire('onBeforeRequest', { ...base, method: 'POST', requestBody: { raw: [{ bytes: new TextEncoder().encode(JSON.stringify({
    sid: 'SYNTHETIC_SID', prompt: 'synthetic prompt '.repeat(1100)
  })).buffer }] } });
  bg.fire('onCompleted', { ...base, responseHeaders: [{ name: 'Link',
    value: '<https://example.invalid/>; rel="next", https://example.invalid/?sid=SYNTHETIC_SID' }] });
  await tick();
  await popup.callbacks['export:click']();
  const text = await popup.blobs.at(-1).text();
  const [record] = JSON.parse(text).capture;
  assert.equal(record.body.text.length, 16384);
  assert.ok(record.body.text.startsWith('{"sid":"REDACTED","prompt":"synthetic prompt '));
  assert.equal(record.body.truncated, true);
  assert.equal(record.responseHeaders[0].value, '<omitted>');
  assert.ok(!text.includes('SYNTHETIC_SID'));
});


test('clear reports retained submission and rejects failed background replies', async () => {
  let reply = {ok:true,cleared:2,inFlight:1};
  const popup=loadPopupStatusRenderer({send:async()=>reply});
  popup.callbacks.DOMContentLoaded();
  await popup.callbacks['reset:click']();
  assert.match(popup.elements.notice.textContent,/outstanding submission/i);
  reply={ok:false,error:'synthetic write failed'};
  await popup.callbacks['reset:click']();
  assert.match(popup.elements.notice.textContent,/Clear failed: synthetic write failed/);
  await popup.callbacks['forcePush:click']();
  assert.match(popup.elements.notice.textContent,/Push failed/);
});

test('unavailable delivery renders counts as unavailable', () => {
  const popup=loadPopupStatusRenderer();
  const node=()=>({style:{},children:[],appendChild(child){this.children.push(child);}});
  popup.elements.list=node();
  popup.context.document.createDocumentFragment=node;
  popup.context.document.createElement=node;
  popup.context.renderStatus({available:false,pending:null,deliveryError:'synthetic read failed'});
  const text=JSON.stringify(popup.elements.list);
  assert.match(text,/unavailable/i);
  assert.match(text,/synthetic read failed/);
});
