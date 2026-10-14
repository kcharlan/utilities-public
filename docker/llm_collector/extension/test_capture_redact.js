const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { test } = require("node:test");
const vm = require("node:vm");

const context = vm.createContext({ URL, URLSearchParams, TextDecoder, TextEncoder });
vm.runInContext(readFileSync(require.resolve("./capture_redact.js"), "utf8"), context);
const { redactUrl, redactHeaders, redactBody, scrubText, MAX_VALUE_CHARS } = context.LLMCaptureRedact;
const plain = v => JSON.parse(JSON.stringify(v));

test("redacts WebChannel session ids and keeps protocol fields", () => {
  const url = redactUrl("https://geminiweb-pa.clients6.google.com/v1/processSession" +
    "?VER=8&gsessionid=SYNTHETIC_GSESSION&SID=SYNTHETIC_SID&RID=12&AID=3&TYPE=terminate&zx=abc&t=1");

  assert.equal(url, "https://geminiweb-pa.clients6.google.com/v1/processSession" +
    "?VER=8&gsessionid=REDACTED&SID=REDACTED&RID=12&AID=3&TYPE=terminate&zx=abc&t=1");
});

test("redacts batchexecute session and XSRF parameters and keeps rpcids", () => {
  const url = redactUrl("https://gemini.google.com/_/BardChatUi/data/batchexecute" +
    "?rpcids=PCck7e&f.sid=SYNTHETIC_FSID&bl=boq_synthetic&at=SYNTHETIC_AT&_reqid=5&rt=c#frag");

  assert.equal(url, "https://gemini.google.com/_/BardChatUi/data/batchexecute" +
    "?rpcids=PCck7e&f.sid=REDACTED&bl=boq_synthetic&at=REDACTED&_reqid=5&rt=c");
});

test("redacts credential headers and keeps the rest", () => {
  const headers = plain(redactHeaders([
    { name: "Authorization", value: "SAPISIDHASH 123_SYNTHETIC" },
    { name: "Cookie", value: "SID=SYNTHETIC" },
    { name: "X-Goog-Api-Key", value: "SYNTHETIC_KEY" },
    { name: "X-Client-Data", value: "SYNTHETIC_VARIATIONS" },
    { name: "Content-Type", value: "application/x-www-form-urlencoded;charset=utf-8" },
    { name: "X-Goog-Ext-525001261-Jspb", value: "[1,null,\"synthetic-model\"]" }
  ]));

  assert.deepEqual(headers, [
    { name: "Authorization", value: "REDACTED" },
    { name: "Cookie", value: "REDACTED" },
    { name: "X-Goog-Api-Key", value: "REDACTED" },
    { name: "X-Client-Data", value: "REDACTED" },
    { name: "Content-Type", value: "application/x-www-form-urlencoded;charset=utf-8" },
    { name: "X-Goog-Ext-525001261-Jspb", value: "[1,null,\"synthetic-model\"]" }
  ]);
});

test("scrubs known token formats anywhere in text", () => {
  const text = scrubText('{"access_token":"SYNTHETIC1","note":"keep me"} Bearer abc.def-ghi ' +
    "ya29.SYNTHETIC_OAUTH AIza" + "S".repeat(35));

  assert.equal(text, '{"access_token":"REDACTED","note":"keep me"} Bearer REDACTED REDACTED REDACTED');
});

test("redacts sensitive form fields and keeps payload fields", () => {
  const body = plain(redactBody({ formData: { "f.req": ["[[\"synthetic prompt\"]]"], at: ["SYNTHETIC_AT"] } }));

  assert.deepEqual(body, { formData: { "f.req": ["[[\"synthetic prompt\"]]"], at: ["REDACTED"] } });
});

test("parses url-encoded raw bodies and redacts sensitive fields", () => {
  const bytes = new TextEncoder().encode("count=1&ofs=0&req0___data__=%5B%22synthetic%22%5D&at=SYNTHETIC_AT").buffer;
  const body = plain(redactBody({ raw: [{ bytes }] }));

  assert.deepEqual(body, {
    bytes: bytes.byteLength,
    formData: { count: ["1"], ofs: ["0"], req0___data__: ["[\"synthetic\"]"], at: ["REDACTED"] }
  });
});

test("keeps non-form raw bodies as scrubbed, truncated text", () => {
  const big = "x".repeat(MAX_VALUE_CHARS + 10);
  const bytes = new TextEncoder().encode(`{"token":"SYNTHETIC","data":"${big}"}`).buffer;
  const body = plain(redactBody({ raw: [{ bytes }] }));

  assert.equal(body.truncated, true);
  assert.equal(body.text.length, MAX_VALUE_CHARS);
  assert.ok(body.text.startsWith('{"token":"REDACTED","data":"xxx'));
});

test("never records local file paths from uploads", () => {
  const body = plain(redactBody({ raw: [{ file: "/Users/synthetic/secret.pdf" }] }));

  assert.deepEqual(body, { bytes: 0, text: "<file>" });
});

test("redacts credentials inside a percent-encoded header block in the URL", () => {
  const block = "Authorization:SAPISIDHASH 1700000000_SYNTHETICHASH\r\n" +
    "X-Goog-AuthUser:0\r\n" +
    "X-Goog-Api-Key:AIza" + "S".repeat(35) + "\r\n" +
    "X-Server-Token:SYNTHETIC_SERVER_TOKEN\r\n" +
    "X-WebChannel-Content-Type:application/json+protobuf\r\n";
  const url = redactUrl("https://geminiweb-pa.clients6.google.com/v1/processSession" +
    `?VER=8&RID=1&CVER=22&%24httpHeaders=${encodeURIComponent(block)}&t=1`);
  const headers = decodeURIComponent(url.match(/%24httpHeaders=([^&]*)/)[1]);

  assert.ok(!/SYNTHETIC|AIzaS/.test(url), `secret survived: ${url}`);
  assert.equal(headers,
    "Authorization:REDACTED\r\nX-Goog-AuthUser:REDACTED\r\nX-Goog-Api-Key:REDACTED\r\n" +
    "X-Server-Token:REDACTED\r\nX-WebChannel-Content-Type:application/json+protobuf\r\n");
  assert.ok(url.includes("VER=8&RID=1&CVER=22&"), "protocol fields lost");
});

test("scrubs percent-encoded token formats", () => {
  assert.equal(scrubText("a=Bearer%20abc.def&b=SAPISIDHASH%201700_abc&c=SAPISIDHASH+1700_def"),
    "a=Bearer%20REDACTED&b=SAPISIDHASH%20REDACTED&c=SAPISIDHASH+REDACTED");
});

test("redacts WebSocket verify tokens and account identifiers", () => {
  const url = redactUrl("wss://ws.chatgpt.com/p3/ws/user/user-SYNTHETICUSERID1234/?verify=SYNTHETIC_VERIFY");
  const headers = plain(redactHeaders([
    { name: "chatgpt-account-id", value: "SYNTHETIC_ACCOUNT" },
    { name: "oai-did", value: "SYNTHETIC_DEVICE" }
  ]));

  assert.equal(url, "wss://ws.chatgpt.com/p3/ws/user/user-REDACTED/?verify=REDACTED");
  assert.deepEqual(headers.map(h => h.value), ["REDACTED", "REDACTED"]);
});
