import test from 'node:test';import assert from 'node:assert/strict';import {readFile} from 'node:fs/promises';import {spawn} from 'node:child_process';
test('verification page links to an explicit game document on directory-browser hosts',async()=>{
  const html=await readFile(new URL('../dist/checks.html',import.meta.url),'utf8');
  assert.match(html,/<a href="\.\/index\.html">Play the game<\/a>/);
});
test('generated sheets decode as alpha PNGs with an even fixed grid',async()=>{
  for(const name of ['plane-sheet.png','pigeon-sheet.png']){
    const data=await readFile(new URL('../dist/assets/'+name,import.meta.url));
    assert.equal(data.subarray(1,4).toString(),'PNG');
    assert.equal(data.readUInt32BE(16)%2,0);assert.equal(data.readUInt32BE(16),data.readUInt32BE(20));assert.equal(data[25],6);
  }
});
test('washer illustration is a high-resolution alpha asset',async()=>{
  const data=await readFile(new URL('../dist/assets/washer-v1.png',import.meta.url));
  assert.equal(data.subarray(1,4).toString(),'PNG');assert.equal(data[25],6);
  assert.ok(data.readUInt32BE(16)>=1024&&data.readUInt32BE(20)>=512);
});
test('static server serves browser modules, checks and assets with correct MIME and rejects unknown paths',async t=>{
  const child=spawn(process.execPath,['scripts/serve.mjs'],{cwd:new URL('../',import.meta.url),env:{...process.env,PORT:'0'},stdio:['ignore','pipe','pipe']});
  t.after(()=>child.kill());
  const base=await new Promise((resolve,reject)=>{child.once('error',reject);child.stdout.on('data',chunk=>{const match=chunk.toString().match(/http:\/\/127\.0\.0\.1:\d+/);if(match)resolve(match[0]);});child.once('exit',code=>reject(Error('Server exited '+code)));});
  const root=await fetch(base);assert.equal(root.status,200);assert.match(root.headers.get('content-type'),/^text\/html/);assert.ok((await root.text()).includes('Office Picnic'));
  const module=await fetch(base+'/game/physics.js');assert.equal(module.status,200);assert.match(module.headers.get('content-type'),/^text\/javascript/);
  assert.equal((await fetch(base+'/checks.html')).status,200);assert.equal((await fetch(base+'/assets/plane-sheet.png')).status,200);assert.equal((await fetch(base+'/missing')).status,404);assert.equal((await fetch(base+'/%2e%2e%2fpackage.json')).status,403);
});
