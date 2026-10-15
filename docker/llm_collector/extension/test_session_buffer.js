const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { test } = require("node:test");
const vm = require("node:vm");

const SOURCE = process.env.SESSION_BUFFER_SOURCE || require.resolve("./session_buffer.js");

function load(sessionStore = {}, control = {}) {
  const runtime = {};
  const reads = [], writes = [];
  control.read = () => reads.shift()?.();
  control.write = () => writes.shift()?.();
  const run = (kind, fn) => {
    const done = () => {
      if (control[kind + 'Error']) runtime.lastError = { message: control[kind + 'Error'] };
      try { fn(!runtime.lastError); } finally { delete runtime.lastError; }
    };
    if (control['defer' + kind]) (kind === 'Read' ? reads : writes).push(done); else done();
  };
  const session = {
    get(keys, cb) { run('Read', () => cb(JSON.parse(JSON.stringify(Object.fromEntries(keys.filter(k => k in sessionStore).map(k => [k, sessionStore[k]])))))); },
    set(obj, cb) { control.attempts = (control.attempts || 0) + 1; const snapshot = JSON.parse(JSON.stringify(obj)); run('Write', ok => { if (ok) Object.assign(sessionStore, snapshot); cb(); }); }
  };
  const context = vm.createContext({ chrome: { runtime, storage: { session } }, setTimeout, console, TextEncoder });
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

test('oversized Unicode singleton is evicted on admission and late growth', async () => {
  const { create } = load();
  const evicted = [];
  const buf = create({ key: 'k', maxItems: 10, maxBytes: 100, onEvict: rec => evicted.push(rec) });
  await buf.loaded;
  buf.push({ text: '界'.repeat(40) });
  assert.equal(buf.items.length, 0);
  const rec = buf.push({ text: 'small' });
  rec.text = '界'.repeat(40);
  await buf.save();
  assert.equal(buf.items.length, 0);
  assert.equal(evicted.length, 2);
});

test('failed read never overwrites unread records and reload merges staging', async () => {
  const control = { ReadError: 'synthetic unread storage' };
  const { create, sessionStore } = load({ k: [{ id: 'stored' }] }, control);
  const buf = create({ key: 'k', maxItems: 10 });
  await buf.loaded;
  buf.push({ id: 'staged' });
  await settle();
  assert.deepEqual(sessionStore.k, [{ id: 'stored' }]);
  assert.equal(buf.status().state, 'error');
  delete control.ReadError;
  assert.equal((await buf.reload()).ok, true);
  await buf.flush();
  assert.deepEqual(sessionStore.k, [{ id: 'stored' }, { id: 'staged' }]);
});

test('quota rejection retries oldest halves only three times and later clear recovers', async () => {
  const control = {};
  const { create, sessionStore } = load({}, control);
  const buf = create({ key: 'k', maxItems: 20 });
  await buf.loaded;
  control.WriteError = 'QUOTA_BYTES quota exceeded';
  const before = control.attempts;
  for (let i = 0; i < 12; i++) buf.push({ i });
  await assert.rejects(buf.flush(), /quota/i);
  assert.equal(control.attempts - before, 4);
  assert.deepEqual(Array.from(buf.items, rec => rec.i), [11]);
  assert.equal(buf.status().state, 'error');
  delete control.WriteError;
  await buf.clear();
  await buf.flush();
  assert.deepEqual(sessionStore.k, []);
  assert.equal(buf.status().state, 'ready');
});

test('clear supersedes deferred restoration and writes the latest empty generation', async () => {
  const control = { deferRead: true, deferWrite: true };
  const { create, sessionStore } = load({ k: [{ id: 'old' }] }, control);
  const buf = create({ key: 'k', maxItems: 10 });
  buf.push({ id: 'staged' });
  const clearing = buf.clear();
  control.read();
  await new Promise(r => setTimeout(r, 0));
  control.write();
  await clearing;
  await buf.flush();
  assert.deepEqual(sessionStore.k, []);
});

test('reload recovers a failed write without duplicating readable records', async () => {
  const control = {}, { create, sessionStore } = load({}, control);
  const buf = create({ key: 'k', maxItems: 10 });
  await buf.loaded;
  await buf.flush();
  control.WriteError = 'synthetic denied write';
  buf.push({ id: 'new' });
  await assert.rejects(buf.flush(), /denied/);
  delete control.WriteError;
  await buf.reload();
  assert.deepEqual(sessionStore.k, [{ id: 'new' }]);
  assert.equal(buf.status().state, 'ready');
});

test('an obsolete quota failure cannot retry old content over clear', async () => {
  const control = {}, { create, sessionStore } = load({}, control);
  const buf = create({ key: 'k', maxItems: 10 });
  await buf.loaded; await buf.flush();
  control.deferWrite = true;
  buf.push({ id: 'old generation' });
  await new Promise(r => setTimeout(r, 0));
  const clearing = buf.clear();
  control.WriteError = 'QUOTA_BYTES exceeded';
  control.write();
  await new Promise(r => setTimeout(r, 0));
  delete control.WriteError;
  control.write();
  await clearing;
  assert.deepEqual(sessionStore.k, []);
  assert.equal(buf.status().state, 'ready');
});

test('concurrent reloads merge an unread store only once', async () => {
  const control = { ReadError: 'synthetic failed initial read' };
  const { create, sessionStore } = load({ k: [{ id: 'stored' }] }, control);
  const buf = create({ key: 'k', maxItems: 10 });
  await buf.loaded;
  buf.push({ id: 'staged' });
  delete control.ReadError; control.deferRead = true;
  const first = buf.reload(), second = buf.reload();
  await new Promise(r => setTimeout(r, 0));
  control.read(); control.read();
  await Promise.all([first, second]);
  await buf.flush();
  assert.deepEqual(sessionStore.k, [{ id: 'stored' }, { id: 'staged' }]);
});

test("drops the oldest records until the stored buffer fits maxChars", async () => {
  const { create, sessionStore } = load();
  const buf = create({ key: "k", maxItems: 1000, maxChars: 2000 });
  for (let i = 0; i < 100; i++) buf.push({ i, pad: "x".repeat(50) });
  await settle();

  assert.ok(JSON.stringify(sessionStore.k).length <= 2000, "stored buffer exceeds maxChars");
  assert.equal(sessionStore.k.at(-1).i, 99, "newest record was dropped");
});
