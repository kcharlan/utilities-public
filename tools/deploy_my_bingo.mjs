import {execFileSync, spawnSync} from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {
  atomicFile, exists, externalDirectory, hashInventory, inspectAncestors,
  parseStagedListing, pruneBackups, regular, requireMain, sha,
} from './deployment_files.mjs';
import {runTransaction} from './transaction.mjs';

const installerRepo = fs.realpathSync.native(fileURLToPath(new URL('../', import.meta.url)));
const samples = ['fixtures/thanksgiving.txt', 'fixtures/thanksgiving2.txt'];
const required = ['bingo_app.html', 'css/app.css', 'js/ui/view.js', ...samples];
const sourcePaths = ['bingo_app.html', 'css', 'js', 'themes', ...samples];
const themeAsset = /\.(?:css|json|avif|gif|ico|jpe?g|png|svg|webp|woff2?)$/i;
const themeId = /^[a-zA-Z0-9_-]+$/;
const route = '/games/my_bingo/bingo_app.html';
function contains(root, name) {
  if (process.platform === 'darwin') {
    root = root.toLowerCase();
    name = name.toLowerCase();
  }
  const relative = path.relative(root, name);
  return relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative);
}
const overlaps = (a, b) => contains(a, b) || contains(b, a);
const cleanPath = name => typeof name === 'string' && !/[\\\x00-\x1f\x7f]/.test(name) &&
  name.split('/').every(part => part && !part.startsWith('.'));

function canonicalPath(name) {
  let ancestor = path.resolve(name);
  while (!exists(ancestor)) ancestor = path.dirname(ancestor);
  return path.join(fs.realpathSync.native(ancestor), path.relative(ancestor, path.resolve(name)));
}

function managed(name) {
  if (!cleanPath(name)) return false;
  return name === 'bingo_app.html' || samples.includes(name) ||
    (name.startsWith('css/') && name.endsWith('.css')) ||
    (name.startsWith('js/') && name.endsWith('.js')) ||
    (name.startsWith('themes/') && themeAsset.test(name) && !name.endsWith('/orig-theme.css'));
}

function sourceInventory(repo) {
  requireMain(repo);
  const git = ['-C', repo];
  const staged = spawnSync('git', [...git, 'diff', '--cached', '--quiet', 'HEAD', '--', ...sourcePaths]);
  if (staged.status !== 0) throw Error('My Bingo runtime must match committed main in the Git index');
  const raw = execFileSync('git', [...git, 'ls-files', '--stage', '-z', '--', ...sourcePaths],
    {encoding: 'utf8'});
  const entries = parseStagedListing(raw).filter(entry => managed(entry.name));
  if (required.some(name => !entries.some(entry => entry.name === name))) {
    throw Error('My Bingo source is missing required tracked runtime files');
  }
  for (const {name} of entries) inspectAncestors(path.dirname(path.join(repo, name)));
  return hashInventory(repo, entries, true).entries.map(({name, bytes, permissions}) =>
    ({name, bytes, mode: permissions}));
}

function current(root, name) {
  const file = path.join(root, name);
  inspectAncestors(path.dirname(file));
  if (!exists(file)) return {name, bytes: null};
  const mode = regular(file).mode & 0o7777;
  if (mode > 0o777) throw Error('Unexpected special permission bits: ' + name);
  return {name, bytes: fs.readFileSync(file), mode};
}

function matches(actual, desired) {
  if (desired.bytes === null) return actual.bytes === null;
  return actual.bytes !== null && actual.mode === desired.mode && actual.bytes.equals(desired.bytes);
}

function publish(root, items) {
  for (const {name, bytes, mode} of items) {
    const file = path.join(root, name);
    inspectAncestors(path.dirname(file));
    if (exists(file)) regular(file);
    if (bytes === null) {
      if (exists(file)) fs.unlinkSync(file);
    } else {
      fs.mkdirSync(path.dirname(file), {recursive: true, mode: 0o755});
      atomicFile(file, bytes, mode, '.my-bingo-file-');
    }
  }
}

function privateDirectory(backups, prefix) {
  inspectAncestors(backups);
  fs.mkdirSync(backups, {recursive: true, mode: 0o700});
  fs.chmodSync(backups, 0o700);
  return fs.mkdtempSync(path.join(backups, prefix));
}

function saveSnapshot(backups, items) {
  const backup = privateDirectory(backups, 'copy-');
  const records = items.map(({name, bytes, mode}) => {
    if (bytes === null) return {name, absent: true};
    const file = path.join(backup, 'payload', name);
    fs.mkdirSync(path.dirname(file), {recursive: true, mode: 0o700});
    fs.writeFileSync(file, bytes, {mode: 0o600});
    return {name, mode, hash: sha(bytes)};
  });
  fs.writeFileSync(path.join(backup, 'state.json'), JSON.stringify(records) + '\n', {mode: 0o600});
  return backup;
}

function loadSnapshot(backups, requested) {
  inspectAncestors(path.resolve(requested));
  const backup = canonicalPath(requested);
  if (path.dirname(backup) !== backups || !path.basename(backup).startsWith('copy-')) {
    throw Error('Rollback must name a My Bingo copy backup');
  }
  const state = path.join(backup, 'state.json');
  regular(state);
  const records = JSON.parse(fs.readFileSync(state, 'utf8'));
  if (!Array.isArray(records) || !records.length) throw Error('Invalid My Bingo backup inventory');
  const names = new Set();
  return records.map(record => {
    if (!record || !managed(record.name) || names.has(record.name)) {
      throw Error('Invalid My Bingo backup inventory');
    }
    const {name, mode, hash} = record;
    names.add(name);
    if (record.absent === true) return {name, bytes: null};
    if (!Number.isInteger(mode) || mode < 0 || mode > 0o777) throw Error('Invalid backup mode');
    const item = current(path.join(backup, 'payload'), name);
    if (item.bytes === null || sha(item.bytes) !== hash) throw Error('Backup content hash mismatch');
    return {name, bytes: item.bytes, mode};
  });
}

function localFiles(target, source) {
  const files = [];
  const shipped = new Set(source.filter(item => item.name.startsWith('themes/'))
    .map(item => item.name.split('/')[1]));
  function readTheme(folder) {
    inspectAncestors(path.join(target, folder));
    for (const entry of fs.readdirSync(path.join(target, folder), {withFileTypes: true})) {
      const name = folder + '/' + entry.name;
      if (!cleanPath(name)) continue;
      if (entry.isDirectory()) readTheme(name);
      else if (entry.isFile()) files.push(current(target, name));
    }
  }
  const themes = path.join(target, 'themes');
  if (exists(themes)) {
    inspectAncestors(themes);
    const manifest = 'themes/manifest.json';
    if (exists(path.join(target, manifest)) && !source.some(item => item.name === manifest)) {
      files.push(current(target, manifest));
    }
    for (const entry of fs.readdirSync(themes, {withFileTypes: true})) {
      if (!entry.isDirectory() || !themeId.test(entry.name) || shipped.has(entry.name)) continue;
      const folder = 'themes/' + entry.name;
      if (exists(path.join(target, folder, 'theme.json'))) readTheme(folder);
    }
  }
  const oldTracked = new Set(execFileSync('git', ['-C', target, 'ls-files', '-z', '--', 'fixtures', 'wordlists'],
    {encoding: 'utf8'}).split('\0'));
  for (const folder of ['fixtures', 'wordlists']) {
    const dir = path.join(target, folder);
    if (!exists(dir)) continue;
    inspectAncestors(dir);
    for (const entry of fs.readdirSync(dir, {withFileTypes: true})) {
      const name = folder + '/' + entry.name;
      if (entry.isFile() && cleanPath(name) && name.endsWith('.txt') && !oldTracked.has(name) &&
          !samples.includes(name)) files.push(current(target, name));
    }
  }
  return files;
}

async function migrate(target, backups, items) {
  let archive;
  await runTransaction({
    name: 'My Bingo checkout migration',
    admit() {},
    isCurrent: () => false,
    build(registerCleanup) {
      const stage = fs.mkdtempSync(path.join(path.dirname(target), '.my-bingo-stage-'));
      registerCleanup(() => fs.rmSync(stage, {recursive: true, force: true}));
      const candidate = path.join(stage, 'runtime');
      publish(candidate, items);
      return {value: candidate};
    },
    install(candidate, recover) {
      archive = privateDirectory(backups, 'legacy-');
      const saved = path.join(archive, 'checkout');
      recover(() => {
        if (!exists(saved)) return;
        if (exists(target)) fs.renameSync(target, path.join(archive, 'failed-runtime'));
        fs.renameSync(saved, target);
      });
      fs.renameSync(target, saved);
      fs.renameSync(candidate, target);
    },
    verify() {
      if (items.some(item => !matches(current(target, item.name), item))) {
        throw Error('Migrated My Bingo runtime failed verification');
      }
    },
  }).catch(error => {
    if (!archive) throw error;
    throw Error(error.message + '\nMigration archive: ' + archive, {cause: error});
  });
  return archive;
}

async function deploy({repo = path.join(path.dirname(installerRepo), 'my_bingo'),
  webroot = process.env.UTILITIES_WEBROOT_DIR || path.join(os.homedir(), 'webroot'),
  backups = path.join(os.homedir(), '.utilities-deploy-backups', 'my-bingo'),
  dryRun, check, rollback, migrateCheckout} = {}) {
  if ([dryRun, check, Boolean(rollback)].filter(Boolean).length > 1 ||
      (migrateCheckout && (check || rollback))) throw Error('Incompatible deployment options');
  repo = rollback ? canonicalPath(repo) : fs.realpathSync.native(repo);
  webroot = canonicalPath(externalDirectory(path.resolve(webroot), repo));
  backups = canonicalPath(externalDirectory(path.resolve(backups), repo));
  if (overlaps(webroot, backups)) throw Error('My Bingo backups must be outside webroot');
  if ([webroot, backups].some(dir => overlaps(dir, repo) || overlaps(dir, installerRepo))) {
    throw Error('My Bingo destinations must be outside both source repositories');
  }
  const target = path.join(webroot, 'games', 'my_bingo');
  inspectAncestors(target);
  const legacy = exists(path.join(target, '.git'));
  if (legacy && !migrateCheckout) throw Error('Existing checkout requires --migrate-checkout');
  if (!legacy && migrateCheckout) throw Error('No legacy My Bingo checkout to migrate');
  const desired = rollback ? loadSnapshot(backups, rollback) : sourceInventory(repo);
  if (migrateCheckout) {
    inspectAncestors(path.join(target, '.git'));
    const local = localFiles(target, desired);
    if (dryRun) {
      console.log(`Dry run: archive legacy checkout and install ${desired.length} runtime files, preserving ${local.length} local files`);
      return;
    }
    const archive = await migrate(target, backups, [...desired, ...local]);
    console.log('My Bingo deployed to ' + route + '\nLegacy checkout: ' + archive);
    return;
  }
  const previous = desired.map(item => current(target, item.name));
  const changed = desired.filter((item, index) => !matches(previous[index], item));
  if (check) {
    if (changed.length) throw Error('Installed My Bingo runtime differs: ' + changed.map(item => item.name).join(', '));
    console.log('My Bingo installed runtime matches committed source');
    return;
  }
  if (dryRun || !changed.length) {
    console.log(dryRun ? `Dry run: ${changed.length} runtime files would change` : 'My Bingo already matches source');
    return;
  }
  let backup;
  await runTransaction({
    name: 'My Bingo deployment',
    admit() {},
    isCurrent: () => false,
    build: () => ({}),
    install(_value, recover) {
      backup = saveSnapshot(backups, previous);
      const names = new Set(changed.map(item => item.name));
      recover(() => publish(target, previous.filter(item => names.has(item.name))));
      publish(target, changed);
    },
    verify() {
      if (desired.some(item => !matches(current(target, item.name), item))) {
        throw Error('Installed My Bingo bytes or modes failed verification');
      }
    },
  }).catch(error => {
    if (!backup) throw error;
    throw Error(error.message + '\nRecovery backup: ' + backup, {cause: error});
  });
  if (!rollback) pruneBackups(backups);
  console.log('My Bingo deployed to ' + route + '\nRecovery backup: ' + backup);
}

const options = {};
try {
  const args = process.argv.slice(2);
  for (let index = 0; index < args.length; index++) {
    const arg = args[index];
    if (arg === '--help') {
      console.log('Usage: node tools/deploy_my_bingo.mjs [--dry-run | --check | --rollback BACKUP] [--migrate-checkout] [--repo DIR] [--webroot DIR] [--backups DIR]');
      process.exit(0);
    }
    if (arg === '--dry-run') options.dryRun = true;
    else if (arg === '--check') options.check = true;
    else if (arg === '--migrate-checkout') options.migrateCheckout = true;
    else if (['--repo', '--webroot', '--backups', '--rollback'].includes(arg) &&
      args[index + 1] && !args[index + 1].startsWith('--')) options[arg.slice(2)] = args[++index];
    else throw Error('Unknown or incomplete option: ' + arg);
  }
  await deploy(options);
} catch (error) {
  console.error('My Bingo deployment failed: ' + error.message);
  process.exitCode = 1;
}
