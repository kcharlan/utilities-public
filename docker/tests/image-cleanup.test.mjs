import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const docker = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
function runs(name) {
  return fs.readFileSync(path.join(docker, name), 'utf8').replace(/\\\n\s*/g, ' ').split('\n').filter(line => line.startsWith('RUN ')).map(line => line.slice(4));
}
function runFragment(fragment, root, fail = false) {
  assert.doesNotMatch(fragment, /\brm\s+[^;&|\n]*-(?:[A-Za-z]*f|-[^\s]*force)/, 'forced cleanup is forbidden');
  const shim = path.join(root, 'shim'); fs.mkdirSync(shim, {recursive:true});
  fs.writeFileSync(path.join(shim, 'rm'), '#!/bin/sh\n[ "${SYNTHETIC_FAIL:-}" = 1 ] && exit 71\nexec /bin/rm "$@"\n', {mode:0o755});
  const rewritten = fragment.replaceAll('/var/lib/apt/lists/', `${root}/apt/`).replaceAll('/tmp/collector-requirements.txt', `${root}/requirements.txt`).replaceAll('/usr/local/lib/node_modules/npm', `${root}/npm`).replaceAll('/usr/local/bin/npm', `${root}/bin/npm`).replaceAll('/usr/local/bin/npx', `${root}/bin/npx`);
  return spawnSync('/bin/sh', ['-c', rewritten], {encoding:'utf8', env:{PATH:`${shim}:/usr/bin:/bin`, SYNTHETIC_FAIL:fail?'1':''}});
}
function scratch(fn) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'docker-cleanup-test-')); console.log(`Fixture root: ${root}`);
  try { fn(root); } finally { fs.rmSync(root, {recursive:true}); console.log(`Removed fixture root: ${root}`); }
}
const ok = r => assert.equal(r.status, 0, r.stderr);
test('collector removes apt contents and temporary requirements without masking failures', () => scratch(root => {
  const commands = runs('llm_collector/llm_collector_container/Dockerfile');
  const apt = commands.find(s => s.includes('/var/lib/apt/lists/')).replace(/^.*?&&\s*(?=(?:\{|for|if|rm)\b)/, '');
  const requirements = commands.find(s => s.includes('/tmp/collector-requirements.txt')).replace(/^.*?&&\s*(?=(?:\{|for|if|rm)\b)/, '');
  fs.mkdirSync(path.join(root, 'apt/partial'), {recursive:true});fs.writeFileSync(path.join(root, 'apt/partial/item'), 'synthetic');fs.writeFileSync(path.join(root, 'apt/index'), 'synthetic');fs.symlinkSync('missing',path.join(root,'apt/dangling'));fs.writeFileSync(path.join(root, 'requirements.txt'), 'synthetic');
  assert.notEqual(runFragment(apt, root, true).status, 0);assert.ok(fs.existsSync(path.join(root, 'apt/index')));ok(runFragment(apt, root));assert.deepEqual(fs.readdirSync(path.join(root, 'apt')), []);ok(runFragment(apt, root));
  assert.notEqual(runFragment(requirements, root, true).status, 0);assert.ok(fs.existsSync(path.join(root, 'requirements.txt')));ok(runFragment(requirements, root));assert.equal(fs.existsSync(path.join(root, 'requirements.txt')), false);ok(runFragment(requirements, root));
}));
for (const dockerfile of ['webserver/index/Dockerfile', 'webserver/app_node_Dockerfile']) test(`${dockerfile} removes npm and links without masking failures`, () => scratch(root => {
  const command = runs(dockerfile).find(s => s.includes('/usr/local/lib/node_modules/npm'));
  fs.mkdirSync(path.join(root, 'npm/nested'), {recursive:true});fs.writeFileSync(path.join(root, 'npm/nested/package'), 'synthetic');fs.mkdirSync(path.join(root,'bin'));fs.symlinkSync('../npm/npm.js', path.join(root,'bin/npm'));fs.symlinkSync('../npm/npx.js', path.join(root,'bin/npx'));
  assert.notEqual(runFragment(command,root,true).status,0);assert.ok(fs.existsSync(path.join(root,'npm')));ok(runFragment(command,root));assert.equal(fs.existsSync(path.join(root,'npm')),false);assert.deepEqual(fs.readdirSync(path.join(root,'bin')),[]);
  fs.symlinkSync('../missing',path.join(root,'bin/npm'));assert.notEqual(runFragment(command,root,true).status,0);assert.equal(fs.lstatSync(path.join(root,'bin/npm')).isSymbolicLink(),true);ok(runFragment(command,root));assert.deepEqual(fs.readdirSync(path.join(root,'bin')),[]);ok(runFragment(command,root));
}));
