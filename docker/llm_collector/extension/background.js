// ===== LLM Usage Counter — Server SOT + Idempotent Adds + Seq Handshake =====

// --- Config ---
importScripts("collector_status.js");
importScripts("delivery.js");
importScripts("request_debug.js");
importScripts("gemini_channel.js");
importScripts("session_buffer.js");
importScripts("capture_redact.js");
importScripts("capture.js");

let CONFIG_LOAD_ERROR = null;
try {
  importScripts("config.local.js");
} catch (err) {
  CONFIG_LOAD_ERROR = err;
}

const LOCAL_CONFIG = globalThis.LLM_USAGE_CONFIG || {};
const COLLECTOR = LOCAL_CONFIG.collectorUrl || "http://127.0.0.1:9000";
const API_KEY   = LOCAL_CONFIG.apiKey || "";
const DEBUG = true;

const DEDUPE_WINDOW_MS = 1500;      // per (tabId, host, path)
const PUSH_COALESCE_MS = 250;       // batch quickly

// Observe these domains; allow/deny rules decide what counts.
const URL_FILTERS = [
  "*://chatgpt.com/*",
  "*://*.chatgpt.com/*",
  "*://chat.openai.com/*",
  "*://api.openai.com/*",
  "*://*.perplexity.ai/*",
  "*://gemini.google.com/*",
  "*://geminiweb-pa.clients6.google.com/*",  // Gemini WebChannel; see GEMINI_CHANNEL
  "*://generativelanguage.googleapis.com/*",
  "*://*.googleapis.com/*",
  "*://*.abacus.ai/*",
  "*://t3.chat/*",
  "*://*.t3.chat/*"
];

// --- Allow rules: endpoints that indicate a user "send" ---
const HOST_ALLOW = {
  "t3.chat": [
    /^\/api\/chat/,
    /^\/api\/trpc\/chat/,
    /^\/api\/inference/
  ],
  "*.t3.chat": [
    /^\/api\/chat/,
    /^\/api\/trpc\/chat/,
    /^\/api\/inference/
  ],
  "api.openai.com": [
    /^\/v1\/chat\/completions$/,
    /^\/v1\/responses$/,
    /^\/v1\/completions$/
  ],
  "chatgpt.com": [
    /^\/backend-api\/f\/conversation$/,
    /^\/backend-api\/conversation$/
  ],
  "chat.openai.com": [
    /^\/backend-api\/f\/conversation$/,
    /^\/backend-api\/conversation$/
  ],
  "*.chatgpt.com": [
    /^\/backend-api\/f\/conversation$/,
    /^\/backend-api\/conversation$/
  ],
  "*.perplexity.ai": [
    /^\/rest\/sse\/perplexity_ask$/
  ],
  "gemini.google.com": [
    /^\/_\/BardChatUi\/data\/assistant\.lamda\.BardFrontendService\/StreamGenerate$/
  ],
  "generativelanguage.googleapis.com": [
    /:generateContent$/,
    /:streamGenerateContent$/
  ],
  "*.googleapis.com": [
    /:generateContent$/,
    /:streamGenerateContent$/
  ],
  "*.abacus.ai": [
    /^\/api\/_chatLLMSendMessageSSE$/,
    /^\/api\/_chatLLMSendMessage$/
  ]
};

// --- Deny rules: noisy endpoints to ignore ---
const HOST_DENY = {
  "chatgpt.com": [
    /^\/ces\//,
    /^\/backend-api\/aip\/connectors\//,
    /^\/backend-api\/conversation\/experimental\/generate_autocompletions$/,
    /^\/backend-api\/f\/conversation\/prepare$/,
    /^\/backend-api\/lat\/r$/,
    /^\/backend-api\/sentinel\//,
    /^\/backend-api\/unified_user_signals$/,
    /^\/cdn-cgi\/challenge-platform\//
  ],
  "chat.openai.com": [
    /^\/ces\//,
    /^\/backend-api\/aip\/connectors\//,
    /^\/backend-api\/conversation\/experimental\/generate_autocompletions$/,
    /^\/backend-api\/f\/conversation\/prepare$/,
    /^\/backend-api\/lat\/r$/,
    /^\/backend-api\/sentinel\//,
    /^\/backend-api\/unified_user_signals$/,
    /^\/cdn-cgi\/challenge-platform\//
  ],
  "ab.chatgpt.com": [ /^\/v1\/rgstr$/ ],
  "realtime.chatgpt.com": [ /^\/v1\/vp\/status$/, /^\/v1\/vps$/ ],
  "*.perplexity.ai": [
    /^\/rest\/event\/analytics$/,
    /^\/rest\/entry\//,
    /^\/rest\/thread\/mark_viewed\//,
    /^\/rest\/autosuggest\/list-autosuggest$/,
    /^\/cdn-cgi\/challenge-platform\//
  ],
  "gemini.google.com": [
    /^\/_\/BardChatUi\/data\/batchexecute$/
  ]
};

// --- Host pattern helpers ---
function matchHostPattern(host, pattern) {
  if (!pattern.includes("*")) return host === pattern;
  const suffix = pattern.replace(/^\*\./, "");
  return host === suffix || host.endsWith("." + suffix);
}
function rulesForHost(table, host) {
  if (table[host]) return table[host];
  for (const [pat, rules] of Object.entries(table)) {
    if (pat.startsWith("*.") && matchHostPattern(host, pat)) return rules;
  }
  return null;
}
function allowedByHost(u) {
  const allow = rulesForHost(HOST_ALLOW, u.hostname);
  if (!allow) return false;
  const pathq = u.pathname + (u.search || "");
  return allow.some(rx => rx.test(u.pathname) || rx.test(pathq));
}
function deniedByHost(u) {
  const deny = rulesForHost(HOST_DENY, u.hostname);
  if (!deny) return false;
  const pathq = u.pathname + (u.search || "");
  return deny.some(rx => rx.test(u.pathname) || rx.test(pathq));
}

// --- Debounce (avoid burst double counts) ---
const recent = new Map();
function dedupeKey(details, u) { return `${details.tabId}|${u.hostname}|${u.pathname}`; }
function passesDebounce(details, u) {
  const now = Date.now();
  const k = dedupeKey(details, u);
  const last = recent.get(k) || 0;
  if (now - last < DEDUPE_WINDOW_MS) return false;
  recent.set(k, now);
  return true;
}

// --- Debug buffer for popup ---
// Mirrored to chrome.storage.session so it survives the worker stopping when idle.
const DEBUG_BUF_MAX = 200;
const debugStore = globalThis.LLMSessionBuffer.createSessionBuffer({
  key: "llm_debug_v1", maxItems: DEBUG_BUF_MAX,
  normalizeRecord: rec => globalThis.LLMCaptureRedact.sanitizeDiagnosticRecord('debug', rec)
});
function dbgPush(decision, d, u, reason) {
  const rec = {
    ts: Date.now(),
    decision,
    method: d.method,
    type: d.type || null,
    host: u.hostname,
    path: globalThis.LLMCaptureRedact.redactPath(u.pathname),
    rpcids: globalThis.LLMRequestDebug.rpcidsFromUrl(u),
    tabId: d.tabId ?? null,
    reason: reason || null
  };
  const admitted = debugStore.push(rec);
  if (DEBUG && admitted) console.log("[LLM-UC]", admitted);
}

function getConfigError() {
  if (CONFIG_LOAD_ERROR) {
    return "Missing extension/config.local.js. Run ./setup.sh, then reload the unpacked extension.";
  }
  if (!API_KEY) {
    return "Missing API_KEY in extension/config.local.js. Run ./setup.sh, then reload the unpacked extension.";
  }
  return null;
}

// Durable delivery owns every accounting write, including migration.
const delivery = globalThis.LLMDelivery.createDelivery({
  storage: chrome.storage.local, fetchImpl: fetch, collectorUrl: COLLECTOR, apiKey: API_KEY
});
let pushTimerHandle = null;
function schedulePush() {
  if (pushTimerHandle !== null) clearTimeout(pushTimerHandle);
  pushTimerHandle = setTimeout(() => { pushTimerHandle = null; delivery.push(); }, PUSH_COALESCE_MS);
}
async function incrementPending(host, count = 1) {
  try { await delivery.increment(host, count); schedulePush(); }
  catch { if (DEBUG) console.log('[LLM-UC] observation recording failed; see delivery status'); }
}

// --- Gemini WebChannel ---
// Gemini (seen first with Gemini 4 Argon) sends prompts over a WebChannel
// session instead of StreamGenerate. One turn makes several posts (handshake,
// setup, prompt, end of turn, terminate beacon); only the prompt message,
// protobuf field 2, is a user send. It is credited to gemini.google.com so the
// count stays in the existing Gemini column.
const GEMINI_CHANNEL = {
  host: "geminiweb-pa.clients6.google.com",
  path: /^\/v1\/processSession$/,
  creditHost: "gemini.google.com"
};
function isGeminiChannel(u) {
  return u.hostname === GEMINI_CHANNEL.host && GEMINI_CHANNEL.path.test(u.pathname);
}
function countGeminiChannel(d, u) {
  const fields = globalThis.LLMGeminiChannel.messageFields(d.requestBody);
  const desc = `channel fields=${fields.length ? fields.map(f => f ?? "?").join(",") : "none"}`;
  const prompts = globalThis.LLMGeminiChannel.promptCount(d.requestBody);
  if (!prompts) { dbgPush("not-prompt", d, u, desc); return; }
  if (getConfigError()) { dbgPush("config-missing", d, u, getConfigError()); return; }
  // Each prompt message is a distinct turn, so the path debounce does not apply.
  incrementPending(GEMINI_CHANNEL.creditHost, prompts);
  dbgPush("counted", d, u, `${desc}; credited to ${GEMINI_CHANNEL.creditHost}`);
}

// --- Network listener (only count real user sends) ---
chrome.webRequest.onBeforeRequest.addListener(
  (d) => {
    try {
      if (d.method !== "POST") return;
      const u = new URL(d.url);

      if (deniedByHost(u)) { dbgPush("host-deny", d, u, "deny rule"); return; }
      if (isGeminiChannel(u)) { countGeminiChannel(d, u); return; }
      if (!allowedByHost(u)) { dbgPush("not-allowlisted", d, u, "no allow"); return; }
      if (getConfigError()) { dbgPush("config-missing", d, u, getConfigError()); return; }
      if (!passesDebounce(d, u)) { dbgPush("debounced", d, u, `window=${DEDUPE_WINDOW_MS}ms`); return; }

      incrementPending(u.hostname, 1);
      dbgPush("counted", d, u, null);
    } catch (e) {
      if (DEBUG) console.log("[LLM-UC] onBeforeRequest error", e);
    }
  },
  { urls: URL_FILTERS },
  ["requestBody"]   // read only by countGeminiChannel, for each message's first byte
);

// --- Bootstrap / recovery ---
chrome.runtime.onInstalled?.addListener(schedulePush);
chrome.runtime.onStartup?.addListener(schedulePush);
delivery.ready.then(schedulePush);

// --- Popup API (optional, keep if your popup uses it) ---
chrome.runtime.onMessage.addListener((m, s, send) => {
  if (m && m.cmd === "get_status") {
    Promise.all([delivery.status(), debugStore.loaded, globalThis.LLMCapture.ready]).then(async ([deliveryStatus]) => {
      const configError = getConfigError();
      const collectorStatus = configError
        ? {
            state: "configuration_error",
            message: configError,
            checkedAt: Date.now(),
            latencyMs: 0
          }
        : await globalThis.LLMCollectorStatus.checkCollectorConnection({
            collectorUrl: COLLECTOR,
            apiKey: API_KEY
          });

      send({
        ...deliveryStatus,
        serverCounters: collectorStatus.serverCounters || {},
        collectorStatus,
        collectorUrl: COLLECTOR,
        debug: debugStore.items,
        captureEnabled: globalThis.LLMCapture.isEnabled(),
        captureCount: globalThis.LLMCapture.records().length,
        configError
      });
    });
    return true;
  } else if (m && m.cmd === "get_config_status") {
    send({ configError: getConfigError(), collectorUrl: COLLECTOR });
    return true;
  } else if (m && m.cmd === "force_push") {
    if (getConfigError()) {
      send({ ok: false, error: getConfigError() });
      return true;
    }
    delivery.status().then(status => {
      if (!status.available) send({ok:false,error:status.deliveryError});
      else { delivery.push(); send({ok:true}); }
    });
    return true;
  } else if (m && m.cmd === "clear_pending") {
    delivery.clearQueued().then(result => send({ok:true,...result}), error => send({ok:false,error:error.message}));
    return true;
  } else if (m && m.cmd === "get_capture") {
    globalThis.LLMCapture.ready.then(() => send({
      captureEnabled: globalThis.LLMCapture.isEnabled(),
      capture: globalThis.LLMCapture.records()
    }));
    return true;
  } else if (m && m.cmd === "set_capture") {
    globalThis.LLMCapture.setEnabled(m.enabled).then(enabled => send({ ok: true, captureEnabled: enabled }));
    return true;
  } else if (m && m.cmd === "clear_capture") {
    globalThis.LLMCapture.ready.then(() => { globalThis.LLMCapture.clear(); send({ ok: true }); });
    return true;
  }
});
