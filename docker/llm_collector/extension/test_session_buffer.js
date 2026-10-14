const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { test } = require("node:test");
const vm = require("node:vm");

const SOURCE = process.env.SESSION_BUFFER_SOURCE || require.resolve("./session_buffer.js");

function load(sessionStore = {}) {
  const session = {
    get(keys, cb) { cb(Object.fromEntries(keys.filter(k => k in sessionStore).map(k => [k, sessionStore[k]]))); },
    set(obj, cb) { Object.assign(sessionStore, JSON.parse(JSON.stringify(obj))); cb(); }
  };
  const context = vm.createContext({ chrome: { storage: { session } }, setTimeout, console });
  context.globalThis = context;
  vm.runInContext(readFileSync(SOURCE, "utf8"), context);
  return { create: context.LLMSessionBuffer.createSessionBuffer, sessionStore };
}

const settle = () => new Promise(resolve => setTimeout(resolve, 400));

test("keeps only the newest maxItems records", async () => {
  const { create, sessionStore } = load();
  const buf = create({ key: "k", maxItems: 3 });
  for (let i = 0; i < 5; i++) buf.push({ i });
  await settle();

  assert.deepEqual(sessionStore.k.map(r => r.i), [2, 3, 4]);
});

test("drops the oldest records until the stored buffer fits maxChars", async () => {
  const { create, sessionStore } = load();
  const buf = create({ key: "k", maxItems: 1000, maxChars: 2000 });
  for (let i = 0; i < 100; i++) buf.push({ i, pad: "x".repeat(50) });
  await settle();

  assert.ok(JSON.stringify(sessionStore.k).length <= 2000, "stored buffer exceeds maxChars");
  assert.equal(sessionStore.k.at(-1).i, 99, "newest record was dropped");
});
