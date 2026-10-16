// popup.js — MV3-safe messaging with timeouts + defensive DOM guards

function $(id){ return document.getElementById(id); }

function textElement(tag, text) {
  const element = document.createElement(tag);
  element.textContent = text;
  return element;
}

function setNotice(message = "", tone = "neutral") {
  const notice = $("notice");
  if (!notice) return;
  notice.textContent = message || (chrome.runtime.getManifest ? `Version ${chrome.runtime.getManifest().version}` : "");
  notice.className = `note ${tone === "success" ? "ok" : tone === "error" ? "bad" : ""}`;
  notice.dataset.tone = tone;
}

function renderConnectionStatus(status, configError = null) {
  const panel = $("status");
  const label = $("statusLabel");
  const detail = $("statusDetail");
  if (!panel || !label || !detail) return;

  const state = status?.state || "unreachable";
  const checkedAt = status?.checkedAt ? new Date(status.checkedAt).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit"
  }) : null;

  if (state === "connected") {
    panel.dataset.state = "connected";
    label.textContent = "Collector connected";
    const latency = Number.isFinite(status.latencyMs) ? `${status.latencyMs} ms` : "authenticated";
    detail.textContent = `${latency}${checkedAt ? ` · checked ${checkedAt}` : ""}`;
    return;
  }

  panel.dataset.state = "error";
  if (state === "configuration_error" || configError) {
    label.textContent = "Configuration required";
    detail.textContent = configError || status.message || "Run setup and reload the extension.";
  } else if (state === "authentication_error") {
    label.textContent = "Authentication failed";
    detail.textContent = `Collector rejected the API key${status.httpStatus ? ` · HTTP ${status.httpStatus}` : ""}`;
  } else if (state === "timeout") {
    label.textContent = "Collector timed out";
    detail.textContent = status.message || "The collector did not respond in time.";
  } else if (state === "server_error") {
    label.textContent = "Collector error";
    detail.textContent = status.message || "The collector returned an error.";
  } else if (state === "invalid_response") {
    label.textContent = "Invalid collector response";
    detail.textContent = status.message || "The response format was not recognized.";
  } else {
    label.textContent = "Collector unreachable";
    detail.textContent = status?.message || "Check that the local container is running.";
  }
  if (state === "unreachable" || state === "timeout") detail.textContent += " Counts keep queuing here and send once it is back.";
}

function renderCaptureState({ captureEnabled, captureCount = 0 } = {}) {
  const toggle = $("captureToggle");
  if (!toggle) return;
  toggle.dataset.enabled = String(!!captureEnabled);
  toggle.checked = !!captureEnabled;
  $("captureState").textContent = captureEnabled ? `On, ${captureCount} held` : "Off";
  $("captureHeld").textContent = `${captureCount} requests`;
  $("clearCapture").disabled = captureCount === 0;
}

function renderPersistenceStatus({ capturePersistence, debugPersistence } = {}) {
  const stores = [['Capture', capturePersistence], ['Debug', debugPersistence]];
  const failed = stores.some(([, status]) => status?.state === 'error');
  $('persistenceStatus').textContent = stores.every(([, status]) => status?.state === 'ready') ? 'Working' : stores.filter(([, status]) => status?.state !== 'ready').map(([name, status]) =>
    `${name} persistence: ${status?.state || 'pending'}${status?.error ? ` (${status.error})` : ''}`
  ).join(' · ');
  $('persistenceStatus').className = failed ? 'v bad' : 'v';
  $('captureState').className = failed ? 'state bad' : 'state';
}

function showCheckingStatus() {
  const panel = $("status");
  const label = $("statusLabel");
  const detail = $("statusDetail");
  if (panel) panel.dataset.state = "checking";
  if (label) label.textContent = "Checking…";
  if (detail) detail.textContent = "Contacting the local collector";
}

let previousDeliveryError = null;
let lastConfirmedStatus = null;
const sumCounts = counts => Object.values(counts || {}).reduce((sum, n) => sum + (Number(n) || 0), 0);

function detailRow(label, value, tone = '', mono = false) {
  const row = textElement('div', '');
  row.className = 'row';
  const key = textElement('span', label);
  key.className = 'k';
  row.appendChild(key);
  const val = textElement(mono ? 'code' : 'span', value);
  val.className = `v ${tone}`;
  val.title = String(value);
  row.appendChild(val);
  return row;
}

function renderStatus(data = {}) {
  lastConfirmedStatus = data;
  const { serverCounters = {}, pending = {}, seq = 0, client_id = '—', debug = [], configError, collectorStatus, deliveryError, inFlight } = data;
  const connected = collectorStatus?.state === 'connected';
  const pendingCount = sumCounts(pending);
  const flightCount = sumCounts(inFlight?.deltas);
  const queued = pendingCount - flightCount;
  const register = $('register');
  register.textContent = '';
  $('registerTotal').textContent = '';
  let empty;
  if (configError) {
    $('registerHeading').textContent = 'Setup needed';
    empty = configError;
  } else if (data.available === false) {
    $('registerHeading').textContent = 'Requests';
    empty = `Counts unavailable: ${deliveryError || 'local delivery storage failed'}`;
  } else {
    $('registerHeading').textContent = connected ? 'Requests since last reset' : 'Waiting to send';
    $('registerTotal').textContent = String(sumCounts(connected ? serverCounters : pending));
    const hosts = new Set([...Object.keys(connected ? serverCounters : {}), ...Object.keys(pending || {})]);
    const rows = [...hosts].map(host => ({
      host,
      total: connected ? (serverCounters?.[host] || 0) : 0,
      queued: pending?.[host] || 0
    })).sort((a,b) => (Number(b.total) + Number(b.queued)) - (Number(a.total) + Number(a.queued))).slice(0,10);
    const max = Math.max(1, ...rows.map(row => Number(row.total) + Number(row.queued)));
    for (const {host, total, queued: waiting} of rows) {
      const row = textElement('div', '');
      row.className = 'row';
      const label = textElement('span', host);
      label.className = 'k';
      label.title = host;
      row.appendChild(label);
      if (connected && waiting) {
        const marker = textElement('span', `+${waiting} queued`);
        marker.className = 'q';
        row.appendChild(marker);
      }
      const count = textElement('span', connected ? total : waiting);
      count.className = 'v num';
      row.appendChild(count);
      const bar = textElement('div', '');
      bar.className = 'bar';
      for (const [className, n] of [['bar-total',total],['bar-queued bq',waiting]]) {
        const segment = textElement('span','');
        segment.className = className;
        segment.style.width = `${Number(n) / max * 100}%`;
        bar.appendChild(segment);
      }
      row.appendChild(bar);
      register.appendChild(row);
    }
    if (!rows.length) empty = connected ? 'No requests yet. Send a prompt on a supported site and it shows up here.' : 'Nothing waiting to send.';
  }
  if (empty) {
    const row = textElement('div',empty);
    row.className = 'empty';
    register.appendChild(row);
  }
  const state = $('deliveryState');
  state.textContent = data.available === false ? 'Unavailable' : deliveryError ? `${pendingCount} waiting, retrying` : pendingCount ? `${pendingCount} queued` : 'Up to date';
  state.className = data.available === false ? 'state bad' : (deliveryError || pendingCount) ? 'state warn' : 'state';
  if (deliveryError && !previousDeliveryError) $('deliveryFold').open = true;
  previousDeliveryError = deliveryError;
  const details = $('deliveryDetails');
  details.textContent = '';
  details.appendChild(detailRow('Queued', queued));
  details.appendChild(detailRow('Sent, unconfirmed', flightCount ? `${flightCount} in batch ${inFlight.seq}` : '0'));
  if (deliveryError) details.appendChild(detailRow('Last error',deliveryError,'bad'));
  details.appendChild(detailRow('Sequence',seq));
  details.appendChild(detailRow('Client',client_id,'',true));
  $('forcePush').disabled = pendingCount === 0 || data.available === false;
  $('reset').disabled = queued === 0 || data.available === false;
  renderCaptureState(data);
  $('captureToggle').disabled = false;
  $('export').disabled = false;
  renderPersistenceStatus(data);
  $('logState').textContent = debug.length ? `${debug.length} logged` : 'None';
  const log = $('logList');
  log.textContent = '';
  for (const d of debug.slice(-5).reverse()) {
    const row = textElement('li','');
    row.appendChild(textElement('time', d.ts ? new Date(d.ts).toLocaleTimeString() : '—'));
    const decision = textElement('span',d.decision);
    decision.className = 'dec' + (d.decision === 'counted' ? ' ok' : ['recording-failed','channel-invalid','config-missing'].includes(d.decision) ? ' bad' : '');
    row.appendChild(decision);
    row.appendChild(textElement('code', `${d.host}${d.path}${d.rpcids ? ` [rpcids=${d.rpcids}]` : ''}`));
    if (d.reason) {
      const reason = textElement('div',d.reason);
      reason.className = 'reason';
      row.appendChild(reason);
    }
    log.appendChild(row);
  }
  if (!debug.length) {
    const row = textElement('li','Nothing observed since the browser started.');
    row.className = 'none';
    log.appendChild(row);
  }
}

function renderUnavailableStatus() {
  // A missing worker reply says nothing about whether recording or storage changed.
  if (lastConfirmedStatus) {
    renderCaptureState(lastConfirmedStatus);
    $('captureState').textContent += ' · stale';
    $('captureHeld').textContent += ' · stale';
    $('logState').textContent = `${lastConfirmedStatus.debug?.length || 0} logged · stale`;
  } else {
    $('captureState').textContent = 'Unknown · status unavailable';
    $('captureHeld').textContent = 'Unknown';
    $('logState').textContent = 'Unknown';
  }
  $('captureState').className = 'state bad';
  $('persistenceStatus').textContent = 'Unavailable · check again';
  $('persistenceStatus').className = 'v bad';
  $('deliveryState').textContent = 'Unavailable';
  $('deliveryState').className = 'state bad';
  for (const id of ['captureToggle', 'clearCapture', 'forcePush', 'reset', 'export']) $(id).disabled = true;
  $('registerHeading').textContent = 'Extension not responding';
  $('registerTotal').textContent = '';
  const register = $('register');
  register.textContent = '';
  for (const message of ['Check again to wake the background worker.', "If it still fails, reload the extension from the browser's Extensions page and reopen this popup."]) {
    const row = textElement('div', message);
    row.className = 'empty';
    register.appendChild(row);
  }
}

let refreshGeneration = 0;

function sendMessageWithTimeout(msg, timeoutMs = 2000){
  return new Promise((resolve, reject) => {
    let done = false;
    const timer = setTimeout(() => {
      if (done) return; done = true; reject(new Error("timeout"));
    }, timeoutMs);

    try {
      chrome.runtime.sendMessage(msg, (resp) => {
        if (done) return; done = true; clearTimeout(timer);
        const err = chrome.runtime.lastError;
        if (err) return reject(new Error(err.message || "lastError"));
        resolve(resp || {});
      });
    } catch (e){
      if (done) return; done = true; clearTimeout(timer); reject(e);
    }
  });
}

async function refresh({ showChecking = true } = {}){
  const generation = ++refreshGeneration;
  if (showChecking) showCheckingStatus();
  try {
    const resp = await sendMessageWithTimeout({ cmd: "get_status" }, 3000);
    if (generation !== refreshGeneration) return;
    if (resp.ok === false) throw new Error(resp.error || 'status rejected');
    if (typeof resp.captureEnabled !== 'boolean' || !Number.isFinite(resp.captureCount)) throw new Error('status reply incomplete');
    renderConnectionStatus(resp.collectorStatus, resp.configError);
    renderStatus(resp);
  } catch (e){
    if (generation !== refreshGeneration) return;
    renderConnectionStatus({ state: "unreachable", message: `Extension status check failed: ${e.message}` });
    renderUnavailableStatus();
  }
}

function bind(id, event, fn){
  const el = $(id);
  if (el) el.addEventListener(event, fn);
}

function bindAppearance() {
  const appearance = globalThis.LLMPopupAppearance;
  const button = $('appearanceButton');
  const menu = $('appearanceMenu');
  const items = ['auto', 'meter', 'native'].map((pref, index) => ({
    pref, element: $(['appearanceAuto', 'appearanceMeter', 'appearanceNative'][index])
  }));
  let storage;
  try { storage = globalThis.localStorage; } catch { /* Use this popup's session when storage is blocked. */ }
  let preference = appearance.readPreference(storage);
  const platform = appearance.currentPlatform();
  $('automaticHint').textContent = appearance.resolveSkin('auto', platform) === 'native' ? 'Native on this Mac' : 'Meter here';
  function updateChecked() {
    for (const { pref, element } of items) element.setAttribute('aria-checked', String(pref === preference));
  }
  function close() {
    menu.hidden = true;
    button.setAttribute('aria-expanded', 'false');
    button.focus();
  }
  function select(pref) {
    preference = pref;
    const saved = appearance.writePreference(storage, pref);
    document.documentElement.dataset.skin = appearance.resolveSkin(pref, platform);
    updateChecked();
    close();
    if (!saved) setNotice('Appearance applied for now; it could not be saved.');
  }
  updateChecked();
  bind('appearanceButton', 'click', () => {
    if (!menu.hidden) { close(); return; }
    menu.hidden = false;
    button.setAttribute('aria-expanded', 'true');
    items.find(item => item.pref === preference).element.focus();
  });
  for (const { pref, element } of items) element.addEventListener('click', () => select(pref));
  bind('appearanceMenu', 'keydown', event => {
    const index = items.findIndex(item => item.element === document.activeElement);
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      items[(index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].element.focus();
    } else if ((event.key === 'Enter' || event.key === ' ') && index >= 0) {
      event.preventDefault();
      select(items[index].pref);
    }
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !menu.hidden) { event.preventDefault(); close(); }
  });
  document.addEventListener('click', event => {
    if (!menu.hidden && !menu.contains(event.target) && !button.contains(event.target)) close();
  });
}

document.addEventListener("DOMContentLoaded", () => {
  bindAppearance();
  bind("reset", "click", async () => {
    setNotice("Clearing pending data…");
    try {
      const resp = await sendMessageWithTimeout({ cmd: "clear_pending" }, 2000);
      if (resp.ok !== true) throw new Error(resp.error || "clear rejected");
      setNotice(resp.inFlight ? `Queued data cleared; outstanding submission (${resp.inFlight}) retained.` : "Queued data cleared.", "success");
    } catch (e) {
      setNotice(`Clear failed: ${e.message}`, "error");
    }
    refresh({ showChecking: false });
  });

  bind("export", "click", async () => {
    setNotice("Exporting diagnostics…");
    try {
      const resp = await sendMessageWithTimeout({ cmd: "get_status" }, 3000);
      const cap = await sendMessageWithTimeout({ cmd: "get_capture" }, 10000);
      const data = {
        collectorStatus: resp.collectorStatus || null,
        collectorUrl: resp.collectorUrl || null,
        serverCounters: resp.serverCounters || {},
        pending: resp.available === false ? null : (resp.pending || {}),
        available: resp.available,
        deliveryError: resp.deliveryError,
        inFlight: resp.inFlight,
        seq: resp.seq,
        client_id: resp.client_id,
        debug: resp.debug || [],
        captureEnabled: cap.captureEnabled,
        capturePersistence: cap.capturePersistence,
        debugPersistence: cap.debugPersistence,
        captureDiagnostics: cap.captureDiagnostics,
        capture: cap.capture || []
      };
      const json = JSON.stringify(data, null, 2);
      
      // Trigger download
      const blob = new Blob([json], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `llm_usage_export_${Date.now()}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      renderConnectionStatus(resp.collectorStatus, resp.configError);
      try {
        if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
        await navigator.clipboard.writeText(json);
        setNotice("Exported and copied to clipboard.", "success");
      } catch (error) {
        setNotice(`Exported. Copy to clipboard failed: ${error.message}`, "success");
      }
    } catch (e){
      setNotice(`Export failed: ${e.message}`, "error");
    }
  });

  bind("forcePush", "click", async () => {
    setNotice("Requesting pending-data push…");
    try {
      const resp = await sendMessageWithTimeout({ cmd: "force_push" }, 2000);
      if (resp.ok !== true) throw new Error(resp.error || "push rejected");
      setNotice("Push requested.", "success");
      setTimeout(() => refresh({ showChecking: false }), 300); // allow background to POST, then refresh
    } catch (e){
      setNotice(`Push failed: ${e.message}`, "error");
    }
  });

  bind("captureToggle", "click", async () => {
    const turnOn = $("captureToggle")?.dataset.enabled !== "true";
    try {
      const result = await sendMessageWithTimeout({ cmd: "set_capture", enabled: turnOn }, 2000);
      if (result.ok !== true) throw new Error(result.error || 'capture setting rejected');
      setNotice(`Full capture turned ${turnOn ? "on" : "off"}.`, "success");
    } catch (e) {
      setNotice(`Capture toggle failed: ${e.message}`, "error");
    }
    refresh({ showChecking: false });
  });

  bind("clearCapture", "click", async () => {
    try {
      const result = await sendMessageWithTimeout({ cmd: "clear_capture" }, 2000);
      if (result.ok !== true) throw new Error(result.error || 'capture clear rejected');
      setNotice("Capture cleared.", "success");
    } catch (e) {
      setNotice(`Clear capture failed: ${e.message}`, "error");
    }
    refresh({ showChecking: false });
  });

  bind("reload", "click", () => {
    setNotice();
    refresh({ showChecking: true });
  });

  setNotice();

  // initial load
  refresh({ showChecking: true });

  // The popup is destroyed when it closes, so this only polls while visible.
  const pollHandle = setInterval(() => refresh({ showChecking: false }), 10000);
  window.addEventListener("unload", () => clearInterval(pollHandle), { once: true });
});
