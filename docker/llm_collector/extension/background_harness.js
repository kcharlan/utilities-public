// Test harness: loads background.js with stubbed Chrome APIs and no
// config.local.js, so no collector traffic is attempted. Chrome applies each
// listener's URL filter before calling it, so the harness does too.
const { readFileSync } = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const WEB_REQUEST_EVENTS = [
  "onBeforeRequest", "onSendHeaders", "onBeforeRedirect", "onCompleted", "onErrorOccurred"
];

function storageArea(store) {
  return {
    get(keys, cb) { cb(JSON.parse(JSON.stringify(Object.fromEntries(keys.filter(k => Object.hasOwn(store, k)).map(k => [k, store[k]]))))); },
    set(obj, cb) { Object.assign(store, JSON.parse(JSON.stringify(obj))); cb && cb(); }
  };
}

function matchPatternToRegExp(pattern) {
  if (pattern === "<all_urls>") return /^(https?|wss?):\/\//;
  const [, scheme, host, rest] = pattern.match(/^(\*|https?|wss?):\/\/([^/]+)(\/.*)$/);
  const esc = s => s.replace(/[.+?^${}()|[\]\\]/g, "\\$&");
  const hostRe = host === "*" ? "[^/]+"
    : host.startsWith("*.") ? `([^/]+\\.)?${esc(host.slice(2))}` : esc(host);
  const pathRe = esc(rest).replace(/\*/g, ".*");
  return new RegExp(`^${scheme === "*" ? "https?" : scheme}://${hostRe}${pathRe}$`);
}

// Pass the same sessionStore to two loads to simulate a service-worker restart:
// chrome.storage.session outlives the worker, in-memory state does not.
// With config: true it loads a synthetic config so counting is active; fetch
// always fails, so counts stay pending where tests can read them.
function loadBackground({ sessionStore = {}, localStore = {}, config = false } = {}) {
  const consoleRecords = [];
  const listeners = Object.fromEntries(WEB_REQUEST_EVENTS.map(e => [e, []]));
  let onMessage;
  const event = () => ({ addListener() {} });
  const webRequest = Object.fromEntries(WEB_REQUEST_EVENTS.map(e => [e, {
    addListener(fn, filter, extra) { listeners[e].push({ fn, filter, extra: extra || [] }); }
  }]));
  const chrome = {
    webRequest,
    runtime: {
      onInstalled: event(),
      onStartup: event(),
      onMessage: { addListener(fn) { onMessage = fn; } }
    },
    storage: { local: storageArea(localStore), session: storageArea(sessionStore) }
  };
  const context = vm.createContext({
    chrome, URL, URLSearchParams, TextDecoder, TextEncoder, Date, crypto,
    setTimeout, clearTimeout, AbortController,
    fetch: async () => { throw new TypeError("synthetic: offline"); },
    console: { log(...args) { consoleRecords.push(JSON.parse(JSON.stringify(args))); } }
  });
  context.globalThis = context;
  context.importScripts = (file) => {
    if (file === "config.local.js") {
      if (!config) throw new Error("synthetic: no local config");
      context.LLM_USAGE_CONFIG = { collectorUrl: "http://127.0.0.1:9", apiKey: "SYNTHETIC_TEST_KEY" };
      return;
    }
    vm.runInContext(readFileSync(path.join(__dirname, file), "utf8"), context);
  };
  vm.runInContext(readFileSync(path.join(__dirname, "background.js"), "utf8"), context);

  const matches = (l, url) => l.filter.urls.some(p => matchPatternToRegExp(p).test(url));
  const counting = () => listeners.onBeforeRequest.find(l => !l.filter.urls.includes("<all_urls>"));

  return {
    consoleRecords,
    // Whether the counting listener (not full capture) observes this URL.
    filterMatches(url) { return matches(counting(), url); },
    fire(eventName, details) {
      for (const l of listeners[eventName]) if (matches(l, details.url)) l.fn(details);
    },
    request(url, method = "POST") {
      this.fire("onBeforeRequest", { requestId: String(Math.random()), method, type: "xmlhttprequest", tabId: 7, url });
    },
    send(msg) {
      // JSON round-trip: objects built in the VM realm have a different prototype.
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error(`no reply to ${msg.cmd}`)), 1000);
        onMessage(msg, {}, r => { clearTimeout(timer); resolve(JSON.parse(JSON.stringify(r))); });
      });
    },
    status() { return this.send({ cmd: "get_status" }); }
  };
}

const tick = () => new Promise(resolve => setTimeout(resolve, 0));

module.exports = { loadBackground, tick };
