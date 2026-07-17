// Shared collector reachability probe for the extension service worker.
// Kept independent of Chrome APIs so its failure classification can be tested.

(() => {
  const DEFAULT_TIMEOUT_MS = 2000;

  function result(state, message, startedAt, extra = {}) {
    return {
      state,
      message,
      checkedAt: Date.now(),
      latencyMs: Math.max(0, Date.now() - startedAt),
      ...extra
    };
  }

  async function checkCollectorConnection({
    collectorUrl,
    apiKey,
    fetchImpl = globalThis.fetch.bind(globalThis),
    timeoutMs = DEFAULT_TIMEOUT_MS
  }) {
    const startedAt = Date.now();
    const controller = new AbortController();
    let timeoutHandle;

    const timeout = new Promise((_, reject) => {
      timeoutHandle = setTimeout(() => {
        controller.abort();
        const error = new Error(`Collector request timed out after ${timeoutMs} ms.`);
        error.name = "TimeoutError";
        reject(error);
      }, timeoutMs);
    });

    try {
      const baseUrl = String(collectorUrl || "").replace(/\/+$/, "");
      const response = await Promise.race([
        fetchImpl(`${baseUrl}/counters`, {
          headers: { "X-API-KEY": apiKey },
          cache: "no-store",
          signal: controller.signal
        }),
        timeout
      ]);

      if (response.status === 401 || response.status === 403) {
        return result(
          "authentication_error",
          "Collector rejected the configured API key.",
          startedAt,
          { httpStatus: response.status }
        );
      }

      if (!response.ok) {
        return result(
          "server_error",
          `Collector returned HTTP ${response.status}.`,
          startedAt,
          { httpStatus: response.status }
        );
      }

      let payload;
      try {
        payload = await response.json();
      } catch {
        return result("invalid_response", "Collector returned invalid JSON.", startedAt, {
          httpStatus: response.status
        });
      }

      if (!payload || typeof payload.counters !== "object" || Array.isArray(payload.counters)) {
        return result("invalid_response", "Collector response did not include valid counters.", startedAt, {
          httpStatus: response.status
        });
      }

      return result("connected", "Authenticated collector response received.", startedAt, {
        httpStatus: response.status,
        serverCounters: payload.counters
      });
    } catch (error) {
      if (error?.name === "TimeoutError" || error?.name === "AbortError") {
        return result("timeout", `Collector did not respond within ${timeoutMs} ms.`, startedAt);
      }
      return result("unreachable", "Could not reach the collector.", startedAt);
    } finally {
      clearTimeout(timeoutHandle);
    }
  }

  globalThis.LLMCollectorStatus = Object.freeze({
    DEFAULT_TIMEOUT_MS,
    checkCollectorConnection
  });
})();
