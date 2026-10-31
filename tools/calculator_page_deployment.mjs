// A narrow direct-copy installer for one standalone calculator page, using only Node built-ins.
// Each page has a thin entry script that names its file, label and backup namespace.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {regular, inspectAncestors, externalDirectory, atomicFile, pruneBackups} from './deployment_files.mjs';

const escapeRegExp = text => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

function deployPage({filename, label, backupName, script}) {
  const relative = `Calculation tools/${filename}`;
  let repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  let webroot = path.resolve(process.env.UTILITIES_WEBROOT_DIR || path.join(os.homedir(), 'webroot'));
  let dryRun = false;
  for (let i = 2; i < process.argv.length; i++) {
    const arg = process.argv[i];
    if (arg === '--help') {
      console.log(`Usage: node tools/${script} [--dry-run] [--webroot DIR] [--repo DIR]`);
      return;
    }
    if (arg === '--dry-run') dryRun = true;
    else if ((arg === '--webroot' || arg === '--repo') && process.argv[i + 1]) {
      const value = path.resolve(process.argv[++i]);
      if (arg === '--webroot') webroot = value; else repo = value;
    } else throw new Error('Unknown or incomplete argument');
  }
  repo = fs.realpathSync(repo);
  webroot = externalDirectory(webroot, repo);
  const source = path.join(repo, relative), stat = regular(source);
  const index = execFileSync('git', ['-C', repo, 'ls-files', '--stage', '-z', '--', relative], {encoding: 'utf8'});
  if (!new RegExp(`^100644 [0-9a-f]+ 0\\t${escapeRegExp(relative)}\\0$`).test(index)) {
    throw new Error(`${label} must be a tracked stage-zero regular HTML file`);
  }
  const bytes = fs.readFileSync(source);
  if (!bytes.equals(execFileSync('git', ['-C', repo, 'show', ':' + relative]))) {
    throw new Error(`${label} working bytes differ from the Git index; validate and stage the source first`);
  }
  const target = path.join(webroot, 'calculators', filename);
  inspectAncestors(path.dirname(target));
  const exists = fs.existsSync(target) || (() => { try { fs.lstatSync(target); return true; } catch { return false; } })();
  if (exists) regular(target);
  if (dryRun) { console.log(`Dry run: validated ${label} direct copy; no files changed`); return; }
  const mode = stat.mode & 0o7777;
  if (exists && fs.readFileSync(target).equals(bytes) && (fs.statSync(target).mode & 0o7777) === mode) {
    console.log(`${label} deployment already matches source`); return;
  }
  let backup;
  if (exists) {
    const backupRoot = path.join(os.homedir(), '.utilities-deploy-backups', backupName);
    inspectAncestors(backupRoot);
    fs.mkdirSync(backupRoot, {recursive: true, mode: 0o700});
    fs.chmodSync(backupRoot, 0o700);
    backup = fs.mkdtempSync(path.join(backupRoot, 'copy-'));
    fs.chmodSync(backup, 0o700);
    fs.copyFileSync(target, path.join(backup, filename));
    fs.chmodSync(path.join(backup, filename), 0o600);
  }
  fs.mkdirSync(path.dirname(target), {recursive: true, mode: 0o755});
  atomicFile(target, bytes, mode, `.${backupName}-stage-`);
  if (backup) pruneBackups(path.dirname(backup));
  console.log(`${label} deployed to /calculators/${filename}`);
  if (backup) console.log(`Previous file retained in a private ${backupName} deployment backup`);
}

export function runCalculatorPageDeployment(page) {
  try { deployPage(page); } catch (error) {
    console.error(`${page.label} deployment failed: ${error.message}`);
    process.exitCode = 1;
  }
}
