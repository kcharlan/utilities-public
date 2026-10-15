import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';

const config = fileURLToPath(new URL('../nginx/default.conf', import.meta.url));
const docker = (...args) => execFileSync('docker', args, { encoding: 'utf8', timeout: 30000 }).trim();

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
