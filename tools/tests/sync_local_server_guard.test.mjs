import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {spawnSync} from 'node:child_process';

const tool = resolve('tools/sync_local_server_guard.mjs');
const run = (cwd, ...args) => spawnSync('node', [tool, ...args], {cwd, encoding: 'utf8'});
const git = (cwd, ...args) => spawnSync('git', args, {cwd, encoding: 'utf8'});
test('sync, check drift, malformed regions and tracked discovery', () => {
  const dir = mkdtempSync(join(tmpdir(), 'guard-test-'));
  try {
    git(dir, 'init', '-q');
    assert.notEqual(run(dir, '--all').status, 0);
    const file = join(dir, 'server.py');
    writeFileSync(file, '# local-server-guard:begin\nstale\n# local-server-guard:end\n');
    git(dir, 'add', 'server.py');
    assert.notEqual(run(dir, '--all', '--check').status, 0);
    assert.match(readFileSync(file, 'utf8'), /stale/);
    assert.equal(run(dir, '--all').status, 0);
    assert.match(readFileSync(file, 'utf8'), /class LocalOriginGuard/);
    assert.equal(run(dir, '--check', file).status, 0);
    writeFileSync(file, '# local-server-guard:begin\n');
    assert.notEqual(run(dir, '--all').status, 0);
  } finally { rmSync(dir, {recursive:true, force:true}); }
});
