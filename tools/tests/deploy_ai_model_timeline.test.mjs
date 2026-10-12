import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync, spawnSync} from 'node:child_process';

const script = path.resolve('tools/deploy_ai_model_timeline.mjs');
function fixture(t) {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'synthetic-timeline-deploy-'));
  t.after(() => fs.rmSync(base, {recursive: true, force: true}));
  const repo = path.join(base, 'synthetic repo'), home = path.join(base, 'synthetic home');
  const webroot = path.join(home, 'synthetic webroot');
  fs.mkdirSync(path.join(repo, 'Calculation tools'), {recursive: true});
  fs.mkdirSync(webroot, {recursive: true});
  const source = path.join(repo, 'Calculation tools/ai-model-timeline.html');
  const target = path.join(webroot, 'calculators/ai-model-timeline.html');
  fs.writeFileSync(source, '<!doctype html><title>Invented timeline A</title>');
  fs.chmodSync(source, 0o644);
  const git = (...args) => execFileSync('git', ['-C', repo, ...args]);
  git('init', '-q'); git('add', '.');
  function run(...args) {
    const result = spawnSync(process.execPath, [script, '--repo', repo, '--webroot', webroot, ...args], {
      env: {...process.env, HOME: home}, encoding: 'utf8'
    });
    return result;
  }
  return {base, repo, home, webroot, source, target, git, run};
}
test('direct copy supports dry run, first install and backed-up update without touching neighbors', t => {
  const f = fixture(t);
  assert.equal(f.run('--dry-run').status, 0);
  assert.equal(fs.existsSync(f.target), false);
  assert.equal(fs.existsSync(path.join(f.home, '.utilities-deploy-backups')), false);
  assert.equal(f.run().status, 0);
  assert.equal(fs.readFileSync(f.target, 'utf8'), '<!doctype html><title>Invented timeline A</title>');
  assert.equal(fs.statSync(f.target).mode & 0o7777, 0o644);
  const neighbor = path.join(f.webroot, 'calculators/synthetic-local-only.txt');
  fs.writeFileSync(neighbor, 'invented local state');
  fs.writeFileSync(f.source, '<!doctype html><title>Invented timeline B</title>'); f.git('add', '.');
  assert.equal(f.run().status, 0);
  assert.equal(fs.readFileSync(f.target, 'utf8'), '<!doctype html><title>Invented timeline B</title>');
  assert.equal(fs.readFileSync(neighbor, 'utf8'), 'invented local state');
  const backups = path.join(f.home, '.utilities-deploy-backups/ai-model-timeline');
  const saved = path.join(backups, fs.readdirSync(backups)[0], 'ai-model-timeline.html');
  assert.equal(fs.readFileSync(saved, 'utf8'), '<!doctype html><title>Invented timeline A</title>');
  assert.equal(fs.statSync(saved).mode & 0o777, 0o600);
});
test('rejects unindexed or unstaged source without replacing installed bytes', t => {
  const f = fixture(t); assert.equal(f.run().status, 0);
  fs.writeFileSync(f.source, 'invented unstaged change');
  assert.equal(f.run().status, 1);
  assert.equal(fs.readFileSync(f.target, 'utf8'), '<!doctype html><title>Invented timeline A</title>');
  f.git('rm', '-f', '--cached', 'Calculation tools/ai-model-timeline.html');
  assert.equal(f.run().status, 1);
});
test('refuses destination links and repository destinations without changing their targets', t => {
  const f = fixture(t), external = path.join(f.home, 'synthetic external');
  fs.writeFileSync(external, 'invented protected bytes');
  fs.mkdirSync(path.dirname(f.target)); fs.symlinkSync(external, f.target);
  assert.equal(f.run().status, 1);
  assert.equal(fs.readFileSync(external, 'utf8'), 'invented protected bytes');
  assert.equal(f.run('--webroot', f.repo).status, 1);
});
test('failed atomic activation preserves previous bytes and mode and cleans the temporary candidate', t => {
  const f = fixture(t); assert.equal(f.run().status, 0);
  fs.writeFileSync(f.source, '<!doctype html><title>Invented timeline update</title>'); f.git('add', '.');
  const preload = path.join(f.base, 'synthetic-rename-failure.cjs');
  fs.writeFileSync(preload, `const fs = require('node:fs');\nfs.renameSync = () => { throw new Error('invented activation failure'); };\n`);
  const result = spawnSync(process.execPath, ['--require', preload, script, '--repo', f.repo, '--webroot', f.webroot], {
    env: {...process.env, HOME: f.home}, encoding: 'utf8'
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /invented activation failure/);
  assert.equal(fs.readFileSync(f.target, 'utf8'), '<!doctype html><title>Invented timeline A</title>');
  assert.equal(fs.statSync(f.target).mode & 0o7777, 0o644);
  assert.deepEqual(fs.readdirSync(path.dirname(f.target)), ['ai-model-timeline.html']);
});
