// A bounded record buffer mirrored to chrome.storage.session. The service
// worker stops after ~30 s idle and loses memory; the session store survives
// that and is cleared when the browser quits. Records written by earlier
// workers are reloaded ahead of anything this worker has recorded.

(() => {
  function createSessionBuffer({ key, maxItems, maxChars = Infinity }) {
    const area = globalThis.chrome?.storage?.session;
    const items = [];

    function trimCount() {
      if (items.length > maxItems) items.splice(0, items.length - maxItems);
    }

    const loaded = new Promise(resolve => {
      if (!area) return resolve();
      area.get([key], v => {
        const stored = v && Array.isArray(v[key]) ? v[key] : [];
        items.unshift(...stored);
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
      items.push(rec);
      trimCount();
      save();
    }

    function clear() {
      items.length = 0;
      save();
    }

    return { items, loaded, push, save, clear };
  }

  globalThis.LLMSessionBuffer = Object.freeze({ createSessionBuffer });
})();
