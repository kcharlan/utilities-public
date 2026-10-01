/** Read-only flat Market Atlas drift check. No build, acquisition or repair. */
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
import {verifySelected} from '../Calculation tools/backtest/tools/data_contract.mjs';
const REPO_ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
export const PROJECT_PREFIX='Calculation tools/backtest/';
export const SOURCE_FILES=Object.freeze(['index.html','format.js','stats.js','views.js','lifestyle.js','charts.js','csv.js','engine.js','app.js','DATA_SOURCES.md']);
export const RUNTIME_FILES=Object.freeze([...SOURCE_FILES,'market-data.js','market-data.csv'].sort());
export const AUDIT_SOURCE_INPUTS=Object.freeze([...SOURCE_FILES.map(n=>PROJECT_PREFIX+n),PROJECT_PREFIX+'tools/data_contract.mjs','tools/check_static_deployments.mjs'].sort());
export const OK_LINE='OK: backtest static deployment';
export function validateSourceInventory(bytes){
 if(!Buffer.isBuffer(bytes)||!bytes.length||bytes.at(-1)!==0)throw Error('Invalid audit source inventory');
 const names=new Set();
 for(const record of bytes.toString().slice(0,-1).split('\0')){
  const match=/^(100644|100755)\t(.+)$/.exec(record);
  if(!match||!AUDIT_SOURCE_INPUTS.includes(match[2])||names.has(match[2]))throw Error('Invalid audit source inventory');
  names.add(match[2]);
 }
 if(names.size!==AUDIT_SOURCE_INPUTS.length)throw Error('Incomplete audit source inventory');
 return names;
}
async function regularBytes(filename){
 if(!(await fs.lstat(filename)).isFile())throw Error('Expected regular runtime file');
 return fs.readFile(filename);
}
export async function auditStaticDeployment({webroot,dataHome,sourceInventory,sourceContext}={}){
 const repoRoot=sourceContext?.repoRoot||REPO_ROOT,sourceRoot=sourceContext?.sourceRoot||path.join(repoRoot,PROJECT_PREFIX);
 try{
  if(!sourceContext)validateSourceInventory(sourceInventory);
  const selected=await verifySelected({dataHome,sourceRoot,repoRoot});
  if(!selected)throw Error('Missing selected local data');
  const site=path.join(webroot,'calculators/backtest');
  if(!(await fs.lstat(site)).isDirectory())throw Error('Expected runtime directory');
  if((await fs.readdir(site)).sort().join('\0')!==RUNTIME_FILES.join('\0'))throw Error('Runtime inventory drift');
  for(const name of RUNTIME_FILES){
   const expected=selected.files.get(name)||await regularBytes(path.join(sourceRoot,name));
   if(!(await regularBytes(path.join(site,name))).equals(expected))throw Error('Runtime byte drift');
  }
  return {ok:true,errors:[]};
 }catch{return {ok:false,errors:['backtest source, selected data or installed bytes unverified']};}
}
async function main(){
 const args=process.argv.slice(2);
 if(args.length!==2||args[0]!=='--source-inventory')throw Error('Use --source-inventory FILE supplied by the fleet audit');
 const home=process.env.UTILITIES_LOCAL_ROOT||os.homedir();
 const result=await auditStaticDeployment({webroot:process.env.UTILITIES_WEBROOT_DIR||path.join(home,'webroot'),dataHome:process.env.MARKET_ATLAS_DATA_HOME||path.join(home,'.cache/market-atlas'),sourceInventory:await fs.readFile(args[1])});
 if(!result.ok)throw Error(result.errors.join('; '));
 console.log(OK_LINE);
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))main().catch(error=>{console.error(error.message);process.exitCode=1;});
