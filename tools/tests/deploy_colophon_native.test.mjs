import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync, execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const script = fileURLToPath(new URL('../deploy_colophon_native.mjs', import.meta.url));
function fixture(t) {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'synthetic-native-deploy-'));
  t.after(() => fs.rmSync(base, {recursive: true, force: true}));
  const repo = path.join(base, 'invented repo'), home = path.join(base, 'invented home');
  const project = path.join(repo, 'colophon-native'), scripts = path.join(home, 'Library/Scripts');
  fs.mkdirSync(project, {recursive: true}); fs.mkdirSync(home);
  function write(name, bytes) {
    const target = path.join(project, name); fs.mkdirSync(path.dirname(target), {recursive: true}); fs.writeFileSync(target, bytes);
  }
  const git = (...args) => execFileSync('git', ['-C', repo, ...args], {stdio: 'pipe'});
  function release(label, failInstalled = false) {
    write('src/main.c', `#include <stdio.h>\n#include <string.h>\nint main(int argc, char **argv) { if (${failInstalled ? 1 : 0} && strstr(argv[0], "/Scripts/")) return 1; if (argc == 2 && !strcmp(argv[1], "--version")) { puts("colophon 0.1.0"); return 0; } if (argc == 2 && !strcmp(argv[1], "--help")) { puts("synthetic ${label}"); return 0; } return 2; }\n`);
    git('add', '.');
  }
  write('Makefile', 'all: colophon\ncolophon: src/main.c\n\tclang -o colophon src/main.c\n');
  for (const name of ['assets/MANIFEST', 'tools/embed.pl', 'vendor/yyjson/yyjson.c', 'vendor/yyjson/yyjson.h']) write(name, 'synthetic unused build input\n');
  git('init', '-q'); git('config', 'user.name', 'Synthetic Tester'); git('config', 'user.email', 'tester@example.invalid');
  release('first'); git('commit', '-qm', 'synthetic baseline');
  const run = (...args) => spawnSync(process.execPath, [script, '--repo', repo, '--scripts-dir', scripts, ...args], {
    encoding: 'utf8', env: {...process.env, HOME: home, TMPDIR: base, CPPFLAGS: '', CFLAGS: '', LDFLAGS: ''}
  });
  return {base, repo, home, project, scripts, git, release, run, target: path.join(scripts, 'colophon'),
    receipt: path.join(scripts, '.colophon-native.json')};
}
function succeeds(result) { assert.equal(result.status, 0, result.stderr + result.stdout); }
test('dry-run leaves source, destination and backup state untouched', t => {
  const f = fixture(t), before = fs.readdirSync(f.home);
  succeeds(f.run('--dry-run')); assert.deepEqual(fs.readdirSync(f.home), before);
  assert.equal(fs.existsSync(path.join(f.project, 'colophon')), false);
});
test('installs, updates, audits and rolls back the native command while preserving local state', t => {
  const f = fixture(t); fs.mkdirSync(f.scripts, {recursive: true});
  fs.writeFileSync(f.target, '#!/bin/sh\necho synthetic previous Python launcher\n'); fs.chmodSync(f.target, 0o755);
  fs.writeFileSync(path.join(f.scripts, 'synthetic-local-state'), 'synthetic keep');
  succeeds(f.run()); succeeds(f.run('--audit'));
  const first = fs.readFileSync(f.target), firstReceipt = fs.readFileSync(f.receipt);
  assert.equal(fs.statSync(f.target).mode & 0o7777, 0o755);
  assert.equal(fs.statSync(f.receipt).mode & 0o7777, 0o600);
  f.release('second'); succeeds(f.run()); succeeds(f.run('--audit'));
  assert.notDeepEqual(fs.readFileSync(f.target), first);
  const backups = path.join(f.home, '.utilities-deploy-backups/colophon-native');
  const updateBackup = fs.readdirSync(backups).map(n => path.join(backups, n)).find(p => fs.existsSync(path.join(p, 'receipt.json')));
  assert.ok(updateBackup); assert.equal(fs.statSync(updateBackup).mode & 0o7777, 0o700);
  succeeds(f.run('--rollback', updateBackup));
  assert.deepEqual(fs.readFileSync(f.target), first); assert.deepEqual(fs.readFileSync(f.receipt), firstReceipt);
  assert.equal(f.run('--audit').status, 1, 'rolled-back binary is older than current source');
  assert.equal(fs.readFileSync(path.join(f.scripts, 'synthetic-local-state'), 'utf8'), 'synthetic keep');
});
test('failed installed activation restores the previous binary and receipt', t => {
  const f = fixture(t); succeeds(f.run());
  const bytes = fs.readFileSync(f.target), receipt = fs.readFileSync(f.receipt);
  f.release('broken', true); const result = f.run();
  assert.equal(result.status, 1); assert.match(result.stderr, /activation|version/);
  assert.deepEqual(fs.readFileSync(f.target), bytes); assert.deepEqual(fs.readFileSync(f.receipt), receipt);
});
test('read-only audit fails for source, binary, modes or receipt drift', t => {
  const f = fixture(t); succeeds(f.run());
  const receipt = fs.readFileSync(f.receipt), binary = fs.readFileSync(f.target);
  const auditSnapshot = fs.readdirSync(f.scripts); succeeds(f.run('--audit'));
  assert.deepEqual(fs.readdirSync(f.scripts), auditSnapshot); assert.deepEqual(fs.readFileSync(f.receipt), receipt);
  fs.appendFileSync(f.target, 'synthetic corruption'); assert.equal(f.run('--audit').status, 1);
  fs.writeFileSync(f.target, binary); fs.chmodSync(f.target, 0o755);
  fs.chmodSync(f.target, 0o4755); assert.equal(f.run('--audit').status, 1); fs.chmodSync(f.target, 0o755);
  fs.chmodSync(f.receipt, 0o644); assert.equal(f.run('--audit').status, 1); fs.chmodSync(f.receipt, 0o600);
  fs.writeFileSync(f.receipt, '{}'); assert.equal(f.run('--audit').status, 1); fs.writeFileSync(f.receipt, receipt);
  fs.appendFileSync(path.join(f.project, 'src/main.c'), '// synthetic drift'); assert.equal(f.run('--audit').status, 1);
});
test('refuses unstaged, missing, unsupported input and linked or repository destinations', t => {
  const f = fixture(t);
  fs.appendFileSync(path.join(f.project, 'src/main.c'), '// unstaged'); assert.equal(f.run().status, 1);
  f.git('checkout', '--', 'colophon-native/src/main.c');
  fs.unlinkSync(path.join(f.project, 'assets/MANIFEST')); assert.equal(f.run().status, 1);
  f.git('checkout', '--', 'colophon-native/assets/MANIFEST');
  fs.mkdirSync(f.scripts, {recursive: true}); const protectedFile = path.join(f.home, 'synthetic protected'); fs.writeFileSync(protectedFile, 'keep');
  fs.symlinkSync(protectedFile, f.target); assert.equal(f.run().status, 1);
  assert.equal(fs.readFileSync(protectedFile, 'utf8'), 'keep');
  fs.unlinkSync(f.target); assert.equal(f.run('--scripts-dir', f.repo).status, 1);
  f.git('rm', '--cached', 'colophon-native/src/main.c'); assert.equal(f.run().status, 1);
});
test('invalid rollback cannot remove or partially replace the installed command', t => {
  const f = fixture(t); succeeds(f.run()); const bytes = fs.readFileSync(f.target), receipt = fs.readFileSync(f.receipt);
  assert.equal(f.run('--rollback', path.join(f.base, 'missing backup')).status, 1);
  assert.deepEqual(fs.readFileSync(f.target), bytes); assert.deepEqual(fs.readFileSync(f.receipt), receipt);
});
