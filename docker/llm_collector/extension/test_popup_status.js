const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { test } = require("node:test");
const vm = require("node:vm");

function fakeNode(markup = []) {
  return { style: {}, dataset: {}, disabled: false, checked: false, open: false, children: [], ownText: '',
    appendChild(child) { this.children.push(child); return child; }, click() {},
    set textContent(value) { this.ownText = String(value); this.children = []; },
    get textContent() { return this.ownText + this.children.map(child => child.textContent).join(''); },
    set innerHTML(value) { markup.push(String(value)); this.ownText = ''; this.children = []; }
  };
}
function loadPopupStatusRenderer(background = null, clipboard = { writeText: async () => {} }, storage = { getItem: () => null, setItem() {} }) {
  const callbacks = {};
  const blobs = [];
  const elements = {};
  const markup = [];
  for (const id of ['appearanceButton','appearanceMenu','appearanceAuto','appearanceMeter','appearanceNative','automaticHint','status','statusLabel','statusDetail','captureToggle','persistenceStatus','registerHeading','registerTotal','register','deliveryState','deliveryDetails','captureState','captureHeld','logState','logList','deliveryFold','captureFold','logFold','export','notice','reset','forcePush','clearCapture','reload']) {
    elements[id] = fakeNode(markup);
    elements[id].addEventListener = (event, fn) => { callbacks[id + ':' + event] = fn; };
    elements[id].attributes = {};
    elements[id].setAttribute = (name, value) => { elements[id].attributes[name] = value; };
    elements[id].focus = () => { document.activeElement = elements[id]; };
    elements[id].contains = target => target === elements[id];
  }
  const document = {
    documentElement: { dataset: {} },
    addEventListener(event, fn) { callbacks[event] = fn; },
    createElement() { return fakeNode(markup); },
    body: { appendChild() {}, removeChild() {} },
    getElementById(id) {
      return elements[id] || null;
    }
  };
  elements.appearanceMenu.hidden = true;
  const context = vm.createContext({
    Blob,
    navigator: { clipboard },
    localStorage: storage,
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
  vm.runInContext(readFileSync(require.resolve('./popup_appearance.js'), 'utf8'), context);
  vm.runInContext(readFileSync(require.resolve("./popup.js"), "utf8"), context);
  return { context, elements, callbacks, blobs, markup };
}

test('Appearance selection persists Native, updates checked state and returns focus', () => {
  let saved;
  const popup = loadPopupStatusRenderer({ send: async () => ({}) }, undefined, { getItem: () => 'meter', setItem(key, value) { saved = [key, value]; } });
  popup.callbacks.DOMContentLoaded();
  assert.equal(typeof popup.callbacks['appearanceButton:click'], 'function');
  popup.callbacks['appearanceButton:click']();
  assert.equal(popup.context.document.activeElement, popup.elements.appearanceMeter);
  popup.callbacks['appearanceNative:click']();
  assert.deepEqual(saved, ['llmUsageCounter.appearance', 'native']);
  assert.equal(popup.context.document.documentElement.dataset.skin, 'native');
  assert.equal(popup.elements.appearanceNative.attributes['aria-checked'], 'true');
  assert.equal(popup.elements.appearanceMeter.attributes['aria-checked'], 'false');
  assert.equal(popup.elements.appearanceMenu.hidden, true);
  assert.equal(popup.elements.appearanceButton.attributes['aria-expanded'], 'false');
  assert.equal(popup.context.document.activeElement, popup.elements.appearanceButton);
});

test('Appearance menu wraps arrow focus, selects with Space, and closes on Escape and outside click', () => {
  const popup = loadPopupStatusRenderer({ send: async () => ({}) });
  popup.callbacks.DOMContentLoaded();
  assert.equal(typeof popup.callbacks['appearanceButton:click'], 'function');
  popup.callbacks['appearanceButton:click']();
  const key = key => popup.callbacks['appearanceMenu:keydown']({ key, preventDefault() {} });
  key('ArrowUp');
  assert.equal(popup.context.document.activeElement, popup.elements.appearanceNative);
  key('ArrowDown');
  assert.equal(popup.context.document.activeElement, popup.elements.appearanceAuto);
  key('ArrowDown'); key(' ');
  assert.equal(popup.context.document.documentElement.dataset.skin, 'meter');
  popup.callbacks['appearanceButton:click']();
  popup.callbacks.keydown({ key: 'Escape', preventDefault() {} });
  assert.equal(popup.elements.appearanceMenu.hidden, true);
  popup.callbacks['appearanceButton:click']();
  popup.callbacks.click({ target: popup.elements.register });
  assert.equal(popup.elements.appearanceMenu.hidden, true);
  assert.equal(popup.context.document.activeElement, popup.elements.appearanceButton);
});

test('blocked Appearance storage still applies the skin with the failed-save notice', () => {
  const storage = { getItem() { throw Error('synthetic read'); }, setItem() { throw Error('synthetic write'); } };
  const popup = loadPopupStatusRenderer({ send: async () => ({}) }, undefined, storage);
  popup.callbacks.DOMContentLoaded();
  assert.equal(typeof popup.callbacks['appearanceNative:click'], 'function');
  popup.callbacks['appearanceNative:click']();
  assert.equal(popup.context.document.documentElement.dataset.skin, 'native');
  assert.equal(popup.elements.notice.textContent, 'Appearance applied for now; it could not be saved.');
});

// Keep every dynamic container present, including in export-only fixtures.
// Capture HTML-parser input separately from text-node output; Chromium acceptance
// checks the resulting real DOM and intercepted resource requests as well.
function attachStatusList(popup) {
  for (const id of ['register','deliveryDetails','logList']) popup.elements[id] = fakeNode(popup.markup);
  return { markup: popup.markup, text: () => ['register','deliveryDetails','logList'].map(id => popup.elements[id].textContent).join('') };
}

test('observed decoded diagnostic markup stays inert through normalization and popup rendering', async () => {
  const { loadBackground, tick } = require('./background_harness.js');
  const bg = loadBackground({ config: true });
  const popup = loadPopupStatusRenderer(bg);
  const { markup, text } = attachStatusList(popup);
  const payload = '<img src="https://synthetic.invalid/probe">';
  bg.request('https://chatgpt.com/user-SYNTHETICUSERID1234/' + encodeURIComponent(payload));
  await tick();
  const status = await bg.status();
  assert.equal(status.debug.at(-1).path, '/user-REDACTED/' + payload);
  assert.ok(Buffer.byteLength(JSON.stringify(status.debug)) <= 256 * 1024);
  popup.context.renderStatus(status);
  assert.ok(!markup.some(html => html.includes(payload)), 'observed markup must never reach the HTML parser');
  assert.ok(text().includes('/user-REDACTED/' + payload));
  assert.ok(!text().includes('SYNTHETICUSERID1234'));
  bg.dispose();
});

test('adjacent diagnostic and status values render as literal text', () => {
  const popup = loadPopupStatusRenderer();
  const { markup, text } = attachStatusList(popup);
  const payload = '<img src="https://synthetic.invalid/adjacent">';
  popup.context.renderStatus({ collectorStatus: { state: 'connected' },
    serverCounters: { [payload]: payload }, pending: { [payload]: payload },
    client_id: payload, seq: payload,
    debug: [{ decision: payload, ts: 1, host: payload, path: payload, rpcids: payload, reason: payload }] });
  assert.ok(!markup.some(html => html.includes(payload)), 'dynamic values must never reach the HTML parser');
  assert.ok(popup.elements.deliveryDetails.textContent.includes(payload));
  assert.ok(popup.elements.logList.textContent.includes('[rpcids=' + payload + ']'));
  assert.deepEqual(markup, []);
  assert.ok(text().includes(payload + payload));
});

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
  // Deliberate copy change: capture state now lives in the fold summary.
  assert.equal(elements.captureState.textContent, "On, 42 held");
  assert.equal(elements.captureHeld.textContent, "42 requests");
  assert.equal(elements.captureToggle.checked, true);
  assert.equal(elements.captureToggle.dataset.enabled, "true");

  context.renderCaptureState({ captureEnabled: false, captureCount: 0 });
  assert.equal(elements.captureState.textContent, "Off");
  assert.equal(elements.captureToggle.checked, false);
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
  attachStatusList(popup);
  popup.context.renderStatus({available:false,pending:null,deliveryError:'synthetic read failed'});
  const text=popup.elements.register.textContent;
  assert.match(text,/unavailable/i);
  assert.match(text,/synthetic read failed/);
});

const connected = { collectorStatus: {state:'connected'}, serverCounters:{'synthetic.example':8}, pending:{'synthetic.example':3,'pending.invalid':2} };
test('register merges totals and queue, and disconnected rows omit markers', () => {
 const p=loadPopupStatusRenderer(); p.context.renderStatus(connected);
 assert.equal(p.elements.registerTotal.textContent,'8');
 assert.match(p.elements.register.textContent,/synthetic.example\+3 queued8/);
 assert.match(p.elements.register.textContent,/pending.invalid\+2 queued0/);
 p.context.renderStatus({...connected,collectorStatus:{state:'unreachable'}});
 assert.equal(p.elements.registerHeading.textContent,'Waiting to send');
 assert.equal(p.elements.registerTotal.textContent,'5');
 assert.ok(!p.elements.register.textContent.includes('queued'));
 const offlineBar = p.elements.register.children[0].children.at(-1);
 assert.equal(offlineBar.children[0].style.width, '0%');
 assert.equal(offlineBar.children[1].style.width, '100%');
 p.context.renderStatus({pending:{}}); assert.equal(p.elements.register.textContent,'Nothing waiting to send.');
});
test('delivery states, queued/inflight arithmetic, buttons and first-error fold opening', () => {
 const p=loadPopupStatusRenderer();
 p.context.renderStatus({pending:{}}); assert.equal(p.elements.deliveryState.textContent,'Up to date'); assert.equal(p.elements.forcePush.disabled,true); assert.equal(p.elements.reset.disabled,true);
 p.context.renderStatus({...connected,inFlight:{seq:2,deltas:{'synthetic.example':3}}});
 assert.equal(p.elements.deliveryState.textContent,'5 queued'); assert.match(p.elements.deliveryDetails.textContent,/Queued2Sent, unconfirmed3 in batch 2/); assert.equal(p.elements.reset.disabled,false);
 p.context.renderStatus({pending:{a:3},inFlight:{seq:2,deltas:{a:3}}}); assert.equal(p.elements.reset.disabled,true); assert.equal(p.elements.forcePush.disabled,false);
 p.context.renderStatus({...connected,deliveryError:'synthetic failure'}); assert.equal(p.elements.deliveryState.textContent,'5 waiting, retrying'); assert.equal(p.elements.deliveryFold.open,true);
 p.elements.deliveryFold.open=false; p.context.renderStatus({...connected,deliveryError:'synthetic failure'}); assert.equal(p.elements.deliveryFold.open,false);
 p.context.renderStatus({available:false}); assert.equal(p.elements.deliveryState.textContent,'Unavailable');
 p.context.renderCaptureState({captureCount:0}); assert.equal(p.elements.clearCapture.disabled,true);
 p.context.renderCaptureState({captureCount:1}); assert.equal(p.elements.clearCapture.disabled,false);
});
test('log shows newest five with decision tones and empty state', () => {
 const p=loadPopupStatusRenderer(); p.context.renderStatus({debug:[]}); assert.equal(p.elements.logState.textContent,'None'); assert.match(p.elements.logList.textContent,/Nothing observed/);
 p.context.renderStatus({debug:['old','neutral','counted','recording-failed','channel-invalid','config-missing'].map((decision,ts)=>({decision,ts,host:'synthetic.invalid',path:'/'}))});
 assert.equal(p.elements.logList.children.length,5); assert.equal(p.elements.logState.textContent,'6 logged');
 assert.match(p.elements.logList.children[0].textContent,/config-missing/);
 assert.equal(p.elements.logList.children[0].children[1].className,'dec bad');
 assert.equal(p.elements.logList.children[3].children[1].className,'dec ok');
 assert.ok(!p.elements.logList.textContent.includes('old'));
});
test('refresh failure renders recovery rows', async () => {
 const p=loadPopupStatusRenderer(); p.context.chrome.runtime.sendMessage=()=>{throw new Error('synthetic worker failure');};
 await p.context.refresh(); assert.equal(p.elements.registerHeading.textContent,'Extension not responding'); assert.match(p.elements.register.textContent,/Check again to wake/); assert.match(p.elements.register.textContent,/Extensions page/);
});

for (const failure of ['throw', 'reject', 'missing']) {
  test(`${failure} status preserves confirmed capture and recovers without capture mutations`, async () => {
    const messages = [];
    let unavailable = false;
    let count = 42;
    const popup = loadPopupStatusRenderer({ send: async message => {
      messages.push(message.cmd);
      if (unavailable) return failure === 'missing' ? undefined : { ok: false, error: 'synthetic rejected status' };
      return { ...connected, captureEnabled: true, captureCount: count,
        capturePersistence: { state: 'ready' }, debugPersistence: { state: 'ready' } };
    } });
    await popup.context.refresh();
    popup.elements.captureFold.open = true;
    popup.elements.logFold.open = true;
    const send = popup.context.chrome.runtime.sendMessage;
    if (failure === 'throw') popup.context.chrome.runtime.sendMessage = () => { throw Error('synthetic worker failure'); };
    else unavailable = true;
    await popup.context.refresh();
    assert.equal(popup.elements.captureState.textContent, 'On, 42 held · stale');
    assert.equal(popup.elements.captureHeld.textContent, '42 requests · stale');
    assert.equal(popup.elements.captureToggle.checked, true);
    assert.match(popup.elements.persistenceStatus.textContent, /unavailable/i);
    for (const id of ['captureToggle', 'clearCapture', 'reset', 'forcePush', 'export']) assert.equal(popup.elements[id].disabled, true, id);
    assert.equal(popup.elements.registerHeading.textContent, 'Extension not responding');
    assert.equal(popup.elements.registerTotal.textContent, '');
    assert.match(popup.elements.register.textContent, /Check again to wake/);
    assert.equal(popup.elements.captureFold.open, true);
    assert.equal(popup.elements.logFold.open, true);
    popup.context.chrome.runtime.sendMessage = send;
    unavailable = false; count = 43;
    await popup.context.refresh();
    assert.equal(popup.elements.captureState.textContent, 'On, 43 held');
    assert.equal(popup.elements.persistenceStatus.textContent, 'Working');
    for (const id of ['captureToggle', 'clearCapture', 'reset', 'forcePush', 'export']) assert.equal(popup.elements[id].disabled, false, id);
    assert.ok(messages.every(cmd => cmd === 'get_status'));
  });
}

test('initial status failure shows unknown capture and disables affected controls', async () => {
  const popup = loadPopupStatusRenderer({ send: async () => ({ ok: false, error: 'synthetic unavailable' }) });
  await popup.context.refresh();
  assert.match(popup.elements.captureState.textContent, /Unknown/);
  assert.match(popup.elements.captureHeld.textContent, /Unknown/);
  assert.ok(!popup.elements.captureState.textContent.includes('Off'));
  assert.ok(!popup.elements.captureHeld.textContent.includes('0 requests'));
  for (const id of ['captureToggle', 'clearCapture', 'reset', 'forcePush', 'export']) assert.equal(popup.elements[id].disabled, true, id);
});
test('popup renderer never uses HTML parsing',()=>{assert.ok(!readFileSync(require.resolve('./popup.js'),'utf8').includes('innerHTML'));});
test('export download survives clipboard rejection and reports successful copy',async()=>{
 let rejects=false; const p=loadPopupStatusRenderer({send:async()=>({})},{writeText:async()=>{if(rejects)throw new Error('synthetic clipboard failure');}});
 p.callbacks.DOMContentLoaded(); await p.callbacks['export:click'](); assert.equal(p.elements.notice.textContent,'Exported and copied to clipboard.');
 rejects=true; await p.callbacks['export:click'](); assert.equal(p.blobs.length,2); assert.equal(p.elements.notice.textContent,'Exported. Copy to clipboard failed: synthetic clipboard failure'); assert.equal(p.elements.notice.dataset.tone,'success');
});

test('rejected capture change restores the last rendered checkbox state', async () => {
  const { tick } = require('./background_harness.js');
  const popup = loadPopupStatusRenderer({ send: async message => message.cmd === 'get_status'
    ? { captureEnabled: false, captureCount: 42 }
    : { ok: false, error: 'synthetic rejected change' } });
  popup.callbacks.DOMContentLoaded();
  await popup.context.refresh();
  popup.elements.captureToggle.checked = true; // The browser toggles before click dispatch.
  await popup.callbacks['captureToggle:click']();
  await tick();
  assert.equal(popup.elements.captureToggle.checked, false);
  assert.equal(popup.elements.captureToggle.dataset.enabled, 'false');
  assert.equal(popup.elements.captureState.textContent, 'Off');
  assert.equal(popup.elements.captureHeld.textContent, '42 requests');
  assert.match(popup.elements.notice.textContent, /Capture toggle failed: synthetic rejected change/);
});

test('storage row summarizes ready stores and highlights capture summary errors', () => {
  const { context, elements } = loadPopupStatusRenderer();
  context.renderPersistenceStatus({ capturePersistence: { state: 'ready' }, debugPersistence: { state: 'ready' } });
  assert.equal(elements.persistenceStatus.textContent, 'Working');
  assert.equal(elements.captureState.className, 'state');
  context.renderPersistenceStatus({ capturePersistence: { state: 'ready' }, debugPersistence: { state: 'error', error: 'synthetic read failure' } });
  assert.equal(elements.persistenceStatus.textContent, 'Debug persistence: error (synthetic read failure)');
  assert.equal(elements.captureState.className, 'state bad');
});

test('missing clipboard keeps the successful export download', async () => {
  const popup = loadPopupStatusRenderer({ send: async () => ({}) }, null);
  popup.callbacks.DOMContentLoaded();
  await popup.callbacks['export:click']();
  assert.equal(popup.blobs.length, 1);
  assert.equal(popup.elements.notice.textContent, 'Exported. Copy to clipboard failed: Clipboard unavailable');
  assert.equal(popup.elements.notice.dataset.tone, 'success');
});
