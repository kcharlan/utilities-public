// Session-only bounded diagnostics. Failed reads preserve unread storage.
(() => {
  function createSessionBuffer({ key, maxItems, maxChars = Infinity, maxBytes = Infinity,
    normalizeRecord = rec => rec, reduceRecord = rec => rec, onEvict = () => {} }) {
    const area = globalThis.chrome?.storage?.session;
    const items = [];
    const bytes = value => new TextEncoder().encode(JSON.stringify(value)).byteLength;
    let omittedRecords = 0, readError = null, writeError = null;
    let readable = false, reading = true, epoch = 0, generation = 0, written = -1, writing = null, reloading = null;
    function report(...args) {
      try { console.log('[LLM-UC] session buffer', ...args); } catch {}
    }
    function normalize(rec) {
      try { const safe = normalizeRecord(rec); if (safe !== null) return safe; } catch {}
      omittedRecords++;
      return null;
    }
    function evict(index = 0) {
      const [rec] = items.splice(index, 1);
      try { onEvict(rec); } catch {} // Diagnostics must never break accounting.
    }
    function trim() {
      for (let i = items.length - 1; i >= 0; i--) if (reduceRecord(items[i]) === null) evict(i);
      while (items.length && (items.length > maxItems || JSON.stringify(items).length > maxChars || bytes(items) > maxBytes)) evict();
    }
    function operation(method, arg) {
      return new Promise((resolve, reject) => {
        if (!area) return reject(new Error('Session storage unavailable'));
        try {
          area[method](arg, value => {
            const error = globalThis.chrome?.runtime?.lastError;
            if (error) reject(new Error(error.message || 'Session storage failed'));
            else resolve(value);
          });
        } catch (error) { reject(error); }
      });
    }
    function status() {
      const error = readError || writeError;
      return { state: error ? 'error' : reading || writing || written !== generation ? 'pending' : 'ready', error };
    }
    async function read() {
      const ticket = epoch;
      reading = true;
      try {
        const value = await operation('get', [key]);
        if (ticket === epoch) {
          const stored = Array.isArray(value?.[key]) ? value[key] : [];
          items.unshift(...stored.map(normalize).filter(rec => rec !== null));
          readable = true;
          readError = null;
          trim();
          generation++;
        }
        return { ok: true, error: null };
      } catch (error) {
        if (ticket === epoch) { readError = error.message; readable = false; }
        return { ok: false, error: error.message };
      } finally { reading = false; }
    }
    // Serialize immutable snapshots. An obsolete failure never retries its old
    // snapshot over a later mutation or intentional clear.
    async function flush() {
      await loaded;
      if (!readable) throw new Error(readError || 'Session storage unread');
      if (writing) { await writing; return flush(); }
      if (written === generation && !writeError) return;
      writing = (async () => {
        let retries = 0;
        while (written !== generation || writeError) {
          trim();
          const ticket = generation;
          const snapshot = JSON.parse(JSON.stringify(items));
          try {
            await operation('set', { [key]: snapshot });
            written = ticket;
            writeError = null;
            retries = 0;
          } catch (error) {
            if (ticket !== generation) { retries = 0; continue; }
            if (writeError !== error.message) report('save error', key, error.message);
            writeError = error.message;
            if (!/quota/i.test(error.message) || retries++ >= 3) throw error;
            const count = Math.ceil(items.length / 2);
            for (let i = 0; i < count; i++) evict();
          }
        }
      })();
      try { await writing; } finally { writing = null; }
    }
    const loaded = read();
    function save() {
      trim();
      generation++;
      // Ordinary saves publish errors in status without unhandled rejections.
      return flush().catch(() => {});
    }
    loaded.then(result => {
      if (result.ok) save();
      else report('load error', key, result.error);
      if (omittedRecords) report('omitted records', key, omittedRecords);
    });
    return {
      items, loaded, status, flush,
      push(rec) {
        const safe = normalize(rec);
        if (safe === null) return null;
        items.push(safe);
        save();
        return items.includes(safe) ? safe : null;
      },
      save,
      reload() {
        if (reloading) return reloading;
        reloading = (async () => {
          await loaded;
          const result = readable ? { ok: true, error: null } : await read();
          if (result.ok) {
            try { await flush(); } catch (error) { return { ok: false, error: error.message }; }
          }
          return result;
        })().finally(() => { reloading = null; });
        return reloading;
      },
      async clear() {
        epoch++;
        while (items.length) evict();
        readable = true;
        readError = null;
        generation++;
        await flush();
      },
      get omittedRecords() { return omittedRecords; }
    };
  }
  globalThis.LLMSessionBuffer = Object.freeze({ createSessionBuffer });
})();
