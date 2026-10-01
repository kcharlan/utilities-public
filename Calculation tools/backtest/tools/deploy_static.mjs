/** Ordinary local copy installation with a whole-directory private backup. */
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { safeRoot, verifySelected } from './data_contract.mjs';
import {
  DEFAULT_SOURCE, REPO_ROOT, defaultDataHome, readRuntime, validateFlat, copyRuntime,
} from './build_static.mjs';

async function canonicalPath(target) {
  let ancestor = target;
  const tail = [];
  while (true) {
    try {
      return path.join(await fs.realpath(ancestor), ...tail.reverse());
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
      const parent = path.dirname(ancestor);
      if (parent === ancestor) throw error;
      tail.push(path.basename(ancestor));
      ancestor = parent;
    }
  }
}

export async function deployStatic(options = {}) {
  const sourceRoot = path.resolve(options.sourceRoot || DEFAULT_SOURCE);
  const dataHome = path.resolve(options.dataHome || defaultDataHome());
  const webroot = path.resolve(
    options.webroot || process.env.UTILITIES_WEBROOT_DIR || path.join(os.homedir(), 'webroot'),
  );
  const buildDir = path.resolve(options.buildDir || path.join(dataHome, 'site'));
  const site = path.join(webroot, 'calculators/backtest');

  // Existing parent aliases must not turn the explicit target into a source tree.
  const canonicalWebroot = await canonicalPath(webroot);
  for (const root of [sourceRoot, REPO_ROOT, dataHome, buildDir, options.dataRoot].filter(Boolean)) {
    const canonical = await canonicalPath(root);
    const relative = path.relative(canonical, canonicalWebroot);
    const reverse = path.relative(canonicalWebroot, canonical);
    const inside = value => value === '' || value !== '..'
      && !value.startsWith('..' + path.sep) && !path.isAbsolute(value);
    if (inside(relative) || inside(reverse)) {
      throw Error('Deployment webroot overlaps source, repository, data or build');
    }
  }

  const backupRoot = path.resolve(
    options.backupRoot || path.join(os.homedir(), '.utilities-deploy-backups/backtest'),
  );
  await safeRoot(buildDir, { sourceRoot, repoRoot: REPO_ROOT, webroots: [webroot] });
  await safeRoot(backupRoot, {
    sourceRoot, repoRoot: REPO_ROOT, webroots: [webroot, buildDir],
  });
  // Parent symlinks must never redirect a deployment into another tree.
  for (const directory of [webroot, path.join(webroot, 'calculators'), site]) {
    try {
      if (!(await fs.lstat(directory)).isDirectory()) {
        throw Error('Deployment path requires regular directories');
      }
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  }

  const selected = options.dataRoot
    ? { root: options.dataRoot }
    : await verifySelected({ sourceRoot, repoRoot: REPO_ROOT, dataHome, requireCurrentRecipe: true });
  if (!selected) throw Error('Local data is missing; run npm run setup:data');
  const expected = await readRuntime({ sourceRoot, dataHome, dataRoot: selected.root });
  await validateFlat(buildDir, expected);
  const hadPrevious = await fs.lstat(site).then(() => true, error => {
    if (error.code === 'ENOENT') return false;
    throw error;
  });
  const summary = {
    dryRun: !!options.dryRun, targetDirectory: site, fileCount: expected.size,
    canonicalURL: '/calculators/backtest/index.html',
    backupAction: hadPrevious ? 'move previous app into private backup' : 'no previous app',
  };
  if (options.dryRun) return summary;

  const hooks = options.hooks || {};
  const rename = hooks.rename || fs.rename;
  await fs.mkdir(backupRoot, { recursive: true, mode: 0o700 });
  const timestamp = new Date().toISOString().replaceAll(':', '-');
  const container = await fs.mkdtemp(path.join(backupRoot, timestamp + '-'));
  await fs.chmod(container, 0o700);
  const backupDirectory = path.join(container, 'backtest');
  let saved = false, created = false;
  try {
    await fs.mkdir(path.dirname(site), { recursive: true, mode: 0o755 });
    if (hadPrevious) {
      await rename(site, backupDirectory);
      saved = true;
    }
    await fs.mkdir(site, { mode: 0o755 });
    created = true;
    await copyRuntime(expected, site, {
      copyFile: hooks.copyFile || fs.copyFile, sourceDir: buildDir,
    });
    await validateFlat(site, expected);
    if (hooks.verify) await hooks.verify(site, expected);
    return {
      ...summary, backupDirectory: saved ? backupDirectory : null,
      backupContainer: container,
    };
  } catch (error) {
    error.backupDirectory = saved ? backupDirectory : null;
    error.targetDirectory = site;
    try {
      if (created) await fs.rm(site, { recursive: true, force: true });
      if (saved) await rename(backupDirectory, site);
      error.restored = true;
    } catch (restoration) {
      error.restorationError = restoration;
    }
    throw error;
  }
}

export const DEPLOY_USAGE = 'Usage: npm run deploy -- [--webroot PATH] [--build-dir PATH] [--dry-run]';
export function parseDeployArgs(args) {
  const options = {};
  for (let index = 0; index < args.length; index++) {
    if (args[index] === '--dry-run' && !options.dryRun) {
      options.dryRun = true;
    } else if (['--webroot', '--build-dir'].includes(args[index])) {
      const key = args[index] === '--webroot' ? 'webroot' : 'buildDir';
      if (options[key] || !args[index + 1] || args[index + 1].startsWith('--')) {
        throw Error(DEPLOY_USAGE);
      }
      options[key] = args[++index];
    } else {
      throw Error(DEPLOY_USAGE);
    }
  }
  return options;
}

export function formatDeploymentFailure(error) {
  const lines = [error.message];
  if (error.restorationError) lines.push('Restoration failed: ' + error.restorationError.message);
  if (error.backupDirectory) lines.push('Backup path to inspect: ' + error.backupDirectory);
  if (error.targetDirectory) lines.push('Target path to inspect: ' + error.targetDirectory);
  return lines;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const result = await deployStatic(parseDeployArgs(process.argv.slice(2)));
    console.log(`${result.dryRun ? 'Dry run:' : 'Installed:'} ${result.targetDirectory} (${result.fileCount} files); ${result.backupAction}`);
    if (result.backupDirectory) console.log('Saved previous app: ' + result.backupDirectory);
  } catch (error) {
    for (const line of formatDeploymentFailure(error)) console.error(line);
    process.exitCode = 1;
  }
}
