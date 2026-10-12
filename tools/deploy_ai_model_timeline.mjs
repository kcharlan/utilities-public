#!/usr/bin/env node
// A narrow direct-copy installer for the standalone timeline, using only Node built-ins.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';

const relative = 'Calculation tools/ai-model-timeline.html';
const filename = 'ai-model-timeline.html';
function regular(file) {
  const stat = fs.lstatSync(file);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error('Expected a regular non-symlink file');
  return stat;
}
function inspectAncestors(directory) {
  for (let current = directory;; current = path.dirname(current)) {
    let stat;
    try { stat = fs.lstatSync(current); } catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (stat) {
      // macOS exposes these standard system aliases to /private; user-created links remain refused.
      const systemAlias = process.platform === 'darwin' && ['/var', '/tmp'].includes(current) && fs.statSync(current).isDirectory();
      if ((!stat.isDirectory() || stat.isSymbolicLink()) && !systemAlias) throw new Error('Directory path contains a symlink or non-directory');
    }
    if (current === path.dirname(current)) break;
  }
}
function deploy() {
  let repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  let webroot = path.resolve(process.env.UTILITIES_WEBROOT_DIR || path.join(os.homedir(), 'webroot'));
  let dryRun = false;
  for (let i = 2; i < process.argv.length; i++) {
    const arg = process.argv[i];
    if (arg === '--help') {
      console.log('Usage: node tools/deploy_ai_model_timeline.mjs [--dry-run] [--webroot DIR] [--repo DIR]');
      return;
    }
    if (arg === '--dry-run') dryRun = true;
    else if ((arg === '--webroot' || arg === '--repo') && process.argv[i + 1]) {
      const value = path.resolve(process.argv[++i]);
      if (arg === '--webroot') webroot = value; else repo = value;
    } else throw new Error('Unknown or incomplete argument');
  }
  repo = fs.realpathSync(repo);
  inspectAncestors(webroot);
  let existingRoot = webroot;
  while (!fs.existsSync(existingRoot)) existingRoot = path.dirname(existingRoot);
  webroot = path.join(fs.realpathSync(existingRoot), path.relative(existingRoot, webroot));
  if (webroot === repo || webroot.startsWith(repo + path.sep)) throw new Error('Webroot must be outside the repository');
  const source = path.join(repo, relative), stat = regular(source);
  const index = execFileSync('git', ['-C', repo, 'ls-files', '--stage', '-z', '--', relative], {encoding: 'utf8'});
  if (!/^100644 [0-9a-f]+ 0\tCalculation tools\/ai-model-timeline\.html\0$/.test(index)) {
    throw new Error('Timeline must be a tracked stage-zero regular HTML file');
  }
  const bytes = fs.readFileSync(source);
  if (!bytes.equals(execFileSync('git', ['-C', repo, 'show', ':' + relative]))) {
    throw new Error('Timeline working bytes differ from the Git index; validate and stage the source first');
  }
  const target = path.join(webroot, 'calculators', filename);
  inspectAncestors(path.dirname(target));
  const exists = fs.existsSync(target) || (() => { try { fs.lstatSync(target); return true; } catch { return false; } })();
  if (exists) regular(target);
  if (dryRun) { console.log('Dry run: validated timeline direct copy; no files changed'); return; }
  const mode = stat.mode & 0o7777;
  if (exists && fs.readFileSync(target).equals(bytes) && (fs.statSync(target).mode & 0o7777) === mode) {
    console.log('Timeline deployment already matches source'); return;
  }
  let backup;
  if (exists) {
    const backupRoot = path.join(os.homedir(), '.utilities-deploy-backups', 'ai-model-timeline');
    inspectAncestors(backupRoot);
    fs.mkdirSync(backupRoot, {recursive: true, mode: 0o700});
    backup = fs.mkdtempSync(path.join(backupRoot, 'copy-'));
    fs.chmodSync(backup, 0o700);
    fs.copyFileSync(target, path.join(backup, filename));
    fs.chmodSync(path.join(backup, filename), 0o600);
  }
  fs.mkdirSync(path.dirname(target), {recursive: true, mode: 0o755});
  const staging = fs.mkdtempSync(path.join(path.dirname(target), '.timeline-stage-'));
  try {
    const candidate = path.join(staging, filename);
    fs.copyFileSync(source, candidate); fs.chmodSync(candidate, mode);
    if (!fs.readFileSync(candidate).equals(bytes) || (fs.statSync(candidate).mode & 0o7777) !== mode) {
      throw new Error('Staged timeline verification failed');
    }
    fs.renameSync(candidate, target);
  } finally { fs.rmSync(staging, {recursive: true, force: true}); }
  console.log('Timeline deployed to /calculators/ai-model-timeline.html');
  if (backup) console.log('Previous file retained in a private ai-model-timeline deployment backup');
}
try { deploy(); } catch (error) { console.error('Timeline deployment failed: ' + error.message); process.exitCode = 1; }
