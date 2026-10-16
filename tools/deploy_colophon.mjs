#!/usr/bin/env node
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {regular, inspectAncestors, externalDirectory, sha, exists, atomicFile, parseIndexSnapshot,
  parseStagedListing, normalizeEntries, hashInventory} from './deployment_files.mjs';

export const buildInput = name => name === 'colophon/Makefile' ||
  /^colophon\/(src|assets|vendor\/(yyjson|zstd))\//.test(name) || name === 'colophon/tools/embed.pl';

// The audit supplies its validated index snapshot; the installer takes one itself.
export function sourceInventory(repo, snapshot, requireStaged = false) {
  let entries;
  if (snapshot) {
    entries = parseIndexSnapshot(snapshot);
  } else {
    const raw = execFileSync('git', ['-C', repo, 'ls-files', '--stage', '--sparse', '-z', '--', 'colophon'], {encoding: 'utf8'});
    entries = parseStagedListing(raw);
  }
  entries = normalizeEntries(entries.filter(e => buildInput(e.name)));
  const names = new Set(entries.map(e => e.name));
  for (const required of ['Makefile', 'src/main.c', 'assets/MANIFEST', 'tools/embed.pl', 'vendor/yyjson/yyjson.c', 'vendor/yyjson/yyjson.h', 'vendor/zstd/zstd.h', 'vendor/zstd/decompress/zstd_decompress.c']) {
    if (!names.has('colophon/' + required)) throw new Error('Required native build input missing: ' + required);
  }
  return hashInventory(repo, entries, requireStaged);
}
function receiptPath(scripts) { return path.join(scripts, '.colophon-native.json'); }
function readReceipt(file) {
  if ((regular(file).mode & 0o7777) !== 0o600) throw new Error('Native receipt must have mode0600');
  const value = JSON.parse(fs.readFileSync(file, 'utf8'));
  if (value.schema !== 1 || value.mode !== 0o755 || !/^[0-9a-f]{64}$/.test(value.sourceHash) || !/^[0-9a-f]{64}$/.test(value.binaryHash)) {
    throw new Error('Invalid native deployment receipt');
  }
  return value;
}
function diagnostic(binary) {
  const version = execFileSync(binary, ['--version'], {encoding: 'utf8', timeout: 10000}).trim();
  if (version !== 'colophon 0.3.0') throw new Error('Native version activation check failed');
  execFileSync(binary, ['--help'], {stdio: 'pipe', timeout: 10000});
}
function backup(scripts, home, repo) {
  const target = path.join(scripts, 'colophon'), receipt = receiptPath(scripts);
  const root = externalDirectory(path.join(home, '.utilities-deploy-backups/colophon-native'), repo);
  fs.mkdirSync(root, {recursive: true, mode: 0o700});
  const directory = fs.mkdtempSync(path.join(root, 'copy-')); fs.chmodSync(directory, 0o700);
  const state = {schema: 1, binary: null, receipt: null};
  if (exists(target)) {
    const stat = regular(target); fs.copyFileSync(target, path.join(directory, 'colophon')); fs.chmodSync(path.join(directory, 'colophon'), 0o600);
    state.binary = {mode: stat.mode & 0o7777, hash: sha(fs.readFileSync(path.join(directory, 'colophon')))};
  }
  if (exists(receipt)) { regular(receipt); fs.copyFileSync(receipt, path.join(directory, 'receipt.json')); fs.chmodSync(path.join(directory, 'receipt.json'), 0o600); state.receipt = sha(fs.readFileSync(path.join(directory, 'receipt.json'))); }
  fs.writeFileSync(path.join(directory, 'state.json'), JSON.stringify(state), {mode: 0o600});
  return directory;
}
function readBackup(directory) {
  inspectAncestors(directory);
  const metadata = path.join(directory, 'state.json'); regular(metadata);
  const state = JSON.parse(fs.readFileSync(metadata, 'utf8'));
  if (state.schema !== 1 || !Object.hasOwn(state, 'binary') || !Object.hasOwn(state, 'receipt')) throw new Error('Invalid backup state');
  const value = {binary: null, receipt: null, mode: 0};
  if (state.binary !== null) {
    const mode = state.binary?.mode;
    if (!Number.isInteger(mode) || mode < 0 || mode > 0o7777) throw new Error('Invalid backup mode');
    const file = path.join(directory, 'colophon'); regular(file); value.binary = fs.readFileSync(file); value.mode = mode;
    if (sha(value.binary) !== state.binary.hash) throw new Error('Backup binary hash mismatch');
  }
  if (state.receipt !== null) {
    const file = path.join(directory, 'receipt.json'); regular(file); value.receipt = fs.readFileSync(file);
    if (sha(value.receipt) !== state.receipt) throw new Error('Backup receipt hash mismatch');
  }
  return value;
}
function restore(value, scripts) {
  const target = path.join(scripts, 'colophon'), receipt = receiptPath(scripts);
  if (value.binary) atomicFile(target, value.binary, value.mode, '.colophon-stage-');
  else if (exists(target)) fs.unlinkSync(target);
  if (value.receipt) atomicFile(receipt, value.receipt, 0o600, '.colophon-stage-');
  else if (exists(receipt)) fs.unlinkSync(receipt);
}
export function main(argv = process.argv.slice(2)) {
  let repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  let scripts = path.resolve(process.env.UTILITIES_SCRIPTS_DIR || path.join(os.homedir(), 'Library/Scripts'));
  let audit = false, dry = false, snapshot, rollback;
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--help') { console.log('Usage: node tools/deploy_colophon.mjs [--dry-run | --audit | --rollback BACKUP] [--repo DIR] [--scripts-dir DIR] [--source-inventory FILE]'); return; }
    if (arg === '--audit') audit = true;
    else if (arg === '--dry-run') dry = true;
    else if (['--repo', '--scripts-dir', '--source-inventory', '--rollback'].includes(arg) && argv[i + 1]) {
      const value = path.resolve(argv[++i]);
      if (arg === '--repo') repo = value; else if (arg === '--scripts-dir') scripts = value; else if (arg === '--rollback') rollback = value; else snapshot = value;
    } else throw new Error('Unknown or incomplete argument');
  }
  if (Number(audit) + Number(dry) + Number(Boolean(rollback)) > 1 || (snapshot && !audit)) throw new Error('Incompatible deployment options');
  repo = fs.realpathSync(repo); scripts = externalDirectory(scripts, repo);
  const target = path.join(scripts, 'colophon'), receipt = receiptPath(scripts);
  if (exists(target)) regular(target); if (exists(receipt)) regular(receipt);
  if (rollback) { const saved = readBackup(rollback); fs.mkdirSync(scripts, {recursive: true}); backup(scripts, os.homedir(), repo); restore(saved, scripts); console.log('Native deployment rollback restored'); return; }
  const inventory = sourceInventory(repo, snapshot, !audit);
  if (audit) {
    const value = readReceipt(receipt);
    if (value.sourceHash !== inventory.sourceHash) throw new Error('Native build source drift');
    if ((regular(target).mode & 0o7777) !== value.mode || sha(fs.readFileSync(target)) !== value.binaryHash) throw new Error('Native binary bytes or mode drift');
    console.log('OK: colophon native deployment'); return;
  }
  if (dry) { console.log('Dry run: validated tracked native build inputs; no files changed'); return; }
  const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'colophon-native-build-'));
  try {
    for (const entry of inventory.entries) {
      const file = path.join(scratch, entry.name); fs.mkdirSync(path.dirname(file), {recursive: true}); fs.writeFileSync(file, entry.bytes, {mode: entry.permissions});
    }
    // Use fixed release settings; do not inherit testing flags or a user's stale binary.
    const env = {...process.env, CPPFLAGS: '', CFLAGS: '', LDFLAGS: '', MAKEFLAGS: '', MFLAGS: ''};
    execFileSync('make', ['-C', path.join(scratch, 'colophon'), 'BUILD=build', 'RELEASE_BIN=colophon', 'CC=clang', 'OPTFLAGS=-O2', 'CFLAGS=', 'CPPFLAGS=', 'LDFLAGS=', 'all'], {env, stdio: 'pipe', timeout: 300000});
    const built = path.join(scratch, 'colophon/colophon'); regular(built); diagnostic(built);
    const bytes = fs.readFileSync(built);
    if (![0xfeedfacf, 0xfeedface, 0xcafebabe, 0xbebafeca].includes(bytes.readUInt32LE(0))) throw new Error('Expected a native Mach-O executable');
    if (sourceInventory(repo, undefined, true).sourceHash !== inventory.sourceHash) throw new Error('Native inputs changed during build');
    fs.mkdirSync(scripts, {recursive: true, mode: 0o755});
    const saved = backup(scripts, os.homedir(), repo);
    try {
      atomicFile(target, bytes, 0o755, '.colophon-stage-'); diagnostic(target);
      atomicFile(receipt, Buffer.from(JSON.stringify({schema: 1, sourceHash: inventory.sourceHash, binaryHash: sha(bytes), mode: 0o755}) + '\n'), 0o600, '.colophon-stage-');
    } catch (error) { restore(readBackup(saved), scripts); throw error; }
    console.log('Native Colophon deployed; rollback backup: ' + saved);
  } finally { fs.rmSync(scratch, {recursive: true, force: true}); }
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { main(); } catch (error) { console.error('Colophon native deployment failed: ' + error.message); process.exitCode = 1; }
}
