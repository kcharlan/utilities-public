import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const composeFile = process.env.EXCALIDRAW_TEST_COMPOSE || fileURLToPath(new URL('../docker-compose.yml', import.meta.url));

test('Excalidraw publishes only on IPv4 loopback', () => {
  const config = JSON.parse(execFileSync('docker', ['compose', '-f', composeFile, 'config', '--format', 'json'], { encoding: 'utf8' }));
  assert.deepEqual(config.services.excalidraw.ports.map(({ host_ip, published, target }) => ({ host_ip, published, target })), [
    { host_ip: '127.0.0.1', published: '5010', target: 80 }
  ]);
});
