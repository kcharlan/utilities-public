import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';

test('playtest rejects a missing tier and diagnostic acceptance checks',()=>{
  for(const args of [['--n','1','--tier'],['--n','1','--check']]){
    const result=spawnSync(process.execPath,['scripts/playtest.mjs',...args],{encoding:'utf8',timeout:20000});
    assert.notEqual(result.status,0,`accepted ${args.join(' ')}`);
    assert.match(result.stderr,/tier|diagnostic/i);
  }
});
