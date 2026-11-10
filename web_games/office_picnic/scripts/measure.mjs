import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {mkdir,writeFile} from 'node:fs/promises';
import {measureFlight} from '../dist/game/measure.js';
const limits=measureFlight();
const out=process.argv[2]==='--out'&&process.argv[3]?resolve(process.argv[3]):new URL('../reports/',import.meta.url);
await mkdir(out,{recursive:true});
await writeFile(resolve(out instanceof URL?fileURLToPath(out):out,'flight-limits.json'),JSON.stringify(limits,null,2)+'\n');
console.log(JSON.stringify(limits,null,2));
