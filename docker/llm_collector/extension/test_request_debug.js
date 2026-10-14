const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { test } = require("node:test");
const vm = require("node:vm");

const script = readFileSync(require.resolve("./request_debug.js"), "utf8");
const context = vm.createContext({ URL });
vm.runInContext(script, context);

const { rpcidsFromUrl } = context.LLMRequestDebug;

const BATCH = "https://gemini.google.com/_/BardChatUi/data/batchexecute";

test("returns only the rpcids parameter from a batchexecute URL", () => {
  const url = new URL(`${BATCH}?rpcids=AbC1d&source-path=%2Fapp&f.sid=SYNTHETIC_SESSION_ID&_reqid=1234&rt=c`);

  assert.equal(rpcidsFromUrl(url), "AbC1d");
});

test("keeps every id of a multi-RPC batch", () => {
  const url = new URL(`${BATCH}?rpcids=AbC1d%2CxYz9_&f.sid=SYNTHETIC_SESSION_ID`);

  assert.equal(rpcidsFromUrl(url), "AbC1d,xYz9_");
});

test("returns null when the URL has no rpcids parameter", () => {
  const url = new URL("https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate?f.sid=SYNTHETIC_SESSION_ID");

  assert.equal(rpcidsFromUrl(url), null);
});

test("refuses an rpcids value that is not a plain id list", () => {
  const url = new URL(`${BATCH}?rpcids=${encodeURIComponent("<img src=x onerror=alert(1)>")}`);

  assert.equal(rpcidsFromUrl(url), "invalid");
});
