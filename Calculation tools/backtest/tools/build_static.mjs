/** Copy the reviewed source and selected local data to a flat static directory. */
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { readOwned, safeRoot, verifyBundle } from './data_contract.mjs';
import { setupData } from './setup_data.mjs';

export const SCRIPT_ASSETS = Object.freeze([
  'market-data.js', 'format.js', 'stats.js', 'views.js', 'lifestyle.js',
  'charts.js', 'csv.js', 'engine.js', 'app.js',
]);
export const RUNTIME_ASSETS = Object.freeze([...SCRIPT_ASSETS, 'market-data.csv', 'DATA_SOURCES.md']);
export const RUNTIME_FILES = Object.freeze(['index.html', ...RUNTIME_ASSETS]);
export const SOURCE_INPUTS = Object.freeze(RUNTIME_FILES.filter(name => !name.startsWith('market-data.')));
export const DATA_INPUTS = Object.freeze(['market-data.js', 'market-data.csv']);
export const DEFAULT_SOURCE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const REPO_ROOT = path.resolve(DEFAULT_SOURCE, '../..');
export const defaultDataHome = () => path.resolve(
  process.env.MARKET_ATLAS_DATA_HOME || path.join(os.homedir(), '.cache/market-atlas'),
);

export async function readRuntime({
  sourceRoot = DEFAULT_SOURCE, dataRoot, dataHome = defaultDataHome(),
} = {}) {
  const bundle = await verifyBundle({
    sourceRoot, repoRoot: REPO_ROOT, dataRoot, dataHome, requireCurrentRecipe: true,
  });
  const files = new Map();
  for (const name of RUNTIME_FILES) {
    const bytes = bundle.files.has(name)
      ? bundle.files.get(name)
      : await readOwned(path.join(sourceRoot, name));
    files.set(name, Buffer.from(bytes));
  }
  return files;
}

export async function validateFlat(directory, expected) {
  if (!(await fs.lstat(directory)).isDirectory()) {
    throw Error('Runtime requires a regular directory');
  }
  const names = (await fs.readdir(directory)).sort();
  if (names.join(',') !== [...RUNTIME_FILES].sort().join(',')) {
    throw Error('Unexpected flat runtime inventory');
  }
  for (const name of RUNTIME_FILES) {
    const bytes = await readOwned(path.join(directory, name));
    if (expected && !bytes.equals(expected.get(name))) {
      throw Error('Runtime bytes differ; stale build must be rebuilt: ' + name);
    }
  }
}

export async function copyRuntime(files, directory, { copyFile, sourceDir } = {}) {
  for (const [name, bytes] of files) {
    const target = path.join(directory, name);
    if (copyFile) {
      await copyFile(path.join(sourceDir, name), target);
    } else {
      await fs.writeFile(target, bytes, { flag: 'wx', mode: 0o644 });
    }
    await fs.chmod(target, 0o644);
  }
  await fs.chmod(directory, 0o755);
}

export async function buildStatic({
  sourceRoot = DEFAULT_SOURCE, dataRoot, dataHome = defaultDataHome(),
  outputDir = path.join(dataHome, 'site'), hooks = {},
} = {}) {
  sourceRoot = path.resolve(sourceRoot);
  outputDir = path.resolve(outputDir);
  await safeRoot(outputDir, {
    sourceRoot, repoRoot: REPO_ROOT, webroots: dataRoot ? [dataRoot] : [],
  });
  const files = await readRuntime({ sourceRoot, dataRoot, dataHome });
  let exists = false;
  try {
    await validateFlat(outputDir);
    exists = true;
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }

  const parent = path.dirname(outputDir);
  await fs.mkdir(parent, { recursive: true, mode: 0o700 });
  const stage = path.join(parent, '.atlas-stage-' + randomUUID());
  const previous = path.join(parent, '.atlas-recovery-' + randomUUID());
  const rename = hooks.rename || fs.rename;
  const remove = hooks.remove || (target => fs.rm(target, { recursive: true, force: true }));
  let moved = false, promoted = false, committed = false, failure, result;
  await fs.mkdir(stage, { mode: 0o755 });
  try {
    for (const [name, bytes] of files) {
      const target = path.join(stage, name);
      if (hooks.copyFile) {
        const inputRoot = name.startsWith('market-data.') ? dataRoot : sourceRoot;
        await hooks.copyFile(path.join(inputRoot, name), target);
      } else {
        await fs.writeFile(target, bytes, { flag: 'wx', mode: 0o644 });
      }
      await fs.chmod(target, 0o644);
    }
    await fs.chmod(stage, 0o755);
    await validateFlat(stage, files);
    if (exists) {
      await rename(outputDir, previous);
      moved = true;
    }
    await rename(stage, outputDir);
    promoted = true;
    await validateFlat(outputDir, files);

    // Once the promoted bytes are verified, cleanup cannot roll them back.
    committed = true;
    if (moved) await remove(previous);
    result = { outputDirectory: outputDir, fileCount: files.size };
  } catch (error) {
    failure = error;
    if (committed) {
      error.committedOutputDirectory = outputDir;
      error.recoveryDirectory = previous;
    } else {
      if (promoted) {
        try {
          await remove(outputDir);
        } catch (removal) {
          error.removalError = removal;
          error.outputDirectory = outputDir;
        }
      }
      // A failed removal leaves an occupied destination. Keep the previous tree
      // available for manual recovery rather than renaming over that directory.
      if (moved) {
        if (error.removalError) {
          error.recoveryDirectory = previous;
        } else {
          try {
            await rename(previous, outputDir);
          } catch (restoration) {
            error.restorationError = restoration;
            error.recoveryDirectory = previous;
          }
        }
      }
    }
  } finally {
    try {
      await remove(stage);
    } catch (cleanup) {
      if (failure) failure.cleanupError = cleanup;
      else failure = cleanup;
      failure.stageDirectory = stage;
      if (committed) failure.committedOutputDirectory = outputDir;
    }
  }
  if (failure) throw failure;
  return result;
}

export async function buildLocal(options = {}) {
  const sourceRoot = options.sourceRoot || DEFAULT_SOURCE;
  const dataHome = options.dataHome || defaultDataHome();
  const setup = options.hooks?.setup || setupData;
  const selected = await setup({ ...options, sourceRoot, dataHome, repoRoot: REPO_ROOT });
  return buildStatic({
    ...options, sourceRoot, dataHome, dataRoot: selected.root,
    outputDir: options.out || options.outputDir || path.join(dataHome, 'site'),
  });
}

export const BUILD_USAGE = 'Usage: npm run build -- [--offline] [--out PATH]';
export function parseBuildArgs(args) {
  const options = {};
  for (let index = 0; index < args.length; index++) {
    if (args[index] === '--offline' && !options.offline) {
      options.offline = true;
    } else if (args[index] === '--out' && !options.out
      && args[index + 1] && !args[index + 1].startsWith('--')) {
      options.out = args[++index];
    } else {
      throw Error(BUILD_USAGE);
    }
  }
  return options;
}

export function formatBuildFailure(error) {
  const lines = [error.message];
  for (const [key, label] of [
    ['removalError', 'Removal'], ['restorationError', 'Restoration'],
    ['cleanupError', 'Stage cleanup'],
  ]) {
    if (error[key]) lines.push(label + ' failed: ' + error[key].message);
  }
  for (const [key, label] of [
    ['committedOutputDirectory', 'Verified output'], ['recoveryDirectory', 'Retained recovery'],
    ['outputDirectory', 'Output to inspect'], ['stageDirectory', 'Retained stage'],
  ]) {
    if (error[key]) lines.push(label + ': ' + error[key]);
  }
  return lines;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const result = await buildLocal(parseBuildArgs(process.argv.slice(2)));
    console.log(`Built ${result.fileCount} files: ${result.outputDirectory}`);
  } catch (error) {
    for (const line of formatBuildFailure(error)) console.error(line);
    process.exitCode = 1;
  }
}
