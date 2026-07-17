// popup.js — MV3-safe messaging with timeouts + defensive DOM guards

function $(id){ return document.getElementById(id); }
function fmt(ts){ if(!ts) return "—"; const d=new Date(ts); return d.toLocaleString(); }

function setNotice(message = "", tone = "neutral") {
  const notice = $("notice");
  if (!notice) return;
  notice.textContent = message;
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
}

function showCheckingStatus() {
  const panel = $("status");
  const label = $("statusLabel");
  const detail = $("statusDetail");
  if (panel) panel.dataset.state = "checking";
  if (label) label.textContent = "Checking…";
  if (detail) detail.textContent = "Contacting the local collector";
}

function renderStatus(data){
  const {
    serverCounters = {},
    pending = {},
    seq = 0,
    client_id = "—",
    debug = [],
    configError = null,
    collectorStatus = null
  } = data || {};
  const list = $("list"); if (!list) return;
  const frag = document.createDocumentFragment();

  if (configError) {
    const row = document.createElement("div");
    row.style.color = "#c00";
    row.style.fontSize = "12px";
    row.style.lineHeight = "1.4";
    row.textContent = configError;
    frag.appendChild(row);
    list.innerHTML = "";
    list.appendChild(frag);
    return;
  }

  const totalsEntries = Object.entries(serverCounters).sort((a,b)=>b[1]-a[1]);
  const serverTitle = document.createElement("div");
  serverTitle.innerHTML = "<b>Server totals</b>";
  frag.appendChild(serverTitle);
  if (collectorStatus?.state !== "connected") {
    const row = document.createElement("div");
    row.textContent = "(unavailable while disconnected)";
    row.style.color = "#64716b";
    frag.appendChild(row);
  } else if (totalsEntries.length === 0){
    const row = document.createElement("div"); row.textContent = "(none yet)";
    frag.appendChild(row);
  } else {
    for (const [h,c] of totalsEntries.slice(0,10)){
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = `<span title="${h}">${h}</span><span>${c}</span>`;
      frag.appendChild(row);
    }
  }

  const pendingEntries = Object.entries(pending).sort((a,b)=>b[1]-a[1]);
  const pendTitle = document.createElement("div");
  pendTitle.style.marginTop = "10px";
  pendTitle.innerHTML = "<b>Pending (unsent)</b>";
  frag.appendChild(pendTitle);
  if (pendingEntries.length === 0){
    const row = document.createElement("div"); row.textContent = "(none)";
    frag.appendChild(row);
  } else {
    for (const [h,c] of pendingEntries.slice(0,10)){
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = `<span title="${h}">${h}</span><span>${c}</span>`;
      frag.appendChild(row);
    }
  }

  const meta = document.createElement("div");
  meta.style.marginTop = "10px";
  meta.innerHTML = `<small>client_id: ${client_id}<br/>seq: ${seq}<br/>debug records: ${debug?.length ?? 0}</small>`;
  frag.appendChild(meta);

  if (debug && debug.length > 0) {
    const debugTitle = document.createElement("div");
    debugTitle.style.marginTop = "10px";
    debugTitle.innerHTML = "<b>Recent Debug Logs</b>";
    frag.appendChild(debugTitle);
    
    // Show last 5
    const recentDebug = debug.slice(-5).reverse();
    for (const d of recentDebug) {
      const row = document.createElement("div");
      row.style.fontSize = "10px";
      row.style.borderBottom = "1px solid #eee";
      row.style.padding = "2px 0";
      const color = d.decision === "counted" ? "#080" : "#666";
      row.innerHTML = `
        <div style="color:${color}"><b>${d.decision}</b> ${fmt(d.ts)}</div>
        <div style="color:#444; word-break:break-all;">${d.host}${d.path}</div>
        ${d.reason ? `<div style="color:#999 italic">${d.reason}</div>` : ""}
      `;
      frag.appendChild(row);
    }
  }

  list.innerHTML = "";
  list.appendChild(frag);
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
    renderConnectionStatus(resp.collectorStatus, resp.configError);
    renderStatus(resp);
  } catch (e){
    if (generation !== refreshGeneration) return;
    renderConnectionStatus({ state: "unreachable", message: `Extension status check failed: ${e.message}` });
    const list = $("list");
    if (list) {
      list.innerHTML = `
        <div style="color:#c00; font-size:12px; line-height:1.4;">
          • If this says <i>"The message port closed before a response was received."</i>:
          <br/>— Ensure <code>background.js</code> handles <code>get_status</code> and returns <code>true</code>.
          <br/>— Click "Reload" to retry (wakes the service worker).
          <br/>— Or reload the extension from <code>vivaldi://extensions</code> and reopen the popup.
        </div>`;
    }
  }
}

function bind(id, event, fn){
  const el = $(id);
  if (el) el.addEventListener(event, fn);
}

document.addEventListener("DOMContentLoaded", () => {
  bind("reset", "click", async () => {
    setNotice("Clearing pending data…");
    try {
      await sendMessageWithTimeout({ cmd: "clear_pending" }, 2000);
      setNotice("Pending data cleared.", "success");
    } catch (e) {
      setNotice(`Clear failed: ${e.message}`, "error");
    }
    refresh({ showChecking: false });
  });

  bind("export", "click", async () => {
    setNotice("Exporting diagnostics…");
    try {
      const resp = await sendMessageWithTimeout({ cmd: "get_status" }, 3000);
      const data = {
        collectorStatus: resp.collectorStatus || null,
        collectorUrl: resp.collectorUrl || null,
        serverCounters: resp.serverCounters || {},
        pending: resp.pending || {},
        seq: resp.seq,
        client_id: resp.client_id,
        debug: resp.debug || []
      };
      const json = JSON.stringify(data, null, 2);
      
      const out = $("out");
      if (out) {
        out.value = json;
        out.focus(); out.select();
        try {
          document.execCommand("copy");
        } catch (err) {
          console.error("Copy failed", err);
        }
      }

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
      setNotice("Exported and copied to clipboard.", "success");
    } catch (e){
      setNotice(`Export failed: ${e.message}`, "error");
    }
  });

  bind("forcePush", "click", async () => {
    setNotice("Requesting pending-data push…");
    try {
      const resp = await sendMessageWithTimeout({ cmd: "force_push" }, 2000);
      if (resp.ok === false) throw new Error(resp.error || "push rejected");
      setNotice("Push requested.", "success");
      setTimeout(() => refresh({ showChecking: false }), 300); // allow background to POST, then refresh
    } catch (e){
      setNotice(`Push failed: ${e.message}`, "error");
    }
  });

  bind("reload", "click", () => {
    setNotice();
    refresh({ showChecking: true });
  });

  // initial load
  refresh({ showChecking: true });

  // The popup is destroyed when it closes, so this only polls while visible.
  const pollHandle = setInterval(() => refresh({ showChecking: false }), 10000);
  window.addEventListener("unload", () => clearInterval(pollHandle), { once: true });
});
