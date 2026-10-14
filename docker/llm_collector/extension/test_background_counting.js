const assert = require("node:assert/strict");
const { test } = require("node:test");
const { loadBackground, tick } = require("./background_harness.js");

const CHANNEL = "https://geminiweb-pa.clients6.google.com/v1/processSession";
const b64 = bytes => Buffer.from(bytes).toString("base64");
const PROMPT = b64([0x12, 0x0a, 0x08, 0x01, 0x4a, 0x06, 0x0a, 0x04, ...Buffer.from("SYNTHETIC_PROMPT")]);
const SETUP = b64([0x0a, 0x03, 0x01, 0x02, 0x03]);
const END = "IgIIAQ==";

let nextId = 0;
function post(bg, url, requestBody, tabId = 7) {
  bg.fire("onBeforeRequest", {
    requestId: String(++nextId), method: "POST", type: "xmlhttprequest", tabId,
    initiator: "https://gemini.google.com", url, requestBody
  });
}
const channelBody = (data) => ({ formData: { count: ["1"], ofs: ["0"], req0___data__: [data] } });

// One Gemini turn as captured from the web app: handshake, setup, prompt,
// end-of-turn message, then the terminate beacon.
function geminiTurn(bg, rid) {
  post(bg, `${CHANNEL}?VER=8&RID=${rid}&CVER=22&t=1`, { formData: { count: ["1"] } });
  post(bg, `${CHANNEL}?VER=8&SID=SYNTHETIC_SID&RID=${rid + 1}&AID=0&t=1`, channelBody(SETUP));
  post(bg, `${CHANNEL}?VER=8&SID=SYNTHETIC_SID&RID=${rid + 2}&AID=2&t=1`, channelBody(PROMPT));
  post(bg, `${CHANNEL}?VER=8&SID=SYNTHETIC_SID&RID=${rid + 3}&AID=30&t=1`, channelBody(END));
  post(bg, `${CHANNEL}?VER=8&SID=SYNTHETIC_SID&RID=${rid + 4}&TYPE=terminate&t=1`, undefined);
}

async function pending(bg) {
  await tick();
  return (await bg.status()).pending;
}

test("counts one Gemini prompt per WebChannel turn, credited to gemini.google.com", async () => {
  const bg = loadBackground({ config: true });
  geminiTurn(bg, 100);

  assert.deepEqual(await pending(bg), { "gemini.google.com": 1 });
});

test("counts each of two turns sent in quick succession", async () => {
  const bg = loadBackground({ config: true });
  geminiTurn(bg, 100);
  geminiTurn(bg, 200);

  assert.deepEqual(await pending(bg), { "gemini.google.com": 2 });
});

test("logs channel posts with their message fields but never their content", async () => {
  const bg = loadBackground({ config: true });
  geminiTurn(bg, 100);
  const { debug } = await bg.status();
  const decisions = debug.map(d => `${d.decision}:${d.reason}`);

  assert.deepEqual(decisions, [
    "not-prompt:channel fields=none",
    "not-prompt:channel fields=1",
    "counted:channel fields=2; credited to gemini.google.com",
    "not-prompt:channel fields=4",
    "not-prompt:channel fields=none"
  ]);
  assert.ok(!JSON.stringify(debug).includes("SYNTHETIC_PROMPT"), "prompt content reached the debug log");
});

test("still counts the StreamGenerate endpoint", async () => {
  const bg = loadBackground({ config: true });
  post(bg, "https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate?bl=x");

  assert.deepEqual(await pending(bg), { "gemini.google.com": 1 });
});
