import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, writeFileSync, readFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
const tool = new URL('../sync_frontend_vendor.mjs', import.meta.url).pathname;

test('sync fills HTML and Python regions idempotently and detects stale content', () => {
  const dir = mkdtempSync(join(tmpdir(), 'frontend-sync-'));
  try {
    for (const [name, begin, end] of [['a.html', '<!-- frontend-vendor:begin kit -->', '<!-- frontend-vendor:end -->'], ['b.py', '# frontend-vendor:begin kit', '# frontend-vendor:end']]) {
      const path = join(dir, name);
      writeFileSync(path, `${begin}\n${end}\n`);
      const run = (...args) => spawnSync('node', [tool, ...args, path], {encoding:'utf8'});
      assert.equal(run().status, 0);
      const generated = readFileSync(path, 'utf8');
      assert.match(generated, /frontendKit/);
      assert.equal(run().status, 0);
      assert.equal(readFileSync(path, 'utf8'), generated);
      assert.equal(run('--check').status, 0);
      writeFileSync(path, generated.replace('frontendKit', 'staleKit'));
      const check = run('--check');
      assert.notEqual(check.status, 0);
      assert.match(check.stderr, /frontend-vendor/);
      assert.match(check.stderr, new RegExp(name.replace('.', '\\.')));
    }
  } finally { rmSync(dir, {recursive:true, force:true}); }
});

test('emits selected icons and inline fonts, and rejects unknown items and icons', () => {
 const dir=mkdtempSync(join(tmpdir(),'frontend-sync-'));
 try {
  const path=join(dir,'x.html'); const run=()=>spawnSync('node',[tool,path],{encoding:'utf8'});
  writeFileSync(path,'<!-- frontend-vendor:begin lucide=Copy font:dm-sans -->\n<!-- frontend-vendor:end -->\n');
  assert.equal(run().status,0); const result=readFileSync(path,'utf8');
  assert.match(result,/lucideIcons/);assert.match(result,/"Copy"/);assert.doesNotMatch(result,/"Trash2"/);
  assert.match(result,/@font-face/);assert.match(result,/DM Sans/);assert.match(result,/font-style:normal;font-weight:100 1000/);assert.match(result,/data:font\/woff2;base64,/);
  for (const name of ['lucide=NotAnIconAtAll','lucide=constructor','missing-item']) {
    writeFileSync(path,`<!-- frontend-vendor:begin ${name} -->\n<!-- frontend-vendor:end -->\n`);
    assert.notEqual(run().status,0);
  }
 } finally {rmSync(dir,{recursive:true,force:true});}
});

test('TOML wrapper parses and round-trips synthetic data', async () => {
 const vm = await import('node:vm');
 const source = readFileSync(new URL('../frontend_vendor/toml/toml.iife.js', import.meta.url),'utf8');
 const context={window:{}};vm.runInNewContext(source,context);
 const object={label:'SYNTHETIC EXAMPLE',count:42};
 assert.deepEqual(JSON.parse(JSON.stringify(context.window.TOML.parse(context.window.TOML.stringify(object)))),object);
});
test('TOML transform removes a source map comment without trailing newline', async () => {
 const {transformToml} = await import('../frontend_vendor/transform_toml.mjs');
 const vm = await import('node:vm');
 const output=transformToml('function p(x){return x} function s(x){return x}\nexport {p as parse,s as stringify};\n//# sourceMappingURL=x');
 const context={window:{}};vm.runInNewContext(output,context);assert.equal(context.window.TOML.parse('ok'),'ok');
});
test('--all handles a repository without marked files', () => {
 const dir=mkdtempSync(join(tmpdir(),'frontend-git-'));
 try {
  assert.equal(spawnSync('git',['init','-q'],{cwd:dir}).status,0);
  const result=spawnSync('node',[tool,'--all','--check'],{cwd:dir,encoding:'utf8'});
  assert.equal(result.status,0,result.stderr);
 } finally {rmSync(dir,{recursive:true,force:true});}
});
test('synthetic manifests enforce hashes, safe embedding and license deduplication', async () => {
 const {mkdirSync,copyFileSync} = await import('node:fs'); const {createHash}=await import('node:crypto');
 const dir=mkdtempSync(join(tmpdir(),'frontend-fixture-'));
 try {
  const tools=join(dir,'tools'), vendor=join(tools,'frontend_vendor');mkdirSync(vendor,{recursive:true});copyFileSync(tool,join(tools,'sync_frontend_vendor.mjs'));
  const script='const x="</script><!--";', license='Synthetic license --> text';
  writeFileSync(join(vendor,'x.js'),script);writeFileSync(join(vendor,'license'),license);writeFileSync(join(vendor,'x.css'),'.synthetic {color: red}');
  const entry={kind:'script',file:'x.js',css:'x.css',version:'synthetic',url:'https://example.invalid/x',sha256:createHash('sha256').update(script).digest('hex'),license:'license'};
  writeFileSync(join(vendor,'manifest.json'),JSON.stringify({schema:1,items:{a:entry,b:entry}}));
  const path=join(dir,'test.html');writeFileSync(path,'<!-- frontend-vendor:begin a b -->\n<!-- frontend-vendor:end -->\n');
  const run=()=>spawnSync('node',[join(tools,'sync_frontend_vendor.mjs'),path],{encoding:'utf8'});
  assert.equal(run().status,0);const output=readFileSync(path,'utf8');
  assert.match(output,/<\\\/script/);assert.match(output,/<\\!--/);assert.equal(output.split('Synthetic license').length-1,1);assert.match(output,/license -- > text/);
  assert.match(output,/<style>\n\.synthetic \{color: red\}/);
  writeFileSync(join(vendor,'x.js'),'changed');assert.notEqual(run().status,0);
 } finally {rmSync(dir,{recursive:true,force:true});}
});
test('--all processes tracked indented markers and skips tools', async () => {
 const {mkdirSync}=await import('node:fs');const dir=mkdtempSync(join(tmpdir(),'frontend-git-'));
 try {
  spawnSync('git',['init','-q'],{cwd:dir});mkdirSync(join(dir,'tools'));
  const marker='  <!-- frontend-vendor:begin kit -->\n  <!-- frontend-vendor:end -->\n';
  writeFileSync(join(dir,'page.html'),marker);writeFileSync(join(dir,'tools','ignored.html'),marker);spawnSync('git',['add','.'],{cwd:dir});
  const result=spawnSync('node',[tool,'--all'],{cwd:dir,encoding:'utf8'});assert.equal(result.status,0,result.stderr);
  assert.match(readFileSync(join(dir,'page.html'),'utf8'),/frontendKit/);assert.equal(readFileSync(join(dir,'tools','ignored.html'),'utf8'),marker);
 } finally {rmSync(dir,{recursive:true,force:true});}
});
test('refuses triple double quotes in a Python vendor region', async () => {
 const {mkdirSync,copyFileSync}=await import('node:fs');const {createHash}=await import('node:crypto');const dir=mkdtempSync(join(tmpdir(),'frontend-triple-'));
 try {
  const vendor=join(dir,'tools','frontend_vendor');mkdirSync(vendor,{recursive:true});copyFileSync(tool,join(dir,'tools','sync_frontend_vendor.mjs'));
  const script='const x = """;';writeFileSync(join(vendor,'x.js'),script);
  writeFileSync(join(vendor,'manifest.json'),JSON.stringify({schema:1,items:{x:{kind:'script',file:'x.js',sha256:createHash('sha256').update(script).digest('hex')}}}));
  const path=join(dir,'x.py'),content='# frontend-vendor:begin x\n# frontend-vendor:end\n';writeFileSync(path,content);
  const result=spawnSync('node',[join(dir,'tools','sync_frontend_vendor.mjs'),path],{encoding:'utf8'});assert.notEqual(result.status,0);assert.match(result.stderr,/triple/);assert.equal(readFileSync(path,'utf8'),content);
 } finally {rmSync(dir,{recursive:true,force:true});}
});
test('kit renders selected icons, reports unknown ones and focuses refs', async () => {
 const vm=await import('node:vm'); const errors=[];let focused=false;
 const window={preact:{h:(tag,props,...children)=>({tag,props,children}),render(){},Component:class {}},preactHooks:{},lucideIcons:{Copy:[['path',{d:'M1 2'}]]}};
 vm.runInNewContext(readFileSync(new URL('../frontend_vendor/kit.js',import.meta.url),'utf8'),{window,console:{error:x=>errors.push(x)}});
 const icon=window.frontendKit.Icon({name:'Copy'});assert.equal(icon.tag,'svg');assert.equal(icon.props.width,16);assert.equal(icon.children[0][0].tag,'path');
 assert.equal(window.frontendKit.Icon({name:'unknown'}),null);assert.match(errors[0],/unknown/);
 assert.equal(window.frontendKit.Icon({name:'constructor'}),null);
 window.frontendKit.focusOnMount({focus(){focused=true;}});assert.equal(focused,true);
});
test('Portal appends before rendering, retains its host on updates and removes it on teardown', async () => {
 const vm=await import('node:vm');const events=[], host={remove(){events.push('remove');}};let slots=[],cursor=0, pending=[];
 const hooks={useMemo(fn){const i=cursor++;return slots[i]??(slots[i]=fn());},useLayoutEffect(fn,deps){const i=cursor++,old=slots[i];if(!old || deps.some((v,j)=>v!==old.deps[j]))pending.push(()=>{old?.cleanup?.();slots[i]={deps,cleanup:fn()};});}};
 const window={preact:{h(){},Component:class {},render:(child,target)=>{assert.equal(target,host);events.push(child===null?'clear':`render ${child}`);}},preactHooks:hooks};
 vm.runInNewContext(readFileSync(new URL('../frontend_vendor/kit.js',import.meta.url),'utf8'),{window,document:{createElement:()=>host,body:{appendChild:value=>{assert.equal(value,host);events.push('append');}}},console});
 function update(children){cursor=0;pending=[];window.frontendKit.Portal({children});for(const effect of pending)effect();}
 update('first');update('second');for(const slot of slots)slot?.cleanup?.();
 assert.deepEqual(events,['append','render first','render second','clear','remove']);
});
test('memo suppresses shallow-equal updates and honors a comparator', async () => {
 const vm=await import('node:vm');class Component {};
 const window={preact:{h:(...args)=>args,render(){},Component},preactHooks:{}};
 vm.runInNewContext(readFileSync(new URL('../frontend_vendor/kit.js',import.meta.url),'utf8'),{window,console});
 const Wrapper=window.frontendKit.memo(()=>null), instance=new Wrapper();instance.props={x:1};assert.equal(instance.shouldComponentUpdate({x:1}),false);assert.equal(instance.shouldComponentUpdate({x:2}),true);
 const Custom=window.frontendKit.memo(()=>null,()=>true), custom=new Custom();custom.props={x:1};assert.equal(custom.shouldComponentUpdate({x:2}),false);
});
test('sync emits svg-charts script and style after preact', () => {
 const dir=mkdtempSync(join(tmpdir(),'frontend-charts-'));
 try {
  const path=join(dir,'page.html');writeFileSync(path,'<!-- frontend-vendor:begin svg-charts preact -->\n<!-- frontend-vendor:end -->\n');
  const result=spawnSync('node',[tool,path],{encoding:'utf8'});assert.equal(result.status,0,result.stderr);
  const output=readFileSync(path,'utf8');assert.ok(output.indexOf('window.svgCharts')>output.indexOf('preact'));assert.match(output,/<style>\n\/\* SVG charts/);
 } finally {rmSync(dir,{recursive:true,force:true});}
});
test('indented HTML preserves multiline script and CSS bytes and behavior', async () => {
 const {mkdirSync,copyFileSync}=await import('node:fs');const {createHash}=await import('node:crypto');const vm=await import('node:vm');
 const dir=mkdtempSync(join(tmpdir(),'frontend-indent-'));
 try {
  const vendor=join(dir,'tools','frontend_vendor');mkdirSync(vendor,{recursive:true});copyFileSync(tool,join(dir,'tools','sync_frontend_vendor.mjs'));
  const script='window.codec = {wrap: value => `first\n${value}\nsecond`, unwrap: value => value.slice(6, -7)};';const css='.one {\n  color: red;\n}';
  writeFileSync(join(vendor,'x.js'),script);writeFileSync(join(vendor,'x.css'),css);
  writeFileSync(join(vendor,'manifest.json'),JSON.stringify({schema:1,items:{x:{kind:'script',file:'x.js',css:'x.css',sha256:createHash('sha256').update(script).digest('hex')}}}));
  const file=join(dir,'sample.html');writeFileSync(file,'  <!-- frontend-vendor:begin x -->\n  <!-- frontend-vendor:end -->\n');
  const run=()=>spawnSync('node',[join(dir,'tools','sync_frontend_vendor.mjs'),file],{encoding:'utf8'});
  assert.equal(run().status,0);const output=readFileSync(file,'utf8');assert.ok(output.includes(`<script>\n${script}\n</script>`));assert.ok(output.includes(`<style>\n${css}\n</style>`));
  const context={window:{}};vm.runInNewContext(output.match(/<script>\n([\s\S]*?)\n<\/script>/)[1],context);
  const wrapped=context.window.codec.wrap('SYNTHETIC');assert.equal(wrapped,'first\nSYNTHETIC\nsecond');assert.equal(context.window.codec.unwrap(wrapped),'SYNTHETIC');
  assert.equal(run().status,0);assert.equal(readFileSync(file,'utf8'),output);
 } finally {rmSync(dir,{recursive:true,force:true});}
});
test('indented HTML keeps real js-yaml multiline round trips intact', async () => {
 const vm=await import('node:vm');const dir=mkdtempSync(join(tmpdir(),'frontend-yaml-'));
 try {
  const file=join(dir,'sample.html');writeFileSync(file,'    <!-- frontend-vendor:begin js-yaml -->\n    <!-- frontend-vendor:end -->\n');
  const result=spawnSync('node',[tool,file],{encoding:'utf8'});assert.equal(result.status,0,result.stderr);
  const html=readFileSync(file,'utf8');const script=html.match(/<script>\n([\s\S]*?)\n<\/script>/)[1];
  const context={};vm.runInNewContext(script,context);
  const output=vm.runInNewContext('jsyaml.load(jsyaml.dump({message:"SYNTHETIC first\\nSYNTHETIC second"}))',context);
  assert.deepEqual(JSON.parse(JSON.stringify(output)),{message:'SYNTHETIC first\nSYNTHETIC second'});
  assert.equal(spawnSync('node',[tool,file],{encoding:'utf8'}).status,0);assert.equal(readFileSync(file,'utf8'),html);
 } finally {rmSync(dir,{recursive:true,force:true});}
});
