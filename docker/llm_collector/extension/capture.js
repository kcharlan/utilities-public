// Full request capture for diagnosing how LLM sites send prompts. Records every
// request an LLM page makes, to any host, with redacted URL, body, request and
// response headers, status, redirects and errors. Response bodies and WebSocket
// frames are not visible to chrome.webRequest. Nothing here is sent to the
// collector; the capture leaves the browser only through the popup's export.

(() => {
  const { redactUrl, redactHeaders, redactBody } = globalThis.LLMCaptureRedact;
  const { rpcidsFromUrl } = globalThis.LLMRequestDebug;

  const ENABLED_KEY = "llm_capture_enabled_v1";   // chrome.storage.local; absent means on
  const store = globalThis.LLMSessionBuffer.createSessionBuffer({
    key: "llm_capture_v1",
    maxItems: 3000,
    maxChars: 8_000_000,   // chrome.storage.session holds 10 MB in total
    normalizeRecord: rec => globalThis.LLMCaptureRedact.sanitizeDiagnosticRecord('capture', rec)
  });

  // Pages whose traffic is captured, matched against the request's initiator
  // (or its own URL, for top-level navigations that have no initiator).
  const LLM_PAGE_HOSTS = [
    "gemini.google.com",
    "chatgpt.com", "*.chatgpt.com", "chat.openai.com",
    "*.perplexity.ai",
    "*.abacus.ai",
    "t3.chat", "*.t3.chat"
  ];
  function hostOf(url) {
    try { return new URL(url).hostname; } catch { return null; }
  }
  function isFromLlmPage(d) {
    const host = hostOf(d.initiator) || (d.initiator ? null : hostOf(d.url));
    return !!host && LLM_PAGE_HOSTS.some(p => globalThis.matchHostPattern(host, p));
  }

  let enabled = true;
  const ready = new Promise(resolve => {
    chrome.storage.local.get([ENABLED_KEY], v => {
      if (v && typeof v[ENABLED_KEY] === "boolean") enabled = v[ENABLED_KEY];
      resolve();
    });
  });

  // requestId -> record; records from before a worker restart are found by scan.
  const open = new Map();
  function recordFor(requestId) {
    if (open.has(requestId)) return open.get(requestId);
    for (let i = store.items.length - 1; i >= 0; i--) {
      if (store.items[i].id === requestId) return store.items[i];
    }
    return null;
  }
  function finish(d, fields) {
    const rec = recordFor(d.requestId);
    if (!rec) return;
    Object.assign(rec, fields);
    if (d.timeStamp && rec.ts) rec.durationMs = Math.round(d.timeStamp - rec.ts);
    open.delete(d.requestId);
    store.save();
  }

  // Listener work waits for the on/off setting; .then keeps event order.
  function whenOn(fn) {
    return d => {
      ready.then(() => {
        if (!enabled || !isFromLlmPage(d)) return;
        try { fn(d); } catch (e) { console.log("[LLM-UC] capture error", e); }
      });
    };
  }

  const ALL = { urls: ["<all_urls>"] };

  chrome.webRequest.onBeforeRequest.addListener(whenOn(d => {
    const u = new URL(d.url);
    const url = redactUrl(d.url);
    const rec = {
      id: d.requestId,
      ts: d.timeStamp ?? Date.now(),
      method: d.method,
      type: d.type || null,
      url,
      host: u.hostname,
      path: new URL(url).pathname,
      rpcids: rpcidsFromUrl(u),
      initiator: d.initiator || null,
      tabId: d.tabId ?? null,
      frameId: d.frameId ?? null,
      body: redactBody(d.requestBody)
    };
    const admitted = store.push(rec);
    if (admitted) open.set(d.requestId, admitted);
  }), ALL, ["requestBody"]);

  chrome.webRequest.onSendHeaders.addListener(whenOn(d => {
    const rec = recordFor(d.requestId);
    if (!rec) return;
    rec.requestHeaders = redactHeaders(d.requestHeaders);
    store.save();
  }), ALL, ["requestHeaders"]);

  chrome.webRequest.onBeforeRedirect.addListener(whenOn(d => {
    const rec = recordFor(d.requestId);
    if (!rec) return;
    (rec.redirects ||= []).push({ statusCode: d.statusCode ?? null, url: redactUrl(d.redirectUrl) });
    store.save();
  }), ALL, []);

  chrome.webRequest.onCompleted.addListener(whenOn(d => finish(d, {
    statusCode: d.statusCode ?? null,
    statusLine: d.statusLine || null,
    fromCache: d.fromCache ?? null,
    ip: d.ip || null,
    responseHeaders: redactHeaders(d.responseHeaders)
  })), ALL, ["responseHeaders"]);

  chrome.webRequest.onErrorOccurred.addListener(whenOn(d => finish(d, { error: d.error || "unknown" })), ALL, []);

  async function setEnabled(value) {
    await ready;
    enabled = !!value;
    await new Promise(r => chrome.storage.local.set({ [ENABLED_KEY]: enabled }, r));
    return enabled;
  }

  globalThis.LLMCapture = Object.freeze({
    ready: Promise.all([ready, store.loaded]),
    isEnabled: () => enabled,
    setEnabled,
    records: () => store.items,
    clear() { open.clear(); store.clear(); }
  });
})();
