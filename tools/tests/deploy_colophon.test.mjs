import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync, execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {buildInput} from '../deploy_colophon.mjs';

const script = fileURLToPath(new URL('../deploy_colophon.mjs', import.meta.url));
test('native build inputs include vendored zstd and exclude unrelated vendor trees', () => {
  assert.equal(buildInput('colophon/vendor/zstd/common/xxhash.c'), true);
  assert.equal(buildInput('colophon/vendor/zstd/VERSION'), true);
  assert.equal(buildInput('colophon/vendor/other/x.c'), false);
});
function fixture(t, root = 'colophon') {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'synthetic-native-deploy-'));
  t.after(() => fs.rmSync(base, {recursive: true, force: true}));
  const repo = path.join(base, 'invented repo'), home = path.join(base, 'invented home');
  const project = path.join(repo, root), scripts = path.join(home, 'Library/Scripts');
  fs.mkdirSync(project, {recursive: true}); fs.mkdirSync(home);
  function write(name, bytes) {
    const target = path.join(project, name); fs.mkdirSync(path.dirname(target), {recursive: true}); fs.writeFileSync(target, bytes);
  }
  const git = (...args) => execFileSync('git', ['-C', repo, ...args], {stdio: 'pipe'});
  function release(label, failInstalled = false) {
    write('src/main.c', `#include <stdio.h>\n#include <string.h>\nint main(int argc, char **argv) { if (${failInstalled ? 1 : 0} && strstr(argv[0], "/Scripts/")) return 1; if (argc == 2 && !strcmp(argv[1], "--version")) { puts("colophon 0.5.1"); return 0; } if (argc == 2 && !strcmp(argv[1], "--help")) { puts("synthetic ${label}"); return 0; } return 2; }\n`);
    git('add', '.');
  }
  write('Makefile', 'all: colophon\ncolophon: src/main.c\n\tclang -o colophon src/main.c\n');
  for (const name of ['assets/MANIFEST', 'tools/embed.pl', 'vendor/yyjson/yyjson.c', 'vendor/yyjson/yyjson.h', 'vendor/zstd/zstd.h', 'vendor/zstd/decompress/zstd_decompress.c']) write(name, 'synthetic unused build input\n');
  git('init', '-q'); git('config', 'user.name', 'Synthetic Tester'); git('config', 'user.email', 'tester@example.invalid');
  release('first'); git('commit', '-qm', 'synthetic baseline');
  const runWith = (installer, ...args) => spawnSync(process.execPath, [fs.realpathSync(installer), '--repo', repo, '--scripts-dir', scripts, ...args], {
    encoding: 'utf8', env: {...process.env, HOME: home, TMPDIR: base, CPPFLAGS: '', CFLAGS: '', LDFLAGS: ''}
  });
  const run = (...args) => runWith(script, ...args);
  return {base, repo, home, project, scripts, git, release, run, runWith, target: path.join(scripts, 'colophon'),
    receipt: path.join(scripts, '.colophon-native.json')};
}
function succeeds(result) { assert.equal(result.status, 0, result.stderr + result.stdout); }
function snapshot(directory) {
  const entries = [];
  function visit(file, name) {
    const stat = fs.lstatSync(file);
    entries.push([name, stat.mode & 0o7777, stat.isDirectory() ? null : fs.readFileSync(file).toString('base64')]);
    if (stat.isDirectory()) for (const child of fs.readdirSync(file).sort()) visit(path.join(file, child), name + '/' + child);
  }
  visit(directory, '');
  return entries;
}
// Reproduce the pre-cutover source-path contract using the same lifecycle code.
// Private receipt/backup names already have their historical spelling.
function preCutoverInstaller(f) {
  const tools = path.join(f.base, 'synthetic old tools'); fs.mkdirSync(tools);
  const old = fs.readFileSync(script, 'utf8')
    .replaceAll('colophon/', 'colophon-native/')
    .replaceAll('colophon\\/', 'colophon-native\\/')
    .replaceAll("'colophon'], {encoding", "'colophon-native'], {encoding")
    .replaceAll("path.join(scratch, 'colophon')", "path.join(scratch, 'colophon-native')");
  const installer = path.join(tools, 'deploy_colophon_native.mjs');
  fs.writeFileSync(installer, old);
  fs.copyFileSync(fileURLToPath(new URL('../deployment_files.mjs', import.meta.url)), path.join(tools, 'deployment_files.mjs'));
  return installer;
}
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
  fs.appendFileSync(path.join(f.project, 'src/main.c'), '// unstaged');
  const unstaged = f.run(); assert.equal(unstaged.status, 1); assert.match(unstaged.stderr, /Native working bytes differ from Git index/);
  f.git('checkout', '--', 'colophon/src/main.c');
  fs.unlinkSync(path.join(f.project, 'assets/MANIFEST')); assert.equal(f.run().status, 1);
  f.git('checkout', '--', 'colophon/assets/MANIFEST');
  fs.mkdirSync(f.scripts, {recursive: true}); const protectedFile = path.join(f.home, 'synthetic protected'); fs.writeFileSync(protectedFile, 'keep');
  fs.symlinkSync(protectedFile, f.target); assert.equal(f.run().status, 1);
  assert.equal(fs.readFileSync(protectedFile, 'utf8'), 'keep');
  fs.unlinkSync(f.target); assert.equal(f.run('--scripts-dir', f.repo).status, 1);
  f.git('rm', '--cached', 'colophon/src/main.c'); assert.equal(f.run().status, 1);
});
test('invalid rollback cannot remove or partially replace the installed command', t => {
  const f = fixture(t); succeeds(f.run()); const bytes = fs.readFileSync(f.target), receipt = fs.readFileSync(f.receipt);
  assert.equal(f.run('--rollback', path.join(f.base, 'missing backup')).status, 1);
  assert.deepEqual(fs.readFileSync(f.target), bytes); assert.deepEqual(fs.readFileSync(f.receipt), receipt);
});
test('canonical dry-run and audit preserve the complete source and private deployment tree', t => {
  const f = fixture(t); succeeds(f.run());
  fs.writeFileSync(path.join(f.scripts, 'synthetic-local-state'), 'synthetic keep');
  fs.writeFileSync(path.join(f.project, 'colophon'), 'synthetic stale working binary');
  const source = snapshot(f.repo), privateState = snapshot(f.home);
  succeeds(f.run('--dry-run')); const audit = f.run('--audit'); succeeds(audit);
  assert.equal(audit.stdout, 'OK: colophon native deployment\n'); assert.equal(Buffer.byteLength(audit.stdout), 31);
  assert.equal(audit.stderr, '');
  assert.deepEqual(snapshot(f.repo), source); assert.deepEqual(snapshot(f.home), privateState);
});
test('actual installer rejects legacy-only and untracked canonical inputs without writing', t => {
  const legacy = fixture(t, 'colophon-native');
  const before = snapshot(legacy.base);
  for (const option of [[], ['--dry-run'], ['--audit']]) {
    const result = legacy.run(...option);
    assert.equal(result.status, 1); assert.match(result.stderr, /Required native build input missing: Makefile/);
  }
  assert.deepEqual(snapshot(legacy.base), before);
  const f = fixture(t); f.git('rm', '--cached', 'colophon/assets/MANIFEST');
  const result = f.run('--dry-run');
  assert.equal(result.status, 1); assert.match(result.stderr, /Required native build input missing: assets\/MANIFEST/);
});
test('pre-cutover receipt drifts after relocation; redeploy and rollback preserve compatible private state', t => {
  const f = fixture(t, 'colophon-native'), old = preCutoverInstaller(f);
  fs.mkdirSync(f.scripts, {recursive: true});
  const launcher = Buffer.from('#!/bin/sh\necho synthetic previous Python launcher\n');
  fs.writeFileSync(f.target, launcher, {mode: 0o755});
  const installed = f.runWith(old); succeeds(installed); assert.match(installed.stdout, /Native Colophon deployed/); succeeds(f.runWith(old, '--audit'));
  const launcherBackup = installed.stdout.trim().split('rollback backup: ')[1];
  const oldBinary = fs.readFileSync(f.target), oldReceipt = fs.readFileSync(f.receipt);
  f.git('mv', 'colophon-native', 'colophon');
  const drift = f.run('--audit'); assert.equal(drift.status, 1); assert.match(drift.stderr, /Native build source drift/);
  const redeploy = f.run(); succeeds(redeploy); succeeds(f.run('--audit'));
  assert.notDeepEqual(fs.readFileSync(f.receipt), oldReceipt);
  const oldReleaseBackup = redeploy.stdout.trim().split('rollback backup: ')[1];
  const canonicalMain = path.join(f.repo, 'colophon/src/main.c');
  const goodSource = fs.readFileSync(canonicalMain, 'utf8');
  const activeBinary = fs.readFileSync(f.target), activeReceipt = fs.readFileSync(f.receipt);
  fs.writeFileSync(canonicalMain, goodSource.replace('if (0 &&', 'if (1 &&')); f.git('add', 'colophon/src/main.c');
  const failed = f.run(); assert.equal(failed.status, 1); assert.match(failed.stderr, /version|activation/);
  assert.deepEqual(fs.readFileSync(f.target), activeBinary); assert.deepEqual(fs.readFileSync(f.receipt), activeReceipt);
  assert.equal(fs.statSync(f.target).mode & 0o7777, 0o755); assert.equal(fs.statSync(f.receipt).mode & 0o7777, 0o600);
  fs.writeFileSync(canonicalMain, goodSource); f.git('add', 'colophon/src/main.c'); succeeds(f.run('--audit'));
  succeeds(f.run('--rollback', oldReleaseBackup));
  assert.deepEqual(fs.readFileSync(f.target), oldBinary); assert.deepEqual(fs.readFileSync(f.receipt), oldReceipt);
  assert.equal(fs.statSync(f.target).mode & 0o7777, 0o755);
  assert.equal(fs.statSync(f.receipt).mode & 0o7777, 0o600);
  assert.match(f.run('--audit').stderr, /Native build source drift/);
  succeeds(f.run('--rollback', launcherBackup));
  assert.deepEqual(fs.readFileSync(f.target), launcher); assert.equal(fs.existsSync(f.receipt), false);
  assert.equal(fs.statSync(f.target).mode & 0o7777, 0o755);
});
