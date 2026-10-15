// A bounded record buffer mirrored to chrome.storage.session. The service
// worker stops after ~30 s idle and loses memory; the session store survives
// that and is cleared when the browser quits. Records written by earlier
// workers are reloaded ahead of anything this worker has recorded.

(() => {
  function createSessionBuffer({ key, maxItems, maxChars = Infinity, normalizeRecord = rec => rec }) {
    const area = globalThis.chrome?.storage?.session;
    const items = [];
    let omittedRecords = 0;
    function normalize(rec) {
      let normalized;
      try { normalized = normalizeRecord(rec); } catch { normalized = null; }
      if (normalized === null) omittedRecords++;
      return normalized;
    }

    function trimCount() {
      if (items.length > maxItems) items.splice(0, items.length - maxItems);
    }

    const loaded = new Promise(resolve => {
      if (!area) return resolve();
      area.get([key], v => {
        const stored = v && Array.isArray(v[key]) ? v[key] : [];
        items.unshift(...stored.map(normalize).filter(rec => rec !== null));
        trimCount();
        resolve();
      });
    });

    // Drops the oldest tenth until the serialized buffer fits maxChars, which
    // keeps it inside the session-storage quota.
    function trimSize() {
      if (!Number.isFinite(maxChars)) return;
      while (items.length > 1 && JSON.stringify(items).length > maxChars) {
        items.splice(0, Math.ceil(items.length / 10));
      }
    }

    // One write in flight at a time; records added meanwhile trigger one more,
    // spaced out so a burst of requests costs a few writes rather than one each.
    const MIN_WRITE_GAP_MS = 300;
    let saving = false;
    let dirty = false;
    async function save() {
      if (!area) return;
      if (saving) { dirty = true; return; }
      saving = true;
      try {
        await loaded;
        do {
          dirty = false;
          trimSize();
          await new Promise(r => area.set({ [key]: items.slice() }, r));
          if (dirty) await new Promise(r => setTimeout(r, MIN_WRITE_GAP_MS));
        } while (dirty);
      } catch (e) {
        console.log("[LLM-UC] session buffer save error", key, e);
      } finally {
        saving = false;
      }
    }

    function push(rec) {
      const normalized = normalize(rec);
      if (normalized === null) return null;
      items.push(normalized);
      trimCount();
      save();
      return normalized;
    }

    function clear() {
      items.length = 0;
      save();
    }

    // Always rewrite restored data after inspection, before exposing it via loaded.
    const ready = loaded.then(async () => {
      if (area) await save();
      if (omittedRecords) console.log('[LLM-UC] session buffer omitted records', key, omittedRecords);
    });
    return { items, loaded: ready, push, save, clear, get omittedRecords() { return omittedRecords; } };
  }

  globalThis.LLMSessionBuffer = Object.freeze({ createSessionBuffer });
})();
