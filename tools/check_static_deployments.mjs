/** Read-only flat Market Atlas drift check. No build, acquisition or repair.
 * Market history is not redistributable and never enters Git, so the installed
 * data pair is checked only for presence: regular, non-empty files. Installed
 * code is compared byte-for-byte with tracked source. */
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
const REPO_ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
export const PROJECT_PREFIX='Calculation tools/backtest/';
export const SOURCE_FILES=Object.freeze(['index.html','format.js','stats.js','views.js','lifestyle.js','charts.js','csv.js','engine.js','app.js','DATA_SOURCES.md']);
export const DATA_FILES=Object.freeze(['market-data.js','market-data.csv']);
export const RUNTIME_FILES=Object.freeze([...SOURCE_FILES,...DATA_FILES].sort());
export const AUDIT_SOURCE_INPUTS=Object.freeze([...SOURCE_FILES.map(n=>PROJECT_PREFIX+n),'tools/check_static_deployments.mjs'].sort());
export const OK_LINE='OK: backtest static deployment';
// Fixed failure reasons; the fleet audit prints them, so they never contain paths or data.
export const FAILURES=Object.freeze({
 inventory:'backtest source inventory invalid',
 directory:'backtest deployment directory missing or not a plain directory',
 data:'backtest market data missing or empty in deployment',
 files:'backtest deployment has extra or missing files',
 code:'backtest installed code differs from source',
 error:'backtest audit error',
});
class AuditFailure extends Error{}
function fail(reason){throw new AuditFailure(reason);}
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
async function lstatOrNull(filename){
 try{return await fs.lstat(filename);}catch(error){if(error.code==='ENOENT'||error.code==='ENOTDIR')return null;throw error;}
}
async function regularBytes(filename){
 if(!(await fs.lstat(filename)).isFile())throw Error('Expected regular runtime file');
 return fs.readFile(filename);
}
export async function auditStaticDeployment({webroot,sourceInventory,sourceContext}={}){
 const sourceRoot=sourceContext?.sourceRoot||path.join(REPO_ROOT,PROJECT_PREFIX);
 try{
  if(!sourceContext){try{validateSourceInventory(sourceInventory);}catch{fail(FAILURES.inventory);}}
  const site=path.join(webroot,'calculators/backtest');
  if(!(await lstatOrNull(site))?.isDirectory())fail(FAILURES.directory);
  for(const name of DATA_FILES){
   const stat=await lstatOrNull(path.join(site,name));
   if(!stat?.isFile()||stat.size===0)fail(FAILURES.data);
  }
  if((await fs.readdir(site)).sort().join('\0')!==RUNTIME_FILES.join('\0'))fail(FAILURES.files);
  for(const name of SOURCE_FILES){
   const installed=await lstatOrNull(path.join(site,name));
   if(!installed?.isFile()||!(await fs.readFile(path.join(site,name))).equals(await regularBytes(path.join(sourceRoot,name))))fail(FAILURES.code);
  }
  return {ok:true,errors:[]};
 }catch(error){return {ok:false,errors:[error instanceof AuditFailure?error.message:FAILURES.error]};}
}
async function main(){
 const args=process.argv.slice(2);
 if(args.length!==2||args[0]!=='--source-inventory')throw Error('Use --source-inventory FILE supplied by the fleet audit');
 const home=process.env.UTILITIES_LOCAL_ROOT||os.homedir();
 const result=await auditStaticDeployment({webroot:process.env.UTILITIES_WEBROOT_DIR||path.join(home,'webroot'),sourceInventory:await fs.readFile(args[1])});
 if(!result.ok)throw Error(result.errors.join('; '));
 console.log(OK_LINE);
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))main().catch(error=>{console.error(error.message);process.exitCode=1;});
