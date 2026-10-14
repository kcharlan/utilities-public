import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync, execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const script = fileURLToPath(new URL('../deploy_storage_monitor.mjs', import.meta.url));
function fixture(t) {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'synthetic-walker-deploy-'));
  t.after(() => fs.rmSync(base, {recursive: true, force: true}));
  const repo = path.join(base, 'invented repo'), home = path.join(base, 'invented home');
  const project = path.join(repo, 'storage_monitor'), scripts = path.join(home, 'Library/Scripts');
  fs.mkdirSync(project, {recursive: true}); fs.mkdirSync(home);
  const write = (name, bytes, mode = 0o644) => {
    const file = path.join(project, name); fs.mkdirSync(path.dirname(file), {recursive: true});
    fs.writeFileSync(file, bytes); fs.chmodSync(file, mode);
  };
  const git = (...args) => execFileSync('git', ['-C', repo, ...args], {stdio: 'pipe'});
  const launcher = (protocol = 1) => { write('storage_monitor', `#!/bin/sh\nWALKER_PROTOCOL = ${protocol}\n# synthetic launcher\n`, 0o755); git('add', '.'); };
  function release(label = 'first', failInstalled = false, dirs = 3, hardlinks = 2) {
    write('native/src/storage_monitor_walk.c', `#include <stdio.h>\n#include <string.h>\n#include <stdlib.h>\n#define SMW_PROTOCOL 1\nint main(int argc, char **argv) {\n const char *marker = getenv("SYNTHETIC_EXECUTION_MARKER"); if (marker) { FILE *f = fopen(marker, "w"); if (f) { fputs("executed", f); fclose(f); } }\n if (${Number(failInstalled)} && strstr(argv[0], "/Scripts/")) return 1;\n if (argc == 2 && !strcmp(argv[1], "--version")) { puts("storage_monitor_walk 1.0.0 protocol 1"); return 0; }\n if (argc > 2 && !strcmp(argv[1], "walk")) {\n const char *fields[] = {${Array.from({length:hardlinks}, () => '"H", "1", "2", "2", "4096", "synthetic", "link",').join('')} "S", "${dirs}", "3", "0", "1"};\n for (unsigned i=0; i<sizeof(fields)/sizeof(fields[0]); i++) printf("%s%c", fields[i], 0);\n return 0; }\n /* synthetic ${label} */ return 2; }\n`);
    git('add', '.');
  }
  write('native/Makefile', 'all: $(BUILD_DIR)/storage_monitor_walk\n$(BUILD_DIR)/storage_monitor_walk: src/storage_monitor_walk.c\n\tmkdir -p $(BUILD_DIR)\n\t$(CC) $(CPPFLAGS) $(CFLAGS) src/storage_monitor_walk.c $(LDFLAGS) -o $@\n');
  git('init', '-q'); launcher(); release();
  const runEnv = (env, ...args) => spawnSync(process.execPath, [script, '--repo', repo, '--scripts-dir', scripts, ...args], {
    encoding: 'utf8', env: {...process.env, HOME: home, TMPDIR: base, ...env}
  });
  const run = (...args) => runEnv({}, ...args);
  const files = ['storage_monitor', 'storage_monitor_walk', '.storage_monitor.json'];
  const deployed = () => files.map(n => {const p = path.join(scripts, n); return [fs.readFileSync(p), fs.statSync(p).mode & 0o7777];});
  const backups = () => {const p = path.join(home, '.utilities-deploy-backups/storage_monitor'); return fs.existsSync(p) ? fs.readdirSync(p).map(n => path.join(p,n)).sort() : [];};
  return {base, repo, home, project, scripts, files, write, git, launcher, release, run, runEnv, deployed, backups};
}
const succeeds = r => assert.equal(r.status, 0, r.stderr + r.stdout);
test('dry-run reports rebuild on first deploy and writes nothing', t => {
  const f = fixture(t); const before = fs.readdirSync(f.home); const r = f.run('--dry-run'); succeeds(r);
  assert.match(r.stdout, /launcher: update\nwalker: rebuild \(no receipt\)\nDry run: no files changed/);
  assert.deepEqual(fs.readdirSync(f.home), before);
});
test('first deploy installs launcher, walker and receipt with modes 0755/0755/0600', t => {
  const f = fixture(t); succeeds(f.run()); assert.deepEqual(f.deployed().map(v=>v[1]), [0o755,0o755,0o600]);
  const receipt = JSON.parse(f.deployed()[2][0]); assert.equal(receipt.protocol,1); assert.equal(receipt.walkerVersion,'1.0.0');
});
test('second run with no changes reports already current and creates no backup', t => {
  const f = fixture(t); succeeds(f.run()); const before = f.backups(); const r = f.run(); succeeds(r);
  assert.match(r.stdout, /Storage Monitor already current; nothing changed/); assert.deepEqual(f.backups(),before);
});
test('launcher-only change does not rebuild', t => {
  const f = fixture(t); succeeds(f.run()); const walker = f.deployed()[1];
  fs.appendFileSync(path.join(f.project,'storage_monitor'),'# synthetic update\n'); f.git('add','.');
  const r = f.run(); succeeds(r); assert.match(r.stdout,/walker: current/); assert.deepEqual(f.deployed()[1],walker);
});
test('native change rebuilds', t => {
  const f = fixture(t); succeeds(f.run()); f.release('second'); const r = f.run(); succeeds(r); assert.match(r.stdout,/walker: rebuild \(source changed\)/);
});
test('--rebuild forces a build and clears inherited make flags', t => {
  const f = fixture(t); succeeds(f.run()); const r = f.runEnv({MAKEFLAGS:'--invalid-synthetic',MFLAGS:'--invalid-synthetic',CFLAGS:'--invalid-synthetic',CPPFLAGS:'--invalid-synthetic',LDFLAGS:'--invalid-synthetic'},'--rebuild');
  succeeds(r); assert.match(r.stdout,/walker: rebuild \(forced\)/);
  const before=f.deployed(), bin=path.join(f.base,'synthetic failing make'); fs.mkdirSync(bin);
  fs.writeFileSync(path.join(bin,'make'),'#!/bin/sh\nif [ "$1" = "--version" ]; then exit 0; fi\necho "synthetic forced build failure" >&2\nexit 1\n',{mode:0o755});
  const env={PATH:bin+path.delimiter+process.env.PATH};
  succeeds(f.runEnv(env));
  const forced=f.runEnv(env,'--rebuild'); assert.equal(forced.status,1); assert.match(forced.stderr,/synthetic forced build failure/); assert.deepEqual(f.deployed(),before);
});
test('protocol mismatch is refused before backup', t => {
  const f = fixture(t); f.launcher(2); const r = f.run(); assert.equal(r.status,1); assert.match(r.stderr,/launcher expects walker protocol 2 but native source declares 1/); assert.deepEqual(f.backups(),[]);
});
test('missing toolchain fails before backup', t => {
  const f = fixture(t); const bin = path.join(f.base,'synthetic bin'); fs.mkdirSync(bin); fs.writeFileSync(path.join(bin,'xcrun'),'#!/bin/sh\nexit 1\n',{mode:0o755});
  const r = f.runEnv({PATH:bin+path.delimiter+process.env.PATH}); assert.equal(r.status,1); assert.match(r.stderr,/Xcode Command Line Tools are required/); assert.deepEqual(f.backups(),[]);
});
test('unstaged working change is refused', t => {
  const f = fixture(t); fs.appendFileSync(path.join(f.project,'storage_monitor'),'# unstaged\n'); const r=f.run(); assert.equal(r.status,1); assert.match(r.stderr,/working bytes differ from Git index/);
});
test('activation failure restores prior deployment', t => {
  const f = fixture(t); succeeds(f.run()); const before=f.deployed(); f.release('broken',true); const r=f.run(); assert.equal(r.status,1); assert.deepEqual(f.deployed(),before);
});
test('audit passes, then fails on walker drift, launcher drift and source drift without execution', t => {
  const f = fixture(t); succeeds(f.run()); const before=f.deployed();
  const inventory=path.join(f.base,'inventory'); fs.writeFileSync(inventory,'100755\tstorage_monitor/storage_monitor\0'+ '100644\tstorage_monitor/native/Makefile\0'+'100644\tstorage_monitor/native/src/storage_monitor_walk.c\0');
  const marker=path.join(f.base,'synthetic execution marker');
  const r=f.runEnv({SYNTHETIC_EXECUTION_MARKER:marker,PATH:''},'--audit','--source-inventory',inventory); succeeds(r); assert.equal(r.stdout,'OK: storage_monitor deployment\n'); assert.equal(Buffer.byteLength(r.stdout),31);
  assert.equal(fs.existsSync(marker),false); assert.deepEqual(f.deployed(),before);
  for (const [index, message] of [[1,/walker drift/],[0,/launcher drift/]]) {
    fs.appendFileSync(path.join(f.scripts,f.files[index]),'synthetic drift'); const bad=f.run('--audit'); assert.equal(bad.status,1); assert.match(bad.stderr,message); fs.writeFileSync(path.join(f.scripts,f.files[index]),before[index][0]);
  }
  f.release('changed'); const bad=f.run('--audit'); assert.equal(bad.status,1); assert.match(bad.stderr,/source drift/); assert.deepEqual(f.deployed(),before);
});
test('rollback restores the previous files and modes', t => {
  const f=fixture(t); succeeds(f.run()); fs.chmodSync(path.join(f.scripts,f.files[0]),0o700); const before=f.deployed(); f.release('second'); const r=f.run(); succeeds(r);
  const backup=r.stdout.match(/rollback backup: (.+)/)[1]; succeeds(f.run('--rollback',backup)); assert.deepEqual(f.deployed(),before);
  for (const name of fs.readdirSync(backup)) assert.equal(fs.statSync(path.join(backup,name)).mode&0o7777,0o600);
  assert.equal(fs.statSync(backup).mode&0o7777,0o700);
});
test('existing direct-copy launcher without receipt is backed up and replaced', t => {
  const f=fixture(t); fs.mkdirSync(f.scripts,{recursive:true}); fs.writeFileSync(path.join(f.scripts,'storage_monitor'),'synthetic old launcher',{mode:0o700});
  const r=f.run(); succeeds(r); const backup=r.stdout.match(/rollback backup: (.+)/)[1]; succeeds(f.run('--rollback',backup));
  assert.equal(fs.readFileSync(path.join(f.scripts,'storage_monitor'),'utf8'),'synthetic old launcher'); assert.equal(fs.existsSync(path.join(f.scripts,'storage_monitor_walk')),false); assert.equal(fs.existsSync(path.join(f.scripts,'.storage_monitor.json')),false);
});
test('invalid smoke summary or hardlink count never replaces a deployment', t => {
  const f=fixture(t); succeeds(f.run()); const before=f.deployed();
  for (const [dirs, links] of [[2,2],[3,1]]) { f.release('invalid smoke',false,dirs,links); const r=f.run(); assert.equal(r.status,1); assert.match(r.stderr,/smoke/); assert.deepEqual(f.deployed(),before); }
});
test('invalid rollback validates all saved files before backup or replacement', t => {
  const f=fixture(t); succeeds(f.run()); f.release('second'); const r=f.run(); succeeds(r);
  const backup=r.stdout.match(/rollback backup: (.+)/)[1], before=f.deployed(), backups=f.backups();
  fs.appendFileSync(path.join(backup,'.storage_monitor.json'),'synthetic corruption');
  const failed=f.run('--rollback',backup); assert.equal(failed.status,1); assert.match(failed.stderr,/Backup hash mismatch/);
  assert.deepEqual(f.deployed(),before); assert.deepEqual(f.backups(),backups);
});
test('walker classification detects missing binary, byte drift and invalid receipt', t => {
  const f=fixture(t); succeeds(f.run()); const before=f.deployed();
  fs.unlinkSync(path.join(f.scripts,'storage_monitor_walk'));
  let r=f.run('--dry-run'); succeeds(r); assert.match(r.stdout,/walker: rebuild \(binary missing\)/);
  fs.writeFileSync(path.join(f.scripts,'storage_monitor_walk'),before[1][0],{mode:0o755});
  fs.appendFileSync(path.join(f.scripts,'storage_monitor_walk'),'synthetic corruption');
  r=f.run('--dry-run'); succeeds(r); assert.match(r.stdout,/walker: rebuild \(binary drift\)/);
  fs.chmodSync(path.join(f.scripts,'.storage_monitor.json'),0o644);
  r=f.run('--dry-run'); succeeds(r); assert.match(r.stdout,/walker: rebuild \(receipt invalid\)/);
  r=f.run('--audit'); assert.equal(r.status,1); assert.match(r.stderr,/receipt invalid/);
});
test('repository and linked destinations are refused without changing their targets', t => {
  const f=fixture(t); assert.equal(f.run('--scripts-dir',f.repo).status,1);
  const link=path.join(f.home,'synthetic link'); fs.symlinkSync(f.repo,link);
  assert.equal(f.run('--scripts-dir',link).status,1);
  fs.mkdirSync(f.scripts,{recursive:true}); const protectedFile=path.join(f.home,'synthetic protected'); fs.writeFileSync(protectedFile,'keep');
  fs.symlinkSync(protectedFile,path.join(f.scripts,'storage_monitor_walk'));
  assert.equal(f.run().status,1); assert.equal(fs.readFileSync(protectedFile,'utf8'),'keep'); assert.deepEqual(f.backups(),[]);
});
