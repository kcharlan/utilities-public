import {mkdir,writeFile} from 'node:fs/promises';
import {measureFlight} from '../dist/game/measure.js';
const limits=measureFlight();
await mkdir(new URL('../reports/',import.meta.url),{recursive:true});
await writeFile(new URL('../reports/flight-limits.json',import.meta.url),JSON.stringify(limits,null,2)+'\n');
console.log(JSON.stringify(limits,null,2));
