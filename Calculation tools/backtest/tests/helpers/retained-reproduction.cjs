'use strict';
// Read-only JSON bridge for Python integration. Historical JS is never evaluated.
const path=require('node:path'),os=require('node:os');
const {getDataset,dataOptions,SOURCE_ROOT,REPO_ROOT}=require('./dataset.cjs');
const {validatePython}=require('./runner.cjs');
async function retainedReproduction({python,env=process.env}={}) {
 const contract=await import('../../tools/data_contract.mjs');
 await validatePython({env:{...env,MARKET_ATLAS_TEST_PYTHON:python}});
 await contract.safeRoot(env.MARKET_ATLAS_TEST_TMPDIR||os.tmpdir(),{sourceRoot:SOURCE_ROOT,repoRoot:REPO_ROOT,privateRoot:false});
 const bundle=await getDataset();
 const dataHome=env.MARKET_ATLAS_DATA_HOME||
  (path.basename(path.dirname(bundle.root))==='datasets'?path.dirname(path.dirname(bundle.root)):dataOptions(env).dataHome);
 const raw=await contract.verifyRetainedInputs({dataHome,provenance:bundle.provenance,sourceRoot:SOURCE_ROOT,repoRoot:REPO_ROOT});
 return {root:bundle.root,dataHome,bundleId:bundle.bundleId,dataId:bundle.dataId,recipeId:bundle.recipeId,generatedDate:bundle.provenance.generatedDate,
  inputs:bundle.provenance.sources.map(source=>({id:source.id,path:path.join(dataHome,source.path),sha256:contract.sha256(raw.get(source.id))})),
  pairHashes:Object.fromEntries([...bundle.files].map(([name,bytes])=>[name,contract.sha256(bytes)]))};
}
if(require.main===module){
 if(process.argv.length!==4||process.argv[2]!=='--python'){process.stderr.write('Retained reproduction requires the existing venv interpreter.\n');process.exitCode=1;}
 else retainedReproduction({python:process.argv[3]}).then(result=>process.stdout.write(JSON.stringify(result)+'\n')).catch(()=>{
  process.stderr.write('Retained reproduction prerequisites failed. Run npm run setup:data; select its verified bundle and ready compatible external venv. No acquisition or preparation runs in tests.\n');process.exitCode=1;
 });
}
module.exports={retainedReproduction};
