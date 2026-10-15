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
    maxBytes: 6 * 1024 * 1024,
    normalizeRecord: rec => globalThis.LLMCaptureRedact.sanitizeDiagnosticRecord('capture', rec),
    reduceRecord: globalThis.LLMCaptureRedact.boundDiagnosticRecord
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

  let enabled = false, settingError = null;
  function settingOperation(method, arg) {
    return new Promise((resolve, reject) => {
      try {
        chrome.storage.local[method](arg, value => {
          const error = chrome.runtime.lastError;
          if (error) reject(new Error(error.message || 'Capture setting failed'));
          else resolve(value);
        });
      } catch (error) { reject(error); }
    });
  }
  async function readSetting() {
    try {
      const value = await settingOperation('get', [ENABLED_KEY]);
      enabled = typeof value?.[ENABLED_KEY] === 'boolean' ? value[ENABLED_KEY] : true;
      settingError = null;
      return { ok: true, error: null };
    } catch (error) {
      enabled = false;
      settingError = error.message;
      return { ok: false, error: error.message };
    }
  }
  const ready = Promise.all([readSetting(), store.loaded]).then(results => ({
    ok: results.every(r => r.ok), error: results.find(r => !r.ok)?.error || null
  }));
  let queue = ready;
  const serialize = fn => {
    const result = queue.then(fn);
    queue = result.catch(() => {});
    return result;
  };

  // Scan retained records, including restored ones, without a second owner.
  function recordFor(requestId) {
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
    store.save();
  }

  let stagedEvents = 0, stagedBytes = 0, droppedEvents = 0;
  const eventBytes = d => new TextEncoder().encode(JSON.stringify(d)).byteLength;
  function snapshot(d) {
    // Do not retain raw request bodies or mutable Chrome event objects while
    // initialization/control work waits. Inspect content before staging it.
    const safeInitiator = d.initiator ? redactUrl(d.initiator) : null;
    const url = redactUrl(d.url);
    let parsed = null;
    try { parsed = new URL(url); } catch {}
    return globalThis.LLMCaptureRedact.boundDiagnosticRecord({
      requestId: String(d.requestId), timeStamp: d.timeStamp, method: d.method,
      type: d.type, url, host: hostOf(d.url), path: parsed?.pathname || '<omitted>',
      rpcids: parsed ? rpcidsFromUrl(parsed) : null,
      ...(url === '<omitted>' && { truncated: true }),
      initiator: safeInitiator === d.initiator + '/' ? d.initiator : safeInitiator,
      tabId: d.tabId, frameId: d.frameId,
      body: d.requestBody ? redactBody(d.requestBody) : null,
      requestHeaders: d.requestHeaders ? redactHeaders(d.requestHeaders) : undefined,
      responseHeaders: d.responseHeaders ? redactHeaders(d.responseHeaders) : undefined,
      statusCode: d.statusCode, statusLine: d.statusLine ? globalThis.LLMCaptureRedact.scrubText(d.statusLine).slice(0, 8192) : undefined,
      fromCache: d.fromCache, ip: d.ip,
      redirectUrl: d.redirectUrl ? redactUrl(d.redirectUrl) : undefined,
      error: d.error ? globalThis.LLMCaptureRedact.scrubText(d.error).slice(0, 8192) : undefined
    });
  }
  function whenOn(fn) {
    return d => {
      if (!isFromLlmPage(d)) return;
      const safe = snapshot(d);
      if (!safe) { droppedEvents++; return; }
      const size = eventBytes(safe);
      if (stagedEvents >= 1000 || stagedBytes + size > 1024 * 1024) {
        droppedEvents++;
        return;
      }
      stagedEvents++; stagedBytes += size;
      serialize(() => {
        stagedEvents--; stagedBytes -= size;
        if (!enabled || settingError) return;
        try { fn(safe); } catch { console.log('[LLM-UC] capture event omitted'); }
      });
    };
  }

  const ALL = { urls: ["<all_urls>"] };

  chrome.webRequest.onBeforeRequest.addListener(whenOn(d => {
    const rec = {
      id: d.requestId,
      ts: d.timeStamp ?? Date.now(),
      method: d.method,
      type: d.type || null,
      url: d.url,
      host: d.host,
      path: d.path,
      rpcids: d.rpcids,
      ...(d.truncated && { truncated: true }),
      initiator: d.initiator || null,
      tabId: d.tabId ?? null,
      frameId: d.frameId ?? null,
      body: d.body
    };
    store.push(rec);
  }), ALL, ["requestBody"]);

  chrome.webRequest.onSendHeaders.addListener(whenOn(d => {
    const rec = recordFor(d.requestId);
    if (!rec) return;
    rec.requestHeaders = d.requestHeaders;
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
    responseHeaders: d.responseHeaders
  })), ALL, ["responseHeaders"]);

  chrome.webRequest.onErrorOccurred.addListener(whenOn(d => finish(d, { error: d.error || "unknown" })), ALL, []);

  async function setEnabled(value) {
    return serialize(async () => {
      try {
        await settingOperation('set', { [ENABLED_KEY]: !!value });
        enabled = !!value;
        settingError = null;
        return enabled;
      } catch (error) { settingError = error.message; enabled = false; throw error; }
    });
  }

  globalThis.LLMCapture = Object.freeze({
    ready,
    isEnabled: () => enabled,
    setEnabled,
    records: () => store.items,
    settled: () => queue,
    status() {
      return settingError ? { state: 'error', error: settingError } : store.status();
    },
    diagnostics: () => ({ stagedEvents, stagedBytes, droppedEvents }),
    reload: () => serialize(async () => {
      const setting = settingError ? await readSetting() : { ok: true, error: null };
      const records = await store.reload();
      return setting.ok ? records : setting;
    }),
    clear: () => serialize(() => store.clear())
  });
})();
