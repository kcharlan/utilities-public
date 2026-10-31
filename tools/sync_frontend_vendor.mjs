#!/usr/bin/env node
import {readFileSync, writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {dirname, extname, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';
const root = join(dirname(fileURLToPath(import.meta.url)), 'frontend_vendor');
const manifest = JSON.parse(readFileSync(join(root, 'manifest.json'), 'utf8'));
const hash = data => createHash('sha256').update(data).digest('hex');
function load(item) {
  const data = readFileSync(join(root, item.file));
  if (hash(data) !== item.sha256) throw Error(`hash mismatch: ${item.file}`);
  return data;
}
function generate(names) {
  const chosen = names.map(token => {
    const [name, requested] = token.split('=');
    const item = manifest.items[name];
    if (!item) throw Error(`unknown item: ${name}`);
    return {name, requested, item};
  });
  const priority = name => ['preact','hooks','htm','lucide','kit','svg-charts'].indexOf(name);
  chosen.sort((a,b) => (priority(a.name) < 0 ? 99 : priority(a.name)) - (priority(b.name) < 0 ? 99 : priority(b.name)));
  const licenses = new Set(), out = [];
  for (const {name,requested,item} of chosen) {
    const bytes = load(item);
    if (item.license) licenses.add(readFileSync(join(root, item.license), 'utf8'));
    if (item.kind === 'font') {
      out.push(`<style>@font-face{font-family:${JSON.stringify(item.family)};font-style:${item.style};font-weight:${item.weight};src:url(data:font/woff2;base64,${bytes.toString('base64')}) format('woff2');}</style>`);
    } else if (name === 'lucide') {
      const sandbox = {window:{}}; vm.runInNewContext(bytes.toString(), sandbox);
      const source = sandbox.lucide || sandbox.window.lucide;
      const icons = {};
      for (const icon of (requested || '').split(',').filter(Boolean)) {
        if (!Object.hasOwn(source, icon) || !Array.isArray(source[icon])) throw Error(`unknown Lucide icon: ${icon}`);
        icons[icon] = source[icon];
      }
      out.push(`<script>window.lucideIcons=${JSON.stringify(icons)};</script>`);
    } else {
      const script = bytes.toString().replace(/<\/script/gi, '<\\/script').replace(/<!--/g, '<\\!--');
      out.push(`<script>\n${script}\n</script>`);
      if (item.css) out.push(`<style>\n${readFileSync(join(root,item.css),'utf8')}\n</style>`);
    }
  }
  return [...licenses].map(x => `<!--\n${x.replace(/-->/g, '-- >')}\n-->`).concat(out).join('\n');
}
function sync(path, check) {
  const source = readFileSync(path,'utf8');
  const pattern = /^([ \t]*)(# |<!-- )frontend-vendor:begin ([^\n]*?)(?: -->)?\r?\n[\s\S]*?^[ \t]*(?:# |<!-- )frontend-vendor:end(?: -->)?[ \t]*$/gm;
  let count=0, changed=false;
  const result = source.replace(pattern, (whole, indent, marker, raw) => {
    count++;
    const names=raw.replace(/ -->$/, '').trim().split(/\s+/);
    const html=generate(names);
    const python=marker === '# ';
    if (python && html.includes('"""')) throw Error(`${path}: frontend-vendor contains triple double quotes`);
    const body=python ? `FRONTEND_VENDOR_HTML = r"""${html}"""` : html;
    const end=python ? '# frontend-vendor:end' : '<!-- frontend-vendor:end -->';
    const begin=python ? `# frontend-vendor:begin ${names.join(' ')}` : `<!-- frontend-vendor:begin ${names.join(' ')} -->`;
    const replacement=`${indent}${begin}\n${python ? indent : ''}${body}\n${indent}${end}`;
    if(whole!==replacement) changed=true;
    return replacement;
  });
  if(!count) throw Error(`${path}: no frontend-vendor region`);
  if (changed && check) throw Error(`${path}: stale frontend-vendor region`);
  if (changed) writeFileSync(path,result);
}
try {
 const args=process.argv.slice(2), check=args.includes('--check'), all=args.includes('--all');
 let files=args.filter(x=>x!=='--check' && x!=='--all');
 if(all) {
  let found='';
  try { found=execFileSync('git',['grep','-lE','^[[:space:]]*(# |<!-- )frontend-vendor:begin '],{encoding:'utf8'}); }
  catch(error) { if(error.status!==1) throw error; }
  files.push(...found.trim().split('\n').filter(f=>f && !f.startsWith('tools/')));
 }
 if(!files.length && !all) throw Error('usage: sync_frontend_vendor.mjs [--check] FILE... | --all [--check]');
 for(const file of files) sync(file,check);
} catch(error) { console.error(error.message); process.exitCode=1; }
