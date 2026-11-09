import {readFile} from 'node:fs/promises';
import {replayTrace} from '../dist/game/trace.js';
try{if(process.argv.length!==3)throw new Error('Usage: node scripts/replay.mjs <trace.json>');const run=replayTrace(JSON.parse(await readFile(process.argv[2],'utf8')));console.log(`Replay passed: ${run.finishTicks} ticks, ${run.crashes} impacts`);}catch(e){console.error(e.message);process.exitCode=1;}
