'use strict';
const fs=require('node:fs/promises'),path=require('node:path');
const {getDataset,SOURCE_ROOT}=require('./helpers/dataset.cjs');
const {SYNTHETIC_TESTS,runChild,validatePython,runSyntheticCompiler,signalController}=require('./helpers/runner.cjs');
const {runArtifactBrowser}=require('./run_artifact_browser.cjs');
function fullTestEnvironment(env,bundle) {
 // A complete gate always uses the two-target matrix; overrides belong to test:browser.
 return {...env,MARKET_ATLAS_TEST_DATA_ROOT:bundle.root,MARKET_ATLAS_TEST_URL:''};
}
async function runTests({synthetic=false,env=process.env,signal}={}) {
 if(synthetic){
  process.stdout.write('Explicit synthetic subset: invented Node fixtures and both invented compiler modules. This does not certify historical/browser acceptance.\n');
  const python=await validatePython({env,signal});
  await runChild(process.execPath,['--test','--test-concurrency=1',...SYNTHETIC_TESTS.map(n=>'tests/'+n)],{env,signal,requireZeroSkips:true});
  await runSyntheticCompiler(python,{env,signal});

 }else{
  const bundle=await getDataset();
  const pinned=fullTestEnvironment(env,bundle);
  const names=(await fs.readdir(path.join(SOURCE_ROOT,'tests'))).filter(n=>n.endsWith('.test.js')&&n!=='browser-smoke.test.js').sort();
  await runChild(process.execPath,['--test','--test-concurrency=1',...names.map(n=>'tests/'+n)],{env:pinned,signal,requireZeroSkips:true});
  await runArtifactBrowser({bundle,env:pinned,signal});
 }
}
if(require.main===module){
 process.umask(0o077);
 const lifecycle=signalController();
 const args=process.argv.slice(2);
 const task=args.length===0||args.length===1&&args[0]==='--synthetic'?runTests({synthetic:args[0]==='--synthetic',signal:lifecycle.signal}):Promise.reject(new Error('Use npm test or npm run test:synthetic; test filtering is not supported by complete-suite drivers.'));
 task.catch(error=>{process.stderr.write(error.message+'\n');if(!process.exitCode)process.exitCode=1;}).finally(()=>lifecycle.dispose());
}
module.exports={runTests,fullTestEnvironment};
