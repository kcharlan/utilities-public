const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { test } = require("node:test");
const vm = require("node:vm");

const script = readFileSync(require.resolve("./collector_status.js"), "utf8");
const context = vm.createContext({ AbortController, clearTimeout, Date, setTimeout });
vm.runInContext(script, context);

const { checkCollectorConnection } = context.LLMCollectorStatus;

function response(status, payload) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: async () => payload
  };
}

test("reports an authenticated collector response as connected", async () => {
  const status = await checkCollectorConnection({
    collectorUrl: "http://127.0.0.1:9000/",
    apiKey: "SYNTHETIC_TEST_KEY",
    fetchImpl: async (url, options) => {
      assert.equal(url, "http://127.0.0.1:9000/counters");
      assert.equal(options.headers["X-API-KEY"], "SYNTHETIC_TEST_KEY");
      assert.equal(options.cache, "no-store");
      assert.ok(options.signal instanceof AbortSignal);
      return response(200, { counters: { "synthetic.example": 3 } });
    }
  });

  assert.equal(status.state, "connected");
  assert.equal(status.httpStatus, 200);
  assert.deepEqual(status.serverCounters, { "synthetic.example": 3 });
  assert.equal(typeof status.checkedAt, "number");
});

test("distinguishes authentication failures from network failures", async () => {
  const authentication = await checkCollectorConnection({
    collectorUrl: "http://127.0.0.1:9000",
    apiKey: "SYNTHETIC_WRONG_KEY",
    fetchImpl: async () => response(403, { error: "forbidden" })
  });
  const network = await checkCollectorConnection({
    collectorUrl: "http://127.0.0.1:9000",
    apiKey: "SYNTHETIC_TEST_KEY",
    fetchImpl: async () => {
      throw new TypeError("synthetic connection refusal");
    }
  });

  assert.equal(authentication.state, "authentication_error");
  assert.equal(authentication.httpStatus, 403);
  assert.equal(network.state, "unreachable");
});

test("reports server errors and malformed successful responses", async () => {
  const serverError = await checkCollectorConnection({
    collectorUrl: "http://127.0.0.1:9000",
    apiKey: "SYNTHETIC_TEST_KEY",
    fetchImpl: async () => response(503, { error: "synthetic outage" })
  });
  const invalidResponse = await checkCollectorConnection({
    collectorUrl: "http://127.0.0.1:9000",
    apiKey: "SYNTHETIC_TEST_KEY",
    fetchImpl: async () => response(200, { unexpected: true })
  });

  assert.equal(serverError.state, "server_error");
  assert.equal(serverError.httpStatus, 503);
  assert.equal(invalidResponse.state, "invalid_response");
});

test("bounds an unresponsive collector request", async () => {
  const status = await checkCollectorConnection({
    collectorUrl: "http://127.0.0.1:9000",
    apiKey: "SYNTHETIC_TEST_KEY",
    timeoutMs: 10,
    fetchImpl: async () => new Promise(() => {})
  });

  assert.equal(status.state, "timeout");
  assert.match(status.message, /10 ms/);
});
