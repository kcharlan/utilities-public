'use strict';
const path=require('node:path'),{pathToFileURL}=require('node:url');
const {getDataset,SOURCE_ROOT}=require('./helpers/dataset.cjs');
const {validateRawTarget,resolveTarget}=require('./helpers/browser-target.cjs');
const {captureInputs,prepareLayouts,serveDirectory,runChild,signalController}=require('./helpers/runner.cjs');
function browserTargets(layouts,server,override) {
 const artifact={runtimeRoot:layouts.artifactRoot,expectedRoot:layouts.artifactExpectedRoot,purpose:'artifact',documentRoutes:'selected-entry'};
 if(override){
  validateRawTarget(override);
  // Validate policy without reading any physical target/manifest as expected truth.
  const purpose=/^http:/i.test(override)?'installed':'artifact';
  resolveTarget(layouts.artifactRoot,override,{expected:{files:new Map(),scripts:[],entryPath:'index.html',noticePath:'DATA_SOURCES.md',datasetCsvPath:'market-data.csv'},purpose,documentRoutes:'selected-entry'});
  return [{...artifact,purpose,label:'explicit local override',url:override}];
 }
 return [{...artifact,label:'flat file',url:pathToFileURL(path.join(layouts.artifactRoot,'index.html')).href},
  {...artifact,label:'isolated HTTP explicit index',url:server.indexUrl}];
}
async function runArtifactBrowser({bundle,env=process.env,signal}={}) {
 const selected=bundle||await getDataset(),pinned={...env,MARKET_ATLAS_TEST_DATA_ROOT:selected.root};
 const captured=await captureInputs(SOURCE_ROOT,selected);
 if(signal?.aborted)throw new Error('Test run interrupted');
 const layouts=await prepareLayouts(captured,{tempParent:env.MARKET_ATLAS_TEST_TMPDIR});let server;
 try{
  if(!env.MARKET_ATLAS_TEST_URL)server=await serveDirectory(layouts.artifactRoot,[...captured.files.keys()]);
  for(const target of browserTargets(layouts,server,env.MARKET_ATLAS_TEST_URL)){
   if(signal?.aborted)throw new Error('Test run interrupted');
   process.stdout.write('\nBrowser matrix: '+target.label+' (all three original scenarios)\n');
   await runChild(process.execPath,['tests/browser-smoke.test.js'],{cwd:SOURCE_ROOT,signal,requireZeroSkips:true,
    env:{...pinned,MARKET_ATLAS_TEST_URL:target.url,MARKET_ATLAS_TEST_RUNTIME_ROOT:target.runtimeRoot,MARKET_ATLAS_TEST_EXPECTED_ROOT:target.expectedRoot,
      MARKET_ATLAS_TEST_PURPOSE:target.purpose,MARKET_ATLAS_TEST_DOCUMENT_ROUTES:target.documentRoutes,MARKET_ATLAS_TEST_BROWSER_TEMP:layouts.root}});
  }
 }finally{
  try{if(server)await server.close();}finally{await layouts.cleanup();}
 }
}
if(require.main===module){
 process.umask(0o077);
 const lifecycle=signalController();
 runArtifactBrowser({signal:lifecycle.signal}).catch(error=>{process.stderr.write(error.message+'\n');if(!process.exitCode)process.exitCode=1;}).finally(()=>lifecycle.dispose());
}
module.exports={browserTargets,runArtifactBrowser};
