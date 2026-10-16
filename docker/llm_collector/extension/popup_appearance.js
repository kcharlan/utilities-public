// Synchronous head script: choose the skin before styles can paint the popup.
(() => {
  const PREF_KEY = 'llmUsageCounter.appearance';
  function readPreference(storage) {
    try {
      const value = storage.getItem(PREF_KEY);
      return ['auto', 'meter', 'native'].includes(value) ? value : 'auto';
    } catch { return 'auto'; }
  }
  function writePreference(storage, value) {
    try { storage.setItem(PREF_KEY, value); return true; }
    catch { return false; }
  }
  function resolveSkin(pref, platform) {
    if (pref === 'meter' || pref === 'native') return pref;
    return platform === 'macOS' || /Mac/.test(platform) ? 'native' : 'meter';
  }
  function currentPlatform() {
    return navigator.userAgentData?.platform || navigator.platform || '';
  }
  function applySkin(doc, storage, platform) {
    doc.documentElement.dataset.skin = resolveSkin(readPreference(storage), platform);
  }
  globalThis.LLMPopupAppearance = { PREF_KEY, readPreference, writePreference, resolveSkin, applySkin, currentPlatform };
  let storage;
  try { storage = globalThis.localStorage; } catch { /* Storage access itself can be blocked. */ }
  applySkin(document, storage, currentPlatform());
})();
