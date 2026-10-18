import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {execFileSync} from 'node:child_process';

export const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
export function exists(file) { try { fs.lstatSync(file); return true; } catch (e) { if (e.code === 'ENOENT') return false; throw e; } }

export function cleanupDirectories(directories) {
  const errors = [];
  for (const directory of directories) {
    try { fs.rmSync(directory, {recursive: true, force: true}); }
    catch (error) { errors.push(new Error('Cleanup failed for ' + directory + ': ' + error.message, {cause: error})); }
  }
  return errors;
}
export function finishCleanup(primary, cleanupErrors, completedMessage, backup) {
  if (!primary && !cleanupErrors.length) return;
  if (primary && !cleanupErrors.length && !backup) throw primary;
  const message = (primary ? primary.message : completedMessage)
    + (cleanupErrors.length ? '; ' + cleanupErrors.map(error => error.message).join('; ') : '')
    + (backup ? '; Recovery backup: ' + backup : '');
  throw new AggregateError([...(primary ? [primary] : []), ...cleanupErrors], message);
}

export function atomicFile(target, bytes, mode, stagePrefix) {
  const staging = fs.mkdtempSync(path.join(path.dirname(target), stagePrefix));
  let primary;
  try {
    const candidate = path.join(staging, 'candidate'); fs.writeFileSync(candidate, bytes, {mode}); fs.chmodSync(candidate, mode);
    if (!fs.readFileSync(candidate).equals(bytes) || (regular(candidate).mode & 0o7777) !== mode) throw new Error('Native staged bytes/mode mismatch');
    fs.renameSync(candidate, target);
  } catch (error) { primary = error; }
  finishCleanup(primary, cleanupDirectories([staging]), 'File publication completed, but cleanup failed');
}

export function parseIndexSnapshot(file) {
  return fs.readFileSync(file, 'utf8').split('\0').filter(Boolean).map(record => {
    const [mode, name, ...extra] = record.split('\t');
    if (extra.length || !['100644', '100755'].includes(mode)) throw new Error('Invalid native source inventory');
    return {mode, name};
  });
}

export function parseStagedListing(raw) {
  return raw.split('\0').filter(Boolean).map(record => {
    const match = /^(100644|100755) ([a-f0-9]+) 0\t(.+)$/.exec(record);
    if (!match) throw new Error('Native project must have only regular stage-zero tracked files');
    return {mode: match[1], oid: match[2], name: match[3]};
  });
}

export function normalizeEntries(entries) {
  entries.sort((a, b) => a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
  const names = new Set(entries.map(e => e.name));
  if (names.size !== entries.length) throw new Error('Duplicate native input');
  return entries;
}

export function hashInventory(repo, entries, requireStaged) {
  const hash = crypto.createHash('sha256');
  for (const entry of entries) {
    if (entry.name.split('/').some(part => part === '..' || part === '.')) throw new Error('Invalid native input path');
    const file = path.join(repo, entry.name), stat = regular(file), bytes = fs.readFileSync(file);
    const mode = stat.mode & 0o7777;
    if (mode !== (entry.mode === '100755' ? 0o755 : 0o644)) throw new Error('Native source mode differs from index');
    if (requireStaged && !bytes.equals(execFileSync('git', ['-C', repo, 'show', ':' + entry.name]))) {
      throw new Error('Native working bytes differ from Git index; validate and stage first');
    }
    hash.update(entry.name + '\0' + mode.toString(8) + '\0' + sha(bytes) + '\0');
    entry.bytes = bytes; entry.permissions = mode;
  }
  return {entries, sourceHash: hash.digest('hex')};
}

export function regular(file) {
  const stat = fs.lstatSync(file);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error('Expected a regular non-symlink file');
  return stat;
}
export function inspectAncestors(directory) {
  for (let current = directory;; current = path.dirname(current)) {
    let stat;
    try { stat = fs.lstatSync(current); } catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (stat) {
      const systemAlias = process.platform === 'darwin' && ['/var', '/tmp'].includes(current) && fs.statSync(current).isDirectory();
      if ((!stat.isDirectory() || stat.isSymbolicLink()) && !systemAlias) throw new Error('Directory path contains a symlink or non-directory');
    }
    if (current === path.dirname(current)) break;
  }
}
export function externalDirectory(directory, repo) {
  inspectAncestors(directory);
  let ancestor = directory;
  while (!fs.existsSync(ancestor)) ancestor = path.dirname(ancestor);
  const canonical = path.join(fs.realpathSync(ancestor), path.relative(ancestor, directory));
  if (canonical === repo || canonical.startsWith(repo + path.sep)) throw new Error('Destination must be outside the repository');
  return canonical;
}
