/** Shared read-only external-data contract. No Python, network, locks or writes. */
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { createHash } from 'node:crypto';
export const RECIPE_FILES = Object.freeze(['data/compile_market_data.py', 'data/requirements.lock',
  'data/sources.json', 'engine.js', 'stats.js', 'tools/check_historical.mjs',
  'tools/data_contract.mjs', 'tools/setup_data.mjs'].sort());
export const PAIR_FILES = Object.freeze(['market-data.csv', 'market-data.js']);
export class DataContractError extends Error {
  constructor(message) { super(message); this.name = 'DataContractError'; }
}
const fail = message => { throw new DataContractError(message); };
export const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const isHash = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const compare = (a,b) => a < b ? -1 : a > b ? 1 : 0;
function keys(value, expected) {
  if (!value || Array.isArray(value) || typeof value !== 'object' ||
    Object.keys(value).sort().join(',') !== [...expected].sort().join(',')) fail('Unrecognized data schema');
}
export function fileIdentity(files) {
  const records = files.map(({path: name, sha256: digest}) => {
    if (typeof name !== 'string' || !/^[a-zA-Z0-9_./-]+$/.test(name) || name.startsWith('/') ||
      name.split('/').some(part => !part || part === '.' || part === '..') || !isHash(digest)) fail('Invalid identity record');
    return {path: name, sha256: digest};
  }).sort((a,b) => compare(a.path,b.path));
  if (new Set(records.map(record => record.path)).size !== records.length) fail('Duplicate identity record');
  return sha256(JSON.stringify({schemaVersion:1,files:records}) + '\n');
}
export function validDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith('0000-') ||
    !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().slice(0,10) !== value) fail('Invalid generated date');
  return value;
}
export function bundleIdentity({dataId,recipeId,sources,generatedDate}) {
  if (!isHash(dataId) || !isHash(recipeId)) fail('Invalid bundle identity');
  validDate(generatedDate);
  const records = sources.map(({id,url,sha256:digest}) => {
    if (!/^[a-z]+$/.test(id) || typeof url !== 'string' || !url.startsWith('https://') || !isHash(digest)) fail('Invalid source identity');
    return {id,url,sha256:digest};
  }).sort((a,b) => compare(a.id,b.id));
  if (new Set(records.map(record=>record.id)).size !== records.length) fail('Duplicate source identity');
  return sha256(JSON.stringify({schemaVersion:1,dataId,recipeId,sources:records,generatedDate})+'\n');
}
const FIELDS = ['year','stock_tr','bond10_tr','tbill_tr','cpi_change','quality'];
export function parsePair(js,csv) {
  const text = new TextDecoder('utf-8',{fatal:true}).decode(js);
  const match = text.match(/^globalThis\.MARKET_DATA = (\{[\s\S]*\});\n$/);
  if (!match) fail('Invalid market-data JSON envelope');
  let payload; try { payload = JSON.parse(match[1]); } catch { fail('Invalid market-data JSON envelope'); }
  keys(payload,['generated','sources','rows']); validDate(payload.generated);
  keys(payload.sources,FIELDS.slice(1,5));
  if(Object.keys(payload.sources).join(',')!==FIELDS.slice(1,5).join(','))fail('Invalid source field order');
  if (Object.values(payload.sources).some(value=>typeof value !== 'string' || !value.length || value.length > 1024 || /[\\/]|:\/\//.test(value)))
    fail('Invalid browser source metadata');
  if (!Array.isArray(payload.rows) || payload.rows.length !== 154) fail('Invalid dataset range/count');
  for (const [index,row] of payload.rows.entries()) {
    keys(row,FIELDS);if(Object.keys(row).join(',')!==FIELDS.join(','))fail('Invalid row field order');
    if (row.year !== 1872+index || row.quality !== (row.year < 1928 ? 'reconstructed' : 'ok')) fail('Invalid year/quality schema');
    for (const field of FIELDS.slice(1,5)) {
      if (field === 'tbill_tr' && row.year < 1928) { if (row[field] !== null) fail('Invalid bill coverage'); }
      else if (typeof row[field] !== 'number' || !Number.isFinite(row[field]) || row[field] <= -1) fail('Invalid finite returns');
    }
  }
  const lines = new TextDecoder('utf-8',{fatal:true}).decode(csv).replaceAll('\r\n','\n').split('\n');
  if (lines.pop() !== '' || lines.shift() !== FIELDS.join(',') || lines.length !== 154) fail('Invalid CSV schema');
  for (const [index,line] of lines.entries()) {
    const values = line.split(','); if (values.length !== FIELDS.length) fail('Invalid CSV row');
    for (let field=0;field<FIELDS.length;field++) {
      const expected=payload.rows[index][FIELDS[field]];
      if(field!==5&&!(field===3&&values[field]==='')&&!/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:e[+-]?\d+)?$/i.test(values[field]))fail('CSV numeric cells must be decimal');
      const actual=field===5 ? values[field] : values[field]==='' ? null : Number(values[field]);
      if (actual!==expected) fail('JS/CSV pair parity failure');
    }
  }
  return payload;
}
function within(candidate, root) { const relative=path.relative(root,candidate); return relative==='' || (!relative.startsWith('..'+path.sep)&&relative!=='..'&&!path.isAbsolute(relative)); }
async function canonical(target) {
  let ancestor=path.resolve(target),tail=[];
  while (true) { try { return path.join(await fs.realpath(ancestor),...tail.reverse()); }
    catch(error) { if(error.code!=='ENOENT') throw error; const parent=path.dirname(ancestor); if(parent===ancestor) throw error;
      tail.push(path.basename(ancestor)); ancestor=parent; } }
}
export async function safeRoot(target,{sourceRoot,repoRoot,webroots=[],privateRoot=true}={}) {
  const requested=path.resolve(target),resolved=await canonical(requested);
  const prohibited=[sourceRoot,repoRoot,path.join(os.homedir(),'webroot'),
    process.env.UTILITIES_WEBROOT_DIR || path.join(process.env.UTILITIES_LOCAL_ROOT || os.homedir(),'webroot'),...webroots].filter(Boolean);
  for(const root of prohibited) { const denied=await canonical(root); if(within(resolved,denied)||within(denied,resolved)) fail('Data root overlaps source, repository or webroot'); }
  let current=requested;
  while(true) {
    try { const stat=await fs.lstat(current); if(stat.isSymbolicLink()&&!['/tmp','/var'].includes(current)) fail('Symlinked data path');
      if(!stat.isDirectory()&&!stat.isSymbolicLink()) fail('Data path requires directories');
      if(current===requested&&privateRoot) await guardDirectory(current);
    } catch(error) { if(error.code!=='ENOENT') throw error; }
    const parent=path.dirname(current); if(parent===current) break; current=parent;
  }
  return resolved;
}
export async function guardDirectory(target) {
  const stat=await fs.lstat(target);
  if(!stat.isDirectory()) fail('Data path requires a regular directory');
  await fs.access(target,fs.constants.R_OK|fs.constants.X_OK); return stat;
}
export async function readOwned(target,{manual=false}={}) {
  const stat=await fs.lstat(target);
  if(!stat.isFile()) fail('Data object must be a plain regular file');
  if(stat.size>32*1024*1024) fail('Oversized data object');
  const handle=await fs.open(target,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);
  try { const actual=await handle.stat(); if(actual.ino!==stat.ino||actual.dev!==stat.dev) fail('Data file changed during read');
    return await handle.readFile(); } finally { await handle.close(); }
}
export async function readRecipe(sourceRoot) {
  const files=[],bytes=new Map();
  for(const name of RECIPE_FILES) { const filename=path.join(sourceRoot,name);
    for(let parent=path.dirname(filename);parent!==path.dirname(sourceRoot);parent=path.dirname(parent)){const info=await fs.lstat(parent);if(!info.isDirectory())fail('Symlinked recipe source directory');}
    const stat=await fs.lstat(filename);
    if(!stat.isFile()) fail('Recipe requires regular source files');
    const content=await fs.readFile(filename); files.push({path:name,sha256:sha256(content)});bytes.set(name,content); }
  const recipe=JSON.parse(bytes.get('data/sources.json'));
  if(recipe.schemaVersion!==1||recipe.output.firstYear!==1872||recipe.output.lastYear!==2025||
    recipe.output.spliceYear!==1928||recipe.output.reconciliationLastYear!==2022||
    recipe.sources.map(source=>source.id).sort().join(',')!=='damodaran,shiller') fail('Unrecognized reviewed source recipe');
  return {recipeId:fileIdentity(files),files,bytes,recipe};
}
export async function verifyBundle({dataHome,dataRoot,bundleId=dataRoot&&path.basename(path.resolve(dataRoot)),sourceRoot,repoRoot,requireCurrentRecipe=false}) {
  if(!isHash(bundleId)) fail('Invalid bundle selector');
  const root=dataRoot?await safeRoot(dataRoot,{sourceRoot,repoRoot}):path.join(await safeRoot(dataHome,{sourceRoot,repoRoot}),'datasets',bundleId);
  if(path.basename(root)!==bundleId)fail('Generation path/identity mismatch');
  if(!dataRoot){await guardDirectory(dataHome);await guardDirectory(path.join(dataHome,'datasets'));}
  await guardDirectory(root);
  const provenance=JSON.parse(await readOwned(path.join(root,'provenance.json')));
  keys(provenance,['schemaVersion','bundleId','dataId','recipeId','generatedDate','sources','files','recipeFiles','range']);
  if(provenance.schemaVersion!==1||provenance.bundleId!==bundleId) fail('Invalid provenance identity');
  if((await fs.readdir(root)).sort().join(',')!==[...PAIR_FILES,'provenance.json','recipe'].sort().join(',')) fail('Unexpected generation inventory');
  const pair=new Map(),files=[];
  for(const name of PAIR_FILES) {const content=await readOwned(path.join(root,name)); pair.set(name,content);files.push({path:name,sha256:sha256(content)});}
  if(JSON.stringify(provenance.files)!==JSON.stringify(files)||fileIdentity(files)!==provenance.dataId) fail('Dataset hash mismatch');
  const payload=parsePair(pair.get('market-data.js'),pair.get('market-data.csv'));
  if(payload.generated!==provenance.generatedDate||JSON.stringify(provenance.range)!==JSON.stringify({firstYear:1872,lastYear:2025,count:154})) fail('Provenance date/range mismatch');
  const recipeFiles=[],recipeBytes=new Map(); await guardDirectory(path.join(root,'recipe'));
  async function inventory(directory,prefix=''){const names=[];for(const entry of await fs.readdir(directory,{withFileTypes:true})){const name=prefix+entry.name;if(entry.isDirectory()){if(!RECIPE_FILES.some(file=>file.startsWith(name+'/')))fail('Unexpected retained recipe directory inventory');await guardDirectory(path.join(directory,entry.name));names.push(...await inventory(path.join(directory,entry.name),name+'/'));}else names.push(name);}return names;}
  if((await inventory(path.join(root,'recipe'))).sort().join(',')!==RECIPE_FILES.join(','))fail('Unexpected retained recipe inventory');
  for(const name of RECIPE_FILES) {
    let parent=path.dirname(path.join(root,'recipe',name)); while(parent!==path.join(root,'recipe')) {await guardDirectory(parent);parent=path.dirname(parent);}
    const content=await readOwned(path.join(root,'recipe',name));recipeFiles.push({path:name,sha256:sha256(content)});recipeBytes.set(name,content);
  }
  if(JSON.stringify(provenance.recipeFiles)!==JSON.stringify(recipeFiles)||fileIdentity(recipeFiles)!==provenance.recipeId) fail('Retained recipe byte mismatch');
  const recipe=JSON.parse(recipeBytes.get('data/sources.json')); const approved=[...recipe.sources].sort((a,b)=>compare(a.id,b.id));
  if(!Array.isArray(provenance.sources)||provenance.sources.length!==approved.length) fail('Invalid provenance sources');
  for(const [index,source] of provenance.sources.entries()) {
    keys(source,['id','url','sha256','path']); const expected=approved[index];
    if(source.id!==expected.id||source.url!==expected.url||!isHash(source.sha256)||source.path!==`inputs/${source.sha256}/source.xls`) fail('Source provenance mismatch');
  }
  if(bundleIdentity(provenance)!==bundleId) fail('Bundle identity mismatch');
  if(requireCurrentRecipe&&(await readRecipe(sourceRoot)).recipeId!==provenance.recipeId) fail('Selected data recipe is stale; run npm run setup:data');
  return {root,bundleId,dataId:provenance.dataId,recipeId:provenance.recipeId,provenance,payload,files:pair};
}
/** Mutation/reproduction validation, separate from generation-local readers. */
export async function verifyRetainedInputs({dataHome,provenance,sourceRoot,repoRoot}) {
  await safeRoot(dataHome,{sourceRoot,repoRoot});await guardDirectory(path.join(dataHome,'inputs'));
  const objects=new Map();
  for(const source of provenance.sources){
    keys(source,['id','url','sha256','path']);
    if(!isHash(source.sha256)||source.path!==`inputs/${source.sha256}/source.xls`)fail('Invalid retained input reference');
    await guardDirectory(path.join(dataHome,'inputs',source.sha256));
    const bytes=await readOwned(path.join(dataHome,source.path));
    if(sha256(bytes)!==source.sha256)fail('Retained input hash mismatch');objects.set(source.id,bytes);
  }
  return objects;
}
export async function verifySelected(options) {
  const {dataHome}=options; let bytes;
  try { bytes=await readOwned(path.join(dataHome,'current.json')); } catch(error) { if(error.code==='ENOENT') return null;throw error; }
  const selected=JSON.parse(bytes); keys(selected,['schemaVersion','bundleId','dataId','recipeId']);
  if(selected.schemaVersion!==1) fail('Invalid selector schema');
  const verified=await verifyBundle({...options,bundleId:selected.bundleId});
  if(verified.dataId!==selected.dataId||verified.recipeId!==selected.recipeId) fail('Selector identity mismatch');
  return verified;
}
