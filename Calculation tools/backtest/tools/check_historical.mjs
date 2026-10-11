/** Trusted acceptance code. Candidates are parsed as JSON by data_contract. */
import assert from 'node:assert/strict';
import engine from '../engine.js';
const { sweepStartYears,maxSafeRate,STRATEGIES }=engine;
export function checkHistorical(rows) {
  for(const [allocation,successes,failed,rates] of [
    [{stock:0.5,bond:0.5,bill:0},64,[1964,1965,1966,1968,1969],[[1966,3.67],[1965,3.75],[1968,3.85],[1969,3.88]]],
    [{stock:0.75,bond:0.25,bill:0},65,[1965,1966,1968,1969],[[1966,3.80]]],
  ]) {
    const options={startingBalance:1_000_000,allocation,feeRate:0,taxRate:0,rebalance:'annual'};
    const complete=sweepStartYears(rows,30,STRATEGIES.fixedReal,{initialRate:0.04},options)
      .filter(({startYear,partial})=>startYear>=1928&&startYear<=1996&&!partial);
    assert.equal(complete.length,69);assert.equal(complete.filter(({metrics})=>metrics.success).length,successes);
    assert.deepEqual(complete.filter(({metrics})=>!metrics.success).map(({startYear})=>startYear),failed);
    const byYear=new Map(rows.map(row=>[row.year,row]));
    const safe=complete.map(({startYear})=>({startYear,rate:maxSafeRate(Array.from({length:30},(_,offset)=>byYear.get(startYear+offset)),STRATEGIES.fixedReal,{initialRate:0.04},options)})).sort((a,b)=>a.rate-b.rate);
    assert.deepEqual(safe.slice(0,rates.length).map(value=>value.startYear),rates.map(([year])=>year));
    for(const [index,[,expected]] of rates.entries()) assert.ok(Math.abs(safe[index].rate*100-expected)<=0.05,'Historical safe-rate control failed');
  }
}

// This CLI is used only with private captured recipe bytes. It has no acquisition
// or validation bypass and reads candidate files without evaluating JavaScript.
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { guardDirectory,readOwned,parsePair } from './data_contract.mjs';
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  try {
    if(process.argv.length!==4||process.argv[2]!=='--pair-dir')throw new Error('Expected candidate pair directory');
    const root=path.resolve(process.argv[3]);await guardDirectory(root);
    const payload=parsePair(await readOwned(path.join(root,'market-data.js')),await readOwned(path.join(root,'market-data.csv')),{requireCurrentSchema:true});
    checkHistorical(payload.rows);console.log('Historical controls passed: 69 windows in each allocation.');
  }catch{console.error('Historical candidate validation failed; previous selection is retained.');process.exitCode=1;}
}
