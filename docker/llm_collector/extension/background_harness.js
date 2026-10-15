// Test harness: loads background.js with stubbed Chrome APIs and no
// config.local.js, so no collector traffic is attempted. Chrome applies each
// listener's URL filter before calling it, so the harness does too.
const { readFileSync } = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const WEB_REQUEST_EVENTS = [
  "onBeforeRequest", "onSendHeaders", "onBeforeRedirect", "onCompleted", "onErrorOccurred"
];

function storageArea(store, control = {}, runtime = {}) {
  const reads = [], writes = [];
  function complete(kind, fn, keys = []) {
    const queue = kind === 'Read' ? reads : writes;
    const run = () => {
      if ((control['fail' + kind] || control[kind.toLowerCase() + 'Error']) && (!control.failKey || keys.includes(control.failKey))) {
        control['fail' + kind] = false;
        runtime.lastError = { message: control[kind.toLowerCase() + 'Error'] || `synthetic ${kind.toLowerCase()} failure` };
        try { fn(false); } finally { delete runtime.lastError; }
      } else fn(true);
    };
    if (control['defer' + kind]) queue.push(run); else run();
  }
  control.flushRead = () => reads.shift()?.();
  control.flushWrite = () => writes.shift()?.();
  return {
    get(keys, cb) { complete('Read', () => cb(JSON.parse(JSON.stringify(Object.fromEntries(keys.filter(k => Object.hasOwn(store, k)).map(k => [k, store[k]]))))), keys); },
    set(obj, cb) { const snapshot = JSON.parse(JSON.stringify(obj)); complete('Write', ok => { if (ok) Object.assign(store, snapshot); cb && cb(); }, Object.keys(obj)); }
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
function loadBackground({ sessionStore = {}, localStore = {}, config = false, fetchImpl, now = Date.now, setTimer = setTimeout, clearTimer = clearTimeout, localStorage, localControl = {}, sessionControl = {} } = {}) {
  const consoleRecords = [];
  const listeners = Object.fromEntries(WEB_REQUEST_EVENTS.map(e => [e, []]));
  let onMessage;
  const lifecycle = {};
  const event = name => ({ addListener(fn) { (lifecycle[name] ||= []).push(fn); } });
  const webRequest = Object.fromEntries(WEB_REQUEST_EVENTS.map(e => [e, {
    addListener(fn, filter, extra) { listeners[e].push({ fn, filter, extra: extra || [] }); }
  }]));
  const runtime = {
    onInstalled: event('installed'), onStartup: event('startup'),
    onMessage: { addListener(fn) { onMessage = fn; } }
  };
  const timers = new Set();
  const chrome = {
    webRequest,
    runtime,
    storage: { local: localStorage || storageArea(localStore, localControl, runtime), session: storageArea(sessionStore, sessionControl, runtime) }
  };
  const context = vm.createContext({
    chrome, URL, URLSearchParams, TextDecoder, TextEncoder, Date, crypto,
    setTimeout: (fn, ms) => { const timer = setTimer(() => { timers.delete(timer); fn(); }, ms); timers.add(timer); timer?.unref?.(); return timer; },
    clearTimeout: timer => { timers.delete(timer); clearTimer(timer); }, AbortController,
    fetch: fetchImpl || (async () => { throw new TypeError("synthetic: offline"); }),
    console: { log(...args) { consoleRecords.push(JSON.parse(JSON.stringify(args))); } }
  });
  context.globalThis = context;
  context.Date = class extends Date { static now() { return now(); } };
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
    dispose() { for (const timer of timers) clearTimer(timer); timers.clear(); for (const name of Object.keys(listeners)) listeners[name] = []; },
    localControl, sessionControl,
    wake(name = 'startup') { for (const fn of lifecycle[name] || []) fn(); },
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

// Synthetic fixture encoder follows Google's WireV8.encodeMessageQueue:
// https://github.com/google/closure-library/blob/master/closure/goog/labs/net/webchannel/wirev8.js
// reqN uses mapId-offset, never the queue's array index. Reordering can move
// offset below the first mapId, with the encoder reserving 100 IDs of space.
function encodeChannelMessages(queue) {
  if (!queue.length) return {formData:{count:['0']}};
  const offset = queue.reduce((base,message) => message.id < base ? Math.max(0,message.id-100) : base,queue[0].id);
  const formData = {count:[String(queue.length)],ofs:[String(offset)]};
  for (const message of queue) formData[`req${message.id-offset}___data__`] = [message.data];
  return {formData};
}

module.exports = { loadBackground, tick, encodeChannelMessages };
