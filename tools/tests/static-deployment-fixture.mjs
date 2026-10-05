// Invented history only. Source is copied to fixture Git; data stays outside it.
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {staticFixture,project}=require('../../Calculation tools/backtest/tests/helpers/static-fixture.cjs');
const repo=path.resolve(project,'../..');
export async function makeFixture(t,{repoRoot,home}={}){
 const f=await staticFixture(t);
 repoRoot=repoRoot||path.join(f.base,'fixture repo');home=home||path.join(f.base,'fixture home');
 const sourceRoot=path.join(repoRoot,'Calculation tools/backtest');
 await fs.mkdir(sourceRoot,{recursive:true});await fs.mkdir(home,{recursive:true,mode:0o700});
 await fs.cp(f.sourceRoot,sourceRoot,{recursive:true});
 await fs.mkdir(path.join(repoRoot,'tools'),{recursive:true});
 await fs.copyFile(path.join(repo,'tools/check_static_deployments.mjs'),path.join(repoRoot,'tools/check_static_deployments.mjs'));
 const dataHome=path.join(home,'invented data home'),webroot=path.join(home,'invented web root');
 await fs.mkdir(path.join(dataHome,'datasets'),{recursive:true,mode:0o700});
 const dataRoot=path.join(dataHome,'datasets',f.provenance.bundleId);await fs.rename(f.dataRoot,dataRoot);
 const {bundleId,dataId,recipeId}=f.provenance;
 await fs.writeFile(path.join(dataHome,'current.json'),JSON.stringify({schemaVersion:1,bundleId,dataId,recipeId}));
 const site=path.join(webroot,'calculators/backtest');await fs.mkdir(site,{recursive:true});
 for(const name of ['index.html','format.js','stats.js','views.js','lifestyle.js','charts.js','csv.js','engine.js','app.js','DATA_SOURCES.md'])await fs.copyFile(path.join(sourceRoot,name),path.join(site,name));
 for(const name of ['market-data.js','market-data.csv'])await fs.copyFile(path.join(dataRoot,name),path.join(site,name));
 return {...f,sourceRoot,repoRoot,home,dataHome,dataRoot,webroot,site};
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 const callbacks=[];try{await makeFixture({after(fn){callbacks.push(fn);}},{repoRoot:process.argv[2],home:process.argv[3]});}finally{for(const fn of callbacks)await fn();}
}
