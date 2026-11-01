#!/usr/bin/env node
import {readFileSync, writeFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const canonical = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'local_server_guard.py'), 'utf8').trimEnd();
const begin = '# local-server-guard:begin';
const end = '# local-server-guard:end';
function result(path) {
  const source = readFileSync(path, 'utf8');
  const pattern = /^# local-server-guard:begin\r?\n[\s\S]*?^# local-server-guard:end[ \t]*$/gm;
  const begins = source.split(begin).length - 1;
  const ends = source.split(end).length - 1;
  let count = 0;
  const updated = source.replace(pattern, () => { count++; return `${begin}\n${canonical}\n${end}`; });
  if (!count || count !== begins || count !== ends) throw Error(`${path}: missing or malformed local-server-guard region`);
  return {path, source, updated};
}
try {
  const args = process.argv.slice(2), check = args.includes('--check'), all = args.includes('--all');
  let files = args.filter(x => x !== '--check' && x !== '--all');
  if (all && files.length) throw Error('use --all or file arguments, not both');
  if (all) {
    const root = execFileSync('git', ['rev-parse', '--show-toplevel'], {encoding:'utf8'}).trim();
    const names = execFileSync('git', ['-C', root, 'ls-files', '-z'], {encoding:'utf8'}).split('\0').filter(Boolean);
    files = names.map(name => join(root, name)).filter(file =>
      /^# local-server-guard:begin[ \t]*$/m.test(readFileSync(file, 'utf8')));
    if (!files.length) throw Error(`${root}: no tracked file has a local-server-guard region`);
  }
  if (!files.length) throw Error('usage: sync_local_server_guard.mjs [--check] [--all | file...]');
  const changes = files.map(result).filter(item => item.source !== item.updated);
  if (check && changes.length) throw Error(`stale local-server-guard region: ${changes.map(x => x.path).join(', ')}`);
  for (const item of changes) writeFileSync(item.path, item.updated);
} catch (error) { console.error(error.message); process.exitCode = 1; }
