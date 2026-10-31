import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync, spawnSync} from 'node:child_process';
import {pruneBackups} from '../deployment_files.mjs';

function retentionFixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'synthetic-retention-'));
  t.after(() => { fs.chmodSync(root, 0o700); fs.rmSync(root, {recursive: true, force: true}); });
  const add = (name, time = 1) => {
    const dir = path.join(root, name); fs.mkdirSync(dir);
    fs.writeFileSync(path.join(dir, 'payload'), name);
    fs.utimesSync(dir, time, time); return dir;
  };
  return {root, add};
}

test('backup retention sorts by mtime then descending name and returns removed paths', t => {
  const {root, add} = retentionFixture(t);
  const old = add('copy-old'); const a = add('copy-a', 2); add('copy-z', 2); add('copy-new', 3);
  const other = add('unrelated'); fs.writeFileSync(path.join(root, 'copy-file'), 'keep');
  fs.symlinkSync(other, path.join(root, 'copy-link'));
  assert.deepEqual(pruneBackups(root), [a, old]);
  assert.equal(fs.readFileSync(path.join(other, 'payload'), 'utf8'), 'unrelated');
  assert.equal(fs.lstatSync(path.join(root, 'copy-link')).isSymbolicLink(), true);
  assert.equal(fs.readFileSync(path.join(root, 'copy-file'), 'utf8'), 'keep');
  assert.deepEqual(pruneBackups(root), []);
});

test('backup retention removes read-only descendants without following nested links', t => {
  const {root, add} = retentionFixture(t); const old = add('copy-old');
  const outside = add('protected'); fs.chmodSync(path.join(outside, 'payload'), 0o400);
  const child = path.join(old, 'nested'); fs.mkdirSync(child); fs.writeFileSync(path.join(child, 'data'), 'old');
  fs.symlinkSync(outside, path.join(old, 'link')); fs.chmodSync(child, 0o500); fs.chmodSync(old, 0o500);
  assert.deepEqual(pruneBackups(root, {keep: 0}), [old]);
  assert.equal(fs.statSync(path.join(outside, 'payload')).mode & 0o777, 0o400);
});

test('backup retention refuses missing, read-only and linked roots and invalid options', t => {
  const {root, add} = retentionFixture(t); const old = add('copy-old');
  const warnings = []; const original = console.warn; console.warn = msg => warnings.push(msg);
  t.after(() => { console.warn = original; });
  assert.deepEqual(pruneBackups(path.join(root, 'absent')), []);
  fs.chmodSync(root, 0o500); assert.deepEqual(pruneBackups(root, {keep: 0}), []); fs.chmodSync(root, 0o700);
  const link = path.join(root, 'alias'); fs.symlinkSync(root, link);
  assert.deepEqual(pruneBackups(link, {keep: 0}), []);
  assert.deepEqual(pruneBackups(link + '/', {keep: 0}), []);
  assert.deepEqual(pruneBackups(path.join(link, 'copy-old'), {keep: 0}), []);
  for (const options of [{keep: -1}, {keep: 1.5}, {isBackup: null}, null]) assert.deepEqual(pruneBackups(root, options), []);
  assert.deepEqual(pruneBackups(root, {isBackup: () => { throw new Error('invented predicate error'); }}), []);
  assert.equal(fs.readFileSync(path.join(old, 'payload'), 'utf8'), 'copy-old');
  assert.ok(warnings.length >= 9);
});

test('backup retention admits custom names and supported system aliases', t => {
  const {root, add} = retentionFixture(t); const old = add('snapshot-old'); add('copy-keep');
  assert.deepEqual(pruneBackups(root, {keep: 0, isBackup: name => name.startsWith('snapshot-')}), [old]);
  if (process.platform === 'darwin' && root.startsWith('/var/')) {
    add('copy-new', 2); assert.equal(pruneBackups(root, {keep: 1}).length, 1);
  }
});

test('backup retention warns and preserves payloads on injected stat and removal errors', t => {
  const {root, add} = retentionFixture(t); const old = add('copy-old');
  const warnings = []; const warn = console.warn; console.warn = msg => warnings.push(msg);
  const stat = fs.lstatSync, rm = fs.rmSync;
  try {
    fs.lstatSync = file => { if (file === old) throw new Error('invented stat error'); return stat(file); };
    assert.deepEqual(pruneBackups(root, {keep: 0}), []); fs.lstatSync = stat;
    fs.rmSync = file => { if (file === old) throw new Error('invented removal error'); return rm(file); };
    assert.deepEqual(pruneBackups(root, {keep: 0}), []);
  } finally { fs.lstatSync = stat; fs.rmSync = rm; console.warn = warn; }
  assert.equal(fs.readFileSync(path.join(old, 'payload'), 'utf8'), 'copy-old'); assert.equal(warnings.length, 2);
});

test('backup retention reports the affected nested path on chmod and enumeration errors', t => {
  const {root, add} = retentionFixture(t); const old = add('copy-old');
  const nested = path.join(old, 'nested'); fs.mkdirSync(nested);
  fs.writeFileSync(path.join(nested, 'payload'), 'invented protected contents');
  const warnings = []; const warn = console.warn; console.warn = msg => warnings.push(msg);
  const chmod = fs.chmodSync, read = fs.readdirSync;
  try {
    fs.chmodSync = (file, mode) => { if (file === nested) throw new Error('invented chmod error'); return chmod(file, mode); };
    assert.deepEqual(pruneBackups(root, {keep: 0}), []); fs.chmodSync = chmod;
    fs.readdirSync = file => { if (file === nested) throw new Error('invented enumeration error'); return read(file); };
    assert.deepEqual(pruneBackups(root, {keep: 0}), []);
  } finally { fs.chmodSync = chmod; fs.readdirSync = read; console.warn = warn; }
  assert.equal(fs.readFileSync(path.join(nested, 'payload'), 'utf8'), 'invented protected contents');
  assert.equal(warnings.length, 2); for (const warning of warnings) assert.ok(warning.includes(nested));
});

// Each single-page calculator installer shares one lifecycle; run it against every page.
const pages = [
  {script: 'tools/deploy_ai_model_timeline.mjs', filename: 'ai-model-timeline.html', backups: 'ai-model-timeline'},
  {script: 'tools/deploy_drawdown.mjs', filename: 'drawdown.html', backups: 'drawdown'},
];

for (const page of pages) {
  const script = path.resolve(page.script);
  const relative = `Calculation tools/${page.filename}`;
  const html = label => `<!doctype html><title>Invented ${page.filename} ${label}</title>`;

  function fixture(t) {
    const base = fs.mkdtempSync(path.join(os.tmpdir(), 'synthetic-calculator-deploy-'));
    t.after(() => fs.rmSync(base, {recursive: true, force: true}));
    const repo = path.join(base, 'synthetic repo'), home = path.join(base, 'synthetic home');
    const webroot = path.join(home, 'synthetic webroot');
    fs.mkdirSync(path.join(repo, 'Calculation tools'), {recursive: true});
    fs.mkdirSync(webroot, {recursive: true});
    const source = path.join(repo, relative);
    const target = path.join(webroot, 'calculators', page.filename);
    fs.writeFileSync(source, html('A'));
    fs.chmodSync(source, 0o644);
    const git = (...args) => execFileSync('git', ['-C', repo, ...args]);
    git('init', '-q'); git('add', '.');
    function run(...args) {
      return spawnSync(process.execPath, [script, '--repo', repo, '--webroot', webroot, ...args], {
        env: {...process.env, HOME: home}, encoding: 'utf8'
      });
    }
    return {base, repo, home, webroot, source, target, git, run};
  }

  test(`${page.filename}: successful update prunes older backups; dry run and failure preserve them`, t => {
    const f = fixture(t); assert.equal(f.run().status, 0);
    const root = path.join(f.home, '.utilities-deploy-backups', page.backups);
    for (const name of ['copy-old-a', 'copy-old-b', 'copy-old-c']) {
      const dir = path.join(root, name); fs.mkdirSync(dir, {recursive: true});
      fs.writeFileSync(path.join(dir, 'payload'), 'invented'); fs.utimesSync(dir, 1, 1);
    }
    fs.writeFileSync(f.source, html('B')); f.git('add', '.');
    assert.equal(f.run('--dry-run').status, 0);
    fs.writeFileSync(f.source, html('unstaged')); assert.equal(f.run().status, 1);
    for (const name of ['copy-old-a', 'copy-old-b', 'copy-old-c']) assert.equal(fs.readFileSync(path.join(root,name,'payload'),'utf8'),'invented');
    fs.writeFileSync(f.source, html('B')); assert.equal(f.run().status, 0);
    const names = fs.readdirSync(root); assert.equal(names.length, 2); assert.ok(names.includes('copy-old-c'));
    const saved = names.find(name => name !== 'copy-old-c'); assert.equal(fs.readFileSync(path.join(root,saved,page.filename),'utf8'),html('A'));
  });

  test(`${page.filename}: dry run, first install and backed-up update without touching neighbors`, t => {
    const f = fixture(t);
    assert.equal(f.run('--dry-run').status, 0);
    assert.equal(fs.existsSync(f.target), false);
    assert.equal(fs.existsSync(path.join(f.home, '.utilities-deploy-backups')), false);
    assert.equal(f.run().status, 0);
    assert.equal(fs.readFileSync(f.target, 'utf8'), html('A'));
    assert.equal(fs.statSync(f.target).mode & 0o7777, 0o644);
    const unchanged = f.run();
    assert.equal(unchanged.status, 0);
    assert.match(unchanged.stdout, /already matches source/);
    assert.equal(fs.existsSync(path.join(f.home, '.utilities-deploy-backups')), false);
    const neighbor = path.join(f.webroot, 'calculators/synthetic-local-only.txt');
    fs.writeFileSync(neighbor, 'invented local state');
    fs.writeFileSync(f.source, html('B')); f.git('add', '.');
    assert.equal(f.run().status, 0);
    assert.equal(fs.readFileSync(f.target, 'utf8'), html('B'));
    assert.equal(fs.readFileSync(neighbor, 'utf8'), 'invented local state');
    const backups = path.join(f.home, '.utilities-deploy-backups', page.backups);
    assert.equal(fs.statSync(backups).mode & 0o777, 0o700);
    const [copy] = fs.readdirSync(backups);
    assert.equal(fs.statSync(path.join(backups, copy)).mode & 0o777, 0o700);
    const saved = path.join(backups, copy, page.filename);
    assert.equal(fs.readFileSync(saved, 'utf8'), html('A'));
    assert.equal(fs.statSync(saved).mode & 0o777, 0o600);
  });

  test(`${page.filename}: rejects unindexed or unstaged source without replacing installed bytes`, t => {
    const f = fixture(t); assert.equal(f.run().status, 0);
    fs.writeFileSync(f.source, 'invented unstaged change');
    assert.equal(f.run().status, 1);
    assert.equal(fs.readFileSync(f.target, 'utf8'), html('A'));
    f.git('rm', '-f', '--cached', relative);
    assert.equal(f.run().status, 1);
  });

  test(`${page.filename}: refuses destination links and repository destinations without changing their targets`, t => {
    const f = fixture(t), external = path.join(f.home, 'synthetic external');
    fs.writeFileSync(external, 'invented protected bytes');
    fs.mkdirSync(path.dirname(f.target)); fs.symlinkSync(external, f.target);
    assert.equal(f.run().status, 1);
    assert.equal(fs.readFileSync(external, 'utf8'), 'invented protected bytes');
    assert.equal(f.run('--webroot', f.repo).status, 1);
  });

  test(`${page.filename}: failed atomic activation preserves previous bytes and mode and cleans the candidate`, t => {
    const f = fixture(t); assert.equal(f.run().status, 0);
    fs.writeFileSync(f.source, html('update')); f.git('add', '.');
    const preload = path.join(f.base, 'synthetic-rename-failure.cjs');
    fs.writeFileSync(preload, `const fs = require('node:fs');\nfs.renameSync = () => { throw new Error('invented activation failure'); };\n`);
    const result = spawnSync(process.execPath, ['--require', preload, script, '--repo', f.repo, '--webroot', f.webroot], {
      env: {...process.env, HOME: f.home}, encoding: 'utf8'
    });
    assert.equal(result.status, 1);
    assert.match(result.stderr, /invented activation failure/);
    assert.equal(fs.readFileSync(f.target, 'utf8'), html('A'));
    assert.equal(fs.statSync(f.target).mode & 0o7777, 0o644);
    assert.deepEqual(fs.readdirSync(path.dirname(f.target)), [page.filename]);
  });

  test(`${page.filename}: rollback by copying the retained backup restores the previous page`, t => {
    const f = fixture(t); assert.equal(f.run().status, 0);
    fs.writeFileSync(f.source, html('B')); f.git('add', '.');
    assert.equal(f.run().status, 0);
    const backups = path.join(f.home, '.utilities-deploy-backups', page.backups);
    const saved = path.join(backups, fs.readdirSync(backups)[0], page.filename);
    fs.copyFileSync(saved, f.target); fs.chmodSync(f.target, 0o644);
    assert.equal(fs.readFileSync(f.target, 'utf8'), html('A'));
    // Redeploying the current source replaces the rolled-back copy again.
    assert.equal(f.run().status, 0);
    assert.equal(fs.readFileSync(f.target, 'utf8'), html('B'));
  });
}

test('drawdown and timeline installers keep separate backup namespaces', t => {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'synthetic-calculator-deploy-'));
  t.after(() => fs.rmSync(base, {recursive: true, force: true}));
  const repo = path.join(base, 'synthetic repo'), home = path.join(base, 'synthetic home');
  const webroot = path.join(home, 'synthetic webroot');
  fs.mkdirSync(path.join(repo, 'Calculation tools'), {recursive: true});
  fs.mkdirSync(path.join(webroot, 'calculators'), {recursive: true});
  for (const {filename} of pages) {
    fs.writeFileSync(path.join(repo, 'Calculation tools', filename), `<!doctype html><title>Invented new ${filename}</title>`);
    fs.writeFileSync(path.join(webroot, 'calculators', filename), `invented old ${filename}`);
    fs.chmodSync(path.join(webroot, 'calculators', filename), 0o644);
  }
  execFileSync('git', ['-C', repo, 'init', '-q']); execFileSync('git', ['-C', repo, 'add', '.']);
  for (const {script} of pages) {
    const result = spawnSync(process.execPath, [path.resolve(script), '--repo', repo, '--webroot', webroot], {
      env: {...process.env, HOME: home}, encoding: 'utf8'
    });
    assert.equal(result.status, 0, result.stderr);
  }
  for (const {filename, backups} of pages) {
    const root = path.join(home, '.utilities-deploy-backups', backups);
    const saved = fs.readdirSync(root).map(copy => fs.readdirSync(path.join(root, copy))).flat();
    assert.deepEqual(saved, [filename]);
  }
});
