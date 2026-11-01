import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { pathToFileURL } from 'node:url';

const scratch = await fs.mkdtemp(path.join(os.tmpdir(), 'webserver-index-test-'));
const webroot = path.join(scratch, 'webroot');
const config = path.join(scratch, 'config');
await fs.mkdir(webroot);
await fs.mkdir(config);
process.env.WEBROOT = webroot;
process.env.CONFIG_ROOT = config;
process.env.CONFIG_FILE = path.join(config, 'endpoints.json');
process.env.FASTIFY_DISABLE_LISTEN = 'true';
process.env.PUBLIC_PORT = '3000';
process.env.HOST_DOCKER_GATEWAY = '127.0.0.1';
const serverUrl = pathToFileURL(path.resolve('docker/webserver/index/server.js')).href;
const { app } = await import(serverUrl);
after(async () => { if (app) await app.close(); await fs.rm(scratch, { recursive: true }); });
const host = 'localhost:3000';
const get = (url, headers = {}) => app.inject({ method: 'GET', url, headers: { host, ...headers } });
const post = (payload, headers = {}) => app.inject({ method: 'POST', url: '/configure/api/endpoints', headers: { host, origin: `http://${host}`, ...headers }, payload });
async function importWithWarning(url, expected) {
  const warnings = [];
  const original = console.warn;
  console.warn = (...args) => warnings.push(args);
  try {
    const result = await import(url);
    assert.deepEqual(warnings, [[expected]]);
    return result;
  } finally { console.warn = original; }
}

test('exports an injectable application', () => assert.ok(app));

test('rejects foreign Host and foreign or missing Origin on mutations', async () => {
  assert.equal((await get('/configure', { host: 'evil.example:3000' })).statusCode, 403);
  const payload = { name: 'Synthetic', path: '/synthetic', target: 'http://example.invalid' };
  assert.equal((await post(payload, { origin: 'http://evil.example' })).statusCode, 403);
  assert.equal((await app.inject({ method: 'POST', url: '/configure/api/endpoints', headers: { host }, payload })).statusCode, 403);
  assert.equal((await post(payload)).statusCode, 201);
});

test('browser hides dotfiles, outside symlinks and tolerates dangling links', async () => {
  await fs.writeFile(path.join(webroot, '.hidden'), 'SECRET');
  await fs.writeFile(path.join(scratch, 'outside'), 'OUTSIDE');
  await fs.symlink(scratch, path.join(webroot, 'escape'));
  await fs.symlink(path.join(scratch, 'missing'), path.join(webroot, 'dangling'));
  assert.equal((await get('/files')).statusCode, 200);
  assert.equal((await get('/.hidden')).statusCode, 404);
  assert.equal((await get('/escape/')).statusCode, 404);
});

test('reserved file browser never proxies through sticky endpoint', async () => {
  const before = await fs.readFile(process.env.CONFIG_FILE, 'utf8');
  const response = await get('/files', { referer: `http://${host}/synthetic` });
  assert.equal(response.statusCode, 200);
  assert.match(response.body, /All Files/);
  assert.equal(await fs.readFile(process.env.CONFIG_FILE, 'utf8'), before);
});

test('invalid configured public port fails closed', async () => {
  process.env.PUBLIC_PORT = '3000evil';
  try { assert.equal((await get('/configure', { host: 'localhost:3000evil' })).statusCode, 403); }
  finally { process.env.PUBLIC_PORT = '3000'; }
});

test('explicit and same-origin referer proxy routes work without cross-app fallback', async () => {
  const requests = [];
  const upstream = http.createServer((req, res) => {
    requests.push({ url: req.url, cookie: req.headers.cookie });
    res.end('synthetic upstream');
  });
  await new Promise(resolve => upstream.listen(0, '127.0.0.1', resolve));
  try {
    const target = `http://127.0.0.1:${upstream.address().port}`;
    const created = await post({ name: 'Local fixture', path: '/fixture', target });
    assert.equal(created.statusCode, 201);
    assert.equal((await get('/fixture/asset.js')).body, 'synthetic upstream');
    assert.equal((await get('/asset.js', { referer: `http://${host}/fixture/page` })).body, 'synthetic upstream');
    assert.equal((await get('/fixture/a%2Fb%3Fc%23d%25e?x=one%26two')).body, 'synthetic upstream');
    const before = requests.length;
    await get('/unrelated', { cookie: 'other-app=synthetic' });
    await get('/files', { referer: `http://${host}/fixture/page`, cookie: 'other-app=synthetic' });
    await get('/%66iles', { referer: `http://${host}/fixture/page`, cookie: 'other-app=synthetic' });
    await get('/unrelated', { referer: 'http://evil.example/fixture/page', cookie: 'other-app=synthetic' });
    assert.equal(requests.length, before);
    assert.deepEqual(requests.map(req => req.url), ['/asset.js', '/asset.js', '/a%2Fb%3Fc%23d%25e?x=one%26two']);
  } finally { await new Promise(resolve => upstream.close(resolve)); }
});

test('configuration writes leave a pre-existing fixed temporary file untouched', async () => {
  const fixed = `${process.env.CONFIG_FILE}.tmp`;
  await fs.writeFile(fixed, 'synthetic marker');
  const response = await post({ name: 'Temporary fixture', path: '/temporary-fixture', target: 'http://example.invalid' });
  assert.equal(response.statusCode, 201);
  assert.equal(await fs.readFile(fixed, 'utf8'), 'synthetic marker');
});

test('invalid stored entry is quarantined while valid routes survive', async () => {
  const dir = await fs.mkdtemp(path.join(scratch, 'bad-entry-'));
  const file = path.join(dir, 'endpoints.json');
  const original = JSON.stringify({ endpoints: [
    { id: 'good', name: 'Good', path: '/good', target: 'http://example.invalid', enabled: true },
    { id: 'bad', name: 'Bad', path: '/bad', target: 'not a URL' }
  ] });
  await fs.writeFile(file, original);
  process.env.CONFIG_FILE = file;
  const other = (await importWithWarning(`${serverUrl}?bad-entry`, '[configure] Configuration contained invalid entries; the original was quarantined.')).app;
  try {
    const response = await other.inject({ method: 'GET', url: '/configure/api/endpoints', headers: { host } });
    assert.deepEqual(response.json().endpoints.map(ep => ep.id), ['good']);
    assert.match(response.json().error, /config/i);
    const quarantines = (await fs.readdir(dir)).filter(name => name.startsWith('endpoints.json.corrupt-'));
    assert.equal(quarantines.length, 1);
    assert.equal(await fs.readFile(path.join(dir, quarantines[0]), 'utf8'), original);
    await other.close();
    const restarted = (await import(`${serverUrl}?bad-entry-restart`)).app;
    try {
      const restored = await restarted.inject({ method: 'GET', url: '/configure/api/endpoints', headers: { host } });
      assert.deepEqual(restored.json().endpoints.map(ep => ep.id), ['good']);
      assert.match(restored.json().error, /config/i);
    } finally { await restarted.close(); }
  } finally { await other.close(); process.env.CONFIG_FILE = path.join(config, 'endpoints.json'); }
});

test('wholly malformed config is quarantined without silently creating a default', async () => {
  const dir = await fs.mkdtemp(path.join(scratch, 'bad-json-'));
  const file = path.join(dir, 'endpoints.json');
  await fs.writeFile(file, '{bad json');
  process.env.CONFIG_FILE = file;
  const other = (await importWithWarning(`${serverUrl}?bad-json`, '[configure] Configuration is corrupt; the original was quarantined.')).app;
  try {
    const response = await other.inject({ method: 'GET', url: '/configure/api/endpoints', headers: { host } });
    assert.match(response.json().error, /config/i);
    assert.equal((await fs.readdir(dir)).filter(name => name.startsWith('endpoints.json.corrupt-')).length, 1);
    await assert.rejects(fs.access(file), { code: 'ENOENT' });
    await other.close();
    const restarted = (await import(`${serverUrl}?bad-json-restart`)).app;
    try {
      const restored = await restarted.inject({ method: 'GET', url: '/configure/api/endpoints', headers: { host } });
      assert.match(restored.json().error, /config/i);
      await assert.rejects(fs.access(file), { code: 'ENOENT' });
    } finally { await restarted.close(); }
  } finally { await other.close(); process.env.CONFIG_FILE = path.join(config, 'endpoints.json'); }
});

test('whole-file corruption restores routes from the last successful save', async () => {
  const dir = await fs.mkdtemp(path.join(scratch, 'last-good-'));
  const file = path.join(dir, 'endpoints.json');
  process.env.CONFIG_FILE = file;
  const first = (await import(`${serverUrl}?last-good-first`)).app;
  try {
    const response = await first.inject({ method: 'POST', url: '/configure/api/endpoints', headers: { host, origin: `http://${host}` }, payload: { name: 'Saved', path: '/saved', target: 'http://example.invalid' } });
    assert.equal(response.statusCode, 201);
    await first.close();
    await fs.writeFile(file, '{broken');
    const second = (await importWithWarning(`${serverUrl}?last-good-second`, '[configure] Configuration is corrupt; the original was quarantined.')).app;
    try {
      const restored = await second.inject({ method: 'GET', url: '/configure/api/endpoints', headers: { host } });
      assert.deepEqual(restored.json().endpoints.map(ep => ep.path), ['/saved']);
      assert.match(restored.json().error, /config/i);
    } finally { await second.close(); }
  } finally { await first.close(); process.env.CONFIG_FILE = path.join(config, 'endpoints.json'); }
});
