const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { test } = require("node:test");
const vm = require("node:vm");

function loadPopupStatusRenderer() {
  const elements = {
    status: { dataset: {} },
    statusLabel: { textContent: "" },
    statusDetail: { textContent: "" }
  };
  const document = {
    addEventListener() {},
    getElementById(id) {
      return elements[id] || null;
    }
  };
  const context = vm.createContext({
    Blob,
    URL,
    clearInterval,
    clearTimeout,
    console,
    document,
    setInterval,
    setTimeout,
    window: { addEventListener() {} }
  });
  vm.runInContext(readFileSync(require.resolve("./popup.js"), "utf8"), context);
  return { context, elements };
}

test("renders a successful authenticated probe as connected", () => {
  const { context, elements } = loadPopupStatusRenderer();

  context.renderConnectionStatus({
    state: "connected",
    checkedAt: Date.now(),
    latencyMs: 24
  });

  assert.equal(elements.status.dataset.state, "connected");
  assert.equal(elements.statusLabel.textContent, "Collector connected");
  assert.match(elements.statusDetail.textContent, /24 ms/);
});

test("renders authentication and network failures as errors", () => {
  const { context, elements } = loadPopupStatusRenderer();

  context.renderConnectionStatus({ state: "authentication_error", httpStatus: 403 });
  assert.equal(elements.status.dataset.state, "error");
  assert.equal(elements.statusLabel.textContent, "Authentication failed");
  assert.match(elements.statusDetail.textContent, /HTTP 403/);

  context.renderConnectionStatus({ state: "unreachable", message: "Could not reach the collector." });
  assert.equal(elements.status.dataset.state, "error");
  assert.equal(elements.statusLabel.textContent, "Collector unreachable");
});

test("renders configuration and checking states without relying on color", () => {
  const { context, elements } = loadPopupStatusRenderer();

  context.renderConnectionStatus(
    { state: "configuration_error" },
    "Synthetic configuration is missing."
  );
  assert.equal(elements.status.dataset.state, "error");
  assert.equal(elements.statusLabel.textContent, "Configuration required");
  assert.equal(elements.statusDetail.textContent, "Synthetic configuration is missing.");

  context.showCheckingStatus();
  assert.equal(elements.status.dataset.state, "checking");
  assert.equal(elements.statusLabel.textContent, "Checking…");
});
