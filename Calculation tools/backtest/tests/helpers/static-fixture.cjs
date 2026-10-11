'use strict';
// Entire pair and raw-input hashes are invented; no workbook is needed here.
const fs = require('node:fs/promises'), path = require('node:path'), os = require('node:os');
const { inventedPair } = require('./invented-pair.cjs');
const project = path.resolve(__dirname, '../..');
async function staticFixture(t) {
  const contract = await import('../../tools/data_contract.mjs');
  const base = await fs.mkdtemp(path.join(os.tmpdir(), 'atlas-static-invented-'));
  await fs.chmod(base, 0o700);
  t.after(() => fs.rm(base, { recursive: true, force: true }));
  const sourceRoot = path.join(base, 'source'), dataHome = path.join(base, 'data');
  await fs.mkdir(sourceRoot, { mode: 0o700 }); await fs.mkdir(dataHome, { mode: 0o700 });
  const sourceNames = [...new Set([...contract.RECIPE_FILES, 'index.html', 'format.js', 'views.js',
    'lifestyle.js', 'charts.js', 'csv.js', 'app.js', 'DATA_SOURCES.md', 'tools/build_static.mjs'])];
  for (const name of sourceNames) {
    await fs.mkdir(path.dirname(path.join(sourceRoot, name)), { recursive: true, mode: 0o700 });
    let bytes; try { bytes = await fs.readFile(path.join(project, name)); }
    catch (error) { if (error.code !== 'ENOENT') throw error; bytes = Buffer.from('// Invented builder placeholder\n'); }
    await fs.writeFile(path.join(sourceRoot, name), bytes, { mode: 0o644 });
  }
  async function generation({ pair = inventedPair(), sourceSalt = 'invented inputs' } = {}) {
    const recipe = await contract.readRecipe(sourceRoot);
    const files = [{path:'market-data.csv',sha256:contract.sha256(pair.csv)}, {path:'market-data.js',sha256:contract.sha256(pair.js)}];
    const dataId = contract.fileIdentity(files), sources = [...recipe.recipe.sources].sort((a,b)=>a.id.localeCompare(b.id)).map(source => {
      const sha256 = contract.sha256(sourceSalt + source.id);
      return {id:source.id,url:source.url,sha256,path:`inputs/${sha256}/${contract.retainedInputName(source.id)}`};
    });
    const generatedDate = JSON.parse(pair.js.toString().slice('globalThis.MARKET_DATA = '.length, -2)).generated;
    const bundleId = contract.bundleIdentity({dataId,recipeId:recipe.recipeId,sources,generatedDate});
    const dataRoot = path.join(dataHome, bundleId); await fs.mkdir(dataRoot, {mode:0o700});
    const provenance = {schemaVersion:1,bundleId,dataId,recipeId:recipe.recipeId,generatedDate,sources,files,
      recipeFiles:recipe.files,range:{firstYear:1872,lastYear:2025,count:154}};
    const dataBytes = new Map([['market-data.js',pair.js],['market-data.csv',pair.csv],
      ['provenance.json',Buffer.from(JSON.stringify(provenance)+'\n')],
      ...[...recipe.bytes].map(([name,bytes])=>['recipe/'+name,bytes])]);
    for (const [name,bytes] of dataBytes) {
      await fs.mkdir(path.dirname(path.join(dataRoot,name)),{recursive:true,mode:0o700});
      await fs.writeFile(path.join(dataRoot,name),bytes,{mode:0o600});
    }
    return {dataRoot,dataBytes,provenance,pair};
  }
  return {base,sourceRoot,dataHome,generation,...await generation()};
}
module.exports = {staticFixture,project};
