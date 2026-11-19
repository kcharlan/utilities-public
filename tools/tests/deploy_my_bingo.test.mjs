import assert from 'node:assert/strict';
import {execFileSync, spawnSync} from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';

const script = fileURLToPath(new URL('../deploy_my_bingo.mjs', import.meta.url));
const inventory = {
  'bingo_app.html': 'synthetic bingo page',
  'css/app.css': 'synthetic styles',
  'js/ui/view.js': 'synthetic module',
  'themes/example/theme.json': '{"name":"Synthetic","version":"1","css":"theme.css"}',
  'themes/example/theme.css': 'synthetic theme',
  'fixtures/thanksgiving.txt': 'synthetic example words',
  'fixtures/thanksgiving2.txt': 'synthetic alternate example words',
};

function write(root, rel, contents) {
  const file = path.join(root, rel);
  fs.mkdirSync(path.dirname(file), {recursive: true});
  fs.writeFileSync(file, contents);
}

function git(repo, ...args) {
  return execFileSync('git', ['-C', repo, ...args], {encoding: 'utf8'});
}

function commit(repo) {
  git(repo, 'add', '-A');
  git(repo, '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid',
    '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Update synthetic fixture');
}

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'my-bingo-deploy-'));
  t.after(() => fs.rmSync(root, {recursive: true, force: true}));
  const repo = path.join(root, 'my_bingo');
  const webroot = path.join(root, 'webroot');
  const backups = path.join(root, 'backups');
  const target = path.join(webroot, 'games', 'my_bingo');
  fs.mkdirSync(repo);
  git(repo, 'init', '-qb', 'main');
  for (const [rel, bytes] of Object.entries(inventory)) write(repo, rel, bytes);
  write(repo, 'README.md', 'synthetic source-only notes');
  write(repo, 'themes/example/orig-theme.css', 'synthetic reference stylesheet');
  write(repo, 'fixtures/bad_23_after_trim.txt', 'synthetic negative fixture');
  commit(repo);
  write(repo, 'js/untracked.js', 'synthetic untracked module');
  function invoke(nodeArgs, args) {
    const result = spawnSync(process.execPath, [...nodeArgs, script, '--repo', repo, '--webroot',
      webroot, '--backups', backups, ...args], {encoding: 'utf8'});
    if (result.error) throw result.error;
    return result;
  }
  const cli = (...args) => invoke([], args);
  function run(...args) {
    const result = cli(...args);
    assert.equal(result.status, 0, result.stdout + result.stderr);
    return result.stdout;
  }
  return {root, repo, webroot, backups, target, cli, invoke, run};
}

test('installs committed runtime, reports drift and rolls back without touching local files', t => {
  const f = fixture(t);
  assert.match(f.run('--dry-run'), /7 runtime files/);
  assert.equal(fs.existsSync(f.webroot), false);
  assert.equal(fs.existsSync(f.backups), false);
  f.run();
  assert.match(f.run('--check'), /matches/);
  for (const [rel, bytes] of Object.entries(inventory)) {
    assert.equal(fs.readFileSync(path.join(f.target, rel), 'utf8'), bytes);
    assert.equal(fs.statSync(path.join(f.target, rel)).mode & 0o777, 0o644);
  }
  for (const excluded of ['README.md', 'js/untracked.js', 'themes/example/orig-theme.css',
    'fixtures/bad_23_after_trim.txt']) {
    assert.equal(fs.existsSync(path.join(f.target, excluded)), false);
  }
  write(f.target, 'local.txt', 'synthetic local state');
  write(f.webroot, 'games/neighbor/index.html', 'synthetic neighbor');
  write(f.repo, 'bingo_app.html', 'synthetic second release');
  write(f.repo, 'js/ui/new.js', 'synthetic new module');
  fs.unlinkSync(path.join(f.repo, 'js/untracked.js'));
  commit(f.repo);
  assert.notEqual(f.cli('--check').status, 0);
  const backup = f.run().match(/Recovery backup: (.+)/)[1];
  assert.match(f.run('--check'), /matches/);
  write(f.repo, 'bingo_app.html', 'synthetic unfinished edit');
  f.run('--rollback', backup);
  assert.equal(fs.readFileSync(path.join(f.target, 'bingo_app.html'), 'utf8'), inventory['bingo_app.html']);
  assert.equal(fs.existsSync(path.join(f.target, 'js/ui/new.js')), false);
  assert.equal(fs.readFileSync(path.join(f.target, 'local.txt'), 'utf8'), 'synthetic local state');
  assert.equal(fs.readFileSync(path.join(f.webroot, 'games/neighbor/index.html'), 'utf8'), 'synthetic neighbor');
  assert.equal(fs.existsSync(backup), true);
});

test('migrates a legacy checkout into a private archive and preserves local themes and word lists', t => {
  const f = fixture(t);
  write(f.target, 'bingo_app.html', 'synthetic old app');
  git(f.target, 'init', '-qb', 'main');
  commit(f.target);
  write(f.target, 'node_modules/example/index.js', 'synthetic tool');
  write(f.target, 'themes/local/theme.json', '{"name":"Synthetic local","version":"1","css":"theme.css"}');
  write(f.target, 'themes/local/theme.css', 'synthetic local styles');
  write(f.target, 'themes/local/assets/texture.bin', 'synthetic texture');
  write(f.target, 'themes/manifest.json', '["example","local"]');
  write(f.target, 'fixtures/local.txt', 'synthetic local words');
  assert.match(f.cli().stderr, /migrate-checkout/);
  assert.match(f.run('--migrate-checkout', '--dry-run'), /archive/i);
  assert.equal(fs.existsSync(f.backups), false);
  assert.equal(fs.readFileSync(path.join(f.target, 'bingo_app.html'), 'utf8'), 'synthetic old app');
  const archive = f.run('--migrate-checkout').match(/Legacy checkout: (.+)/)[1];
  assert.equal(fs.statSync(archive).mode & 0o777, 0o700);
  assert.equal(git(path.join(archive, 'checkout'), 'rev-parse', '--abbrev-ref', 'HEAD').trim(), 'main');
  assert.equal(fs.readFileSync(path.join(archive, 'checkout/bingo_app.html'), 'utf8'), 'synthetic old app');
  assert.equal(fs.existsSync(path.join(f.target, '.git')), false);
  assert.equal(fs.existsSync(path.join(f.target, 'node_modules')), false);
  assert.equal(fs.readFileSync(path.join(f.target, 'themes/local/theme.css'), 'utf8'), 'synthetic local styles');
  assert.equal(fs.readFileSync(path.join(f.target, 'themes/local/assets/texture.bin'), 'utf8'), 'synthetic texture');
  assert.equal(fs.readFileSync(path.join(f.target, 'themes/manifest.json'), 'utf8'), '["example","local"]');
  assert.equal(fs.readFileSync(path.join(f.target, 'fixtures/local.txt'), 'utf8'), 'synthetic local words');
  assert.match(f.run('--check'), /matches/);
});

test('restores the old checkout when activation fails after archiving it', t => {
  const f = fixture(t);
  write(f.target, 'bingo_app.html', 'synthetic old app');
  git(f.target, 'init', '-qb', 'main');
  commit(f.target);
  const head = git(f.target, 'rev-parse', 'HEAD');
  const hook = path.join(f.root, 'fail-activation.mjs');
  fs.writeFileSync(hook, [
    "import fs from 'node:fs';",
    "import path from 'node:path';",
    'const rename = fs.renameSync;',
    'fs.renameSync = (source, destination) => {',
    "  if (path.basename(source) === 'runtime' && path.basename(destination) === 'my_bingo') {",
    "    throw Error('synthetic activation failed');",
    '  }',
    '  return rename(source, destination);',
    '};',
  ].join('\n'));
  const result = f.invoke(['--import', hook], ['--migrate-checkout']);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /synthetic activation failed/);
  assert.equal(git(f.target, 'rev-parse', 'HEAD'), head);
  assert.equal(fs.readFileSync(path.join(f.target, 'bingo_app.html'), 'utf8'), 'synthetic old app');
  assert.deepEqual(fs.readdirSync(path.dirname(f.target)), ['my_bingo']);
});

test('rejects staged changes, symlinked targets and backups inside webroot', t => {
  const f = fixture(t);
  write(f.repo, 'bingo_app.html', 'synthetic staged edit');
  git(f.repo, 'add', 'bingo_app.html');
  assert.match(f.cli().stderr, /committed|index/i);
  assert.equal(fs.existsSync(f.webroot), false);
  git(f.repo, 'restore', '--staged', '--worktree', 'bingo_app.html');
  assert.match(f.cli('--backups', path.join(f.webroot, 'backups')).stderr, /outside webroot/i);
  fs.mkdirSync(path.dirname(f.target), {recursive: true});
  fs.symlinkSync(f.repo, f.target);
  assert.match(f.cli().stderr, /symlink/i);
  assert.equal(fs.existsSync(f.backups), false);
});

test('rejects a case alias for a backup directory inside the webroot', t => {
  const f = fixture(t);
  fs.mkdirSync(f.webroot);
  const alias = path.join(f.root, 'WEBROOT');
  if (!fs.existsSync(alias)) return t.skip('filesystem is case-sensitive');
  assert.match(f.cli('--backups', path.join(alias, 'archive'), '--dry-run').stderr, /outside webroot/);
  assert.deepEqual(fs.readdirSync(f.webroot), []);
});

test('rejects a release missing either promised word list', t => {
  const f = fixture(t);
  fs.unlinkSync(path.join(f.repo, 'fixtures/thanksgiving2.txt'));
  fs.unlinkSync(path.join(f.repo, 'js/untracked.js'));
  commit(f.repo);
  assert.match(f.cli('--dry-run').stderr, /missing required tracked runtime files/);
  assert.equal(fs.existsSync(f.webroot), false);
});
