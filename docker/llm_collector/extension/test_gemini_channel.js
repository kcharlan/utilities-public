const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { test } = require("node:test");
const vm = require("node:vm");
const { encodeChannelMessages } = require('./background_harness.js');

const context = vm.createContext({ URLSearchParams, TextDecoder });
vm.runInContext(readFileSync(require.resolve("./gemini_channel.js"), "utf8"), context);
const { messageFields, promptCount } = context.LLMGeminiChannel;
const plain = v => JSON.parse(JSON.stringify(v));

// Synthetic WebChannel messages: base64 protobuf whose first byte is the tag.
const b64 = bytes => Buffer.from(bytes).toString("base64");
const PROMPT = b64([0x12, 0x0a, 0x08, 0x01, 0x4a, 0x06, 0x0a, 0x04, ...Buffer.from("test")]);
const SETUP = b64([0x0a, 0x03, 0x01, 0x02, 0x03]);
const END = "IgIIAQ==";   // field 4, as seen at the end of a turn

test("reads the field number of each channel message without decoding the rest", () => {
  const body = { formData: { count: ["3"], ofs: ["0"], req0___data__: [SETUP], req1___data__: [PROMPT], req2___data__: [END] } };

  assert.deepEqual(plain(messageFields(body)), [1, 2, 4]);
  assert.equal(promptCount(body), 1);
});

test("counts nothing for setup, end-of-turn, and handshake posts", () => {
  assert.equal(promptCount({ formData: { count: ["1"], ofs: ["0"], req0___data__: [SETUP] } }), 0);
  assert.equal(promptCount({ formData: { count: ["1"], ofs: ["0"], req0___data__: [END] } }), 0);
  assert.equal(promptCount({ formData: { count: ["1"] } }), 0);
  assert.equal(promptCount(undefined), 0);
});

test("reads raw url-encoded bodies the same way", () => {
  const text = `count=1&ofs=1&req0___data__=${encodeURIComponent(PROMPT)}`;
  const bytes = new TextEncoder().encode(text).buffer;

  assert.equal(promptCount({ raw: [{ bytes }] }), 1);
});

test("ignores messages that are not base64 protobuf", () => {
  const body = { formData: { count: ["2"], req0___data__: ["[[\"json\"]]"], req1___data__: [""] } };

  assert.deepEqual(plain(messageFields(body)), [null, null]);
  assert.equal(promptCount(body), 0);
});

test("orders messages by index, not by key order", () => {
  const body = { formData: { req10___data__: [END], req2___data__: [PROMPT] } };

  assert.deepEqual(plain(messageFields(body)), [2, 4]);
});

test('transport IDs use encoder offsets, including reordered sparse retry indexes', () => {
  // WireV8 restarts encoding when mapId 102 follows 250, choosing ofs=2.
  const body = encodeChannelMessages([{id:250,data:PROMPT},{id:102,data:END}]);
  assert.deepEqual(body.formData,{count:['2'],ofs:['2'],req248___data__:[PROMPT],req100___data__:[END]});
  assert.equal(typeof context.LLMGeminiChannel.describeMessages, 'function');
  assert.deepEqual(plain(context.LLMGeminiChannel.describeMessages(body)), [
    {index:100,id:102,field:4,isPrompt:false}, {index:248,id:250,field:2,isPrompt:true}
  ]);
});

test('raw chunk boundaries do not affect classification', () => {
  const text = `count=1&ofs=31&label=文🌈&req0___data__=${encodeURIComponent(PROMPT)}`;
  const bytes = new TextEncoder().encode(text);
  for (let split=1; split<bytes.length; split++) {
    const body = {raw:[{bytes:bytes.slice(0,split).buffer},{bytes:bytes.slice(split).buffer}]};
    assert.equal(promptCount(body),1,`split ${split}`);
    assert.deepEqual(plain(context.LLMGeminiChannel.describeMessages(body)),[{index:0,id:31,field:2,isPrompt:true}],`identity split ${split}`);
  }
});

test('invalid transport identities are rejected without timing fallback', () => {
  assert.equal(typeof context.LLMGeminiChannel.describeMessages, 'function');
  for (const formData of [
    {ofs:['-1'],req0___data__:[PROMPT]}, {ofs:['1.5'],req0___data__:[PROMPT]},
    {ofs:['9007199254740991'],req1___data__:[PROMPT]},
    {ofs:['0'],req9007199254740992___data__:[PROMPT]},
    {ofs:['0','1'],req0___data__:[PROMPT]}, {req0___data__:[PROMPT]},
    {ofs:['0'],req0___data__:[PROMPT,PROMPT]}
  ]) assert.throws(()=>context.LLMGeminiChannel.describeMessages({formData}), /channel-invalid/);
});
