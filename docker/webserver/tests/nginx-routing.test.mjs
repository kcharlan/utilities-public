import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import http from 'node:http';
import { PassThrough } from 'node:stream';

const config = process.env.NGINX_TEST_CONFIG || fileURLToPath(new URL('../nginx/default.conf', import.meta.url));
const docker = (...args) => execFileSync('docker', args, { encoding: 'utf8', timeout: 30000 }).trim();

function observeFrames(stream, onFrame) {
  let pending = Buffer.alloc(0);
  stream.on('data', chunk => {
    pending = Buffer.concat([pending, chunk]);
    while (pending.length >= 2) {
      const masked = Boolean(pending[1] & 0x80);
      let length = pending[1] & 0x7f, offset = 2;
      if (length === 126) {
        if (pending.length < 4) return;
        length = pending.readUInt16BE(2); offset = 4;
      } else if (length === 127) {
        if (pending.length < 10) return;
        const large = pending.readBigUInt64BE(2);
        if (large > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error('Fixture frame too large');
        length = Number(large); offset = 10;
      }
      const bodyOffset = offset + (masked ? 4 : 0);
      if (pending.length < bodyOffset + length) return;
      const body = Buffer.from(pending.subarray(bodyOffset, bodyOffset + length));
      if (masked) for (let i = 0; i < length; i++) body[i] ^= pending[offset + i % 4];
      pending = pending.subarray(bodyOffset + length);
      onFrame(body);
    }
  });
}

test('fixture frame reader handles fragmented and coalesced TCP data', () => {
  const stream = new PassThrough();
  const frames = [];
  observeFrames(stream, body => frames.push(body.toString()));
  stream.write(Buffer.from([0x81]));
  assert.deepEqual(frames, []);
  stream.write(Buffer.from([3, 97]));
  assert.deepEqual(frames, []);
  stream.write(Buffer.from([98, 99, 0x81, 1, 120]));
  assert.deepEqual(frames, ['abc', 'x']);
  stream.destroy();
});

test('real Nginx preserves calculator caching and shared routing', { timeout: 90000 }, async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'synthetic-nginx-'));
  const id = 'synthetic-nginx-' + randomUUID();
  const backend = id + '-backend', web = id + '-web';
  let networkCreated = false;
  t.after(async () => {
    const failures = [];
    for (const name of [web, backend]) {
      try { if (docker('container', 'ls', '-aq', '--filter', 'name=^/' + name + '$')) docker('rm', '-f', name); }
      catch (error) { failures.push(error); }
    }
    if (networkCreated) { try { docker('network', 'rm', id); } catch (error) { failures.push(error); } }
    await fs.rm(root, { recursive: true, force: true });
    if (failures.length) throw new AggregateError(failures, 'Disposable Docker cleanup failed');
  });
  const html = path.join(root, 'html');
  await fs.mkdir(path.join(html, 'calculators'), { recursive: true, mode: 0o755 });
  await fs.chmod(root, 0o755);
  for (const [name, body] of Object.entries({
    'index.html': 'synthetic landing', 'regular.js': 'synthetic regular asset',
    '.hidden.js': 'synthetic hidden asset', 'calculators/.hidden.js': 'synthetic hidden calculator',
    'calculators/example.html': 'synthetic calculator HTML',
    'calculators/example.js': 'synthetic calculator script',
  })) await fs.writeFile(path.join(html, name), body, { mode: 0o644 });
  await fs.writeFile(path.join(root, 'backend.cjs'), `
const http = require('node:http');
for (const [port, label] of [[3000, 'index'], [80, 'python'], [4000, 'node']]) {
  http.createServer((req, res) => {
    res.setHeader('Content-Type', 'text/plain');
    res.end(label + ':' + req.url);
  }).listen(port, '0.0.0.0');
}
`);
  // --pull=never makes missing prerequisites fail rather than acquiring images.
  const nginxImage = process.env.NGINX_TEST_IMAGE || 'nginx:stable-alpine';
  const nodeImage = process.env.NGINX_TEST_NODE_IMAGE || 'node:24-alpine';
  docker('image', 'inspect', nginxImage);
  docker('image', 'inspect', nodeImage);
  docker('network', 'create', id); networkCreated = true;
  docker('run', '-d', '--pull=never', '--name', backend, '--network', id,
    '--network-alias', 'index', '--network-alias', 'app_py', '--network-alias', 'app_node',
    '-v', root + ':/fixture:ro', '--entrypoint', 'node', nodeImage, '/fixture/backend.cjs');
  docker('run', '-d', '--pull=never', '--name', web, '--network', id,
    '-p', '127.0.0.1::80', '-v', config + ':/etc/nginx/conf.d/default.conf:ro',
    '-v', html + ':/usr/share/nginx/html:ro', nginxImage);
  t.diagnostic(docker('exec', web, 'nginx', '-t'));
  const address = docker('port', web, '80/tcp');
  const origin = 'http://' + address;
  let ready = false;
  for (let attempt = 0; attempt < 50; attempt++) {
    try { const response = await fetch(origin + '/files', { signal: AbortSignal.timeout(1000) }); ready = response.status === 200 && await response.text() === 'index:/files'; }
    catch { /* Nginx or the synthetic backend may still be starting. */ }
    if (ready) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.ok(ready, 'isolated Nginx and backend must become ready');
  async function check(route, status, body, cache) {
    const response = await fetch(origin + route, { redirect: 'error', signal: AbortSignal.timeout(5000) });
    assert.equal(response.status, status, route + ' status');
    const actual = await response.text();
    if (body !== null) assert.equal(actual, body, route + ' body');
    if (cache !== undefined) assert.equal(response.headers.get('cache-control'), cache, route + ' Cache-Control');
  }
  await t.test('calculator HTML and JS override the common asset cache rule', async () => {
    await check('/calculators/example.html', 200, 'synthetic calculator HTML', 'no-store');
    await check('/calculators/example.js', 200, 'synthetic calculator script', 'no-store');
  });
  await t.test('ordinary assets retain validation caching and missing assets return 404', async () => {
    await check('/regular.js', 200, 'synthetic regular asset', 'no-cache');
    await check('/missing.js', 404, null);
  });
  await t.test('rejects foreign Host and hidden path segments before routing', async () => {
    const foreignStatus = await new Promise((resolve, reject) => {
      http.get(origin + '/files', { headers: { host: 'evil.example' } }, response => { response.resume(); resolve(response.statusCode); }).on('error', reject);
    });
    assert.equal(foreignStatus, 421);
    for (const route of ['/.hidden', '/.hidden.js', '/calculators/.hidden.js']) {
      assert.equal((await fetch(origin + route)).status, 404, route);
    }
  });
  await t.test('static landing wins and missing documents use the shared fallback', async () => {
    await check('/', 200, 'synthetic landing');
    await check('/missing-document', 200, 'index:/missing-document');
    await check('/calculators/missing.js', 200, 'index:/calculators/missing.js');
    await check('/calculators/', 200, 'index:/calculators/');
    await fs.unlink(path.join(html, 'index.html'));
    // Docker Desktop propagates host bind-mount deletion asynchronously.
    // Observe it inside the container before checking the no-landing branch.
    let removed = false;
    for (let attempt = 0; attempt < 50; attempt++) {
      try { docker('exec', web, 'test', '!', '-e', '/usr/share/nginx/html/index.html'); removed = true; break; }
      catch { await new Promise(resolve => setTimeout(resolve, 100)); }
    }
    assert.ok(removed, 'synthetic landing removal must reach the container');
    await check('/', 200, 'index:/');
  });
  await t.test('file browser, configuration and both API prefixes keep their upstream and URI', async () => {
    await check('/files', 200, 'index:/files');
    await check('/configure', 200, 'index:/configure');
    await check('/api/py/hello?synthetic=1', 200, 'python:/api/py/hello?synthetic=1');
    await check('/api/node/hello', 200, 'node:/api/node/hello');
  });
});

test('dynamic WebSocket crosses real Nginx and Fastify', { timeout: 90000 }, async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'synthetic-ws-'));
  const id = 'synthetic-ws-' + randomUUID();
  const backend = id + '-backend', web = id + '-web';
  let networkCreated = false;
  t.after(async () => {
    const failures = [];
    for (const name of [web, backend]) {
      try { if (docker('container', 'ls', '-aq', '--filter', 'name=^/' + name + '$')) docker('rm', '-f', name); } catch (e) { failures.push(e); }
    }
    if (networkCreated) { try { docker('network', 'rm', id); } catch (e) { failures.push(e); } }
    await fs.rm(root, { recursive: true, force: true });
    if (failures.length) throw new AggregateError(failures);
  });
  await fs.chmod(root, 0o777);
  const net = await import('node:net');
  const reservation = net.createServer();
  await new Promise(resolve => reservation.listen(0, '127.0.0.1', resolve));
  const port = reservation.address().port;
  await new Promise(resolve => reservation.close(resolve));
  await fs.writeFile(path.join(root, 'backend.mjs'), `
import http from 'node:http';
import crypto from 'node:crypto';
import fs from 'node:fs';
${observeFrames.toString()}
const server = http.createServer(async (req, res) => {
  if (req.headers.host !== '127.0.0.1:8080') { res.writeHead(403).end(); return; }
  for await (const chunk of req) res.write(chunk); res.end();
});
server.on('upgrade', (req, socket) => {
  fs.appendFileSync('/fixture/upgrades.log', JSON.stringify({ host: req.headers.host, forwardedHost: req.headers['x-forwarded-host'], url: req.url }) + '\\n');
  if (req.headers.host !== '127.0.0.1:8080') return socket.end('HTTP/1.1 403 Forbidden\\r\\nConnection: close\\r\\n\\r\\n');
  const accept = crypto.createHash('sha1').update(req.headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
  socket.write('HTTP/1.1 101 Switching Protocols\\r\\nUpgrade: websocket\\r\\nConnection: Upgrade\\r\\nSec-WebSocket-Accept: ' + accept + '\\r\\n\\r\\n');
  observeFrames(socket, data => {
    const frame = Buffer.concat([Buffer.from([0x81, data.length]), data]);
    socket.write(frame.subarray(0, 1));
    setImmediate(() => socket.write(frame.subarray(1)));
  });
});
server.listen(8080, '0.0.0.0');
http.createServer((_req, res) => res.end('fixture')).listen(80, '0.0.0.0');
http.createServer((_req, res) => res.end('fixture')).listen(4000, '0.0.0.0');
await import('/index/server.js');
`);
  docker('network', 'create', id); networkCreated = true;
  docker('run', '-d', '--pull=never', '--name', backend, '--network', id,
    '--network-alias', 'index', '--network-alias', 'app_py', '--network-alias', 'app_node',
    '-e', `PUBLIC_PORT=${port}`, '-e', 'WEBROOT=/fixture', '-e', 'CONFIG_ROOT=/fixture', '-e', 'HOST_DOCKER_GATEWAY=127.0.0.1',
    '-v', root + ':/fixture', '-v', path.resolve('docker/webserver/index') + ':/index:ro',
    '--entrypoint', 'node', process.env.NGINX_TEST_NODE_IMAGE || 'node:24-alpine', '/fixture/backend.mjs');
  docker('run', '-d', '--pull=never', '--name', web, '--network', id,
    '-p', `127.0.0.1:${port}:80`, '-v', config + ':/etc/nginx/conf.d/default.conf:ro',
    '-v', root + ':/usr/share/nginx/html:ro', process.env.NGINX_TEST_IMAGE || 'nginx:stable-alpine');
  const origin = `http://127.0.0.1:${port}`;
  let response;
  for (let i = 0; i < 50; i++) {
    try { response = await fetch(origin + '/configure'); if (response.status === 200) break; } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.equal(response?.status, 200, 'real Fastify ready behind nginx');
  const configBefore = await fs.readFile(path.join(root, 'endpoints.json'), 'utf8');
  await fetch(origin + '/configure/api/endpoints');
  await fetch(origin + '/files');
  assert.equal(await fs.readFile(path.join(root, 'endpoints.json'), 'utf8'), configBefore);
  const compose = await fs.readFile(path.resolve('docker/webserver/docker-compose.yml'), 'utf8');
  const health = compose.match(/test: (\["CMD", "node", "-e", "[^\n]+"\])/);
  assert.ok(health, 'index healthcheck is declared');
  const [, , , healthScript] = JSON.parse(health[1]);
  docker('exec', backend, 'node', '-e', healthScript);
  const webHealth = compose.match(/test: (\["CMD", "wget", [^\n]+\])/);
  assert.ok(webHealth);
  const [, , ...wgetArgs] = JSON.parse(webHealth[1]);
  docker('exec', web, 'wget', ...wgetArgs.map(arg => arg.replace('7711', String(port))));
  const payload = JSON.stringify({ name: 'Synthetic socket', path: '/socket', target: 'http://127.0.0.1:8080' });
  const create = headers => fetch(origin + '/configure/api/endpoints', { method: 'POST', headers: { 'content-type': 'application/json', ...headers }, body: payload });
  assert.equal((await create({ origin: 'http://evil.example' })).status, 403);
  assert.equal((await create({ origin })).status, 201);
  const bytes = Buffer.from([0, 255, 128, 10]);
  const forwarded = await fetch(origin + '/socket/upload', { method: 'POST', headers: { origin, 'content-type': 'application/octet-stream' }, body: bytes });
  assert.equal(forwarded.status, 200);
  assert.deepEqual(Buffer.from(await forwarded.arrayBuffer()), bytes);
  const upgrade = (route, requestOrigin, requestHost = `127.0.0.1:${port}`) => new Promise((resolve, reject) => {
    const request = http.request(origin + route, { headers: { host: requestHost, connection: 'Upgrade', upgrade: 'websocket', origin: requestOrigin, 'sec-websocket-version': '13', 'sec-websocket-key': 'c3ludGhldGljLWtleS0xMg==' } });
    request.setTimeout(5000, () => request.destroy(new Error('WebSocket timed out')));
    request.on('response', response => { response.resume(); resolve({ status: response.statusCode }); });
    request.on('upgrade', (_response, socket) => {
      const message = Buffer.from('synthetic message'), mask = Buffer.from([1, 2, 3, 4]);
      const masked = Buffer.from(message.map((byte, i) => byte ^ mask[i % 4]));
      const frame = Buffer.concat([Buffer.from([0x81, 0x80 | message.length]), mask, masked]);
      socket.write(frame.subarray(0, 3));
      setImmediate(() => socket.write(frame.subarray(3)));
      observeFrames(socket, data => { socket.destroy(); resolve({ status: 101, message: data.toString() }); });
      socket.on('error', reject);
    });
    request.on('error', reject);
    request.end();
  });
  assert.deepEqual(await upgrade('/socket/a%2Fb?x=one%26two', origin), { status: 101, message: 'synthetic message' });
  assert.deepEqual(await upgrade('/socket', origin), { status: 101, message: 'synthetic message' });
  assert.equal((await upgrade('/unknown', origin)).status, 404);
  assert.equal((await upgrade('/%66iles', origin)).status, 404);
  assert.equal((await upgrade('/socket', 'http://evil.example')).status, 403);
  assert.equal((await upgrade('/socket', origin, 'evil.example')).status, 421);
  const upstreamRequests = (await fs.readFile(path.join(root, 'upgrades.log'), 'utf8')).trim().split('\n').map(JSON.parse);
  assert.deepEqual(upstreamRequests, [
    { host: '127.0.0.1:8080', forwardedHost: `127.0.0.1:${port}`, url: '/a%2Fb?x=one%26two' },
    { host: '127.0.0.1:8080', forwardedHost: `127.0.0.1:${port}`, url: '/' }
  ]);
});
