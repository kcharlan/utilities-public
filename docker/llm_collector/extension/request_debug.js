// Debug-buffer fields derived from observed request URLs.
// Kept independent of Chrome APIs so it can be tested. Only the named query
// parameter is ever returned; session ids and other parameters are never read.

(() => {
  const RPCIDS_PATTERN = /^[A-Za-z0-9_]+(,[A-Za-z0-9_]+)*$/;

  // Google batchexecute calls name the RPCs they carry in `rpcids`; the path
  // alone cannot tell a prompt send from page or sidebar traffic.
  function rpcidsFromUrl(u) {
    const value = u.searchParams.get("rpcids");
    if (value === null) return null;
    return RPCIDS_PATTERN.test(value) ? value : "invalid";
  }

  globalThis.LLMRequestDebug = Object.freeze({ rpcidsFromUrl });
})();
