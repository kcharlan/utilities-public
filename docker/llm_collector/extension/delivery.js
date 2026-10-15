// One owner for durable accounting. A sequence always identifies one wire batch.
(function (root) {
  'use strict';
  const KEY = 'llm_delivery_v2';
  const LEGACY = ['llm_client_id_v1', 'llm_seq_v1', 'llm_pending_v1'];
  const copy = value => JSON.parse(JSON.stringify(value));
  function integer(value) {
    if (!Number.isSafeInteger(value) || value < 0) throw new Error('Unsafe delivery integer');
    return value;
  }
  function sum(counts) {
    if (!counts || typeof counts !== 'object' || Array.isArray(counts)) throw new Error('Invalid delivery counts');
    let total = 0;
    for (const [host, value] of Object.entries(counts)) {
      if (!host || integer(value) === 0) throw new Error('Invalid delivery count');
      total = integer(total + value);
    }
    return total;
  }
  function validate(s) {
    if (!s || s.version !== 2 || typeof s.clientId !== 'string' || !s.clientId) throw new Error('Invalid delivery state');
    integer(s.lastAckSeq); sum(s.queued);
    if (s.baseline?.state === 'unresolved') integer(s.baseline.legacySeq);
    else if (s.baseline?.state !== 'ready') throw new Error('Invalid baseline');
    if (s.inFlight !== null) {
      const b = s.inFlight;
      if (s.baseline.state !== 'ready' || b.client_id !== s.clientId || integer(b.seq) !== integer(s.lastAckSeq + 1) || !Number.isSafeInteger(b.ts)) throw new Error('Invalid delivery batch');
      if (!sum(b.deltas)) throw new Error('Empty delivery batch');
    }
    integer(sum(s.queued) + (s.inFlight ? sum(s.inFlight.deltas) : 0));
    return s;
  }
  function createDelivery({storage, fetchImpl = root.fetch, collectorUrl, apiKey, now = Date.now, setTimer = setTimeout, clearTimer = clearTimeout}) {
    let state = null, deliveryError = null, queue = Promise.resolve(), drain = null, retryTimer = null, retryIndex = 0;
    const errorText = e => e?.message || 'Delivery failed';
    function storageCall(method, arg) {
      return new Promise((resolve, reject) => {
        try { storage[method](arg, value => {
          const error = root.chrome?.runtime?.lastError;
          if (error) reject(new Error(error.message || 'Local storage failed'));
          else resolve(value);
        }); } catch (e) { reject(e); }
      });
    }
    function transaction(change) {
      const run = queue.then(async () => {
        if (!state) throw new Error(deliveryError || 'Delivery unavailable');
        const candidate = copy(state);
        const result = change(candidate);
        validate(candidate);
        await storageCall('set', {[KEY]: candidate});
        state = candidate;
        return result;
      });
      queue = run.catch(e => { deliveryError = errorText(e); });
      return run;
    }
    const ready = (async () => {
      try {
        const data = await storageCall('get', [KEY, ...LEGACY]) || {};
        if (Object.hasOwn(data, KEY)) state = validate(copy(data[KEY]));
        else {
          const migrated = LEGACY.some(key => Object.hasOwn(data, key));
          const candidate = validate({version:2, clientId:data[LEGACY[0]] || root.crypto.randomUUID(), lastAckSeq:0,
            baseline:migrated ? {state:'unresolved',legacySeq:integer(data[LEGACY[1]] ?? 0)} : {state:'ready'},
            queued:data[LEGACY[2]] || {}, inFlight:null});
          await storageCall('set', {[KEY]:candidate});
          state = candidate;
        }
        return {ok:true};
      } catch (e) { state = null; deliveryError = errorText(e); return {ok:false,error:deliveryError}; }
    })();
    async function request(path, body) {
      if (!apiKey) throw Object.assign(new Error('Missing collector configuration'), {retryable:false});
      const controller = new AbortController();
      const timer = setTimer(() => controller.abort(), 5000);
      try {
        let response;
        try { response = await fetchImpl(`${collectorUrl.replace(/\/$/,'')}${path}`, {
          headers: {'X-API-KEY':apiKey, ...(body ? {'Content-Type':'application/json'} : {})},
          ...(body ? {method:'POST',body:JSON.stringify(body)} : {}), signal:controller.signal
        }); } catch (e) { throw Object.assign(new Error(controller.signal.aborted ? 'Collector request timed out' : 'Collector network failure'), {retryable:true}); }
        if (!response.ok) throw Object.assign(new Error(`Collector HTTP ${response.status}`), {retryable:response.status >= 500});
        try { return await response.json(); } catch { throw new Error('Invalid collector JSON'); }
      } finally { clearTimer(timer); }
    }
    function retry() {
      if (retryTimer !== null) return;
      const delay = [1000,2000,4000,8000,16000,30000][Math.min(retryIndex++,5)];
      retryTimer = setTimer(() => { retryTimer = null; push(); }, delay);
    }
    async function run() {
      await ready;
      if (!state) return {ok:false,error:deliveryError};
      try {
        if (state.baseline.state === 'unresolved') {
          const reply = await request(`/client_status?client_id=${encodeURIComponent(state.clientId)}`);
          if (!reply || reply.client_id !== state.clientId) throw new Error('Invalid client status');
          const last = integer(reply.last_seq);
          await transaction(s => { s.lastAckSeq = last; s.baseline = {state:'ready'}; });
        }
        for (;;) {
          await queue;
          if (!state.inFlight) {
            if (!sum(state.queued)) break;
            await transaction(s => {
              s.inFlight = {client_id:s.clientId, seq:integer(s.lastAckSeq + 1), deltas:s.queued, ts:integer(now())};
              s.queued = {};
            });
          }
          const batch = copy(state.inFlight);
          const reply = await request('/add', batch);
          if (!reply || reply.ok !== true || reply.last_seq !== batch.seq || (reply.applied !== 0 && reply.applied !== sum(batch.deltas))) throw new Error('Unexpected collector acknowledgement sequence or applied count');
          await transaction(s => { s.lastAckSeq = batch.seq; s.inFlight = null; });
        }
        deliveryError = null; retryIndex = 0;
        return {ok:true};
      } catch (e) {
        deliveryError = errorText(e);
        if (e.retryable) retry();
        return {ok:false,error:deliveryError};
      }
    }
    function push() {
      if (retryTimer !== null) { clearTimer(retryTimer); retryTimer = null; }
      if (!drain) drain = run().finally(() => { drain = null; });
      return drain;
    }
    async function increment(host, count = 1) {
      await ready;
      if (typeof host !== 'string' || !host || integer(count) === 0) throw new Error('Invalid observation');
      return transaction(s => {
        const value = integer((Object.hasOwn(s.queued,host) ? s.queued[host] : 0) + count);
        Object.defineProperty(s.queued,host,{value,enumerable:true,writable:true,configurable:true});
      });
    }
    async function clearQueued() {
      await ready;
      return transaction(s => { const result = {cleared:sum(s.queued),inFlight:s.inFlight ? sum(s.inFlight.deltas) : 0}; s.queued = {}; return result; });
    }
    async function status() {
      await ready; await queue;
      if (!state) return {available:false,client_id:null,seq:null,pending:null,inFlight:null,deliveryError};
      const pending = copy(state.queued);
      for (const [host,count] of Object.entries(state.inFlight?.deltas || {})) Object.defineProperty(pending,host,{value:integer((Object.hasOwn(pending,host) ? pending[host] : 0) + count),enumerable:true,configurable:true});
      return {available:true,client_id:state.clientId,seq:state.lastAckSeq,pending,inFlight:copy(state.inFlight),deliveryError};
    }
    return {ready,increment,push,clearQueued,status};
  }
  root.LLMDelivery = {createDelivery};
})(globalThis);
