// Invented artifacts for read-only fleet fixtures; lifecycle tests compile C.
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {parseStagedListing, normalizeEntries, hashInventory, sha} from '../deployment_files.mjs';

const [repo, home] = process.argv.slice(2);
const entries = normalizeEntries(parseStagedListing(execFileSync('git', [
  '-C', repo, 'ls-files', '--stage', '-z', '--', 'storage_monitor',
], {encoding: 'utf8'})));
const nativeEntries = entries.filter(e => e.name.startsWith('storage_monitor/native/'));
const nativeSourceHash = hashInventory(repo, nativeEntries, true).sourceHash;
const scripts = path.join(home, 'Library/Scripts');
const launcher = fs.readFileSync(path.join(repo, 'storage_monitor/storage_monitor'));
const walker = Buffer.from('synthetic walker artifact for read-only audit\n');
for (const [name, bytes] of [['storage_monitor', launcher], ['storage_monitor_walk', walker]]) {
  fs.writeFileSync(path.join(scripts, name), bytes, {mode: 0o755});
  fs.chmodSync(path.join(scripts, name), 0o755);
}
fs.writeFileSync(path.join(scripts, '.storage_monitor.json'), JSON.stringify({
  schema: 1, launcherHash: sha(launcher), launcherMode: 0o755,
  nativeSourceHash, walkerHash: sha(walker), walkerMode: 0o755,
  walkerVersion: '0.0.1', protocol: 1,
}) + '\n', {mode: 0o600});
