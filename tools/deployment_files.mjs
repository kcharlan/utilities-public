import fs from 'node:fs';
import path from 'node:path';

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
