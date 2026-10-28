// Shared by the native app deployer suites, for makeRelease in tools/deploy_brew_version.mjs.
// Everything lives inside the caller's fixture directory, which the caller removes.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

// A getconf double on the fixture PATH whose DARWIN_USER_TEMP_DIR is a directory inside the
// fixture, so no suite reads or sweeps the real Darwin user temp dir. Other queries pass through.
export function fakeDarwinTemp(base,bin) {
  const darwin=path.join(base,'synthetic darwin temp');fs.mkdirSync(darwin);
  fs.writeFileSync(path.join(bin,'getconf'),`#!/bin/sh\n[ "$*" = DARWIN_USER_TEMP_DIR ] || exec /usr/bin/getconf "$@"\nprintf '%s/\\n' '${darwin}'\n`,{mode:0o755});
  return darwin;
}

// Stands in for SwiftPM at the start of the fixture's release recipe: a path-named lock file and a
// TemporaryDirectory.* in TMPDIR, plus, in the Darwin user temp dir, a new marker-only
// TemporaryDirectory.* and a new one with other content. With fail, the recipe then fails.
export function releaseTempMakefile(makefile,fail=false) {
  const darwin='d=$$(getconf DARWIN_USER_TEMP_DIR) && mkdir "$${d}TemporaryDirectory.synthetic-';
  const lines=["printf '%s\\n' \"$$TMPDIR\" > \"$$SYNTHETIC_TMPDIR_LOG\"",': > "$${TMPDIR%/}/_synthetic_project_.build.lock"','mkdir "$${TMPDIR%/}/TemporaryDirectory.synthetic"',
    darwin+'new" && : > "$${d}TemporaryDirectory.synthetic-new/.keep-directory"',darwin+'content" && echo synthetic > "$${d}TemporaryDirectory.synthetic-content/other"',...(fail?['false']:[])];
  assert.ok(makefile.startsWith('release:\n'));
  return 'release:\n'+lines.map(line=>'\t'+line+'\n').join('')+makefile.slice('release:\n'.length);
}

// run(fail) rewrites the fixture Makefile with releaseTempMakefile, commits it and deploys. A
// marker-only TemporaryDirectory.* that existed before the build must survive the sweep.
export function assertReleaseTempHygiene({base,darwin,env,run},scratchPrefix,fail) {
  const log=path.join(base,'synthetic-tmpdir.log'),old=path.join(darwin,'TemporaryDirectory.synthetic-old');
  fs.mkdirSync(old);fs.writeFileSync(path.join(old,'.keep-directory'),'');
  env.SYNTHETIC_TMPDIR_LOG=log;
  const result=run(fail);
  assert.equal(result.status,fail?1:0,result.stdout+result.stderr);
  const child=fs.readFileSync(log,'utf8').trim();
  assert.match(child,new RegExp('^'+base.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'/'+scratchPrefix+'[^/]+/tmp/$'),child);
  assert.equal(fs.existsSync(child),false,'the scratch TMPDIR must be removed with the scratch');
  assert.deepEqual(fs.readdirSync(base).filter(name=>name.startsWith(scratchPrefix) || /TemporaryDirectory|build\.lock/.test(name)),[]);
  assert.deepEqual(fs.readdirSync(darwin).sort(),['TemporaryDirectory.synthetic-content','TemporaryDirectory.synthetic-old']);
  assert.deepEqual(fs.readdirSync(old),['.keep-directory']);
  assert.match(result.stderr,/Left 1 new TemporaryDirectory\.\* with other content in .*: TemporaryDirectory\.synthetic-content/);
}
