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

const rawBody = text => plain(redactBody({ raw: [{ bytes: new TextEncoder().encode(text).buffer }] }));

test("raw JSON redacts sensitive members regardless of value type", () => {
  const body = rawBody('{"at":"SYNTHETIC_AT","sid":"SYNTHETIC_SID","account_id":"SYNTHETIC_ACCOUNT","authorization":{"value":"SYNTHETIC_AUTH"},"token":["SYNTHETIC_TOKEN"],"nested":[{"\\u0073id":42,"verify":false,"secret":null,"prompt":"synthetic prompt","data":"{\\"at\\":\\"SYNTHETIC_NESTED\\"}"}]}');
  assert.deepEqual(JSON.parse(body.text), {
    at: "REDACTED", sid: "REDACTED", account_id: "REDACTED", authorization: "REDACTED", token: "REDACTED",
    nested: [{ sid: "REDACTED", verify: "REDACTED", secret: "REDACTED", prompt: "synthetic prompt", data: '{"at":"REDACTED"}' }]
  });
});

test("encoded containers use the shared policy", () => {
  for (const ending of ["", "\r\n", "\n", "\r"]) {
    const url = new URL(redactUrl('https://example.invalid/?VER=8&RID=12&plain=%2f&%24HtTpHeAdErS=' +
      encodeURIComponent('X-Server-Token:SYNTHETIC_TOKEN' + ending) +
      '&data=%7B%22token%22%3A%22SYNTHETIC_TOKEN%22%7D&note=Bearer%20SYNTHETIC%2FSECRET'));
    assert.equal(url.searchParams.get('$HtTpHeAdErS'), 'X-Server-Token:REDACTED' + ending);
    assert.equal(url.searchParams.get('data'), '{"token":"REDACTED"}');
    assert.equal(url.searchParams.get('note'), 'Bearer REDACTED');
    assert.ok(url.search.includes('VER=8&RID=12&plain=%2f'));
  }
  for (const name of ['Location', 'Content-Location', 'Referer', 'Refresh', 'Link']) {
    const target = '/user-SYNTHETICUSERID1234/?sid=SYNTHETIC_SID';
    const value = name === 'Refresh' ? '0; url=' + target : name === 'Link' ? '<' + target + '>; rel="next"' : target;
    const result = redactHeaders([{ name, value }])[0].value;
    assert.ok(!result.includes('SYNTHETIC'), name);
    assert.ok(result.includes('sid=REDACTED'), name);
  }
  assert.equal(redactHeaders([{ name: 'Content-Location', value: 'https://[' }])[0].value, '<omitted>');
  assert.equal(new URL(redactUrl('https://example.invalid/?data=%ZZ')).searchParams.get('data'), '<omitted>');
  assert.equal(new URL(redactUrl('https://example.invalid/?data=%257B%2522at%2522%253A%2522SYNTHETIC_AT%2522%257D')).searchParams.get('data'), '%7B%22at%22%3A%22REDACTED%22%7D');
  assert.ok(!redactUrl('https://example.invalid/?data=%25257B%252522at%252522%25253A%252522SYNTHETIC_AT%252522%25257D').includes('SYNTHETIC'));
});

test("form and JSON keys cannot mutate prototypes", () => {
  const form = rawBody('__proto__=first&__proto__=second&constructor=third&toString=fourth');
  assert.deepEqual(form.formData, { ['__proto__']: ['first', 'second'], constructor: ['third'], toString: ['fourth'] });
  const json = JSON.parse(rawBody('{"__proto__":{"at":"SYNTHETIC_AT"},"constructor":{"sid":12},"prompt":"keep"}').text);
  assert.deepEqual(json, { ['__proto__']: { at: 'REDACTED' }, constructor: { sid: 'REDACTED' }, prompt: 'keep' });
  assert.equal({}.at, undefined);
});

test("uninspectable structures are omitted without raw prefixes", () => {
  assert.equal(rawBody('{"sid":"SYNTHETIC_AT"').text, '<omitted>');
  const deep = JSON.stringify(Array.from({ length: 1 }, () => 'synthetic prompt'));
  const nested = '['.repeat(34) + deep + ']'.repeat(34);
  assert.ok(!rawBody(nested).text.includes('synthetic prompt'));
  const wide = rawBody(JSON.stringify(Array(10002).fill('synthetic prompt'))).text;
  assert.ok(wide.includes('<omitted>'));
  const cycle = {}; cycle.self = cycle;
  assert.equal(context.LLMCaptureRedact.sanitizeDiagnosticRecord('capture', cycle), null);
});

test("nested names and named header containers cannot bypass the policy", () => {
  const url = new URL(redactUrl('https://example.invalid/?%2573id=SYNTHETIC_SID&%ZZ=SYNTHETIC_BAD&%252573id=SYNTHETIC_DEEP'));
  assert.ok(!url.href.includes('SYNTHETIC'));
  const header = 'X-Server-Token:SYNTHETIC_TOKEN';
  assert.equal(rawBody('%24httpHeaders=' + encodeURIComponent(header)).formData.$httpHeaders[0], 'X-Server-Token:REDACTED');
  assert.equal(JSON.parse(rawBody(JSON.stringify({ $httpHeaders: header })).text).$httpHeaders, 'X-Server-Token:REDACTED');
});

test("encoded paths and ordinary URL/header diagnostics stay readable", () => {
  const path = context.LLMCaptureRedact.redactPath('/example/user-%53YNTHETICUSERID1234/');
  assert.equal(path, '/example/user-REDACTED/');
  assert.equal(redactHeaders([{ name: 'Link', value: '<https://[>; rel="next"' }])[0].value, '<omitted>');
  assert.equal(redactHeaders([{ name: 'Location', value: 'javascript:synthetic' }])[0].value, '<omitted>');
  const safe = context.LLMCaptureRedact.sanitizeDiagnosticRecord('capture', {
    body: { formData: { at: ['SYNTHETIC_AT'], prompt: ['synthetic prompt'] } },
    requestHeaders: [{ name: 'Location', value: '/?sid=SYNTHETIC_SID' }]
  });
  assert.deepEqual(plain(safe).body.formData, { at: ['REDACTED'], prompt: ['synthetic prompt'] });
  assert.equal(safe.requestHeaders[0].value, '/?sid=REDACTED');
  assert.equal(redactHeaders([{ name: 'Location', value: '?sid=SYNTHETIC_SID' }])[0].value, '?sid=REDACTED');
  assert.equal(redactHeaders([{ name: 'Location', value: '../next?sid=SYNTHETIC_SID' }])[0].value, '../next?sid=REDACTED');
});

test("inspection budgets cover form fields, headers, and decoded query values", () => {
  const form = Object.fromEntries(Array.from({ length: 10001 }, (_, i) => ['field' + i, ['synthetic value']]));
  const result = plain(redactBody({ formData: form }));
  assert.ok(JSON.stringify(result).includes('<omitted>'));
  assert.ok(!JSON.stringify(result).includes('synthetic value'));
  const headers = Array.from({ length: 10001 }, () => ({ name: 'X-Ordinary', value: 'synthetic value' }));
  const safe = JSON.stringify(redactHeaders(headers));
  assert.ok(safe.includes('<omitted>'));
  assert.ok(!safe.includes('synthetic value'));
  const query = Array.from({ length: 10001 }, () => 'data=synthetic').join('&');
  assert.equal(redactUrl('https://example.invalid/?' + query), '<omitted>');
});
